"""TARGET_PO80 integration: frozen trajectory, real pipeline, budgets and IO."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
from random import Random
from unittest.mock import patch

import pytest

from gapo_timetabling.core import hybrid, target_hybrid as target, po, decoder
from gapo_timetabling.core.encoder import build_option_domains
from gapo_timetabling.core.population import (
    CandidateEvaluationConfig, CandidateEvaluationStatus, evaluate_candidate,
    initialize_population,
)
from gapo_timetabling.core.placement_decoder import PlacementDecoder
from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.fitness import calculate_fitness
from gapo_timetabling.application.optimization_service import (
    OptimizationRunConfig, _optimization_config_payload, optimization_config_from_json,
)
from gapo_timetabling.application.run_contract import parse_run_request, RunContractError
from gapo_timetabling.core.models import OptimizationAlgorithm
from tests import reference_target_po80 as reference
from tests.test_constraints import ConstraintFixture
from tests import test_dynamic_lecturer_assignment as fixtures
from tests.test_run_contract import make_run_request_payload


def inputs(seed=1, *, fixed=False, repair=False, size=30, iterations=20):
    if fixed:
        fixture=ConstraintFixture(); fixture.setUp(); problem=fixture.problem
    else:
        problem=fixtures.TestDynamicLecturerAssignment().build_problem(first_lecturer_unavailable=repair)
    domains=build_option_domains(problem)
    evaluation=CandidateEvaluationConfig(500, True, 3)
    initial=initialize_population(problem,domains,size,5000,seed,evaluation)
    assert initial.is_success
    return problem,domains,initial,hybrid.HybridConfig(size*(iterations+1),5,seed,evaluation)


def stable(result):
    value=asdict(result); value['metrics'].pop('runtime_seconds')
    value.pop('hybrid_activity')
    return value


@pytest.mark.parametrize('seed',[1,7,42])
@pytest.mark.parametrize('repair',[False,True])
def test_exact_frozen_research_trajectory_and_activity(seed,repair):
    assert sha256(Path(reference.__file__).read_bytes()).hexdigest()=='b63d412cda990992a1d9d19548226c0a7569a3ac0f6c86f98210d43fc96398a1'
    args=inputs(seed,repair=repair)
    expected,activity=reference.run_target(*args)
    actual=hybrid.run_hybrid(*args)
    assert stable(actual)==stable(expected)
    assert actual.hybrid_activity==activity
    assert actual.hybrid_activity['counts']['ga_slots']==480
    assert actual.hybrid_activity['counts']['target_slots']==120


@pytest.mark.parametrize('reason,component',[
    ('gap','gap_component'),('consecutive','lecturer_consecutive_component'),
    ('room','room_discouraged_component'),('workload','workload_balance_component'),
    ('suitability','course_suitability_component'),('preference',None),
])
def test_group_choice_matches_reference_and_does_not_rescore(reason,component):
    problem,domains,initial,_=inputs()
    item=initial.individuals[0]
    fields=dict(gap_component=0.,lecturer_consecutive_component=0.,room_discouraged_component=0.,workload_balance_component=0.,course_suitability_component=0.)
    if component:fields[component]=1.
    item=replace(item,fitness=replace(item.fitness,breakdown=replace(item.fitness.breakdown,**fields)))
    with patch.object(target.fitness,'calculate_fitness',side_effect=AssertionError('extra FE')):
        actual=target.Targeter(problem).choose(item,Random(41))
    assert actual==reference.Targeter(problem).choose(item,Random(41))
    assert actual[2]==reason
    assert actual[0] and min(actual[0])>=0 and max(actual[0])<problem.dimension


@pytest.mark.parametrize('behavior',list(po.PoBehavior))
def test_original_po_formulas_on_mask_and_unchanged_outside(behavior):
    p,_,initial,_=inputs()
    anchor=initial.individuals[0]; pool=initial.individuals[24:]
    mask,_,_=target.Targeter(p).choose(anchor,Random(1))
    actual=target.propose(anchor,pool,anchor,mask,0,behavior,3,.1,.3,Random(22),max_iterations=20)
    expected=reference.propose(anchor,pool,anchor,mask,0,behavior,3,.1,.3,Random(22),False)
    assert actual==expected
    assert all(x==anchor.vector[j] for j,x in enumerate(actual) if j not in mask)
    assert all(0<=x<=1 for x in actual)


@pytest.mark.parametrize('size,iterations',[(8,0),(10,1),(30,10),(60,3)])
def test_configured_population_iterations_not_hardcoded(size,iterations):
    args=inputs(size=size,iterations=iterations)
    result=hybrid.run_hybrid(*args)
    assert len(result.final_population)==size
    assert result.metrics.completed_iterations==iterations
    assert len(result.convergence_history)==iterations+1
    assert result.metrics.fitness_evaluations<=size*(iterations+1)
    assert result.hybrid_activity['counts'].get('target_slots',0)==(size-round(size*.8))*iterations


def test_failure_retries_do_not_manufacture_fe_or_drop_population():
    args=inputs(size=10,iterations=2)
    p,domains,initial,config=args
    value=evaluate_candidate(p,domains,initial.individuals[0].vector,config.evaluation_config)
    failed=replace(value,status=CandidateEvaluationStatus.DECODE_FAILED,individual=None,fitness_evaluations=0)
    with patch.object(target,'evaluate_candidate',return_value=failed) as call:
        result=hybrid.run_hybrid(*args)
    assert call.call_count==10*2*5
    assert result.metrics.fitness_evaluations==10
    assert result.metrics.discarded_offspring_count==20
    assert len(result.final_population)==10


def test_valid_worse_target_replaces_memory_without_ga_injection_or_best_loss():
    p,domains,initial,config=inputs(size=10,iterations=1)
    value=evaluate_candidate(p,domains,initial.individuals[0].vector,config.evaluation_config)
    worse=replace(value.individual,fitness=replace(value.individual.fitness,general_quality_score=10.))
    value=replace(value,individual=worse)
    with patch.object(target,'evaluate_candidate',return_value=value):
        result=hybrid.run_hybrid(p,domains,initial,config)
    assert all(item==worse for item in result.final_population[8:])
    assert result.hybrid_activity['counts'].get('injected',0)==0
    assert result.best_individual.fitness_key==min(i.fitness_key for i in initial.individuals)


def test_cancel_and_parallel_calls_keep_inputs_and_rng_isolated():
    args=inputs(size=10,iterations=2)
    before=asdict(args[2])
    def stop(progress):
        if progress.metrics.fitness_evaluations>10:raise InterruptedError('cancel')
    with pytest.raises(InterruptedError,match='cancel'):hybrid.run_hybrid(*args,progress_callback=stop)
    expected=stable(hybrid.run_hybrid(*args))
    with ThreadPoolExecutor(max_workers=3) as executor:
        actual=list(executor.map(lambda _:stable(hybrid.run_hybrid(*args)),range(3)))
    assert all(r==expected for r in actual)
    assert asdict(args[2])==before


def test_fixed_snapshot_works_and_final_vectors_replay_with_no_soft_search():
    args=inputs(fixed=True,size=10,iterations=2)
    engine=PlacementDecoder(); decoder.clear_decode_cache(); decoder._PRIORITY_LOCAL.decoder=engine
    try: result=hybrid.run_hybrid(*args)
    finally: decoder.clear_decode_cache()
    assert engine.stats['soft_option_scores']==0
    for item in result.final_population+(result.best_individual,):
        replay=PlacementDecoder()(args[0],args[1],item.vector,500)
        assert replay.selected_options==item.selected_options
        assert replay.selected_option_indices==item.selected_option_indices
        assert validate_timetable(args[0],replay.selected_options).is_valid
        assert calculate_fitness(args[0],replay.selected_options,args[1])==item.fitness


def test_mechanism_version_and_old_pending_request_are_not_reinterpreted(tmp_path):
    assert hybrid.HYBRID_MECHANISM=='GA_PO_TARGET_PO80.v1'
    config=OptimizationRunConfig(algorithm=OptimizationAlgorithm.GA_PO,population_size=10,
        max_fitness_evaluations=20,random_seed=1,algorithm_version='test',max_initialization_attempts=100,max_offspring_attempts=5)
    raw=_optimization_config_payload(config)
    assert optimization_config_from_json(json.dumps(raw))==config
    raw['hybrid_mechanism']=hybrid.ISLAND_HYBRID_MECHANISM
    with pytest.raises(ValueError,match='cơ chế lai cũ'):optimization_config_from_json(json.dumps(raw))
    payload=make_run_request_payload('unused.json')
    payload['hybrid']['mechanism']=hybrid.ISLAND_HYBRID_MECHANISM
    with pytest.raises(RunContractError,match='TARGET_PO80'):parse_run_request(payload,base_directory=tmp_path)
    with pytest.raises(ValueError,match='GA individuals'):hybrid.validate_target_sizes(10,.4)


@pytest.mark.parametrize('scale,dimension,occurrences',[
    ('small',60,232),('medium',90,343),('large',120,454),
])
def test_current_target_suite_separates_historical_results(scale,dimension,occurrences):
    root=Path(__file__).resolve().parents[1]
    folder=root/'benchmark_configs/target_po80_stress'
    suite=json.loads((folder/'timetable_stress_suite.json').read_text(encoding='utf-8'))
    case=next(c for c in suite['cases'] if c['case_id']==scale)
    assert (case['dimension'],case['class_session_count'])==(dimension,occurrences)
    experiment=json.loads((folder/case['experiment_config_path']).read_text(encoding='utf-8'))
    assert experiment['seeds']==list(range(1,11))
    assert experiment['algorithms']==['GA','PO','GA_PO']
    raw=json.loads((folder/experiment['base_request_path']).read_text(encoding='utf-8'))
    request=parse_run_request(raw,base_directory=folder)
    assert raw['hybrid']['mechanism']==hybrid.HYBRID_MECHANISM
    assert request.population_size==30 and request.max_fitness_evaluations==630
    assert request.ga_ratio==.8
    assert request.snapshot.path.resolve()==(root/f'benchmark_configs/stress/data/{scale}.json').resolve()
