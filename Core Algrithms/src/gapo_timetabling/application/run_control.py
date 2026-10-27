"""Điều khiển hợp tác cho progress, timeout và hủy optimization run.

Optimizer chỉ dừng ở các checkpoint an toàn giữa những lần đánh giá ứng viên.
Không dùng cơ chế cưỡng bức kết thúc thread vì có thể để lại transaction hoặc
trạng thái quần thể không nhất quán.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Lock
from time import monotonic
from typing import Callable

from ..core.metrics import OptimizationProgress


class OptimizationRunInterrupted(RuntimeError):
    """Tín hiệu điều khiển dừng run, không phải lỗi công thức optimizer."""

    status: str
    error_code: str


class OptimizationRunCancelled(OptimizationRunInterrupted):
    status = "CANCELLED"
    error_code = "CANCEL_REQUESTED"


class OptimizationRunTimedOut(OptimizationRunInterrupted):
    status = "TIMED_OUT"
    error_code = "TIMEOUT"


@dataclass(frozen=True, slots=True)
class RunProgressSnapshot:
    """Trạng thái bất biến dùng cho API theo dõi một run nền."""

    run_id: int | None
    status: str
    iteration: int
    max_iterations: int
    fitness_evaluations: int
    max_fitness_evaluations: int
    progress_ratio: float
    best_general_quality_score: float | None
    best_lecturer_preference_score: float | None
    updated_at: datetime


class RunExecutionControl:
    """Giữ cờ hủy, deadline và snapshot progress theo cách thread-safe."""

    def __init__(
        self,
        *,
        max_fitness_evaluations: int,
        timeout_seconds: float | None = None,
        progress_listener: Callable[[RunProgressSnapshot], None] | None = None,
    ) -> None:
        if max_fitness_evaluations < 1:
            raise ValueError("max_fitness_evaluations phải là số dương.")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds phải lớn hơn 0 hoặc None.")
        self._max_fitness_evaluations = max_fitness_evaluations
        self._timeout_seconds = timeout_seconds
        # Timeout bắt đầu khi database run đã được tạo và chuyển RUNNING, không
        # tính thời gian job phải chờ trong hàng đợi thread pool.
        self._deadline: float | None = None
        self._listener = progress_listener
        self._cancel_event = Event()
        self._lock = Lock()
        self._run_id: int | None = None
        self._snapshot = RunProgressSnapshot(
            run_id=None,
            status="QUEUED",
            iteration=0,
            max_iterations=0,
            fitness_evaluations=0,
            max_fitness_evaluations=max_fitness_evaluations,
            progress_ratio=0.0,
            best_general_quality_score=None,
            best_lecturer_preference_score=None,
            updated_at=datetime.now(timezone.utc),
        )

    def bind_run_id(self, run_id: int) -> None:
        if run_id < 1:
            raise ValueError("run_id phải là số nguyên dương.")
        with self._lock:
            self._run_id = run_id
            if self._timeout_seconds is not None:
                self._deadline = monotonic() + self._timeout_seconds
            self._snapshot = _replace_snapshot(
                self._snapshot,
                run_id=run_id,
                status="RUNNING",
            )
            snapshot = self._snapshot
        self._notify(snapshot)

    @property
    def timeout_seconds(self) -> float | None:
        return self._timeout_seconds

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def check_interruption(self) -> None:
        if self._cancel_event.is_set():
            raise OptimizationRunCancelled("Run đã nhận yêu cầu hủy.")
        if self._deadline is not None and monotonic() >= self._deadline:
            raise OptimizationRunTimedOut("Run đã vượt quá timeout được cấu hình.")

    def report(self, progress: OptimizationProgress) -> None:
        """Kiểm tra dừng rồi công bố số FE và best hiện tại."""

        self.check_interruption()
        with self._lock:
            self._snapshot = RunProgressSnapshot(
                run_id=self._run_id,
                status="RUNNING",
                iteration=progress.iteration,
                max_iterations=progress.max_iterations,
                fitness_evaluations=progress.metrics.fitness_evaluations,
                max_fitness_evaluations=progress.max_fitness_evaluations,
                progress_ratio=progress.progress_ratio,
                best_general_quality_score=progress.best_general_quality_score,
                best_lecturer_preference_score=(
                    progress.best_lecturer_preference_score
                ),
                updated_at=datetime.now(timezone.utc),
            )
            snapshot = self._snapshot
        self._notify(snapshot)

    def mark_terminal(self, status: str) -> RunProgressSnapshot:
        with self._lock:
            self._snapshot = _replace_snapshot(self._snapshot, status=status)
            snapshot = self._snapshot
        self._notify(snapshot)
        return snapshot

    def snapshot(self) -> RunProgressSnapshot:
        with self._lock:
            return self._snapshot

    def _notify(self, snapshot: RunProgressSnapshot) -> None:
        if self._listener is not None:
            self._listener(snapshot)


def _replace_snapshot(
    current: RunProgressSnapshot,
    *,
    run_id: int | None = None,
    status: str | None = None,
) -> RunProgressSnapshot:
    return RunProgressSnapshot(
        run_id=current.run_id if run_id is None else run_id,
        status=current.status if status is None else status,
        iteration=current.iteration,
        max_iterations=current.max_iterations,
        fitness_evaluations=current.fitness_evaluations,
        max_fitness_evaluations=current.max_fitness_evaluations,
        progress_ratio=current.progress_ratio,
        best_general_quality_score=current.best_general_quality_score,
        best_lecturer_preference_score=current.best_lecturer_preference_score,
        updated_at=datetime.now(timezone.utc),
    )
