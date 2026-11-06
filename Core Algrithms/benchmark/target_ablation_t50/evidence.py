"""Frozen, serial optimizer jobs; outputs are confined to the new experiment."""
from __future__ import annotations
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import monotonic
from unittest.mock import patch
import argparse, json, os, pickle, sys, traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'source'))
from gapo_timetabling.core import decoder, population
from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.fitness import calculate_fitness
from gapo_timetabling.core.ga import GAConfig, run_ga
from gapo_timetabling.core.po import PoConfig, run_po
from gapo_timetabling.core.hybrid import HybridConfig, run_hybrid
from gapo_timetabling.core.greedy_baseline import run_greedy_first_feasible
from gapo_timetabling.core.placement_decoder import PlacementDecoder
from gapo_timetabling.core.snapshot import canonical_json, prepare_snapshot_for_optimization
from gapo_timetabling.application.run_contract import build_completed_result_payload

from variants import VARIANTS, run_variant
METHODS = VARIANTS
CASES = ('small', 'medium', 'large')
POPULATION_SIZE = 30
ITERATIONS = 50
FITNESS_CAP = POPULATION_SIZE * (ITERATIONS + 1)
EVALUATION = population.CandidateEvaluationConfig(20000, True, 3)


def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return sha256(value).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def packed(value): return canonical_json(value).encode('utf-8')


def save(path, value):
    path = Path(path).resolve()
    assert path.is_relative_to(ROOT), path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f'.{os.getpid()}.tmp')
    temporary.write_bytes(json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str).encode('utf-8'))
    temporary.replace(path)


def verify_source():
    manifest = read(ROOT / 'manifest.json')
    for rel, checksum in manifest['frozen_sha256'].items():
        assert digest((ROOT / rel).read_bytes()) == checksum, f'Frozen source/input changed: {rel}'
    return manifest


def prepared(scale):
    value = prepare_snapshot_for_optimization(ROOT / 'inputs' / f'{scale}.json')
    expected = dict(small=(12, 24, 232, 72), medium=(18, 36, 343, 108), large=(24, 48, 454, 144))[scale]
    p = value.problem
    assert value.is_ready and p.lecturer_assignment_scope == 'TEACHING_PART'
    assert (len(p.course_sections), p.schedule_dimension, len(p.class_sessions), p.dimension) == expected
    assert p.assignment_dimension == len(p.teaching_parts)
    return value


def signature(options):
    return digest(json.dumps([asdict(o) for o in options], sort_keys=True, default=str, separators=(',', ':')).encode())


class ObservedDecoder(PlacementDecoder):
    def __init__(self):
        super().__init__()
        self.failures = Counter()
        self.last = None

    def __call__(self, *args, **kwargs):
        result = super().__call__(*args, **kwargs)
        self.last = result
        if not result.is_success:
            self.failures[result.status.value] += 1
        return result


class Tracker:
    def __init__(self, records=(), trace=()):
        self.records = list(records)
        self.trace = list(trace)
        self.engine = ObservedDecoder()

    def fitness(self, problem, options, domains, **kwargs):
        value = calculate_fitness(problem, options, domains, **kwargs)
        result = self.engine.last
        assert result is not None and result.is_success and tuple(options) == result.selected_options
        quality = list(value.fitness_key)
        self.records.append(dict(vector=list(result.repaired_vector), quality=quality, phenotype=signature(options)))
        best = quality if not self.trace else min(self.trace[-1]['best'], quality)
        self.trace.append(dict(fe=len(self.records), best=best))
        return value

    @contextmanager
    def active(self):
        decoder.clear_decode_cache()
        decoder._PRIORITY_LOCAL.decoder = self.engine
        try:
            with patch.object(population, 'calculate_fitness', self.fitness):
                yield self
        finally:
            decoder.clear_decode_cache()


class Progress:
    def __init__(self, key, phase):
        self.key, self.phase, self.last = key, phase, 0.

    def __call__(self, value=None, *, force=False, **extra):
        if not force and monotonic() - self.last < 1:
            return
        import psutil
        data = asdict(value) if value is not None else {}
        save(ROOT / 'progress' / f'{self.key}.json', dict(phase=self.phase, pid=os.getpid(),
            at=now(), rss=psutil.Process().memory_info().rss, progress=data, **extra))
        self.last = monotonic()


def entries(problem, options):
    return sorted((dict(class_session_id=problem.class_sessions[o.session_index].class_session_id,
        lecturer_code=problem.lecturers[problem.option_lecturer_index(o)].lecturer_code,
        term_code=problem.term.term_code, teaching_date=o.teaching_date.isoformat(),
        location_id=problem.locations[o.location_index].location_id,
        location_type=problem.locations[o.location_index].location_type.value,
        start_period=o.start_period, end_period=o.end_period) for o in options), key=lambda row: row['class_session_id'])


def audit(payload, prep):
    data = payload['result']
    best = data['best_solution']
    engine = PlacementDecoder()
    replay = engine(prep.problem, prep.option_domains, tuple(best['vector']), 20000)
    assert replay.is_success and list(replay.repaired_vector) == best['vector']
    assert list(replay.selected_option_indices) == best['selected_option_indices']
    validation = validate_timetable(prep.problem, replay.selected_options)
    assert validation.is_valid and len(replay.selected_options) == len(prep.problem.class_sessions)
    assert sum(o.end_period-o.start_period+1 for o in replay.selected_options) == sum(s.duration_periods for s in prep.problem.class_sessions)
    assert entries(prep.problem, replay.selected_options) == data['timetable_entries']
    assert canonical_json(asdict(calculate_fitness(prep.problem, replay.selected_options, prep.option_domains))) == canonical_json(data['best_fitness'])
    assert engine.stats['soft_option_scores'] == 0
    return dict(hard_violations=0, coverage=len(replay.selected_options), fullfitness_indices_entries_match=True)


def validate_trace(payload, detail):
    data = payload['result']
    records, trace = detail['records'], detail['trace']
    assert len(trace) == len(records) == data['metrics']['fitness_evaluations'] <= FITNESS_CAP
    assert len(trace) >= POPULATION_SIZE and data['metrics']['completed_iterations'] == ITERATIONS
    best = None
    for fe, (record, point) in enumerate(zip(records, trace, strict=True), 1):
        best = record['quality'] if best is None else min(best, record['quality'])
        assert point == dict(fe=fe, best=best)
    assert trace[-1]['best'] == [data['best_fitness']['general_quality_score'], data['best_fitness']['lecturer_preference_score']]
    history = data['convergence_history']
    assert [h['iteration'] for h in history] == list(range(ITERATIONS + 1))
    for h in history:
        assert trace[h['fitness_evaluations']-1]['best'] == [h['general_quality_score'], h['lecturer_preference_score']]


def load_initial(scale, seed, prep):
    meta = read(ROOT / 'cohorts' / f'{scale}_{seed}.json')
    binary = (ROOT / 'cohorts' / f'{scale}_{seed}.pkl').read_bytes()
    assert digest(binary) == meta['pickle_sha'] and meta['snapshot_checksum'] == prep.snapshot_checksum
    assert digest(packed({'records':meta['records']})) == meta['initial_sha']
    initial = pickle.loads(binary)  # Only own generated bytes, locked by the saved SHA.
    records = [dict(vector=list(i.vector), quality=list(i.fitness_key), phenotype=signature(i.selected_options)) for i in initial.individuals]
    assert records == meta['records'] and len(records) == 30
    return initial, meta


def optimize(scale, seed, method):
    prep = prepared(scale)
    initial, meta = load_initial(scale, seed, prep)
    key = f'{scale}_{seed}_{method}'
    assert not (ROOT / 'checkpoints' / f'{key}.json').exists()
    tracker = Tracker(meta['records'], meta['trace'])
    progress = Progress(key, 'OPTIMIZING')
    with tracker.active():
        result = run_variant(prep.problem, prep.option_domains, initial,
            HybridConfig(FITNESS_CAP, 5, seed, EVALUATION), variant=method,
            progress_callback=progress)
    assert tracker.engine.stats['soft_option_scores'] == 0
    if method in METHODS:
        counts = result.hybrid_activity['counts']
        assert counts['ga_slots'] == 24 * ITERATIONS and counts['target_slots'] == 6 * ITERATIONS
    payload = build_completed_result_payload(request_id=key, algorithm_name=method, prepared=prep,
        best_individual=result.best_individual, metrics=result.metrics,
        convergence_history=result.convergence_history, hybrid_activity=result.hybrid_activity)
    payload['research_variant'] = method
    payload['full_hybrid_mechanism'] = 'GA_PO_TARGET_PO80.v1'
    detail = dict(initial_sha=meta['initial_sha'], snapshot_checksum=prep.snapshot_checksum,
        records=tracker.records, trace=tracker.trace, decoder_work=tracker.engine.stats,
        failures=dict(tracker.engine.failures), activity=result.hybrid_activity)
    validate_trace(payload, detail)
    detail['audit'] = audit(payload, prep)
    save(ROOT / 'runs' / f'{key}.json', payload)
    save(ROOT / 'details' / f'{key}.json', detail)
    save(ROOT / 'checkpoints' / f'{key}.json', dict(at=now(), initial_sha=meta['initial_sha'],
        result_sha=digest((ROOT/'runs'/f'{key}.json').read_bytes()), detail_sha=digest((ROOT/'details'/f'{key}.json').read_bytes())))
    progress(force=True, status='COMPLETED', fe=result.metrics.fitness_evaluations)



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run exactly one ablation; never GA, PO, FULL or Greedy.')
    parser.add_argument('scale', choices=CASES)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--variant', choices=METHODS, required=True)
    args = parser.parse_args()
    verify_source()
    key = f'{args.scale}_{args.seed}_{args.variant}'
    try:
        optimize(args.scale, args.seed, args.variant)
    except BaseException:
        save(ROOT/'errors'/f'{key}.json', dict(at=now(), pid=os.getpid(), error=traceback.format_exc()))
        raise
