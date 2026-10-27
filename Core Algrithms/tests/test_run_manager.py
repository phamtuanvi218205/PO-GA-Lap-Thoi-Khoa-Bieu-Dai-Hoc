"""Kiểm thử hàng đợi chạy nền mà không cần SQL Server thật."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from threading import Event
from time import monotonic

import pytest

import gapo_timetabling.application.run_manager as manager_module
from gapo_timetabling.application.optimization_service import (
    OptimizationRunConfig,
    PersistedOptimizationRun,
)
from gapo_timetabling.application.run_control import OptimizationRunCancelled
from gapo_timetabling.application.run_manager import (
    OptimizationJobNotFoundError,
    OptimizationRunManager,
)
from gapo_timetabling.core.metrics import OptimizationMetrics, OptimizationProgress
from gapo_timetabling.core.models import OptimizationAlgorithm


class FakeCursor:
    def __init__(self, run_id: int = 18) -> None:
        self.run_id = run_id
        self.description = None
        self._row = None

    def execute(self, sql, *parameters):
        if "UPDATE OptimizationRun" in sql and "cancel_requested = 1" in sql:
            self._set_run_row("RUNNING")
            return self
        if "FROM OptimizationRun" in sql and "WHERE run_id = ?" in sql:
            self._set_run_row("RUNNING")
            return self
        raise AssertionError(f"Truy vấn không được fake hỗ trợ: {sql}")

    def fetchone(self):
        return self._row

    def _set_run_row(self, status: str) -> None:
        columns = [
            "run_id", "scenario_id", "status", "population_size",
            "max_fitness_evaluations", "current_fitness_evaluations",
            "completed_iterations", "queued_at", "started_at",
            "progress_updated_at", "finished_at", "general_quality_score",
            "lecturer_preference_score", "error_message",
        ]
        now = datetime(2026, 10, 22)
        values = [
            self.run_id, 3, status, 4, 20, 8, 2, now, now, now,
            None, 0.2, 0.3, None,
        ]
        self.description = [(column,) for column in columns]
        self._row = tuple(values)


class FakeConnection:
    def __init__(self, run_id: int = 18) -> None:
        self.closed = False
        self.fake_cursor = FakeCursor(run_id)

    def cursor(self):
        return self.fake_cursor

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def make_config() -> OptimizationRunConfig:
    return OptimizationRunConfig(
        algorithm=OptimizationAlgorithm.GA_PO,
        population_size=4,
        max_fitness_evaluations=20,
        random_seed=42,
        algorithm_version="test",
        max_initialization_attempts=20,
        max_offspring_attempts=2,
    )


def wait_until_terminal(manager: OptimizationRunManager, job_id: str):
    deadline = monotonic() + 2.0
    while monotonic() < deadline:
        snapshot = manager.get_job(job_id)
        if snapshot.status in {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}:
            return snapshot
    raise AssertionError("Job không kết thúc trong thời gian kiểm thử.")


def test_manager_reports_progress_and_completion(monkeypatch) -> None:
    connections: list[FakeConnection] = []

    class FakeOptimizationService:
        def __init__(self, connection) -> None:
            connections.append(connection)

        def create_pending_run(self, scenario_id, config):
            return 17

        def run_scenario(
                self, scenario_id, config, execution_control, *, run_id=None,
                worker_id=None, lease_seconds=300
        ):
            execution_control.bind_run_id(run_id)
            metrics = OptimizationMetrics(
                completed_iterations=1,
                candidate_attempts=10,
                fitness_evaluations=10,
                decode_failed_count=0,
                validation_failed_count=0,
                repaired_individual_count=0,
                failed_repair_count=0,
                total_repair_attempts=0,
                discarded_offspring_count=0,
                total_decode_nodes=10,
                total_decode_backtracks=0,
                runtime_seconds=0.0,
            )
            execution_control.report(OptimizationProgress(
                algorithm=OptimizationAlgorithm.GA_PO,
                iteration=1,
                max_iterations=2,
                max_fitness_evaluations=20,
                metrics=metrics,
                best_general_quality_score=0.2,
                best_lecturer_preference_score=0.3,
            ))
            return PersistedOptimizationRun(17, "COMPLETED", {"error": None})

    monkeypatch.setattr(manager_module, "OptimizationRunService", FakeOptimizationService)
    manager = OptimizationRunManager(lambda: FakeConnection(), max_workers=1)
    try:
        job = manager.start_run(3, make_config())
        completed = wait_until_terminal(manager, job.job_id)
    finally:
        manager.shutdown()

    assert completed.status == "COMPLETED"
    assert completed.run_id == 17
    assert completed.fitness_evaluations == 10
    assert completed.progress_ratio == pytest.approx(0.5)
    assert connections[0].closed is True


def test_manager_cancel_request_reaches_running_control(monkeypatch) -> None:
    started = Event()
    continue_run = Event()

    class FakeOptimizationService:
        def __init__(self, connection) -> None:
            pass

        def create_pending_run(self, scenario_id, config):
            return 18

        def run_scenario(
                self, scenario_id, config, execution_control, *, run_id=None,
                worker_id=None, lease_seconds=300
        ):
            execution_control.bind_run_id(run_id)
            started.set()
            continue_run.wait(timeout=2)
            execution_control.check_interruption()
            raise AssertionError("Run phải bị hủy tại checkpoint.")

    monkeypatch.setattr(manager_module, "OptimizationRunService", FakeOptimizationService)
    manager = OptimizationRunManager(lambda: FakeConnection(), max_workers=1)
    try:
        job = manager.start_run(3, make_config())
        assert started.wait(timeout=1)
        requested = manager.cancel_job(job.job_id)
        assert requested.status == "CANCEL_REQUESTED"
        continue_run.set()
        cancelled = wait_until_terminal(manager, job.job_id)
    finally:
        continue_run.set()
        manager.shutdown()

    assert cancelled.status == "CANCELLED"
    assert cancelled.error_code == "CANCEL_REQUESTED"


def test_unknown_job_is_rejected() -> None:
    manager = OptimizationRunManager(lambda: FakeConnection(), max_workers=1)
    try:
        with pytest.raises(OptimizationJobNotFoundError):
            manager.get_job("missing")
    finally:
        manager.shutdown()


def test_job_status_and_cancel_are_available_from_database_after_restart() -> None:
    manager = OptimizationRunManager(lambda: FakeConnection(23), max_workers=1)
    try:
        persisted = manager.get_job("run-23")
        requested = manager.cancel_job("run-23")
    finally:
        manager.shutdown()

    assert persisted.run_id == 23
    assert persisted.status == "RUNNING"
    assert persisted.fitness_evaluations == 8
    assert requested.status == "CANCEL_REQUESTED"


@pytest.mark.parametrize("timeout_seconds", [0, -1, True])
def test_run_config_rejects_invalid_timeout(timeout_seconds) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        replace(make_config(), timeout_seconds=timeout_seconds)
