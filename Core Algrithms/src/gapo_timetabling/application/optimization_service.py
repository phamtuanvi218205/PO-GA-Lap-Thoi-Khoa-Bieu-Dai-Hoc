"""Điều phối một lần tối ưu và lưu kết quả trực tiếp bằng Python."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic
from typing import Any

from .database import ConnectionProtocol, fetch_one_dict
from ..core.models import OptimizationAlgorithm
from ..core.population import CandidateEvaluationConfig
from .run_contract import (
    RunRequest,
    SnapshotReference,
    execute_prepared_run_request,
)
from ..core.snapshot import canonical_json, prepare_snapshot_for_optimization
from .snapshot_builder import ProblemInstanceSnapshotBuilder
from .run_control import OptimizationRunInterrupted, RunExecutionControl


@dataclass(frozen=True, slots=True)
class OptimizationRunConfig:
    """Cấu hình một lần chạy GA, PO hoặc GA–PO trên scenario đã khóa."""

    algorithm: OptimizationAlgorithm
    population_size: int
    max_fitness_evaluations: int
    random_seed: int
    algorithm_version: str
    max_initialization_attempts: int
    max_offspring_attempts: int
    evaluation_config: CandidateEvaluationConfig = field(
        default_factory=lambda: CandidateEvaluationConfig(
            max_decode_nodes=50_000,
            enable_repair=True,
            max_repair_attempts=2,
            max_decode_nodes_per_repair_attempt=50_000,
        )
    )
    tournament_size: int = 3
    crossover_probability: float = 0.9
    crossover_distribution_index: float = 15.0
    mutation_probability: float | None = None
    mutation_distribution_index: float = 20.0
    ga_ratio: float = 0.5
    timeout_seconds: int | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.population_size, bool)
            or not isinstance(self.population_size, int)
            or self.population_size < 2
        ):
            raise ValueError("population_size phải là số nguyên lớn hơn hoặc bằng 2.")
        if (
            isinstance(self.max_fitness_evaluations, bool)
            or not isinstance(self.max_fitness_evaluations, int)
            or self.max_fitness_evaluations < self.population_size
        ):
            raise ValueError(
                "max_fitness_evaluations phải lớn hơn hoặc bằng population_size."
            )
        remaining_fitness_evaluations = (
            self.max_fitness_evaluations - self.population_size
        )
        if remaining_fitness_evaluations % self.population_size != 0:
            raise ValueError(
                "Phần FE sau khởi tạo phải chia hết cho population_size."
            )
        if (
            isinstance(self.max_initialization_attempts, bool)
            or not isinstance(self.max_initialization_attempts, int)
            or self.max_initialization_attempts < self.population_size
        ):
            raise ValueError(
                "max_initialization_attempts phải lớn hơn hoặc bằng population_size."
            )
        if (
            isinstance(self.max_offspring_attempts, bool)
            or not isinstance(self.max_offspring_attempts, int)
            or self.max_offspring_attempts < 1
        ):
            raise ValueError("max_offspring_attempts phải là số nguyên dương.")
        if (
            self.timeout_seconds is not None
            and (
                isinstance(self.timeout_seconds, bool)
                or self.timeout_seconds < 1
            )
        ):
            raise ValueError("timeout_seconds phải là số nguyên dương hoặc None.")


@dataclass(frozen=True, slots=True)
class PersistedOptimizationRun:
    """Kết quả tối thiểu trả về sau khi đã cập nhật database."""

    run_id: int
    status: str
    result: dict[str, Any]


def _optimization_config_payload(config: OptimizationRunConfig) -> dict[str, Any]:
    """Tạo payload đầy đủ để một run PENDING có thể được phục hồi sau restart."""

    return {
        "schema_version": "optimization-run-config.v1",
        "algorithm": config.algorithm.value,
        "population_size": config.population_size,
        "max_fitness_evaluations": config.max_fitness_evaluations,
        "random_seed": config.random_seed,
        "algorithm_version": config.algorithm_version,
        "max_initialization_attempts": config.max_initialization_attempts,
        "max_offspring_attempts": config.max_offspring_attempts,
        "evaluation_config": asdict(config.evaluation_config),
        "tournament_size": config.tournament_size,
        "crossover_probability": config.crossover_probability,
        "crossover_distribution_index": config.crossover_distribution_index,
        "mutation_probability": config.mutation_probability,
        "mutation_distribution_index": config.mutation_distribution_index,
        "ga_ratio": config.ga_ratio,
        "timeout_seconds": config.timeout_seconds,
    }


def optimization_config_from_json(raw_json: str) -> OptimizationRunConfig:
    """Khôi phục cấu hình đã lưu để chạy lại job PENDING sau khi API restart."""

    payload = json.loads(raw_json)
    if payload.get("schema_version") != "optimization-run-config.v1":
        raise ValueError("Phiên bản request_config_json không được hỗ trợ.")
    evaluation_payload = payload.get("evaluation_config")
    if not isinstance(evaluation_payload, dict):
        raise ValueError("request_config_json thiếu evaluation_config hợp lệ.")
    return OptimizationRunConfig(
        algorithm=OptimizationAlgorithm(payload["algorithm"]),
        population_size=payload["population_size"],
        max_fitness_evaluations=payload["max_fitness_evaluations"],
        random_seed=payload["random_seed"],
        algorithm_version=payload["algorithm_version"],
        max_initialization_attempts=payload["max_initialization_attempts"],
        max_offspring_attempts=payload["max_offspring_attempts"],
        evaluation_config=CandidateEvaluationConfig(**evaluation_payload),
        tournament_size=payload["tournament_size"],
        crossover_probability=payload["crossover_probability"],
        crossover_distribution_index=payload["crossover_distribution_index"],
        mutation_probability=payload["mutation_probability"],
        mutation_distribution_index=payload["mutation_distribution_index"],
        ga_ratio=payload["ga_ratio"],
        timeout_seconds=payload["timeout_seconds"],
    )


class OptimizationRunService:
    """Build snapshot, chạy optimizer và lưu TimetableEntry trong một runtime."""

    def __init__(self, connection: ConnectionProtocol) -> None:
        self._connection = connection
        self._snapshot_builder = ProblemInstanceSnapshotBuilder(connection)

    def create_pending_run(
        self,
        scenario_id: int,
        config: OptimizationRunConfig,
    ) -> int:
        """Tạo bản ghi bền vững trước khi snapshot hoặc optimizer được chạy.

        Một payload JSON tối thiểu được dùng trong thời gian ``PENDING`` để giữ
        tương thích với schema cũ vốn yêu cầu các cột snapshot không được NULL.
        Payload này được thay nguyên tử bằng snapshot thật trước khi tối ưu.
        """

        pending_snapshot_json = canonical_json({
            "schema_version": "problem-instance.pending",
            "status": "PENDING",
        })
        pending_mapping_json = canonical_json({
            "schema_version": "gene-option-mapping.pending",
            "status": "PENDING",
        })
        pending_checksum = sha256(pending_snapshot_json.encode("utf-8")).hexdigest()
        request_config_json = json.dumps(
            _optimization_config_payload(config),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        inserted = fetch_one_dict(self._connection.cursor().execute(
            """
            INSERT INTO OptimizationRun(
                scenario_id, algorithm_name, population_size,
                max_fitness_evaluations, random_seed, algorithm_version,
                status, snapshot_json, snapshot_checksum,
                gene_option_mapping_json, timeout_seconds,
                request_config_json, queued_at
            )
            OUTPUT INSERTED.run_id
            VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?)
            """,
            scenario_id,
            config.algorithm.value,
            config.population_size,
            config.max_fitness_evaluations,
            config.random_seed,
            config.algorithm_version,
            pending_snapshot_json,
            pending_checksum,
            pending_mapping_json,
            config.timeout_seconds,
            request_config_json,
            datetime.now(),
        ))
        if inserted is None:
            raise RuntimeError("SQL Server không trả về run_id vừa tạo.")
        self._connection.commit()
        return int(inserted["run_id"])

    def run_scenario(
        self,
        scenario_id: int,
        config: OptimizationRunConfig,
        execution_control: RunExecutionControl | None = None,
        *,
        run_id: int | None = None,
        worker_id: str | None = None,
        lease_seconds: int = 300,
    ) -> PersistedOptimizationRun:
        """Chạy đồng bộ một scenario và ghi trạng thái cuối vào SQL Server."""

        if lease_seconds < 30:
            raise ValueError("lease_seconds phải lớn hơn hoặc bằng 30.")
        actual_run_id = run_id or self.create_pending_run(scenario_id, config)
        actual_worker_id = worker_id or f"sync-run-{actual_run_id}"
        result: dict[str, Any]
        try:
            if execution_control is not None:
                execution_control.bind_run_id(actual_run_id)
                execution_control.check_interruption()
            claimed = fetch_one_dict(self._connection.cursor().execute(
                """
                UPDATE OptimizationRun
                SET status = 'RUNNING', started_at = ?, progress_updated_at = ?,
                    error_message = NULL, worker_id = ?, lease_expires_at = ?
                OUTPUT INSERTED.run_id
                WHERE run_id = ? AND status = 'PENDING'
                """,
                datetime.now(),
                datetime.now(),
                actual_worker_id,
                datetime.now() + timedelta(seconds=lease_seconds),
                actual_run_id,
            ))
            if claimed is None:
                current = fetch_one_dict(self._connection.cursor().execute(
                    """
                    SELECT status, error_message, worker_id
                    FROM OptimizationRun
                    WHERE run_id = ?
                    """,
                    actual_run_id,
                ))
                if current is None:
                    raise RuntimeError("OptimizationRun không còn tồn tại.")
                current_status = str(current["status"])
                if current_status in {
                    "COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"
                }:
                    return PersistedOptimizationRun(
                        run_id=actual_run_id,
                        status=current_status,
                        result={
                            "status": current_status,
                            "error": (
                                None
                                if current_status == "COMPLETED"
                                else {
                                    "code": "PERSISTED_TERMINAL_STATUS",
                                    "message": current.get("error_message"),
                                }
                            ),
                        },
                    )
                if current_status == "RUNNING":
                    return PersistedOptimizationRun(
                        run_id=actual_run_id,
                        status="RUNNING",
                        result={
                            "status": "RUNNING",
                            "error": None,
                            "delegated": True,
                            "worker_id": current.get("worker_id"),
                        },
                    )
                raise RuntimeError(
                    f"OptimizationRun {actual_run_id} không ở trạng thái PENDING."
                )
            self._connection.commit()

            if execution_control is not None:
                cancellation = fetch_one_dict(self._connection.cursor().execute(
                    """
                    SELECT cancel_requested
                    FROM OptimizationRun
                    WHERE run_id = ?
                    """,
                    actual_run_id,
                ))
                if cancellation and bool(cancellation["cancel_requested"]):
                    execution_control.request_cancel()
                execution_control.check_interruption()

            stored_snapshot = fetch_one_dict(self._connection.cursor().execute(
                """
                SELECT snapshot_json, snapshot_checksum
                FROM OptimizationRun
                WHERE run_id = ?
                """,
                actual_run_id,
            ))
            if stored_snapshot is None:
                raise RuntimeError("Không đọc được snapshot của OptimizationRun.")
            stored_payload = json.loads(str(stored_snapshot["snapshot_json"]))
            if stored_payload.get("schema_version") == "problem-instance.pending":
                built = self._snapshot_builder.build(scenario_id)
                snapshot_payload = built.payload
                snapshot_json = built.canonical_json
                snapshot_checksum = built.sha256_checksum
            else:
                # Run phục hồi phải dùng đúng ảnh chụp đã lưu, không dựng lại từ
                # dữ liệu nghiệp vụ có thể đã thay đổi sau lần chạy ban đầu.
                snapshot_payload = stored_payload
                snapshot_json = str(stored_snapshot["snapshot_json"])
                snapshot_checksum = str(stored_snapshot["snapshot_checksum"])
            prepared = prepare_snapshot_for_optimization(
                snapshot_payload,
                expected_checksum=snapshot_checksum,
            )
            if prepared.gene_option_mapping_json is not None:
                mapping_json = prepared.gene_option_mapping_json
            else:
                mapping_json = canonical_json({
                    "schema_version": "gene-option-mapping.v3",
                    "status": "NO_OPTION",
                    "issues": [
                        {
                            "session_index": issue.session_index,
                            "class_session_id": issue.class_session_id,
                            "reason": issue.reason,
                        }
                        for issue in prepared.no_option_issues
                    ],
                })
            self._connection.cursor().execute(
                """
                UPDATE OptimizationRun
                SET snapshot_json = ?, snapshot_checksum = ?,
                    gene_option_mapping_json = ?
                WHERE run_id = ? AND status = 'RUNNING'
                """,
                snapshot_json,
                snapshot_checksum,
                mapping_json,
                actual_run_id,
            )
            self._connection.commit()

            request = RunRequest(
                request_id=f"db-run-{actual_run_id}",
                algorithm=config.algorithm,
                snapshot=SnapshotReference(
                    path=Path("<database-snapshot>"),
                    checksum=snapshot_checksum,
                ),
                population_size=config.population_size,
                max_fitness_evaluations=config.max_fitness_evaluations,
                random_seed=config.random_seed,
                max_initialization_attempts=config.max_initialization_attempts,
                max_offspring_attempts=config.max_offspring_attempts,
                evaluation_config=config.evaluation_config,
                tournament_size=config.tournament_size,
                crossover_probability=config.crossover_probability,
                crossover_distribution_index=config.crossover_distribution_index,
                mutation_probability=config.mutation_probability,
                mutation_distribution_index=config.mutation_distribution_index,
                ga_ratio=config.ga_ratio,
            )

            last_progress_persisted_at = 0.0

            def report_progress(progress) -> None:
                nonlocal last_progress_persisted_at
                if execution_control is not None:
                    cancellation = fetch_one_dict(self._connection.cursor().execute(
                        """
                        SELECT cancel_requested
                        FROM OptimizationRun
                        WHERE run_id = ?
                        """,
                        actual_run_id,
                    ))
                    if cancellation and bool(cancellation["cancel_requested"]):
                        execution_control.request_cancel()
                    execution_control.report(progress)
                now = monotonic()
                if (
                    now - last_progress_persisted_at < 1.0
                    and progress.metrics.fitness_evaluations
                    < progress.max_fitness_evaluations
                ):
                    return
                self._connection.cursor().execute(
                    """
                    UPDATE OptimizationRun
                    SET current_fitness_evaluations = ?, completed_iterations = ?,
                        progress_updated_at = ?, lease_expires_at = ?
                    WHERE run_id = ? AND status = 'RUNNING' AND worker_id = ?
                    """,
                    progress.metrics.fitness_evaluations,
                    progress.iteration,
                    datetime.now(),
                    datetime.now() + timedelta(seconds=lease_seconds),
                    actual_run_id,
                    actual_worker_id,
                )
                self._connection.commit()
                last_progress_persisted_at = now

            result = execute_prepared_run_request(
                request,
                prepared,
                progress_callback=report_progress,
            )
            if result["status"] == "COMPLETED":
                self._persist_completed_result(actual_run_id, result)
            else:
                self._persist_failed_result(actual_run_id, result)
            self._connection.commit()
        except OptimizationRunInterrupted as interruption:
            self._connection.rollback()
            result = {
                "status": interruption.status,
                "error": {
                    "code": interruption.error_code,
                    "message": str(interruption),
                },
            }
            self._persist_interrupted_result(actual_run_id, interruption)
            self._connection.commit()
        except Exception as exception:
            self._connection.rollback()
            failure = {
                "status": "FAILED",
                "error": {"code": "UNEXPECTED_ERROR", "message": str(exception)},
            }
            try:
                self._persist_failed_result(actual_run_id, failure)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
            raise

        return PersistedOptimizationRun(
            run_id=actual_run_id,
            status=str(result["status"]),
            result=result,
        )

    def _persist_completed_result(self, run_id: int, result: dict[str, Any]) -> None:
        payload = result["result"]
        fitness = payload["best_fitness"]
        entries = payload["timetable_entries"]
        cursor = self._connection.cursor()
        if entries:
            cursor.executemany(
                """
                INSERT INTO TimetableEntry(
                    run_id, class_session_id, lecturer_code, term_code,
                    teaching_date, location_id, location_type,
                    start_period, end_period
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        entry["class_session_id"],
                        entry["lecturer_code"],
                        entry["term_code"],
                        entry["teaching_date"],
                        entry["location_id"],
                        entry["location_type"],
                        entry["start_period"],
                        entry["end_period"],
                    )
                    for entry in entries
                ],
            )
        cursor.execute(
            """
            UPDATE OptimizationRun
            SET status = 'COMPLETED', hard_violation_count = 0,
                general_quality_score = ?,
                lecturer_preference_score = ?, fitness_breakdown_json = ?,
                current_fitness_evaluations = ?, completed_iterations = ?,
                progress_updated_at = ?, finished_at = ?, error_message = NULL,
                worker_id = NULL, lease_expires_at = NULL
            WHERE run_id = ?
            """,
            fitness["general_quality_score"],
            fitness["lecturer_preference_score"],
            json.dumps(fitness["breakdown"], ensure_ascii=False, separators=(",", ":")),
            payload["metrics"]["fitness_evaluations"],
            payload["metrics"]["completed_iterations"],
            datetime.now(),
            datetime.now(),
            run_id,
        )

    def _persist_interrupted_result(
        self,
        run_id: int,
        interruption: OptimizationRunInterrupted,
    ) -> None:
        self._connection.cursor().execute(
            """
            UPDATE OptimizationRun
            SET status = ?, cancel_requested = ?, finished_at = ?,
                progress_updated_at = ?, error_message = ?,
                worker_id = NULL, lease_expires_at = NULL
            WHERE run_id = ?
            """,
            interruption.status,
            1 if interruption.status == "CANCELLED" else 0,
            datetime.now(),
            datetime.now(),
            f"[{interruption.error_code}] {interruption}",
            run_id,
        )

    def _persist_failed_result(self, run_id: int, result: dict[str, Any]) -> None:
        error = result.get("error") or {}
        message = str(error.get("message", "Optimizer thất bại không có mô tả."))
        code = error.get("code")
        if code:
            message = f"[{code}] {message}"
        self._connection.cursor().execute(
            """
            UPDATE OptimizationRun
            SET status = 'FAILED', finished_at = ?, error_message = ?,
                worker_id = NULL, lease_expires_at = NULL
            WHERE run_id = ?
            """,
            datetime.now(),
            message,
            run_id,
        )
