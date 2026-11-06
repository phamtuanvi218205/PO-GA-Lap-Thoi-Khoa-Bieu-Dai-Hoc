"""Execute production TARGET on D155 and compare directly with saved history.

Keeps T20/cap630 even for a short prefix, since changing T changes PO formulas.
No writes to the historical experiment; only a new diagnostic JSON is emitted.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import argparse
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from zipfile import ZipFile

from gapo_timetabling.core import decoder, population, hybrid
from gapo_timetabling.core.fitness import calculate_fitness
from gapo_timetabling.application.run_contract import build_completed_result_payload
from verify_target_po80_integration import CORE, ROOT, module, read, digest


class PrefixVerified(Exception):
    pass


def check_case(scale, seed, rounds):
    started=perf_counter()
    h=module('history_evidence_helper',ROOT/'evidence_helpers.py')
    manifest=read(ROOT/'manifest.json')
    request,prepared=h.snapshot(scale)
    with ZipFile(h.BUNDLE/'evidence/d155.zip') as archive:
        initial,meta=h.load_initial(archive,manifest['archives']['d155'],scale,seed)
    name=f'{scale}_{seed}_TARGET_PO80.json'
    result_path=ROOT/'runs'/name; detail_path=ROOT/'details'/name
    checkpoint=read(ROOT/'checkpoints'/name)
    historical,detail=read(result_path),read(detail_path)
    assert digest(result_path)==checkpoint['result_sha']
    assert digest(detail_path)==checkpoint['detail_sha']
    assert meta['initial_sha']==detail['initial_sha']==checkpoint['initial_sha']
    engine=h.ObservedDecoder()
    records=list(meta['records']); trace=list(detail['trace'][:30])
    checkpoints=[]
    def observe(*args,**kwargs):
        f=calculate_fitness(*args,**kwargs)
        row=dict(vector=list(engine.last_vector),quality=list(f.fitness_key),phenotype=h.digest(args[1]))
        # Fail immediately at the first divergent successful proposal, not just
        # when the final quality differs.
        assert row==detail['records'][len(records)],(scale,seed,'record',len(records)+1)
        records.append(row)
        step=dict(fe=len(records),best=min(trace[-1]['best'],list(f.fitness_key)))
        assert step==detail['trace'][len(trace)],(scale,seed,'dense trace',len(trace)+1)
        trace.append(step)
        return f
    def progress(value):
        generation=value.metrics.completed_iterations
        if value.iteration!=generation or generation==0:
            return
        if checkpoints and checkpoints[-1]['iteration']==generation:
            return
        row=dict(iteration=generation,fitness_evaluations=value.metrics.fitness_evaluations,
                 general_quality_score=value.best_general_quality_score,
                 lecturer_preference_score=value.best_lecturer_preference_score)
        assert row==historical['result']['convergence_history'][generation],(scale,seed,'generation',generation)
        checkpoints.append(row)
        if generation==rounds and rounds<20:
            raise PrefixVerified()
    decoder.clear_decode_cache(); decoder._PRIORITY_LOCAL.decoder=engine
    result=None
    try:
        with patch.object(population,'calculate_fitness',observe):
            try:
                result=hybrid.run_hybrid(prepared.problem,prepared.option_domains,initial,
                    hybrid.HybridConfig(630,5,seed,request.evaluation_config,ga_ratio=.8),
                    progress_callback=progress)
            except PrefixVerified:
                assert rounds<20
        assert len(checkpoints)==rounds
        assert engine.stats['soft_option_scores']==0
        audit=None
        if rounds==20:
            assert result is not None
            payload=build_completed_result_payload(request_id='integration-history-check',algorithm_name='GA_PO',
                prepared=prepared,best_individual=result.best_individual,metrics=result.metrics,
                convergence_history=result.convergence_history,hybrid_activity=result.hybrid_activity)
            for key in ('best_solution','best_fitness','convergence_history','timetable_entries'):
                assert payload['result'][key]==historical['result'][key],(scale,key)
            actual_metrics=asdict(result.metrics)
            old_metrics=dict(historical['result']['metrics'])
            actual_metrics.pop('runtime_seconds');old_metrics.pop('runtime_seconds')
            assert actual_metrics==old_metrics
            assert h.canonical(result.hybrid_activity)==detail['activity']
            assert records==detail['records'] and trace==detail['trace']
            audit=h.audit(payload,prepared)
        return dict(scale=scale,seed=seed,rounds_checked=rounds,
            configured_total_rounds=20,configured_fe_cap=630,population=30,
            initialization='loaded exact historical cohort; no reinitialization',
            initial_sha=meta['initial_sha'],successful_proposals_compared=len(records)-30,
            fe=checkpoints[-1]['fitness_evaluations'],generation_checkpoints=checkpoints,
            full_final_audit=audit,soft_queries=engine.stats['soft_option_scores'],
            decoder_work=engine.stats,elapsed_seconds=perf_counter()-started,passed=True)
    finally:
        decoder.clear_decode_cache()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    reports=[]
    # Three independent processes; each comparison uses the historical seed 1.
    with ProcessPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(check_case,scale,1,rounds) for scale,rounds in
                 [('small',20),('medium',3),('large',3)]]
        for future in as_completed(futures):
            result=future.result();reports.append(result)
            print(json.dumps(result,ensure_ascii=False),flush=True)
    report=dict(passed=True,checks=sorted(reports,key=lambda row:row['scale']),
        scope='production optimizer vs saved historical TARGET_PO80, no new benchmark ranking',
        historical_results_modified=False,word_modified=False,
        production_source_sha256=digest(CORE/'src/gapo_timetabling/core/target_hybrid.py'))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS: small full20 + medium first3 + large first3, with original T20 preserved.',flush=True)
