"""Thực nghiệm GA, PO, GA–PO và baseline trên bài toán thời khóa biểu.

Runner sử dụng trực tiếp ``optimization-run-request.v1`` và
``optimization-run-result.v1``. Với mỗi seed, chỉ hai trường ``algorithm`` và
``request_id`` thay đổi; snapshot, quần thể, số vòng, decoder, repair và
các tham số còn lại được giữ nguyên. Nhờ tính xác định của bước khởi tạo, ba
optimizer nhận cùng quần thể ban đầu ở cùng một seed. Greedy First Feasible
được chạy đúng một lần như mốc tham khảo xác định; baseline không nhận rank
theo seed và không được mô tả là có cùng ngân sách tìm kiếm với ba optimizer.

Các run được thực hiện tuần tự. Điều này tránh việc nhiều tiến trình tranh chấp
CPU làm sai lệch runtime như khi chạy song song. Module lưu JSON gốc của từng
run trước khi tạo CSV, thống kê và biểu đồ, nên mọi con số tổng hợp đều có thể
truy ngược về dữ liệu nguồn.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from ..core.decoder import decode_vector
from ..core.greedy_baseline import GREEDY_BASELINE_NAME
from ..core.models import OptimizationAlgorithm
from ..core.snapshot import prepare_snapshot_for_optimization
from .greedy_baseline import execute_greedy_baseline
from .reporting import (
    _plot_detailed_timetable,
    _write_timetable_csv,
    build_timetable_report_rows,
)
from .run_contract import (
    REQUEST_SCHEMA_VERSION,
    execute_run_request,
    parse_run_request,
    write_result_json,
)


EXPERIMENT_SCHEMA_VERSION = "timetable-experiment.v1"
EXPERIMENT_METADATA_SCHEMA_VERSION = "timetable-experiment-metadata.v1"
ALGORITHM_ORDER = (
    OptimizationAlgorithm.GA,
    OptimizationAlgorithm.PO,
    OptimizationAlgorithm.GA_PO,
)


class ExperimentContractError(ValueError):
    """Cho biết cấu hình thực nghiệm không đáp ứng giao thức so sánh."""


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Cấu hình bất biến cho một nhóm run so sánh tuần tự."""

    experiment_id: str
    base_request_path: Path
    algorithms: tuple[OptimizationAlgorithm, ...]
    seeds: tuple[int, ...]
    include_greedy_baseline: bool = False
    create_plots: bool = True
    runtime_comparison_valid: bool = True


@dataclass(frozen=True, slots=True)
class ExperimentPaths:
    """Các artifact được tạo bởi một lần thực nghiệm."""

    output_directory: Path
    runs_directory: Path
    raw_results_csv: Path
    convergence_csv: Path
    summary_csv: Path
    metadata_json: Path
    baseline_result_json: Path | None
    convergence_image: Path | None
    fitness_comparison_image: Path | None
    plot_manifest_json: Path | None
    plot_images: tuple[Path, ...]


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExperimentContractError(f"{field_name} phải là một JSON object.")
    return value


def load_experiment_config(path: Path) -> ExperimentConfig:
    """Đọc cấu hình và giải đường dẫn request tương đối theo file config."""

    try:
        payload = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "experiment",
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentContractError(
            f"Không thể đọc cấu hình thực nghiệm: {error}"
        ) from error

    if payload.get("schema_version") != EXPERIMENT_SCHEMA_VERSION:
        raise ExperimentContractError(
            "schema_version phải là timetable-experiment.v1."
        )

    experiment_id = payload.get("experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ExperimentContractError("experiment_id phải là chuỗi không rỗng.")

    request_path_value = payload.get("base_request_path")
    if not isinstance(request_path_value, str) or not request_path_value.strip():
        raise ExperimentContractError(
            "base_request_path phải là chuỗi không rỗng."
        )
    base_request_path = Path(request_path_value)
    if not base_request_path.is_absolute():
        base_request_path = (path.resolve().parent / base_request_path).resolve()

    algorithms_value = payload.get("algorithms")
    if not isinstance(algorithms_value, list) or not algorithms_value:
        raise ExperimentContractError("algorithms phải là danh sách không rỗng.")
    try:
        algorithms = tuple(OptimizationAlgorithm(value) for value in algorithms_value)
    except (TypeError, ValueError) as error:
        raise ExperimentContractError(
            "algorithms chỉ được chứa GA, PO và GA_PO."
        ) from error
    if len(algorithms) != len(set(algorithms)):
        raise ExperimentContractError("algorithms không được chứa giá trị trùng.")

    seeds_value = payload.get("seeds")
    if not isinstance(seeds_value, list) or not seeds_value:
        raise ExperimentContractError("seeds phải là danh sách không rỗng.")
    if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds_value):
        raise ExperimentContractError("Mỗi seed phải là số nguyên.")
    seeds = tuple(seeds_value)
    if len(seeds) != len(set(seeds)):
        raise ExperimentContractError("seeds không được chứa giá trị trùng.")

    create_plots = payload.get("create_plots", True)
    if not isinstance(create_plots, bool):
        raise ExperimentContractError("create_plots phải là boolean.")

    include_greedy_baseline = payload.get("include_greedy_baseline", False)
    if not isinstance(include_greedy_baseline, bool):
        raise ExperimentContractError(
            "include_greedy_baseline phải là boolean."
        )

    runtime_comparison_valid = payload.get("runtime_comparison_valid", True)
    if not isinstance(runtime_comparison_valid, bool):
        raise ExperimentContractError(
            "runtime_comparison_valid phải là boolean."
        )

    return ExperimentConfig(
        experiment_id=experiment_id.strip(),
        base_request_path=base_request_path,
        algorithms=algorithms,
        seeds=seeds,
        include_greedy_baseline=include_greedy_baseline,
        create_plots=create_plots,
        runtime_comparison_valid=runtime_comparison_valid,
    )


def _load_base_request(path: Path) -> dict[str, Any]:
    """Đọc template request mà không thay đổi nội dung trên đĩa."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentContractError(
            f"Không thể đọc base request: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise ExperimentContractError("Base request phải là một JSON object.")
    if payload.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ExperimentContractError(
            "Base request phải dùng optimization-run-request.v1."
        )
    return payload


def _algorithm_label(algorithm: str) -> str:
    return {
        "GA": "GA",
        "PO": "PO",
        "GA_PO": "GA–PO",
        GREEDY_BASELINE_NAME: "Greedy First Feasible",
    }[algorithm]


def _completed_row(
    result: Mapping[str, Any],
    seed: int | str,
) -> dict[str, Any]:
    """Rút một result thành một dòng phẳng để ghi CSV."""

    result_payload = _mapping(result["result"], "result")
    fitness = _mapping(result_payload["best_fitness"], "best_fitness")
    metrics = _mapping(result_payload["metrics"], "metrics")
    return {
        "request_id": result["request_id"],
        "algorithm": result["algorithm"],
        "seed": seed,
        "status": result["status"],
        "q_general": fitness["general_quality_score"],
        "q_lecturer": fitness["lecturer_preference_score"],
        "runtime_seconds": metrics["runtime_seconds"],
        "fitness_evaluations": metrics["fitness_evaluations"],
        "completed_iterations": metrics["completed_iterations"],
        "candidate_attempts": metrics["candidate_attempts"],
        "decode_failed_count": metrics["decode_failed_count"],
        "validation_failed_count": metrics["validation_failed_count"],
        "repaired_individual_count": metrics["repaired_individual_count"],
        "failed_repair_count": metrics["failed_repair_count"],
        "total_repair_attempts": metrics["total_repair_attempts"],
        "discarded_offspring_count": metrics["discarded_offspring_count"],
        "total_decode_nodes": metrics["total_decode_nodes"],
        "total_decode_backtracks": metrics["total_decode_backtracks"],
        "hard_violation_count": 0,
        "timetable_entry_count": len(result_payload["timetable_entries"]),
        "rank": "",
        "error_code": "",
        "error_message": "",
    }


def _failed_row(
    result: Mapping[str, Any],
    seed: int | str,
) -> dict[str, Any]:
    """Giữ run thất bại trong dữ liệu gốc thay vì âm thầm loại khỏi thống kê."""

    error = _mapping(result.get("error") or {}, "error")
    return {
        "request_id": result.get("request_id"),
        "algorithm": result.get("algorithm"),
        "seed": seed,
        "status": result.get("status", "FAILED"),
        "q_general": "",
        "q_lecturer": "",
        "runtime_seconds": "",
        "fitness_evaluations": "",
        "completed_iterations": "",
        "candidate_attempts": "",
        "decode_failed_count": "",
        "validation_failed_count": "",
        "repaired_individual_count": "",
        "failed_repair_count": "",
        "total_repair_attempts": "",
        "discarded_offspring_count": "",
        "total_decode_nodes": "",
        "total_decode_backtracks": "",
        "hard_violation_count": "",
        "timetable_entry_count": "",
        "rank": "",
        "error_code": error.get("code", "UNKNOWN"),
        "error_message": error.get("message", "Không có thông báo lỗi."),
    }


def _assign_seed_ranks(rows: list[dict[str, Any]]) -> None:
    """Xếp hạng theo tuple Q_general → Q_lecturer cho từng seed.

    Các lịch có cùng chính xác hai score nhận hạng trung bình của những vị trí
    bị hòa. Run thất bại không được gán hạng và được phản ánh riêng qua success
    rate trong summary.
    """

    seeds = sorted({int(row["seed"]) for row in rows})
    for seed in seeds:
        completed = [
            row for row in rows
            if row["seed"] == seed and row["status"] == "COMPLETED"
        ]
        completed.sort(
            key=lambda row: (
                float(row["q_general"]),
                float(row["q_lecturer"]),
            )
        )
        index = 0
        while index < len(completed):
            key = (
                completed[index]["q_general"],
                completed[index]["q_lecturer"],
            )
            end = index + 1
            while end < len(completed):
                other_key = (
                    completed[end]["q_general"],
                    completed[end]["q_lecturer"],
                )
                if other_key != key:
                    break
                end += 1
            average_rank = ((index + 1) + end) / 2.0
            for row in completed[index:end]:
                row["rank"] = average_rank
            index = end


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    """Ghi CSV UTF-8 BOM để mở trực tiếp bằng Excel không lỗi tiếng Việt."""

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _mean(values: Sequence[float]) -> float | str:
    return statistics.fmean(values) if values else ""


def _median(values: Sequence[float]) -> float | str:
    return statistics.median(values) if values else ""


def _stdev(values: Sequence[float]) -> float | str:
    return statistics.stdev(values) if len(values) >= 2 else ""


def _build_summary(
    rows: list[dict[str, Any]],
    algorithms: tuple[OptimizationAlgorithm, ...],
) -> list[dict[str, Any]]:
    """Tổng hợp riêng từng tầng fitness; không cộng hai tầng thành một số."""

    summary: list[dict[str, Any]] = []
    for algorithm in algorithms:
        algorithm_rows = [row for row in rows if row["algorithm"] == algorithm.value]
        completed = [row for row in algorithm_rows if row["status"] == "COMPLETED"]

        def values(field: str) -> list[float]:
            return [float(row[field]) for row in completed]

        ranks = [float(row["rank"]) for row in completed if row["rank"] != ""]
        summary.append({
            "algorithm": algorithm.value,
            "total_runs": len(algorithm_rows),
            "completed_runs": len(completed),
            "success_rate": len(completed) / len(algorithm_rows),
            "median_q_general": _median(values("q_general")),
            "mean_q_general": _mean(values("q_general")),
            "stdev_q_general": _stdev(values("q_general")),
            "median_q_lecturer": _median(values("q_lecturer")),
            "mean_q_lecturer": _mean(values("q_lecturer")),
            "stdev_q_lecturer": _stdev(values("q_lecturer")),
            "median_runtime_seconds": _median(values("runtime_seconds")),
            "mean_runtime_seconds": _mean(values("runtime_seconds")),
            "median_fitness_evaluations": _median(values("fitness_evaluations")),
            "average_rank": _mean(ranks),
        })
    return summary


def _build_baseline_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    """Tạo một dòng mốc tham khảo, không giả lập thống kê nhiều seed."""

    completed = row["status"] == "COMPLETED"
    return {
        "algorithm": GREEDY_BASELINE_NAME,
        "total_runs": 1,
        "completed_runs": 1 if completed else 0,
        "success_rate": 1.0 if completed else 0.0,
        "median_q_general": row["q_general"] if completed else "",
        "mean_q_general": row["q_general"] if completed else "",
        "stdev_q_general": "",
        "median_q_lecturer": row["q_lecturer"] if completed else "",
        "mean_q_lecturer": row["q_lecturer"] if completed else "",
        "stdev_q_lecturer": "",
        "median_runtime_seconds": (
            row["runtime_seconds"] if completed else ""
        ),
        "mean_runtime_seconds": row["runtime_seconds"] if completed else "",
        "median_fitness_evaluations": (
            row["fitness_evaluations"] if completed else ""
        ),
        "average_rank": "",
    }


def _load_plotting_library():
    """Nạp matplotlib ở backend không cần giao diện cho terminal và CI."""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as pyplot
    except ImportError as error:
        raise RuntimeError(
            "Không thể tạo biểu đồ vì môi trường thiếu matplotlib."
        ) from error
    return pyplot


def _plot_convergence(
    path: Path,
    completed_results: list[tuple[str, int, Mapping[str, Any]]],
) -> None:
    """Vẽ từng run mờ và đường trung vị của mỗi thuật toán theo FE."""

    pyplot = _load_plotting_library()
    score_fields = (
        ("general_quality_score", "Chất lượng chung (Q_general)"),
        ("lecturer_preference_score", "Mong muốn giảng viên (Q_lecturer)"),
    )
    colors = {"GA": "#2f66e8", "PO": "#16837a", "GA_PO": "#e03131"}
    figure, axes = pyplot.subplots(2, 1, figsize=(12, 8), sharex=True)

    for axis, (field, title) in zip(axes, score_fields, strict=True):
        for algorithm in (item.value for item in ALGORITHM_ORDER):
            runs = [
                (seed, result["result"]["convergence_history"])
                for current_algorithm, seed, result in completed_results
                if current_algorithm == algorithm
            ]
            if not runs:
                continue
            for _, history in runs:
                axis.plot(
                    [point["fitness_evaluations"] for point in history],
                    [point[field] for point in history],
                    color=colors[algorithm],
                    alpha=0.18,
                    linewidth=1.0,
                )

            common_length = min(len(history) for _, history in runs)
            median_fe = []
            median_score = []
            for point_index in range(common_length):
                median_fe.append(statistics.median([
                    history[point_index]["fitness_evaluations"]
                    for _, history in runs
                ]))
                median_score.append(statistics.median([
                    history[point_index][field]
                    for _, history in runs
                ]))
            axis.plot(
                median_fe,
                median_score,
                color=colors[algorithm],
                linewidth=2.6,
                marker="o",
                markersize=4,
                label=f"{_algorithm_label(algorithm)} — trung vị",
            )

        axis.set_title(title, fontweight="bold")
        axis.set_ylabel("Điểm phạt")
        axis.grid(True, alpha=0.25)
        axis.legend()

    axes[-1].set_xlabel("Số lần đánh giá fitness (FE)")
    figure.suptitle(
        "Hội tụ trên bài toán thời khóa biểu\n"
        "Đường mờ: từng seed; đường đậm: trung vị các seed",
        fontsize=14,
        fontweight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def _plot_fitness_comparison(path: Path, rows: list[dict[str, Any]]) -> None:
    """Vẽ phân bố hai tầng fitness theo thuật toán, không tạo điểm tổng giả."""

    pyplot = _load_plotting_library()
    completed = [row for row in rows if row["status"] == "COMPLETED"]
    algorithms = [item.value for item in ALGORITHM_ORDER if any(
        row["algorithm"] == item.value for row in completed
    )]
    if any(row["algorithm"] == GREEDY_BASELINE_NAME for row in completed):
        algorithms.append(GREEDY_BASELINE_NAME)
    fields = (
        ("q_general", "Q_general"),
        ("q_lecturer", "Q_lecturer"),
    )
    figure, axes = pyplot.subplots(1, 2, figsize=(10, 5))
    for axis, (field, title) in zip(axes, fields, strict=True):
        data = [
            [float(row[field]) for row in completed if row["algorithm"] == algorithm]
            for algorithm in algorithms
        ]
        box = axis.boxplot(
            data,
            tick_labels=[_algorithm_label(algorithm) for algorithm in algorithms],
            patch_artist=True,
            widths=0.58,
        )
        for patch, color in zip(
            box["boxes"],
            ("#8bb6ff", "#82d1c6", "#ff9a9a", "#b8b8b8"),
        ):
            patch.set_facecolor(color)
        axis.set_title(title, fontweight="bold")
        axis.set_ylabel("Điểm phạt — nhỏ hơn tốt hơn")
        axis.grid(True, axis="y", alpha=0.25)

    figure.suptitle(
        "Phân bố chất lượng lịch qua các seed",
        fontsize=14,
        fontweight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.92))
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def _completed_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Chỉ lấy những run có đủ số liệu để vẽ biểu đồ định lượng."""

    return [row for row in rows if row.get("status") == "COMPLETED"]


def _ordered_algorithm_names(
    rows: Sequence[Mapping[str, Any]],
    *,
    include_baseline: bool = True,
) -> list[str]:
    """Giữ thứ tự thuật toán nhất quán trên mọi ảnh báo cáo."""

    present = {str(row["algorithm"]) for row in _completed_rows(rows)}
    ordered = [item.value for item in ALGORITHM_ORDER if item.value in present]
    if include_baseline and GREEDY_BASELINE_NAME in present:
        ordered.append(GREEDY_BASELINE_NAME)
    return ordered


def _boxplot_metric(
    axis: Any,
    rows: Sequence[Mapping[str, Any]],
    algorithms: Sequence[str],
    field: str,
    title: str,
    ylabel: str,
) -> None:
    """Vẽ boxplot chung; baseline một lượt được biểu diễn như một điểm đơn."""

    data = [
        [
            float(row[field])
            for row in _completed_rows(rows)
            if row["algorithm"] == algorithm and row.get(field) not in ("", None)
        ]
        for algorithm in algorithms
    ]
    box = axis.boxplot(
        data,
        tick_labels=[_algorithm_label(item) for item in algorithms],
        patch_artist=True,
        widths=0.58,
        showmeans=True,
    )
    for patch, color in zip(
        box["boxes"],
        ("#8bb6ff", "#82d1c6", "#ff9a9a", "#b8b8b8"),
    ):
        patch.set_facecolor(color)
    axis.set_title(title, fontweight="bold")
    axis.set_ylabel(ylabel)
    axis.grid(True, axis="y", alpha=0.25)


def _plot_runtime_and_fe(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    runtime_comparison_valid: bool = True,
) -> None:
    """So sánh chi phí thời gian và số lần gọi fitness thực tế."""

    pyplot = _load_plotting_library()
    algorithms = _ordered_algorithm_names(rows)
    figure, axes = pyplot.subplots(1, 2, figsize=(12, 5.5))
    _boxplot_metric(
        axes[0], rows, algorithms, "runtime_seconds",
        (
            "Thời gian chạy"
            if runtime_comparison_valid
            else "Thời gian tham khảo (chạy trên các máy khác nhau)"
        ),
        "Giây",
    )
    _boxplot_metric(
        axes[1], rows, algorithms, "fitness_evaluations",
        "Số lần đánh giá fitness thực tế", "FE",
    )
    figure.suptitle(
        (
            "Chi phí tính toán của các phương pháp"
            if runtime_comparison_valid
            else "FE dùng để so sánh; thời gian chỉ được lưu để tham khảo"
        ),
        fontsize=14,
        fontweight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.92))
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def _plot_search_diagnostics(path: Path, rows: list[dict[str, Any]]) -> None:
    """Thể hiện phần chi phí tìm kiếm không nhìn thấy chỉ qua fitness cuối."""

    pyplot = _load_plotting_library()
    algorithms = _ordered_algorithm_names(rows, include_baseline=False)
    metrics = (
        ("candidate_attempts", "Số nghiệm đã thử", "Lần thử"),
        ("decode_failed_count", "Số lần giải mã thất bại", "Số lần"),
        ("discarded_offspring_count", "Số nghiệm con bị loại", "Số nghiệm"),
        ("total_repair_attempts", "Số lần gọi repair", "Số lần"),
    )
    figure, axes = pyplot.subplots(2, 2, figsize=(13, 9))
    for axis, (field, title, ylabel) in zip(
        axes.flat,
        metrics,
        strict=True,
    ):
        _boxplot_metric(axis, rows, algorithms, field, title, ylabel)
    figure.suptitle(
        "Chẩn đoán quá trình tìm kiếm của GA, PO và GA–PO",
        fontsize=14,
        fontweight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.95))
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def _plot_rank_and_wins(path: Path, rows: list[dict[str, Any]]) -> None:
    """Vẽ hạng trung bình và số seed đứng đầu của ba optimizer."""

    pyplot = _load_plotting_library()
    algorithms = _ordered_algorithm_names(rows, include_baseline=False)
    completed = _completed_rows(rows)
    average_ranks = []
    win_counts = []
    for algorithm in algorithms:
        algorithm_rows = [row for row in completed if row["algorithm"] == algorithm]
        ranks = [float(row["rank"]) for row in algorithm_rows if row.get("rank") not in ("", None)]
        average_ranks.append(statistics.fmean(ranks) if ranks else 0.0)
        win_counts.append(sum(1 for rank in ranks if rank == 1.0))

    labels = [_algorithm_label(item) for item in algorithms]
    colors = ("#8bb6ff", "#82d1c6", "#ff9a9a")
    figure, axes = pyplot.subplots(1, 2, figsize=(11, 5))
    axes[0].bar(labels, average_ranks, color=colors[:len(labels)])
    axes[0].set_title("Hạng trung bình", fontweight="bold")
    axes[0].set_ylabel("Hạng — nhỏ hơn tốt hơn")
    axes[0].grid(True, axis="y", alpha=0.25)
    axes[1].bar(labels, win_counts, color=colors[:len(labels)])
    axes[1].set_title("Số seed đứng hạng nhất", fontweight="bold")
    axes[1].set_ylabel("Số seed")
    axes[1].grid(True, axis="y", alpha=0.25)
    figure.suptitle(
        "Xếp hạng theo cặp (Q_general, Q_lecturer)",
        fontsize=14,
        fontweight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.92))
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def _plot_objective_space(path: Path, rows: list[dict[str, Any]]) -> None:
    """Biểu diễn đồng thời hai tầng fitness mà không cộng thành điểm giả."""

    pyplot = _load_plotting_library()
    completed = _completed_rows(rows)
    algorithms = _ordered_algorithm_names(rows)
    colors = {
        "GA": "#2f66e8",
        "PO": "#16837a",
        "GA_PO": "#e03131",
        GREEDY_BASELINE_NAME: "#555555",
    }
    figure, axis = pyplot.subplots(figsize=(8.5, 6.5))
    for algorithm in algorithms:
        algorithm_rows = [row for row in completed if row["algorithm"] == algorithm]
        axis.scatter(
            [float(row["q_general"]) for row in algorithm_rows],
            [float(row["q_lecturer"]) for row in algorithm_rows],
            color=colors[algorithm],
            marker="*" if algorithm == GREEDY_BASELINE_NAME else "o",
            s=150 if algorithm == GREEDY_BASELINE_NAME else 55,
            alpha=0.85,
            label=_algorithm_label(algorithm),
        )
    axis.set_title("Không gian hai mục tiêu — góc trái dưới tốt hơn", fontweight="bold")
    axis.set_xlabel("Q_general — nhỏ hơn tốt hơn")
    axis.set_ylabel("Q_lecturer — nhỏ hơn tốt hơn")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def _plot_per_seed_scores(path: Path, rows: list[dict[str, Any]]) -> None:
    """Đặt kết quả các thuật toán cạnh nhau trên từng seed dùng chung."""

    pyplot = _load_plotting_library()
    completed = _completed_rows(rows)
    algorithms = _ordered_algorithm_names(rows, include_baseline=False)
    colors = {"GA": "#2f66e8", "PO": "#16837a", "GA_PO": "#e03131"}
    fields = (("q_general", "Q_general"), ("q_lecturer", "Q_lecturer"))
    figure, axes = pyplot.subplots(2, 1, figsize=(12, 8), sharex=True)
    for axis, (field, title) in zip(axes, fields, strict=True):
        for algorithm in algorithms:
            algorithm_rows = sorted(
                (row for row in completed if row["algorithm"] == algorithm),
                key=lambda row: int(row["seed"]),
            )
            axis.plot(
                [int(row["seed"]) for row in algorithm_rows],
                [float(row[field]) for row in algorithm_rows],
                marker="o",
                linewidth=1.8,
                markersize=4,
                color=colors[algorithm],
                label=_algorithm_label(algorithm),
            )
        axis.set_title(title, fontweight="bold")
        axis.set_ylabel("Điểm phạt")
        axis.grid(True, alpha=0.25)
        axis.legend()
    axes[-1].set_xlabel("Seed")
    figure.suptitle(
        "Kết quả cuối của từng seed dùng chung",
        fontsize=14,
        fontweight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.95))
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def _plot_success_rate(path: Path, rows: list[dict[str, Any]]) -> None:
    """Cho biết tỷ lệ tạo được lịch hợp lệ thay vì chỉ nhìn run thành công."""

    pyplot = _load_plotting_library()
    algorithms = [item.value for item in ALGORITHM_ORDER]
    if any(row["algorithm"] == GREEDY_BASELINE_NAME for row in rows):
        algorithms.append(GREEDY_BASELINE_NAME)
    rates = []
    completed_counts = []
    total_counts = []
    for algorithm in algorithms:
        algorithm_rows = [row for row in rows if row["algorithm"] == algorithm]
        completed_count = sum(row["status"] == "COMPLETED" for row in algorithm_rows)
        total_count = len(algorithm_rows)
        completed_counts.append(completed_count)
        total_counts.append(total_count)
        rates.append(100.0 * completed_count / total_count if total_count else 0.0)

    labels = [_algorithm_label(item) for item in algorithms]
    figure, axis = pyplot.subplots(figsize=(9, 5.5))
    bars = axis.bar(
        labels,
        rates,
        color=("#8bb6ff", "#82d1c6", "#ff9a9a", "#b8b8b8")[:len(labels)],
    )
    for bar, rate, completed_count, total_count in zip(
        bars, rates, completed_counts, total_counts, strict=True,
    ):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            min(rate + 2, 103),
            f"{rate:.1f}%\n({completed_count}/{total_count})",
            ha="center",
            va="bottom",
        )
    axis.set_ylim(0, 110)
    axis.set_title("Tỷ lệ hoàn thành với lịch hợp lệ", fontweight="bold")
    axis.set_ylabel("Tỷ lệ (%)")
    axis.grid(True, axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def _read_raw_result_rows(path: Path) -> list[dict[str, Any]]:
    """Đọc CSV đã lưu để có thể tạo lại ảnh mà không chạy optimizer."""

    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _export_best_timetable_images(
    config: ExperimentConfig,
    output_directory: Path,
) -> tuple[list[Path], list[dict[str, str]]]:
    """Xuất lịch tốt nhất riêng cho từng phương pháp từ vector đã lưu."""

    base_payload = _load_base_request(config.base_request_path)
    request = parse_run_request(
        base_payload,
        base_directory=config.base_request_path.parent,
    )
    prepared = prepare_snapshot_for_optimization(
        request.snapshot.path,
        expected_checksum=request.snapshot.checksum,
    )
    if not prepared.is_ready:
        raise ExperimentContractError(
            "Snapshot không còn sẵn sàng để dựng ảnh thời khóa biểu."
        )

    result_paths: dict[str, list[Path]] = {
        algorithm.value: [
            output_directory / "runs" / algorithm.value / f"seed_{seed}.json"
            for seed in config.seeds
        ]
        for algorithm in config.algorithms
    }
    if config.include_greedy_baseline:
        result_paths[GREEDY_BASELINE_NAME] = [
            output_directory / "runs" / GREEDY_BASELINE_NAME / "result.json"
        ]

    generated: list[Path] = []
    failed: list[dict[str, str]] = []
    metadata: list[dict[str, Any]] = []
    for algorithm, paths in result_paths.items():
        candidates: list[tuple[Path, Mapping[str, Any]]] = []
        for path in paths:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("status") == "COMPLETED":
                candidates.append((path, payload))
        if not candidates:
            failed.append({
                "file": f"09_best_timetable_{algorithm}.png",
                "error": "Không có run hoàn thành của phương pháp này.",
            })
            continue

        source_path, payload = min(
            candidates,
            key=lambda item: (
                float(item[1]["result"]["best_fitness"]["general_quality_score"]),
                float(item[1]["result"]["best_fitness"]["lecturer_preference_score"]),
            ),
        )
        image_path = output_directory / f"09_best_timetable_{algorithm}.png"
        csv_path = output_directory / f"09_best_timetable_{algorithm}.csv"
        try:
            vector = tuple(
                float(value)
                for value in payload["result"]["best_solution"]["vector"]
            )
            decoded = decode_vector(
                prepared.problem,
                prepared.option_domains,
                vector,
                max_decode_nodes=request.evaluation_config.max_decode_nodes,
            )
            if not decoded.is_success:
                raise RuntimeError(
                    f"Không thể giải mã lại vector tốt nhất: {decoded.reason}"
                )
            report_proxy = SimpleNamespace(
                best_individual=SimpleNamespace(
                    selected_options=decoded.selected_options,
                )
            )
            timetable_rows = build_timetable_report_rows(
                prepared.problem,
                report_proxy,
            )
            _write_timetable_csv(csv_path, timetable_rows)
            _plot_detailed_timetable(image_path, timetable_rows)
            generated.append(image_path)
            metadata.append({
                "algorithm": algorithm,
                "source_run": str(source_path.relative_to(output_directory)),
                "request_id": payload["request_id"],
                "image": image_path.name,
                "csv": csv_path.name,
                "entry_count": len(timetable_rows),
                "best_fitness": payload["result"]["best_fitness"],
            })
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
            failed.append({"file": image_path.name, "error": str(error)})

    metadata_path = output_directory / "09_best_timetables_metadata.json"
    metadata_path.write_text(
        json.dumps({
            "schema_version": "best-timetables-by-algorithm.v1",
            "selection_rule": "LEXICOGRAPHIC_Q_GENERAL_Q_LECTURER",
            "timetables": metadata,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return generated, failed


def generate_experiment_plots(
    config: ExperimentConfig,
    output_directory: Path,
) -> tuple[tuple[Path, ...], Path]:
    """Tạo toàn bộ ảnh từ artifact đã lưu và ghi manifest thành công/lỗi.

    Hàm cố ý không chạy optimizer. Vì vậy người dùng có thể dùng chế độ
    ``--plots-only`` để tạo lại ảnh sau một lượt benchmark nhiều giờ.
    """

    raw_results_path = output_directory / "raw_results.csv"
    if not raw_results_path.exists():
        raise ExperimentContractError(
            f"Không tìm thấy dữ liệu để vẽ ảnh: {raw_results_path}"
        )
    rows = _read_raw_result_rows(raw_results_path)
    completed_results: list[tuple[str, int, Mapping[str, Any]]] = []
    for seed in config.seeds:
        for algorithm in config.algorithms:
            result_path = output_directory / "runs" / algorithm.value / f"seed_{seed}.json"
            if not result_path.exists():
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if result.get("status") == "COMPLETED":
                completed_results.append((algorithm.value, seed, result))

    plot_specs = (
        ("01_convergence.png", lambda path: _plot_convergence(path, completed_results)),
        ("02_fitness_comparison.png", lambda path: _plot_fitness_comparison(path, rows)),
        (
            "03_runtime_and_fe.png",
            lambda path: _plot_runtime_and_fe(
                path,
                rows,
                runtime_comparison_valid=config.runtime_comparison_valid,
            ),
        ),
        ("04_search_diagnostics.png", lambda path: _plot_search_diagnostics(path, rows)),
        ("05_rank_and_wins.png", lambda path: _plot_rank_and_wins(path, rows)),
        ("06_objective_space.png", lambda path: _plot_objective_space(path, rows)),
        ("07_per_seed_scores.png", lambda path: _plot_per_seed_scores(path, rows)),
        ("08_success_rate.png", lambda path: _plot_success_rate(path, rows)),
    )
    generated: list[Path] = []
    failed: list[dict[str, str]] = []
    for filename, plotter in plot_specs:
        path = output_directory / filename
        try:
            plotter(path)
            generated.append(path)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as error:
            failed.append({"file": filename, "error": str(error)})

    try:
        timetable_images, timetable_failures = _export_best_timetable_images(
            config,
            output_directory,
        )
        generated.extend(timetable_images)
        failed.extend(timetable_failures)
    except (ExperimentContractError, OSError, RuntimeError, TypeError, ValueError) as error:
        failed.append({
            "file": "09_best_timetable_*.png",
            "error": str(error),
        })

    manifest_path = output_directory / "plot_manifest.json"
    manifest_path.write_text(
        json.dumps({
            "schema_version": "timetable-experiment-plots.v1",
            "generated": [path.name for path in generated],
            "failed": failed,
            "regeneration_note": (
                "Dùng lại file cấu hình ban đầu, cùng output-directory và "
                "thêm --plots-only; optimizer sẽ không chạy lại."
            ),
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return tuple(generated), manifest_path


def run_experiment(
    config: ExperimentConfig,
    output_directory: Path,
    *,
    resume_completed: bool = False,
) -> ExperimentPaths:
    """Chạy tuần tự toàn bộ algorithm × seed và tạo artifact kiểm chứng.

    Khi ``resume_completed`` được bật, runner tái sử dụng duy nhất những JSON
    đã hoàn thành, đúng thuật toán và đúng checksum snapshot. Run thiếu, lỗi
    hoặc không khớp đề bài sẽ được chạy lại. Cơ chế này tránh mất nhiều giờ
    tính toán khi benchmark phân tán bị ngắt giữa chừng.
    """

    output_directory.mkdir(parents=True, exist_ok=True)
    runs_directory = output_directory / "runs"
    runs_directory.mkdir(parents=True, exist_ok=True)
    base_payload = _load_base_request(config.base_request_path)

    rows: list[dict[str, Any]] = []
    convergence_rows: list[dict[str, Any]] = []
    completed_results: list[tuple[str, int, Mapping[str, Any]]] = []
    snapshot_checksums: set[str] = set()
    started_at = datetime.now(timezone.utc)
    baseline_result_json: Path | None = None
    baseline_row: dict[str, Any] | None = None
    expected_snapshot_checksum = str(
        _mapping(base_payload.get("snapshot"), "snapshot").get("checksum")
    )

    def reusable_result(path: Path, algorithm_name: str) -> Mapping[str, Any] | None:
        if not resume_completed or not path.exists():
            return None
        try:
            payload = _mapping(
                json.loads(path.read_text(encoding="utf-8")),
                "result",
            )
        except (OSError, json.JSONDecodeError, ExperimentContractError):
            return None
        if (
            payload.get("status") != "COMPLETED"
            or payload.get("algorithm") != algorithm_name
            or str(payload.get("snapshot_checksum")) != expected_snapshot_checksum
        ):
            return None
        return payload

    if config.include_greedy_baseline:
        baseline_directory = runs_directory / GREEDY_BASELINE_NAME
        baseline_result_json = baseline_directory / "result.json"
        baseline_result = reusable_result(
            baseline_result_json,
            GREEDY_BASELINE_NAME,
        )
        if baseline_result is None:
            baseline_result = execute_greedy_baseline(
                base_payload,
                base_directory=config.base_request_path.parent,
                request_id=f"{config.experiment_id}-{GREEDY_BASELINE_NAME}",
            )
            write_result_json(baseline_result_json, baseline_result)
        if baseline_result["status"] == "COMPLETED":
            baseline_row = _completed_row(baseline_result, "DETERMINISTIC")
            snapshot_checksums.add(str(baseline_result["snapshot_checksum"]))
        else:
            baseline_row = _failed_row(baseline_result, "DETERMINISTIC")

    # Seed nằm ở vòng ngoài để ba thuật toán của cùng điều kiện được chạy gần
    # nhau về thời gian, giảm ảnh hưởng của tải máy thay đổi dài hạn.
    for seed in config.seeds:
        for algorithm in config.algorithms:
            run_directory = runs_directory / algorithm.value
            run_path = run_directory / f"seed_{seed}.json"
            result = reusable_result(run_path, algorithm.value)

            request_payload = deepcopy(base_payload)
            request_payload["request_id"] = (
                f"{config.experiment_id}-{algorithm.value}-seed-{seed}"
            )
            request_payload["algorithm"] = algorithm.value
            request_payload["random_seed"] = seed
            if result is None:
                request = parse_run_request(
                    request_payload,
                    base_directory=config.base_request_path.parent,
                )
                result = execute_run_request(request)
                write_result_json(run_path, result)

            if result["status"] == "COMPLETED":
                row = _completed_row(result, seed)
                completed_results.append((algorithm.value, seed, result))
                snapshot_checksums.add(str(result["snapshot_checksum"]))
                for point in result["result"]["convergence_history"]:
                    convergence_rows.append({
                        "algorithm": algorithm.value,
                        "seed": seed,
                        **point,
                    })
            else:
                row = _failed_row(result, seed)
            rows.append(row)

    _assign_seed_ranks(rows)
    summary_rows = _build_summary(rows, config.algorithms)
    if baseline_row is not None:
        # Baseline xác định là mốc tham khảo riêng, không nhận rank theo seed
        # và không được biến thành 30 quan sát giả giống nhau.
        rows.append(baseline_row)
        summary_rows.append(_build_baseline_summary(baseline_row))

    raw_results_csv = output_directory / "raw_results.csv"
    convergence_csv = output_directory / "convergence.csv"
    summary_csv = output_directory / "summary.csv"
    metadata_json = output_directory / "experiment_metadata.json"
    raw_fields = tuple(rows[0].keys())
    convergence_fields = (
        "algorithm",
        "seed",
        "iteration",
        "fitness_evaluations",
        "general_quality_score",
        "lecturer_preference_score",
    )
    summary_fields = tuple(summary_rows[0].keys())
    _write_csv(raw_results_csv, rows, raw_fields)
    _write_csv(convergence_csv, convergence_rows, convergence_fields)
    _write_csv(summary_csv, summary_rows, summary_fields)

    finished_at = datetime.now(timezone.utc)
    metadata = {
        "schema_version": EXPERIMENT_METADATA_SCHEMA_VERSION,
        "experiment_id": config.experiment_id,
        "execution_mode": "SEQUENTIAL",
        "resume_completed": resume_completed,
        "base_request_path": str(config.base_request_path),
        # Lưu nguyên template request để kết quả vẫn tái lập được ngay cả khi
        # file cấu hình demo bị chỉnh sửa sau ngày thực nghiệm.
        "base_request": base_payload,
        "algorithms": [algorithm.value for algorithm in config.algorithms],
        "seeds": list(config.seeds),
        "include_greedy_baseline": config.include_greedy_baseline,
        "runtime_comparison_valid": config.runtime_comparison_valid,
        "planned_optimizer_run_count": len(config.algorithms) * len(config.seeds),
        "planned_baseline_run_count": 1 if config.include_greedy_baseline else 0,
        "planned_run_count": (
            len(config.algorithms) * len(config.seeds)
            + (1 if config.include_greedy_baseline else 0)
        ),
        "completed_optimizer_run_count": len(completed_results),
        "completed_baseline_run_count": (
            1
            if baseline_row is not None and baseline_row["status"] == "COMPLETED"
            else 0
        ),
        "completed_run_count": (
            len(completed_results)
            + (
                1
                if baseline_row is not None
                and baseline_row["status"] == "COMPLETED"
                else 0
            )
        ),
        "snapshot_checksums": sorted(snapshot_checksums),
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "elapsed_seconds": (finished_at - started_at).total_seconds(),
        "fairness_note": (
            "Ở cùng seed, GA, PO và GA_PO dùng cùng snapshot, cấu hình, "
            "quần thể khởi tạo, population size và số vòng xử lý quần thể. "
            "Do vector không hợp lệ bị loại trước Fitness, FE thực tế có thể "
            "khác nhau và được báo cáo như một chỉ số hiệu quả, không được "
            "mô tả là ngân sách FE bằng nhau. GREEDY_FIRST_FEASIBLE chỉ dựng "
            "một lịch xác định làm mốc tham khảo, không thuộc phép so sánh "
            "nhiều seed."
        ),
    }
    metadata_json.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    convergence_image = None
    fitness_comparison_image = None
    plot_manifest_json = None
    plot_images: tuple[Path, ...] = ()
    if config.create_plots and completed_results:
        # Vẽ lại từ JSON/CSV vừa lưu thay vì dùng object trong bộ nhớ. Cách này
        # kiểm chứng luôn rằng chế độ --plots-only có thể phục hồi ảnh mà không
        # phải chạy lại thực nghiệm nhiều giờ.
        plot_images, plot_manifest_json = generate_experiment_plots(
            config,
            output_directory,
        )
        plot_manifest = json.loads(
            plot_manifest_json.read_text(encoding="utf-8")
        )
        metadata["generated_plot_files"] = plot_manifest["generated"]
        metadata["plot_failures"] = plot_manifest["failed"]
        metadata_json.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        candidate = output_directory / "01_convergence.png"
        convergence_image = candidate if candidate in plot_images else None
        candidate = output_directory / "02_fitness_comparison.png"
        fitness_comparison_image = candidate if candidate in plot_images else None

    return ExperimentPaths(
        output_directory=output_directory,
        runs_directory=runs_directory,
        raw_results_csv=raw_results_csv,
        convergence_csv=convergence_csv,
        summary_csv=summary_csv,
        metadata_json=metadata_json,
        baseline_result_json=baseline_result_json,
        convergence_image=convergence_image,
        fitness_comparison_image=fitness_comparison_image,
        plot_manifest_json=plot_manifest_json,
        plot_images=plot_images,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Chạy Greedy baseline cùng thực nghiệm GA, PO và GA-PO trên "
            "cùng bài toán lịch."
        ),
    )
    parser.add_argument("config", type=Path, help="File timetable-experiment.v1.")
    parser.add_argument(
        "--output-directory",
        type=Path,
        required=True,
        help="Thư mục lưu JSON gốc, CSV và biểu đồ.",
    )
    parser.add_argument(
        "--plots-only",
        action="store_true",
        help=(
            "Chỉ tạo lại ảnh từ JSON/CSV đã lưu; không chạy Greedy, GA, PO "
            "hoặc GA–PO."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Tái sử dụng các run COMPLETED đúng thuật toán và checksum; chỉ "
            "chạy lại kết quả còn thiếu, lỗi hoặc không khớp."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point dùng cho pilot và thực nghiệm chính thức."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    args = _build_parser().parse_args(argv)
    try:
        config = load_experiment_config(args.config)
        if args.plots_only:
            plot_images, manifest_path = generate_experiment_plots(
                config,
                args.output_directory,
            )
            print(json.dumps({
                "schema_version": "timetable-experiment-event.v1",
                "event": "PLOTS_GENERATED",
                "experiment_id": config.experiment_id,
                "plot_count": len(plot_images),
                "plot_manifest": str(manifest_path.resolve()),
                "output_directory": str(args.output_directory.resolve()),
            }, ensure_ascii=False))
            return 0
        paths = run_experiment(
            config,
            args.output_directory,
            resume_completed=args.resume,
        )
    except (ExperimentContractError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"Không thể chạy thực nghiệm: {error}", file=sys.stderr)
        return 2

    metadata = json.loads(paths.metadata_json.read_text(encoding="utf-8"))
    print(json.dumps({
        "schema_version": "timetable-experiment-event.v1",
        "event": "COMPLETED",
        "experiment_id": config.experiment_id,
        "planned_run_count": metadata["planned_run_count"],
        "completed_run_count": metadata["completed_run_count"],
        "generated_plot_count": len(metadata.get("generated_plot_files", [])),
        "plot_failure_count": len(metadata.get("plot_failures", [])),
        "output_directory": str(paths.output_directory.resolve()),
    }, ensure_ascii=False))
    return 0 if metadata["completed_run_count"] == metadata["planned_run_count"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
