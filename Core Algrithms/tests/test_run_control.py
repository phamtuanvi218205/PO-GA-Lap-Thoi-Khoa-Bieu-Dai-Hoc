"""Kiểm thử progress, timeout và cờ hủy hợp tác."""

from __future__ import annotations

import pytest

import gapo_timetabling.application.run_control as control_module
from gapo_timetabling.application.run_control import (
    OptimizationRunCancelled,
    OptimizationRunTimedOut,
    RunExecutionControl,
)
from gapo_timetabling.core.metrics import OptimizationMetrics, OptimizationProgress
from gapo_timetabling.core.models import OptimizationAlgorithm


def make_progress(fitness_evaluations: int = 20) -> OptimizationProgress:
    metrics = OptimizationMetrics(
        completed_iterations=2,
        candidate_attempts=25,
        fitness_evaluations=fitness_evaluations,
        decode_failed_count=3,
        validation_failed_count=2,
        repaired_individual_count=0,
        failed_repair_count=0,
        total_repair_attempts=0,
        discarded_offspring_count=1,
        total_decode_nodes=100,
        total_decode_backtracks=10,
        runtime_seconds=0.0,
    )
    return OptimizationProgress(
        algorithm=OptimizationAlgorithm.GA_PO,
        iteration=2,
        max_iterations=10,
        max_fitness_evaluations=100,
        metrics=metrics,
        best_general_quality_score=0.2,
        best_lecturer_preference_score=0.4,
    )


def test_reports_progress_and_binds_database_run() -> None:
    observed = []
    control = RunExecutionControl(
        max_fitness_evaluations=100,
        progress_listener=observed.append,
    )

    control.bind_run_id(7)
    control.report(make_progress())

    snapshot = control.snapshot()
    assert snapshot.run_id == 7
    assert snapshot.status == "RUNNING"
    assert snapshot.fitness_evaluations == 20
    assert snapshot.progress_ratio == pytest.approx(0.2)
    assert len(observed) == 2


def test_cancel_request_stops_at_next_checkpoint() -> None:
    control = RunExecutionControl(max_fitness_evaluations=100)
    control.request_cancel()

    with pytest.raises(OptimizationRunCancelled):
        control.report(make_progress())


def test_timeout_begins_when_run_id_is_bound(monkeypatch) -> None:
    current_time = [10.0]
    monkeypatch.setattr(control_module, "monotonic", lambda: current_time[0])
    control = RunExecutionControl(
        max_fitness_evaluations=100,
        timeout_seconds=5,
    )

    current_time[0] = 100.0
    control.check_interruption()  # Thời gian chờ QUEUED không tính timeout.
    control.bind_run_id(7)
    current_time[0] = 106.0

    with pytest.raises(OptimizationRunTimedOut):
        control.check_interruption()
