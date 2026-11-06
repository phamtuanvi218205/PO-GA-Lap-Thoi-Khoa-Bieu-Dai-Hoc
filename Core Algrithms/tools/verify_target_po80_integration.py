"""Read-only replay of saved TARGET_PO80 evidence, not an optimizer benchmark.

Writes only the requested verification report. Never changes old manifests,
saved results or frozen research sources. Run from the repository root with
PYTHONPATH='Core Algrithms/src'.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from random import Random
import sys
from zipfile import ZipFile

from gapo_timetabling.core import po, target_hybrid


CORE=Path(__file__).resolve().parents[1]
ROOT=CORE/'test_results/target_po80_d155_20261105'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value
    spec.loader.exec_module(value)
    return value


def verify():
    helper=module('target_integration_evidence_helper',ROOT/'evidence_helpers.py')
    reference=module('target_integration_reference',CORE/'tests/reference_target_po80.py')
    assert digest(ROOT/'target.py')=='3115fed10c26e3f4d31056646526e86857292911925af014ca9b3a7fab2d4dc5'
    assert digest(CORE/'tests/reference_target_po80.py')=='b63d412cda990992a1d9d19548226c0a7569a3ac0f6c86f98210d43fc96398a1'
    manifest=read(ROOT/'manifest.json')
    changes=[]
    for name,expected in manifest['sha256'].items():
        path=Path(name)
        if digest(path)!=expected:
            changes.append(path.relative_to(CORE).as_posix())
    expected_changes={
        'src/gapo_timetabling/core/hybrid.py',
        'src/gapo_timetabling/core/metrics.py',
        'src/gapo_timetabling/application/run_contract.py',
    }
    assert set(changes)==expected_changes,changes
    # The historical manifest remains intact. Only the three intentionally
    # integrated live modules differ; GA/PO/Encoder/Decoder/Fitness are unchanged.
    results=[]; cohorts={}; mask_checks=0; proposal_checks=0
    with ZipFile(helper.BUNDLE/'evidence/d155.zip') as archive:
        for scale in helper.CASES:
            _,prepared=helper.snapshot(scale)
            current=target_hybrid.Targeter(prepared.problem)
            original=reference.Targeter(prepared.problem)
            for seed in helper.SEEDS:
                initial,meta=helper.load_initial(archive,manifest['archives']['d155'],scale,seed)
                name=f'{scale}_{seed}_TARGET_PO80.json'
                result_path=ROOT/'runs'/name
                detail_path=ROOT/'details'/name
                checkpoint=read(ROOT/'checkpoints'/name)
                result,detail=read(result_path),read(detail_path)
                assert digest(result_path)==checkpoint['result_sha']
                assert digest(detail_path)==checkpoint['detail_sha']
                assert checkpoint['initial_sha']==detail['initial_sha']==meta['initial_sha']
                assert detail['records'][:30]==meta['records']
                assert result['status']=='COMPLETED' and result['algorithm']=='TARGET_PO80'
                assert result['snapshot_checksum']==prepared.snapshot_checksum
                assert detail['decoder_work']['soft_option_scores']==0
                helper.validate_trace(result,detail['trace'])
                checked=helper.audit(result,prepared)
                cohorts[f'{scale}_{seed}']=meta['initial_sha']
                pool=initial.individuals[24:]
                guide=min(initial.individuals,key=lambda item:item.fitness_key)
                for index,anchor in enumerate(initial.individuals[:6]):
                    mask,sessions,reason=current.choose(anchor,Random(seed+index))
                    assert (mask,sessions,reason)==original.choose(anchor,Random(seed+index))
                    mask_checks+=1
                    for behavior in po.PoBehavior:
                        a=Random(seed+index+1000); b=Random(seed+index+1000)
                        vector=target_hybrid.propose(anchor,pool,guide,mask,index,behavior,3,.1,.3,a,max_iterations=20)
                        assert vector==reference.propose(anchor,pool,guide,mask,index,behavior,3,.1,.3,b,False)
                        assert a.getstate()==b.getstate()
                        assert all(vector[j]==anchor.vector[j] for j in range(len(vector)) if j not in mask)
                        proposal_checks+=1
                results.append(dict(scale=scale,seed=seed,**checked))
                print(f'Replayed {scale} seed {seed}: hard0 / full coverage / fitness and entries match',flush=True)
    assert len(results)==len(cohorts)==len(set(cohorts.values()))==30
    return dict(
        method='TARGET_PO80',optimizer_rerun=False,word_modified=False,
        saved_best_replays=results,shared_initial_sha=cohorts,
        real_d155_mask_comparisons=mask_checks,real_d155_formula_comparisons=proposal_checks,
        intentionally_changed_live_sources=changes,historical_manifest_modified=False,
        current_source_sha256={str(path.relative_to(CORE)):digest(path) for path in (
            CORE/'src/gapo_timetabling/core/hybrid.py',CORE/'src/gapo_timetabling/core/target_hybrid.py',
            CORE/'src/gapo_timetabling/core/metrics.py',CORE/'src/gapo_timetabling/application/run_contract.py',
        )},
    )


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=verify()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'PASS: 30 best replays; {report["real_d155_mask_comparisons"]} mask and {report["real_d155_formula_comparisons"]} formula comparisons. No optimizer rerun.')
