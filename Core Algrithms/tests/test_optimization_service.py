"""Kiểm thử persistence sớm và cấu hình bền vững của optimization run."""

from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace
from typing import Any

import pytest

from gapo_timetabling.application.optimization_service import (
    OptimizationRunConfig,
    OptimizationRunService,
    _optimization_config_payload,
    optimization_config_from_json,
)
from gapo_timetabling.core.models import OptimizationAlgorithm
from gapo_timetabling.core.snapshot import canonical_json


class RecordingCursor:
    def __init__(self, snapshot_json: str | None = None) -> None:
        self.description = None
        self._row = None
        self.statements: list[tuple[str, tuple[Any, ...]]] = []
        self.snapshot_json = snapshot_json or canonical_json({
            "schema_version": "problem-instance.pending",
            "status": "PENDING",
        })

    def execute(self, sql: str, *parameters: Any) -> "RecordingCursor":
        self.statements.append((sql, parameters))
        if "INSERT INTO OptimizationRun" in sql:
            self.description = [("run_id",)]
            self._row = (41,)
        elif "OUTPUT INSERTED.run_id" in sql and "status = 'RUNNING'" in sql:
            self.description = [("run_id",)]
            self._row = (41,)
        elif "SELECT snapshot_json, snapshot_checksum" in sql:
            self.description = [("snapshot_json",), ("snapshot_checksum",)]
            self._row = (
                self.snapshot_json,
                sha256(self.snapshot_json.encode("utf-8")).hexdigest(),
            )
        else:
            self.description = None
            self._row = None
        return self

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class RecordingConnection:
    def __init__(self, snapshot_json: str | None = None) -> None:
        self.recording_cursor = RecordingCursor(snapshot_json)
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        pass


class AlreadyClaimedCursor(RecordingCursor):
    def execute(self, sql: str, *parameters: Any) -> "RecordingCursor":
        if "OUTPUT INSERTED.run_id" in sql and "status = 'RUNNING'" in sql:
            self.statements.append((sql, parameters))
            self.description = [("run_id",)]
            self._row = None
            return self
        if "SELECT status, error_message, worker_id" in sql:
            self.statements.append((sql, parameters))
            self.description = [
                ("status",), ("error_message",), ("worker_id",),
            ]
            self._row = ("RUNNING", None, "other-api-process")
            return self
        return super().execute(sql, *parameters)


class AlreadyClaimedConnection(RecordingConnection):
    def __init__(self) -> None:
        super().__init__()
        self.recording_cursor = AlreadyClaimedCursor()


class FailingSnapshotBuilder:
    def build(self, scenario_id: int):
        raise ValueError(f"snapshot broken for scenario {scenario_id}")


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


def test_config_json_round_trip_preserves_complete_run_configuration() -> None:
    config = make_config()

    restored = optimization_config_from_json(canonical_json(
        _optimization_config_payload(config)
    ))

    assert restored == config


def test_snapshot_failure_is_persisted_after_pending_run_was_created() -> None:
    connection = RecordingConnection()
    service = OptimizationRunService(connection)
    service._snapshot_builder = FailingSnapshotBuilder()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="snapshot broken"):
        service.run_scenario(7, make_config())

    sql_text = "\n".join(
        statement for statement, _ in connection.recording_cursor.statements
    )
    assert "INSERT INTO OptimizationRun" in sql_text
    assert "'PENDING'" in sql_text
    assert "SET status = 'FAILED'" in sql_text
    assert connection.commit_count >= 2
    assert connection.rollback_count == 1


def test_recovered_run_reuses_persisted_snapshot(monkeypatch) -> None:
    persisted_json = canonical_json({
        "schema_version": "problem-instance.v2",
        "marker": "persisted-snapshot",
    })
    connection = RecordingConnection(persisted_json)
    service = OptimizationRunService(connection)
    service._snapshot_builder = FailingSnapshotBuilder()  # type: ignore[assignment]
    observed_payloads = []

    def prepare(payload, *, expected_checksum):
        observed_payloads.append((payload, expected_checksum))
        return SimpleNamespace(
            gene_option_mapping_json=canonical_json({"status": "READY"}),
            no_option_issues=(),
        )

    monkeypatch.setattr(
        "gapo_timetabling.application.optimization_service."
        "prepare_snapshot_for_optimization",
        prepare,
    )
    monkeypatch.setattr(
        "gapo_timetabling.application.optimization_service."
        "execute_prepared_run_request",
        lambda *args, **kwargs: {
            "status": "FAILED",
            "error": {"code": "TEST", "message": "stop after snapshot"},
        },
    )

    result = service.run_scenario(7, make_config(), run_id=41)

    assert result.status == "FAILED"
    assert observed_payloads[0][0]["marker"] == "persisted-snapshot"
    assert observed_payloads[0][1] == sha256(persisted_json.encode("utf-8")).hexdigest()


def test_second_api_worker_does_not_execute_an_already_claimed_run() -> None:
    connection = AlreadyClaimedConnection()
    service = OptimizationRunService(connection)
    service._snapshot_builder = FailingSnapshotBuilder()  # type: ignore[assignment]

    result = service.run_scenario(
        7,
        make_config(),
        run_id=41,
        worker_id="this-api-process",
    )

    assert result.status == "RUNNING"
    assert result.result["delegated"] is True
    assert result.result["worker_id"] == "other-api-process"


@pytest.mark.parametrize(
    ("population_size", "max_fe", "message"),
    [
        (60, 2, "lớn hơn hoặc bằng population_size"),
        (30, 2_000, "chia hết"),
    ],
)
def test_run_config_rejects_invalid_fe_contract(
    population_size: int,
    max_fe: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        OptimizationRunConfig(
            algorithm=OptimizationAlgorithm.PO,
            population_size=population_size,
            max_fitness_evaluations=max_fe,
            random_seed=1,
            algorithm_version="test",
            max_initialization_attempts=100,
            max_offspring_attempts=2,
        )
