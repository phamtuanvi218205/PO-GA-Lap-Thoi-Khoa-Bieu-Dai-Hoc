"""Real spawn-process parity checks, no SQL and no benchmark optimizer reruns."""
from copy import deepcopy
from dataclasses import replace
import multiprocessing as mp
from pathlib import Path
from time import monotonic
import pytest

from gapo_timetabling.application import parallel_execution as parallel
from gapo_timetabling.application.run_contract import parse_run_request,execute_prepared_run_request
from gapo_timetabling.application.run_control import OptimizationRunCancelled
from gapo_timetabling.core.snapshot import prepare_snapshot_for_optimization
from tests.test_run_contract import make_run_request_payload
from tests.test_snapshot import make_snapshot_payload


@pytest.mark.parametrize('method',['GA','PO','GA_PO'])
def test_real_process_result_and_fe_match_serial(method,monkeypatch):
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS','2')
    prepared=prepare_snapshot_for_optimization(make_snapshot_payload())
    payload=make_run_request_payload('not-used.json',algorithm=method)
    payload['max_fitness_evaluations']=40
    request=parse_run_request(payload,base_directory=Path.cwd())
    before=set(p.pid for p in mp.active_children())
    serial=execute_prepared_run_request(request,prepared)
    progress=[]
    actual=parallel.execute_web_run_request(request,prepared,progress_callback=progress.append)
    execution=actual.pop('execution')
    assert execution['workers']==2 and execution['consumed_decodes']>=40
    assert execution['fitness_calls']==actual['result']['metrics']['fitness_evaluations']<=40
    assert execution['search_semantics']=='serial'
    assert progress
    serial['result']['metrics'].pop('runtime_seconds')
    actual['result']['metrics'].pop('runtime_seconds')
    assert actual==serial
    assert set(p.pid for p in mp.active_children())==before


def test_cancellation_cleans_up_child_processes(monkeypatch):
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS','2')
    prepared=prepare_snapshot_for_optimization(make_snapshot_payload())
    request=parse_run_request(make_run_request_payload('unused.json'),base_directory=Path.cwd())
    before=set(p.pid for p in mp.active_children())
    def cancel(): raise OptimizationRunCancelled('test cancel')
    with pytest.raises(OptimizationRunCancelled):
        parallel.execute_web_run_request(request,prepared,check_interruption=cancel)
    assert set(p.pid for p in mp.active_children())==before
    assert parallel._allocated_workers==0


def test_serial_opt_out_does_not_start_process(monkeypatch):
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS','1')
    prepared=prepare_snapshot_for_optimization(make_snapshot_payload())
    request=parse_run_request(make_run_request_payload('unused.json'),base_directory=Path.cwd())
    with monkeypatch.context() as m:
        m.setattr(parallel.mp,'get_context',lambda *args: pytest.fail('must not spawn'))
        result=parallel.execute_web_run_request(request,prepared)
    assert result['status']=='COMPLETED' and 'execution' not in result


def test_worker_budget_accounts_for_cpu_memory_and_setting(monkeypatch):
    monkeypatch.setattr(parallel.os,'cpu_count',lambda:16)
    monkeypatch.setattr(parallel,'available_memory_bytes',lambda:4*1024**3)
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS','auto')
    assert parallel.recommended_workers()==8
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS','4')
    assert parallel.recommended_workers()==4
    monkeypatch.setattr(parallel,'available_memory_bytes',lambda:1100*1024**2)
    assert parallel.recommended_workers()==1
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS','0')
    with pytest.raises(ValueError): parallel.recommended_workers()


@pytest.mark.parametrize('method',['GA','PO','GA_PO'])
@pytest.mark.parametrize('scenario',['recurring','assignment_repair'])
def test_parity_for_recurring_groups_and_assignment_failures(method,scenario,monkeypatch):
    from tests.test_schedule_adjustment import recurring_fixture
    from tests.test_dynamic_lecturer_assignment import TestDynamicLecturerAssignment
    from gapo_timetabling.core.encoder import build_option_domains
    from gapo_timetabling.core.population import CandidateEvaluationConfig
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS','3')
    prepared=prepare_snapshot_for_optimization(make_snapshot_payload())
    if scenario=='recurring': problem,domains,_=recurring_fixture()
    else:
        problem=TestDynamicLecturerAssignment().build_problem(first_lecturer_unavailable=True)
        domains=build_option_domains(problem)
    prepared=replace(prepared,problem=problem,option_domains=domains)
    request=parse_run_request(make_run_request_payload('unused.json',algorithm=method),base_directory=Path.cwd())
    request=replace(request,max_initialization_attempts=200,
        evaluation_config=CandidateEvaluationConfig(100,True,3))
    serial=execute_prepared_run_request(request,prepared)
    actual=parallel.execute_web_run_request(request,prepared)
    execution=actual.pop('execution')
    assert serial['status']==actual['status']=='COMPLETED'
    assert execution['fitness_calls']==actual['result']['metrics']['fitness_evaluations']
    if scenario=='assignment_repair': assert actual['result']['metrics']['candidate_attempts']>0
    for result in (serial,actual): result['result']['metrics'].pop('runtime_seconds')
    assert serial==actual


def test_cancellation_during_active_worker_decode_and_progress(monkeypatch):
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS','2')
    prepared=prepare_snapshot_for_optimization(make_snapshot_payload())
    request=parse_run_request(make_run_request_payload('unused.json'),base_directory=Path.cwd())
    before=set(p.pid for p in mp.active_children())
    def cancel_after_first(progress):
        if progress.metrics.fitness_evaluations>=1: raise OptimizationRunCancelled('after first FE')
    with pytest.raises(OptimizationRunCancelled):
        parallel.execute_web_run_request(request,prepared,progress_callback=cancel_after_first)
    assert set(p.pid for p in mp.active_children())==before
    assert parallel._allocated_workers==0


def test_n60_target_hybrid_preserves_full_result(monkeypatch):
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS','4')
    prepared=prepare_snapshot_for_optimization(make_snapshot_payload())
    payload=make_run_request_payload('unused.json')
    payload.update(population_size=60,max_fitness_evaluations=240,max_initialization_attempts=1000,random_seed=42)
    request=parse_run_request(payload,base_directory=Path.cwd())
    serial=execute_prepared_run_request(request,prepared)
    actual=parallel.execute_web_run_request(request,prepared)
    assert actual.pop('execution')['fitness_calls']==240
    for result in (serial,actual): result['result']['metrics'].pop('runtime_seconds')
    assert serial==actual


def test_timeout_during_progress_cleans_up_and_releases_budget(monkeypatch):
    from gapo_timetabling.application.run_control import OptimizationRunTimedOut
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS','2')
    prepared=prepare_snapshot_for_optimization(make_snapshot_payload())
    request=parse_run_request(make_run_request_payload('unused.json'),base_directory=Path.cwd())
    before=set(p.pid for p in mp.active_children())
    def timeout(progress): raise OptimizationRunTimedOut('test deadline')
    with pytest.raises(OptimizationRunTimedOut):
        parallel.execute_web_run_request(request,prepared,progress_callback=timeout)
    assert parallel._allocated_workers==0
    assert set(p.pid for p in mp.active_children())==before
