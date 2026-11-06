"""One ratio job, using unchanged production TARGET and shared saved initials."""
import argparse
from pathlib import Path
import sys
import traceback

import reference_evidence as base
from gapo_timetabling.core.hybrid import HybridConfig
from gapo_timetabling.core.target_hybrid import run_target_hybrid

ROOT = base.ROOT
RATIOS = {"GA70_PO30": 0.7, "GA60_PO40": 0.6}
METHODS = tuple(RATIOS)
CASES = base.CASES
ITERATIONS = base.ITERATIONS
FITNESS_CAP = base.FITNESS_CAP
read, save, digest, now = base.read, base.save, base.digest, base.now
prepared, audit = base.prepared, base.audit
load_initial, verify_source = base.load_initial, base.verify_source


def config_for(method, seed):
    return HybridConfig(FITNESS_CAP, 5, seed, base.EVALUATION, ga_ratio=RATIOS[method])


def validate_trace(payload, detail):
    base.validate_trace(payload, detail)
    method = payload.get('research_variant')
    if method in METHODS:
        ratio = RATIOS[method]
        n_ga = round(30 * ratio)
        counts = detail['activity']['counts']
        if (payload['research_ratio'] != ratio or detail['ga_ratio'] != ratio
                or detail['ga_slots_per_generation'] != n_ga
                or detail['po_slots_per_generation'] != 30-n_ga
                or counts['ga_slots'] != n_ga*50 or counts['target_slots'] != (30-n_ga)*50):
            raise ValueError('Saved ratio/config/slot counters disagree.')


def optimize(scale, seed, method):
    if method not in METHODS or seed not in range(1, 11) or scale not in CASES:
        raise ValueError("Only the two planned ratios, three scales and seeds 1-10 are allowed.")
    prep = prepared(scale)
    initial, meta = load_initial(scale, seed, prep)
    key = f"{scale}_{seed}_{method}"
    if (ROOT / 'checkpoints' / f'{key}.json').exists():
        raise FileExistsError("Completed ratio run must not be rerun.")
    tracker = base.Tracker(meta['records'], meta['trace'])
    progress = base.Progress(key, 'OPTIMIZING_RATIO')
    config = config_for(method, seed)
    with tracker.active():
        result = run_target_hybrid(prep.problem, prep.option_domains, initial,
                                   config, progress_callback=progress)
    n_ga = round(30 * RATIOS[method])
    counts = result.hybrid_activity['counts']
    if counts['ga_slots'] != n_ga * 50 or counts['target_slots'] != (30-n_ga) * 50:
        raise ValueError("Ratio slot counts differ from the preregistered design.")
    if tracker.engine.stats['soft_option_scores'] != 0:
        raise ValueError("Decoder queried a soft score.")
    payload = base.build_completed_result_payload(request_id=key, algorithm_name=method,
        prepared=prep, best_individual=result.best_individual, metrics=result.metrics,
        convergence_history=result.convergence_history, hybrid_activity=result.hybrid_activity)
    payload.update(research_ratio=RATIOS[method], research_variant=method,
                   full_hybrid_mechanism='GA_PO_TARGET_PO80.v1')
    detail = dict(initial_sha=meta['initial_sha'], snapshot_checksum=prep.snapshot_checksum,
        records=tracker.records, trace=tracker.trace, decoder_work=tracker.engine.stats,
        failures=dict(tracker.engine.failures), activity=result.hybrid_activity,
        ga_ratio=RATIOS[method], ga_slots_per_generation=n_ga, po_slots_per_generation=30-n_ga)
    validate_trace(payload, detail)
    detail['audit'] = audit(payload, prep)
    save(ROOT / 'runs' / f'{key}.json', payload)
    save(ROOT / 'details' / f'{key}.json', detail)
    save(ROOT / 'checkpoints' / f'{key}.json', dict(at=now(), initial_sha=meta['initial_sha'],
        result_sha=digest((ROOT/'runs'/f'{key}.json').read_bytes()),
        detail_sha=digest((ROOT/'details'/f'{key}.json').read_bytes())))
    progress(force=True, status='COMPLETED', fe=result.metrics.fitness_evaluations)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scale', choices=CASES)
    parser.add_argument('--seed', type=int, choices=range(1, 11), required=True)
    parser.add_argument('--variant', choices=METHODS, required=True)
    args = parser.parse_args()
    verify_source()
    try:
        optimize(args.scale, args.seed, args.variant)
    except BaseException:
        save(ROOT/'errors'/f'{args.scale}_{args.seed}_{args.variant}.json',
             dict(at=now(), pid=base.os.getpid(), error=traceback.format_exc()))
        raise
