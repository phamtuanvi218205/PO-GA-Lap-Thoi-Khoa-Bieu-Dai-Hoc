"""Replay saved SECTION bests and validate V3 vectors without optimizer runs.

Converted vectors are compatibility checks only, never benchmark initial
populations or evidence that an optimizer searched the new model.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / 'src'))

from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.decoder import PLACEMENT_ENCODING, PART_PLACEMENT_ENCODING, decode_saved_vector
from gapo_timetabling.core.fitness import calculate_fitness
from gapo_timetabling.core.snapshot import canonical_json, prepare_snapshot_for_optimization

ROOT = CORE / 'test_results/target_po80_d155_20261105'


def entries(problem, options):
    return sorted((dict(
        class_session_id=problem.class_sessions[o.session_index].class_session_id,
        lecturer_code=problem.lecturers[problem.option_lecturer_index(o)].lecturer_code,
        term_code=problem.term.term_code, teaching_date=o.teaching_date.isoformat(),
        location_id=problem.locations[o.location_index].location_id,
        location_type=problem.locations[o.location_index].location_type.value,
        start_period=o.start_period, end_period=o.end_period,
    ) for o in options), key=lambda row: row['class_session_id'])


def verify():
    backup = CORE.parent / '.tmp/part_integration_20261105/before/src/gapo_timetabling/core/target_hybrid.py'
    unchanged_functions = []
    if backup.exists():
        old_tree = ast.parse(backup.read_text(encoding='utf-8'))
        new_tree = ast.parse((CORE / 'src/gapo_timetabling/core/target_hybrid.py').read_text(encoding='utf-8'))
        functions = lambda tree: {n.name: ast.dump(n, include_attributes=False)
                                 for n in tree.body if isinstance(n, ast.FunctionDef)}
        old_functions, new_functions = functions(old_tree), functions(new_tree)
        for name in ('propose', '_create_and_evaluate_target_offspring', 'run_target_hybrid'):
            assert old_functions[name] == new_functions[name]
            unchanged_functions.append(name)
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    formula_checks = {path: sha256(Path(path).read_bytes()).hexdigest() == checksum
        for path, checksum in manifest['sha256'].items()
        if path.replace('\\', '/').endswith(('/core/ga.py', '/core/po.py'))}
    assert len(formula_checks) == 2 and all(formula_checks.values())
    legacy_checks, part_checks = [], []
    evidence = [p for folder in ('runs', 'checkpoints', 'details', 'inputs/data')
                for p in (ROOT / folder).glob('*.json')]
    before = {p: sha256(p.read_bytes()).hexdigest() for p in evidence}
    for scale, dimension in (('small', 72), ('medium', 108), ('large', 144)):
        source = ROOT / 'inputs/data' / f'{scale}.json'
        payload = json.loads(source.read_text(encoding='utf-8'))
        old = prepare_snapshot_for_optimization(payload)
        assert old.problem.lecturer_assignment_scope == 'SECTION'
        saved_first = None
        for seed in range(1, 11):
            path = ROOT / 'runs' / f'{scale}_{seed}_TARGET_PO80.json'
            saved = json.loads(path.read_text(encoding='utf-8'))
            data = saved['result']
            best = data['best_solution']
            assert best['vector_encoding'] == PLACEMENT_ENCODING
            replay = decode_saved_vector(old.problem, old.option_domains,
                tuple(best['vector']), 20000, encoding=best['vector_encoding'])
            assert replay.is_success
            assert list(replay.repaired_vector) == best['vector']
            assert list(replay.selected_option_indices) == best['selected_option_indices']
            assert validate_timetable(old.problem, replay.selected_options).is_valid
            assert entries(old.problem, replay.selected_options) == data['timetable_entries']
            fitness = calculate_fitness(old.problem, replay.selected_options, old.option_domains)
            assert canonical_json(asdict(fitness)) == canonical_json(data['best_fitness'])
            legacy_checks.append(dict(scale=scale, seed=seed, hard_violations=0,
                sessions=len(replay.selected_options), full_fitness_indices_entries_match=True))
            if seed == 1:
                saved_first = saved
        # The raw data is unchanged. Only this in-memory copy uses the new scope.
        updated = dict(payload, schema_version='problem-instance.v3',
            lecturer_assignment_scope='TEACHING_PART')
        current = prepare_snapshot_for_optimization(updated)
        problem = current.problem
        assert current.is_ready and problem.dimension == dimension
        assert problem.assignment_dimension == len(problem.teaching_parts)
        assert len(problem.class_sessions) == len(old.problem.class_sessions)
        assert current.snapshot_checksum != old.snapshot_checksum
        vector = saved_first['result']['best_solution']['vector']
        lecturer_genes = dict(zip(old.problem.assignment_keys,
            vector[:old.problem.assignment_dimension], strict=True))
        converted = tuple(lecturer_genes[problem.parts_for_assignment(key)[0].section_code]
            for key in problem.assignment_keys) + tuple(vector[old.problem.assignment_dimension:])
        assert len(converted) == dimension
        replay = decode_saved_vector(problem, current.option_domains, converted, 20000,
            encoding=PART_PLACEMENT_ENCODING)
        assert replay.is_success and tuple(replay.repaired_vector) == converted
        assert validate_timetable(problem, replay.selected_options).is_valid
        assert entries(problem, replay.selected_options) == saved_first['result']['timetable_entries']
        fitness = calculate_fitness(problem, replay.selected_options, current.option_domains)
        part_checks.append(dict(scale=scale, dimension=dimension,
            assignment_genes=problem.assignment_dimension, blocks=problem.schedule_dimension,
            sessions=len(replay.selected_options), hard_violations=0,
            vector_encoding=PART_PLACEMENT_ENCODING,
            mapping_schema=current.gene_option_mapping['schema_version'],
            general_quality_score=fitness.general_quality_score,
            lecturer_preference_score=fitness.lecturer_preference_score,
            converted_saved_vector_only=True, optimizer_run=False))
        print(f'{scale}: 10 old bests unchanged; V3 {dimension} genes, hard0/full coverage', flush=True)
    assert all(sha256(p.read_bytes()).hexdigest() == digest for p, digest in before.items())
    return dict(passed=True, optimizer_runs=0, benchmark_runs=0,
        original_ga_po_source_matches=formula_checks,
        target_functions_unchanged_from_preintegration=unchanged_functions,
        legacy_best_replays=legacy_checks, v3_compatibility_checks=part_checks,
        old_evidence_files_verified_unchanged=len(before),
        note='Converted vectors are not fresh initial cohorts or benchmark results.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = verify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('PASS: 30 legacy replays and three V3 compatibility checks; no optimizer benchmark.', flush=True)
