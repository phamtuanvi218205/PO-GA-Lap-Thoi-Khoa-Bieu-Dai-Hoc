"""Điều phối Greedy First Feasible cho runner thực nghiệm ngoại tuyến."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from ..core.constraints import validate_timetable
from ..core.greedy_baseline import (
    GREEDY_BASELINE_NAME,
    run_greedy_first_feasible,
)
from ..core.snapshot import prepare_snapshot_for_optimization
from .run_contract import (
    RESULT_SCHEMA_VERSION,
    RunErrorCode,
    build_completed_result_payload,
    parse_run_request,
)


def _failure(
    *,
    request_id: str,
    code: RunErrorCode,
    message: str,
    snapshot_checksum: str | None = None,
    details: Any = None,
) -> dict[str, Any]:
    """Tạo envelope lỗi riêng cho baseline không thuộc enum production."""

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "request_id": request_id,
        "status": "FAILED",
        "algorithm": GREEDY_BASELINE_NAME,
        "snapshot_checksum": snapshot_checksum,
        "error": {
            "code": code.value,
            "message": message,
            "details": details,
        },
        "result": None,
    }


def execute_greedy_baseline(
    base_request_payload: Mapping[str, Any],
    *,
    base_directory: Path,
    request_id: str,
) -> dict[str, Any]:
    """Chạy một baseline từ cùng request/snapshot của ba optimizer.

    Hợp đồng request vẫn được parser production kiểm tra. Trường ``algorithm``
    tạm đặt thành GA chỉ để tái sử dụng validation cấu hình; baseline không gọi
    GA và kết quả luôn mang tên ``GREEDY_FIRST_FEASIBLE``.
    """

    request_payload = deepcopy(dict(base_request_payload))
    request_payload["request_id"] = request_id
    request_payload["algorithm"] = "GA"
    request = parse_run_request(
        request_payload,
        base_directory=base_directory,
    )

    try:
        prepared = prepare_snapshot_for_optimization(
            request.snapshot.path,
            expected_checksum=request.snapshot.checksum,
        )
    except (OSError, TypeError, ValueError) as error:
        return _failure(
            request_id=request_id,
            code=RunErrorCode.SNAPSHOT_ERROR,
            message=str(error),
        )

    if not prepared.is_ready:
        return _failure(
            request_id=request_id,
            code=RunErrorCode.NO_OPTION,
            message="Có ClassSession không có SessionOption hợp lệ.",
            snapshot_checksum=prepared.snapshot_checksum,
            details=[asdict(issue) for issue in prepared.no_option_issues],
        )

    baseline = run_greedy_first_feasible(
        prepared.problem,
        prepared.option_domains,
        request.evaluation_config,
    )
    if not baseline.is_success or baseline.individual is None:
        return _failure(
            request_id=request_id,
            code=RunErrorCode.NO_FEASIBLE_SOLUTION_FOUND,
            message=baseline.reason,
            snapshot_checksum=prepared.snapshot_checksum,
            details={
                "baseline_status": baseline.status.value,
                "candidate_attempts": baseline.metrics.candidate_attempts,
                "fitness_evaluations": baseline.metrics.fitness_evaluations,
                "decode_failed_count": baseline.metrics.decode_failed_count,
                "validation_failed_count": (
                    baseline.metrics.validation_failed_count
                ),
            },
        )

    validation = validate_timetable(
        prepared.problem,
        baseline.individual.selected_options,
    )
    if not validation.is_valid:
        return _failure(
            request_id=request_id,
            code=RunErrorCode.INVALID_RESULT,
            message="Lịch baseline còn vi phạm điều kiện bắt buộc.",
            snapshot_checksum=prepared.snapshot_checksum,
            details=[asdict(item) for item in validation.violations],
        )

    return build_completed_result_payload(
        request_id=request_id,
        algorithm_name=GREEDY_BASELINE_NAME,
        prepared=prepared,
        best_individual=baseline.individual,
        metrics=baseline.metrics,
        convergence_history=baseline.convergence_history,
    )
