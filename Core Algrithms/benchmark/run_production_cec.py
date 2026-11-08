"""Independent-process CEC2022 run of the production GA/PO/ISLAND80 adapter.

Example: python benchmark/run_production_cec.py --output ... --workers 14
No old results are reused; existing completed cases are read only when an
explicit --resume is supplied with the exact same protocol and source hash.
"""
from __future__ import annotations
import os
for _k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_k]='1'
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'src')]
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import time
import traceback
import numpy as np
from production_algorithms import ALGORITHMS
from benchmark_functions import get_cec2022_suite
from experiment import (create_initial_population, _algorithm_seed, _sample_history,
                        write_csv, RAW_RESULT_FIELDS, CONVERGENCE_FIELDS,
                        summarize_results, calculate_ranks_and_tests)
from prepare_cec2022 import (ARCHIVE_PATH, LIBRARY_PATH, SOURCE_DIRECTORY,
                            ARCHIVE_SHA256, OFFICIAL_COMMIT)

def now(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    tmp.replace(path)

def source_hashes():
    files=list(HERE.glob('*.py'))+list((HERE.parent/'src/gapo_timetabling/core').glob('*.py'))
    return {str(p.relative_to(HERE.parent)).replace('\\','/'):sha(p) for p in files}

def run_cohort(args):
    output, number, seed, cap, resume = args
    out=Path(output); key=f'F{number:02d}_seed_{seed:02d}'
    function=get_cec2022_suite(20)[number-1]
    initial=create_initial_population(function,20,30,seed)
    initial_sha=hashlib.sha256(initial.astype('<f8').tobytes()).hexdigest()
    cohort_path=out/'initial'/f'{key}.npz'
    cohort_path.parent.mkdir(exist_ok=True)
    if not cohort_path.exists(): np.savez_compressed(cohort_path,population=initial)
    else:
        if not resume: raise RuntimeError('Existing cohort without explicit resume.')
        with np.load(cohort_path) as saved:
            np.testing.assert_array_equal(saved['population'],initial)
    for index,(name,algorithm) in enumerate(ALGORITHMS.items(),1):
        path=out/'runs'/name/f'{key}.json'
        if resume and path.exists(): continue
        atomic_json(out/'progress'/f'{key}.json',dict(pid=os.getpid(),command=__file__,
            cohort=key,algorithm=name,started_at=now(),status='RUNNING'))
        t=time.perf_counter()
        result=algorithm(function.evaluate_population,initial.copy(),-100.,100.,cap,
                         _algorithm_seed(seed,index))
        runtime=time.perf_counter()-t
        # Independent replay of the saved physical best. Not an optimizer FE.
        replay=float(function.evaluate_population(result.best_position.reshape(1,-1))[0])
        if not np.isclose(replay,result.best_value,rtol=1e-12,atol=1e-10):
            raise RuntimeError('Best replay does not match saved objective.')
        if result.best_value < function.optimum_value-1e-10*max(1.,abs(function.optimum_value)):
            raise RuntimeError('CEC result below known optimum.')
        if result.evaluations != cap or result.history_evaluations[-1] != cap:
            raise RuntimeError('Incorrect FE accounting.')
        if any(a<b for a,b in zip(result.history_best_values,result.history_best_values[1:])):
            raise RuntimeError('Non-monotone best history.')
        sampled=_sample_history(result.history_evaluations,result.history_best_values)
        row=dict(profile='cec2022_production_island80',function=function.name,
                 category=function.category,algorithm=name,seed=seed,dimensions=20,
                 population_size=30,max_evaluations=cap,best_value=result.best_value,
                 optimum_value=function.optimum_value,
                 final_error=max(0.,result.best_value-function.optimum_value),runtime_seconds=runtime)
        trace=out/'traces'/name/f'{key}.npz';trace.parent.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(trace,fe=result.history_evaluations,best=result.history_best_values,
            final_population=np.asarray([i.vector for i in result.final_population]),
            final_fitness=np.asarray([i.value for i in result.final_population]))
        atomic_json(path,dict(row=row,cohort=key,initial_sha256=initial_sha,
            algorithm_seed=_algorithm_seed(seed,index),best_unit=result.best_unit_position,
            best_position=result.best_position.tolist(),replay_value=replay,
            actual_FE=result.evaluations,completed_generations=(cap-30)//30,
            history=sampled,diagnostics=result.diagnostics,trace_sha256=sha(trace)))
    atomic_json(out/'progress'/f'{key}.json',dict(pid=os.getpid(),cohort=key,status='COMPLETED',at=now()))
    return key

def aggregate(out,expected,cap):
    rows=[];curves=[];initial={};diags={name:[] for name in ALGORITHMS}
    for number,seed in expected:
        key=f'F{number:02d}_seed_{seed:02d}'
        for name in ALGORITHMS:
            case=json.loads((out/'runs'/name/f'{key}.json').read_text(encoding='utf8'))
            rows.append(case['row']);initial.setdefault(key,set()).add(case['initial_sha256'])
            diags[name].append(case['diagnostics'])
            assert case['actual_FE']==cap
            for fe,value in case['history']:
                curves.append(dict(function=case['row']['function'],algorithm=name,seed=seed,
                    evaluations=fe,best_error=max(0.,value-case['row']['optimum_value'])))
    assert all(len(s)==1 for s in initial.values())
    write_csv(out/'raw_results.csv',rows,RAW_RESULT_FIELDS)
    write_csv(out/'convergence.csv',curves,CONVERGENCE_FIELDS)
    summarize_results(rows,out,algorithms=ALGORITHMS)
    calculate_ranks_and_tests(rows,out,algorithms=ALGORITHMS)
    atomic_json(out/'audit.json',dict(runs=len(rows),cohorts=len(initial),
        all_shared_initial=True,all_replayed=True,all_exact_FE=True,
        all_monotone=True,source_hashes_unchanged=True,
        diagnostics={name:{k:sum(d[k] for d in values) for k in values[0]
                           if k!='po_behaviors'} for name,values in diags.items()}))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=14)
    p.add_argument('--seeds',type=int,default=30)
    p.add_argument('--max-fe',type=int,default=300000)
    p.add_argument('--functions',type=int,default=12)
    p.add_argument('--resume',action='store_true')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if not 1<=a.seeds<=30 or not 1<=a.functions<=12 or not 1<=a.workers<=16:
        raise ValueError('Invalid run dimensions.')
    assert a.max_fe>=30 and (a.max_fe-30)%30==0
    if not LIBRARY_PATH.exists() or sha(ARCHIVE_PATH)!=ARCHIVE_SHA256:
        raise RuntimeError('Prepare and verify official evaluator before starting workers.')
    protocol=dict(version='cec2022-production-island80-v1',dimensions=20,N=30,
        max_FE=a.max_fe,seeds=list(range(1,a.seeds+1)),functions=a.functions,
        algorithms=list(ALGORITHMS),initial='numpy.default_rng(seed), shared physical population',
        random_streams='SeedSequence([seed, algorithm_index, 2026]); Python Random operators',
        unit_search='u in [0,1]^20; x=-100+200*u; every CEC query counts one FE',
        GA='production tournament3/SBX0.9 eta15/mutation1D eta20; parent+child bestN',
        PO='production four behaviors; parent replaced even worse; own best; mean at generation start',
        ISLAND80='production24GA/6PO; PO archive6; migration every2 except final; protect elite; pre-migration sources',
        numerical_phenotype='exact unit vector, no distance threshold',
        CEC_commit=OFFICIAL_COMMIT,archive_sha256=ARCHIVE_SHA256,dll_sha256=sha(LIBRARY_PATH),
        evaluator_data={str(f.relative_to(SOURCE_DIRECTORY)):sha(f)
                        for f in sorted((SOURCE_DIRECTORY/'input_data').glob('*')) if f.is_file()},
        source_sha256=source_hashes())
    config=out/'config.json'
    if config.exists():
        if not a.resume: raise RuntimeError('Existing output; --resume must be explicit.')
        if json.loads(config.read_text(encoding='utf8'))!=protocol:
            raise RuntimeError('Resume source/config does not match.')
    else: atomic_json(config,protocol)
    expected=[(f,s) for f in range(1,a.functions+1) for s in range(1,a.seeds+1)]
    start=time.time()
    def status(state,**extra):
        count=sum(1 for _ in (out/'runs').glob('*/*.json'))
        atomic_json(out/'status.json',dict(status=state,controller_pid=os.getpid(),
            command_line=sys.argv,started_epoch=start,updated_at=now(),workers=a.workers,
            saved_runs=count,total_runs=len(expected)*3,elapsed_seconds=time.time()-start,**extra))
    status('RUNNING');print(json.dumps(dict(pid=os.getpid(),workers=a.workers,total=len(expected)*3)),flush=True)
    try:
        with ProcessPoolExecutor(max_workers=a.workers) as pool:
            futures={pool.submit(run_cohort,(str(out),f,s,a.max_fe,a.resume)):(f,s) for f,s in expected}
            for future in as_completed(futures):
                try:
                    key=future.result()
                except BaseException as error:
                    status('FAILED',error=f'{type(error).__name__}: {error}')
                    for pending in futures: pending.cancel()
                    raise
                status('RUNNING',last_completed_cohort=key)
                print(f'{key} completed',flush=True)
        if protocol['source_sha256']!=source_hashes(): raise RuntimeError('Frozen source changed.')
        aggregate(out,expected,a.max_fe)
        status('COMPLETED')
    except BaseException as e:
        status('FAILED',error=f'{type(e).__name__}: {e}',traceback=traceback.format_exc())
        raise

if __name__=='__main__':main()
