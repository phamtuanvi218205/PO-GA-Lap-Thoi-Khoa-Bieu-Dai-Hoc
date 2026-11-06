from dataclasses import replace
from datetime import datetime,timezone
from gapo_timetabling.application import run_manager as module
from gapo_timetabling.application.run_control import RunExecutionControl,RunProgressSnapshot
from gapo_timetabling.application.run_manager import OptimizationRunManager,OptimizationJobSnapshot,_ManagedJob,_snapshot_from_run_row


def progress(iteration=0,maximum=0,fe=0):
    return RunProgressSnapshot(8,'RUNNING',iteration,maximum,fe,3060,fe/3060,.1,.2,datetime.now(timezone.utc),fe+10,10)


def make_manager(monkeypatch):
    clock=[100.]; monkeypatch.setattr(module,'monotonic',lambda:clock[0])
    manager=OptimizationRunManager(lambda:None,max_workers=1)
    snapshot=OptimizationJobSnapshot('run-8',1,'PENDING',8,0,3060,0.,0,50,None,None,datetime.now(timezone.utc),datetime.now(timezone.utc))
    manager._jobs['run-8']=_ManagedJob(snapshot,RunExecutionControl(max_fitness_evaluations=3060))
    return manager,clock


def test_history_only_records_real_initialization_and_round_boundaries(monkeypatch):
    manager,clock=make_manager(monkeypatch)
    try:
        manager._apply_progress('run-8',progress())
        clock[0]=110; manager._apply_progress('run-8',progress(fe=30))
        assert not manager.get_job('run-8').iteration_history
        clock[0]=120; manager._apply_progress('run-8',progress(maximum=50,fe=60))
        clock[0]=125; manager._apply_progress('run-8',progress(maximum=50,fe=75))
        assert len(manager.get_job('run-8').iteration_history)==1
        clock[0]=130; manager._apply_progress('run-8',progress(1,50,119))
        row=manager.get_job('run-8').iteration_history[-1]
        assert row.iteration==1 and row.new_fitness_evaluations==59
        assert row.duration_seconds==10 and row.elapsed_seconds==30
        assert row.best_general_quality_score==.1
        assert manager.get_job('run-8').candidate_attempts==129
    finally: manager.shutdown()


def test_elapsed_keeps_advancing_without_fake_progress_and_freezes_on_finish(monkeypatch):
    manager,clock=make_manager(monkeypatch)
    try:
        manager._apply_progress('run-8',progress(maximum=50,fe=60))
        clock[0]=170
        job=manager.get_job('run-8')
        assert job.elapsed_seconds==70 and job.fitness_evaluations==60
        assert len(job.iteration_history)==1
        manager._set_status('run-8','COMPLETED')
        clock[0]=200; assert manager.get_job('run-8').elapsed_seconds==70
    finally: manager.shutdown()


def test_database_fallback_does_not_invent_round_history():
    row=dict(run_id=8,scenario_id=1,status='COMPLETED',population_size=60,max_fitness_evaluations=3060,
        current_fitness_evaluations=3000,completed_iterations=50,started_at=datetime(2026,1,1,1),finished_at=datetime(2026,1,1,1,2))
    snapshot=_snapshot_from_run_row(row)
    assert snapshot.elapsed_seconds==120 and snapshot.iteration_history==()
    assert snapshot.candidate_attempts is None
