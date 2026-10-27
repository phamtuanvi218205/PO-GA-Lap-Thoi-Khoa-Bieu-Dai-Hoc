"""Quản lý các optimization run chạy nền trong tiến trình API.

Manager dùng thread pool vì optimizer hiện là mã Python đồng bộ. Việc dừng là
hợp tác: cờ hủy hoặc timeout được kiểm tra tại checkpoint giữa các lần đánh giá
ứng viên, không cưỡng bức hủy thread đang giữ transaction.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
import os
from threading import Event, Lock, Thread
from typing import Callable
from uuid import uuid4

from .database import ConnectionProtocol, fetch_all_dicts, fetch_one_dict
from .optimization_service import OptimizationRunConfig, OptimizationRunService
from .optimization_service import optimization_config_from_json
from .run_control import (
    OptimizationRunInterrupted,
    RunExecutionControl,
    RunProgressSnapshot,
)


TERMINAL_JOB_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"})
LOGGER = logging.getLogger(__name__)


class OptimizationJobNotFoundError(KeyError):
    """Không tồn tại job trong bộ nhớ hoặc SQL Server."""


@dataclass(frozen=True, slots=True)
class OptimizationJobSnapshot:
    job_id: str
    scenario_id: int
    status: str
    run_id: int | None
    fitness_evaluations: int
    max_fitness_evaluations: int
    progress_ratio: float
    completed_iterations: int
    max_iterations: int
    best_general_quality_score: float | None
    best_lecturer_preference_score: float | None
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class _ManagedJob:
    snapshot: OptimizationJobSnapshot
    control: RunExecutionControl


class OptimizationRunManager:
    """Khởi chạy, theo dõi và yêu cầu hủy run trong tiến trình hiện tại."""

    def __init__(
        self,
        connection_factory: Callable[[], ConnectionProtocol],
        *,
        max_workers: int | None = None,
    ) -> None:
        if max_workers is None:
            max_workers = int(os.getenv("GAPO_RUN_WORKERS", "2"))
        if max_workers < 1:
            raise ValueError("max_workers phải lớn hơn hoặc bằng 1.")
        self._lease_seconds = int(os.getenv("GAPO_RUN_LEASE_SECONDS", "300"))
        self._recovery_interval_seconds = int(
            os.getenv("GAPO_RUN_RECOVERY_INTERVAL_SECONDS", "30")
        )
        if self._lease_seconds < 30:
            raise ValueError("GAPO_RUN_LEASE_SECONDS phải lớn hơn hoặc bằng 30.")
        if self._recovery_interval_seconds < 5:
            raise ValueError(
                "GAPO_RUN_RECOVERY_INTERVAL_SECONDS phải lớn hơn hoặc bằng 5."
            )
        self._worker_id = uuid4().hex
        self._connection_factory = connection_factory
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="gapo-run",
        )
        self._jobs: dict[str, _ManagedJob] = {}
        self._scheduled_run_ids: set[int] = set()
        self._lock = Lock()
        self._recovery_stop = Event()
        self._recovery_thread: Thread | None = None

    def start_run(
        self,
        scenario_id: int,
        config: OptimizationRunConfig,
    ) -> OptimizationJobSnapshot:
        if scenario_id < 1:
            raise ValueError("scenario_id phải là số nguyên dương.")
        connection = self._connection_factory()
        try:
            run_id = OptimizationRunService(connection).create_pending_run(
                scenario_id,
                config,
            )
        finally:
            connection.close()
        job_id = _job_id_for_run(run_id)
        now = datetime.now(timezone.utc)

        def listener(progress: RunProgressSnapshot) -> None:
            self._apply_progress(job_id, progress)

        control = RunExecutionControl(
            max_fitness_evaluations=config.max_fitness_evaluations,
            timeout_seconds=config.timeout_seconds,
            progress_listener=listener,
        )
        snapshot = OptimizationJobSnapshot(
            job_id=job_id,
            scenario_id=scenario_id,
            status="PENDING",
            run_id=run_id,
            fitness_evaluations=0,
            max_fitness_evaluations=config.max_fitness_evaluations,
            progress_ratio=0.0,
            completed_iterations=0,
            max_iterations=0,
            best_general_quality_score=None,
            best_lecturer_preference_score=None,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job_id] = _ManagedJob(snapshot=snapshot, control=control)
            self._scheduled_run_ids.add(run_id)
        self._executor.submit(self._run_job, job_id, run_id, scenario_id, config)
        return snapshot

    def get_job(self, job_id: str) -> OptimizationJobSnapshot:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return job.snapshot
        run_id = _run_id_from_job_id(job_id)
        persisted = self._read_persisted_snapshot(run_id)
        if persisted is None:
            raise OptimizationJobNotFoundError(job_id)
        return persisted

    def cancel_job(self, job_id: str) -> OptimizationJobSnapshot:
        run_id = _run_id_from_job_id(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.snapshot.status in TERMINAL_JOB_STATUSES:
                return job.snapshot
            if job is not None:
                job.control.request_cancel()

        connection = self._connection_factory()
        try:
            updated = fetch_one_dict(connection.cursor().execute(
                """
                UPDATE OptimizationRun
                SET cancel_requested = 1,
                    status = CASE WHEN status = 'PENDING'
                                  THEN 'CANCELLED' ELSE status END,
                    finished_at = CASE WHEN status = 'PENDING'
                                       THEN ? ELSE finished_at END,
                    progress_updated_at = ?
                OUTPUT INSERTED.run_id, INSERTED.scenario_id,
                       INSERTED.status, INSERTED.population_size,
                       INSERTED.max_fitness_evaluations,
                       INSERTED.current_fitness_evaluations,
                       INSERTED.completed_iterations,
                       INSERTED.queued_at, INSERTED.started_at,
                       INSERTED.progress_updated_at, INSERTED.finished_at,
                       INSERTED.general_quality_score,
                       INSERTED.lecturer_preference_score,
                       INSERTED.error_message
                WHERE run_id = ?
                  AND status IN ('PENDING', 'RUNNING')
                """,
                datetime.now(),
                datetime.now(),
                run_id,
            ))
            if updated is None:
                existing = self._read_persisted_snapshot(run_id, connection=connection)
                if existing is None:
                    raise OptimizationJobNotFoundError(job_id)
                connection.commit()
                return existing
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

        persisted = _snapshot_from_run_row(updated)
        with self._lock:
            managed = self._jobs.get(job_id)
            if managed is not None:
                requested_status = (
                    "CANCELLED"
                    if persisted.status == "CANCELLED"
                    else "CANCEL_REQUESTED"
                )
                managed.snapshot = replace(
                    managed.snapshot,
                    status=requested_status,
                    updated_at=datetime.now(timezone.utc),
                )
                return managed.snapshot
        if persisted.status == "RUNNING":
            return replace(
                persisted,
                status="CANCEL_REQUESTED",
                updated_at=datetime.now(timezone.utc),
            )
        return persisted

    def recover_incomplete_runs(self) -> tuple[OptimizationJobSnapshot, ...]:
        """Khôi phục PENDING/RUNNING sau restart và đưa lại vào thread pool.

        Một run từng ở ``RUNNING`` được chạy lại từ snapshot/seed ban đầu, không
        tiếp tục từ quần thể giữa chừng. Cách này bảo toàn tính xác định và tránh
        sử dụng trạng thái quần thể chưa được lưu đầy đủ.
        """

        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE OptimizationRun
                SET status = CASE WHEN cancel_requested = 1
                                  THEN 'CANCELLED' ELSE 'PENDING' END,
                    current_fitness_evaluations = 0,
                    completed_iterations = 0,
                    started_at = NULL,
                    finished_at = CASE WHEN cancel_requested = 1
                                       THEN ? ELSE NULL END,
                    progress_updated_at = ?,
                    error_message = CASE WHEN cancel_requested = 1
                        THEN error_message
                        ELSE N'Run được khởi động lại từ đầu sau khi worker mất lease.'
                    END,
                    worker_id = NULL, lease_expires_at = NULL
                WHERE status = 'RUNNING'
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                """,
                datetime.now(),
                datetime.now(),
                datetime.now(),
            )
            rows = fetch_all_dicts(cursor.execute(
                """
                SELECT run_id, scenario_id, request_config_json
                FROM OptimizationRun
                WHERE status = 'PENDING' AND cancel_requested = 0
                ORDER BY queued_at, run_id
                """
            ))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

        recovered: list[OptimizationJobSnapshot] = []
        for row in rows:
            raw_config = row.get("request_config_json")
            if not raw_config:
                self._mark_unrecoverable_run(
                    int(row["run_id"]),
                    "Run cũ không có request_config_json để khôi phục.",
                )
                continue
            try:
                config = optimization_config_from_json(str(raw_config))
            except (KeyError, TypeError, ValueError) as error:
                self._mark_unrecoverable_run(int(row["run_id"]), str(error))
                continue
            snapshot = self._schedule_existing_run(
                int(row["run_id"]),
                int(row["scenario_id"]),
                config,
            )
            if snapshot is not None:
                recovered.append(snapshot)
        return tuple(recovered)

    def shutdown(self, *, wait: bool = True) -> None:
        self._recovery_stop.set()
        recovery_thread = self._recovery_thread
        if recovery_thread is not None and recovery_thread.is_alive():
            recovery_thread.join(timeout=2.0 if wait else 0.0)
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def start_recovery_monitor(self) -> None:
        """Khởi động bộ quét PENDING và lease hết hạn cho API process này."""

        with self._lock:
            if self._recovery_thread is not None:
                return
            self._recovery_thread = Thread(
                target=self._recovery_loop,
                name=f"gapo-recovery-{self._worker_id[:8]}",
                daemon=True,
            )
            thread = self._recovery_thread
        self.recover_incomplete_runs()
        thread.start()

    def _recovery_loop(self) -> None:
        while not self._recovery_stop.wait(self._recovery_interval_seconds):
            try:
                self.recover_incomplete_runs()
            except Exception:
                # Lỗi database tạm thời không được làm chết API process. Lượt
                # quét tiếp theo sẽ thử lại; lỗi vẫn xuất hiện trong log server.
                LOGGER.exception("Không thể quét optimization run cần phục hồi.")
                continue

    def _apply_progress(self, job_id: str, progress: RunProgressSnapshot) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.snapshot = replace(
                job.snapshot,
                status=progress.status,
                run_id=progress.run_id,
                fitness_evaluations=progress.fitness_evaluations,
                max_fitness_evaluations=progress.max_fitness_evaluations,
                progress_ratio=progress.progress_ratio,
                completed_iterations=progress.iteration,
                max_iterations=progress.max_iterations,
                best_general_quality_score=progress.best_general_quality_score,
                best_lecturer_preference_score=(
                    progress.best_lecturer_preference_score
                ),
                updated_at=progress.updated_at,
            )

    def _run_job(
        self,
        job_id: str,
        run_id: int,
        scenario_id: int,
        config: OptimizationRunConfig,
    ) -> None:
        connection: ConnectionProtocol | None = None
        try:
            connection = self._connection_factory()
            with self._lock:
                control = self._jobs[job_id].control
            persisted = OptimizationRunService(connection).run_scenario(
                scenario_id,
                config,
                execution_control=control,
                run_id=run_id,
                worker_id=self._worker_id,
                lease_seconds=self._lease_seconds,
            )
            if persisted.result.get("delegated") is True:
                with self._lock:
                    self._jobs.pop(job_id, None)
                return
            error = persisted.result.get("error") or {}
            self._set_status(
                job_id,
                persisted.status,
                run_id=persisted.run_id,
                error_code=error.get("code"),
                error_message=error.get("message"),
            )
        except OptimizationRunInterrupted as interruption:
            self._set_status(
                job_id,
                interruption.status,
                error_code=interruption.error_code,
                error_message=str(interruption),
            )
        except Exception as exception:
            self._set_status(
                job_id,
                "FAILED",
                error_code="UNEXPECTED_ERROR",
                error_message=str(exception),
            )
        finally:
            with self._lock:
                self._scheduled_run_ids.discard(run_id)
            if connection is not None:
                connection.close()

    def _schedule_existing_run(
        self,
        run_id: int,
        scenario_id: int,
        config: OptimizationRunConfig,
    ) -> OptimizationJobSnapshot | None:
        job_id = _job_id_for_run(run_id)
        with self._lock:
            if run_id in self._scheduled_run_ids:
                return None
            now = datetime.now(timezone.utc)

            def listener(progress: RunProgressSnapshot) -> None:
                self._apply_progress(job_id, progress)

            control = RunExecutionControl(
                max_fitness_evaluations=config.max_fitness_evaluations,
                timeout_seconds=config.timeout_seconds,
                progress_listener=listener,
            )
            snapshot = OptimizationJobSnapshot(
                job_id=job_id,
                scenario_id=scenario_id,
                status="PENDING",
                run_id=run_id,
                fitness_evaluations=0,
                max_fitness_evaluations=config.max_fitness_evaluations,
                progress_ratio=0.0,
                completed_iterations=0,
                max_iterations=(
                    config.max_fitness_evaluations - config.population_size
                ) // config.population_size,
                best_general_quality_score=None,
                best_lecturer_preference_score=None,
                created_at=now,
                updated_at=now,
            )
            self._jobs[job_id] = _ManagedJob(snapshot=snapshot, control=control)
            self._scheduled_run_ids.add(run_id)
        self._executor.submit(self._run_job, job_id, run_id, scenario_id, config)
        return snapshot

    def _read_persisted_snapshot(
        self,
        run_id: int,
        *,
        connection: ConnectionProtocol | None = None,
    ) -> OptimizationJobSnapshot | None:
        owns_connection = connection is None
        actual_connection = connection or self._connection_factory()
        try:
            row = fetch_one_dict(actual_connection.cursor().execute(
                """
                SELECT run_id, scenario_id, status, population_size,
                       max_fitness_evaluations, current_fitness_evaluations,
                       completed_iterations, queued_at, started_at,
                       progress_updated_at, finished_at,
                       general_quality_score, lecturer_preference_score,
                       error_message
                FROM OptimizationRun
                WHERE run_id = ?
                """,
                run_id,
            ))
            return None if row is None else _snapshot_from_run_row(row)
        finally:
            if owns_connection:
                actual_connection.close()

    def _mark_unrecoverable_run(self, run_id: int, message: str) -> None:
        connection = self._connection_factory()
        try:
            connection.cursor().execute(
                """
                UPDATE OptimizationRun
                SET status = 'FAILED', finished_at = ?, progress_updated_at = ?,
                    error_message = ?, worker_id = NULL, lease_expires_at = NULL
                WHERE run_id = ? AND status = 'PENDING'
                """,
                datetime.now(),
                datetime.now(),
                f"[RECOVERY_ERROR] {message}",
                run_id,
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _set_status(
        self,
        job_id: str,
        status: str,
        *,
        run_id: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.snapshot = replace(
                job.snapshot,
                status=status,
                run_id=job.snapshot.run_id if run_id is None else run_id,
                updated_at=datetime.now(timezone.utc),
                error_code=error_code,
                error_message=error_message,
            )


def _job_id_for_run(run_id: int) -> str:
    return f"run-{run_id}"


def _run_id_from_job_id(job_id: str) -> int:
    prefix = "run-"
    if not isinstance(job_id, str) or not job_id.startswith(prefix):
        raise OptimizationJobNotFoundError(job_id)
    try:
        run_id = int(job_id[len(prefix):])
    except ValueError as error:
        raise OptimizationJobNotFoundError(job_id) from error
    if run_id < 1:
        raise OptimizationJobNotFoundError(job_id)
    return run_id


def _utc_datetime(value: object, fallback: datetime) -> datetime:
    if not isinstance(value, datetime):
        return fallback
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _snapshot_from_run_row(row: dict[str, object]) -> OptimizationJobSnapshot:
    now = datetime.now(timezone.utc)
    run_id = int(row["run_id"])
    population_size = int(row.get("population_size") or 1)
    max_fitness_evaluations = int(row.get("max_fitness_evaluations") or 0)
    fitness_evaluations = int(row.get("current_fitness_evaluations") or 0)
    error_message = (
        None if row.get("error_message") is None else str(row["error_message"])
    )
    error_code = None
    if error_message and error_message.startswith("[") and "]" in error_message:
        error_code = error_message[1:error_message.index("]")]
    created_at = _utc_datetime(
        row.get("queued_at") or row.get("started_at"),
        now,
    )
    updated_at = _utc_datetime(
        row.get("progress_updated_at")
        or row.get("finished_at")
        or row.get("started_at")
        or row.get("queued_at"),
        created_at,
    )
    remaining = max(0, max_fitness_evaluations - population_size)
    return OptimizationJobSnapshot(
        job_id=_job_id_for_run(run_id),
        scenario_id=int(row["scenario_id"]),
        status=str(row["status"]),
        run_id=run_id,
        fitness_evaluations=fitness_evaluations,
        max_fitness_evaluations=max_fitness_evaluations,
        progress_ratio=(
            min(1.0, fitness_evaluations / max_fitness_evaluations)
            if max_fitness_evaluations > 0
            else 0.0
        ),
        completed_iterations=int(row.get("completed_iterations") or 0),
        max_iterations=remaining // population_size,
        best_general_quality_score=(
            None
            if row.get("general_quality_score") is None
            else float(row["general_quality_score"])
        ),
        best_lecturer_preference_score=(
            None
            if row.get("lecturer_preference_score") is None
            else float(row["lecturer_preference_score"])
        ),
        created_at=created_at,
        updated_at=updated_at,
        error_code=error_code,
        error_message=error_message,
    )
