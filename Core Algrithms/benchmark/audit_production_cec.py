"""Read-only independent audit of completed production CEC results."""
import sys, json, hashlib, argparse, math, csv
from pathlib import Path
import numpy as np

def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args()
    out=a.output.resolve()
    sys.path.insert(0,str(out/'source/benchmark'))
    from benchmark_functions import get_cec2022_suite
    from experiment import create_initial_population, _algorithm_seed
    from prepare_cec2022 import LIBRARY_PATH, SOURCE_DIRECTORY
    sha=lambda x:hashlib.sha256(Path(x).read_bytes()).hexdigest()
    cfg=json.loads((out/'config.json').read_text(encoding='utf8'))
    environment=json.loads((out/'runtime_environment.json').read_text(encoding='utf8'))
    assert environment['numpy']==np.__version__
    assert sha(SOURCE_DIRECTORY/'cec22_test_func.cpp')==environment['official_cpp_sha256']
    assert sha(out/'source/benchmark/cec2022_native_wrapper.cpp')==environment['wrapper_sha256']
    assert json.loads((out/'status.json').read_text(encoding='utf8'))['status']=='COMPLETED'
    for path,value in cfg['source_sha256'].items():
        assert sha(out/'source'/path)==value,path
        current=Path(__file__).resolve().parent.parent/path
        assert sha(current)==value,('Current source differs',path)
    assert sha(LIBRARY_PATH)==cfg['dll_sha256']
    for path,value in cfg['evaluator_data'].items():assert sha(SOURCE_DIRECTORY/path)==value
    suite=get_cec2022_suite(20);runs=0;trace_points=0;cohort_sha={}
    for number in range(1,cfg['functions']+1):
        fn=suite[number-1]
        for seed in cfg['seeds']:
            key=f'F{number:02d}_seed_{seed:02d}'
            expected=create_initial_population(fn,20,30,seed)
            with np.load(out/'initial'/f'{key}.npz') as z:
                np.testing.assert_array_equal(z['population'],expected)
            digest=hashlib.sha256(expected.astype('<f8').tobytes()).hexdigest()
            cohort_sha[key]=digest
            for index,name in enumerate(cfg['algorithms'],1):
                case=json.loads((out/'runs'/name/f'{key}.json').read_text(encoding='utf8'))
                assert case['initial_sha256']==digest
                assert case['algorithm_seed']==_algorithm_seed(seed,index)
                assert case['actual_FE']==cfg['max_FE']==case['row']['max_evaluations']
                assert case['completed_generations']==(cfg['max_FE']-30)//30
                physical=-100+200*np.asarray(case['best_unit'])
                np.testing.assert_array_equal(physical,case['best_position'])
                value=float(fn.evaluate_population(physical.reshape(1,-1))[0])
                assert math.isclose(value,case['row']['best_value'],rel_tol=1e-12,abs_tol=1e-10)
                assert value>=fn.optimum_value-1e-10*max(1,abs(fn.optimum_value))
                trace=out/'traces'/name/f'{key}.npz'
                assert sha(trace)==case['trace_sha256']
                with np.load(trace) as z:
                    fe,best=z['fe'],z['best']
                    np.testing.assert_array_equal(fe,np.arange(30,cfg['max_FE']+1,30))
                    assert np.isfinite(best).all() and np.all(np.diff(best)<=0)
                    assert float(best[-1])==case['row']['best_value']
                    assert math.isclose(float(best[0]),float(np.min(fn.evaluate_population(expected))),rel_tol=1e-12,abs_tol=1e-10)
                    pop,fit=z['final_population'],z['final_fitness']
                    assert pop.shape==(30,20) and np.isfinite(pop).all()
                    assert np.all(pop>=0) and np.all(pop<=1)
                    np.testing.assert_allclose(fn.evaluate_population(-100+200*pop),fit,rtol=1e-12,atol=1e-10)
                    trace_points+=len(fe)
                if name=='ISLAND80':
                    d=case['diagnostics'];g=case['completed_generations']
                    assert d['ga_offspring']==24*g and d['po_offspring']==6*g
                    assert d['migration_events']==(g-1)//2
                    assert sum(d['po_behaviors'])==6*g
                runs+=1
    assert runs==cfg['functions']*len(cfg['seeds'])*3
    # Independently recompute summaries and the stated statistical tests from
    # all raw outcomes, rather than trusting generated display tables.
    from scipy.stats import rankdata, friedmanchisquare, wilcoxon
    def readcsv(path):
        with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    raw=readcsv(out/'raw_results.csv');summary=readcsv(out/'summary.csv')
    expected_keys={(f'CEC2022-F{i}',m,s) for i in range(1,cfg['functions']+1)
                   for m in cfg['algorithms'] for s in cfg['seeds']}
    assert {(x['function'],x['algorithm'],int(x['seed'])) for x in raw}==expected_keys
    assert len(raw)==len(expected_keys)
    medians=[]
    for i in range(1,cfg['functions']+1):
        values=[]
        for method in cfg['algorithms']:
            errors=np.asarray([float(x['final_error']) for x in raw
                if x['function']==f'CEC2022-F{i}' and x['algorithm']==method])
            assert len(errors)==len(cfg['seeds'])
            item=next(x for x in summary if x['function']==f'CEC2022-F{i}' and x['algorithm']==method)
            for field,val in [('median_error',np.median(errors)),('mean_error',np.mean(errors)),
                              ('std_error',np.std(errors,ddof=1)),('best_error',np.min(errors)),
                              ('worst_error',np.max(errors))]:
                assert math.isclose(float(item[field]),float(val),rel_tol=1e-12,abs_tol=1e-12)
            values.append(float(np.median(errors)))
        medians.append(values)
    matrix=np.asarray(medians);avg=np.mean([rankdata(row,method='average') for row in matrix],axis=0)
    for row in readcsv(out/'average_ranks.csv'):
        assert math.isclose(float(row['average_rank']),avg[cfg['algorithms'].index(row['algorithm'])],abs_tol=1e-12)
    tests=readcsv(out/'statistical_tests.csv')
    fr=friedmanchisquare(*matrix.T)
    assert math.isclose(float(tests[0]['statistic']),float(fr.statistic),abs_tol=1e-12)
    assert math.isclose(float(tests[0]['p_value']),float(fr.pvalue),abs_tol=1e-12)
    ps=[]
    for first,second in [(0,1),(0,2),(1,2)]:
        test=wilcoxon(matrix[:,first],matrix[:,second],zero_method='zsplit')
        row=tests[len(ps)+1]
        assert math.isclose(float(row['statistic']),float(test.statistic),abs_tol=1e-12)
        assert math.isclose(float(row['p_value']),float(test.pvalue),abs_tol=1e-12)
        ps.append(float(test.pvalue))
    adjusted={};previous=0
    for position,index in enumerate(sorted(range(3),key=lambda k:ps[k])):
        previous=max(previous,min(1.,ps[index]*(3-position)));adjusted[index]=previous
    assert all(math.isclose(float(tests[i+1]['holm_adjusted_p']),adjusted[i],abs_tol=1e-12) for i in range(3))
    result=dict(runs_checked=runs,initial_cohorts=len(cohort_sha),full_generation_trace_points=trace_points,
        shared_initial=True,best_replay=True,final_population_replay=True,exact_FE=True,
        main_and_frozen_source_SHA_match=True,evaluator_SHA_match=True,
        migration_schedule=True,physical_mapping=True,summary_rank_Friedman_Wilcoxon_Holm_recomputed=True,
        extra_optimizer_runs=0)
    (out/'independent_audit.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
