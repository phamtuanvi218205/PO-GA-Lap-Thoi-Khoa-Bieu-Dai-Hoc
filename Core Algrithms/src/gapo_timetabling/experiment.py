"""Thực nghiệm công bằng GA, PO và GA–PO trên bài toán thời khóa biểu.

Runner sử dụng trực tiếp ``optimization-run-request.v1`` và
``optimization-run-result.v1``. Với mỗi seed, chỉ hai trường ``algorithm`` và
``request_id`` thay đổi; snapshot, quần thể, ngân sách FE, decoder, repair và
các tham số còn lại được giữ nguyên. Nhờ tính xác định của bước khởi tạo, ba
optimizer nhận cùng quần thể ban đầu ở cùng một seed.

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
from typing import Any, Mapping, Sequence

from .models import OptimizationAlgorithm
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
    create_plots: bool = True


@dataclass(frozen=True, slots=True)
class ExperimentPaths:
    """Các artifact được tạo bởi một lần thực nghiệm."""

    output_directory: Path
    runs_directory: Path
    raw_results_csv: Path
    convergence_csv: Path
    summary_csv: Path
    metadata_json: Path
    convergence_image: Path | None
    fitness_comparison_image: Path | None


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

    return ExperimentConfig(
        experiment_id=experiment_id.strip(),
        base_request_path=base_request_path,
        algorithms=algorithms,
        seeds=seeds,
        create_plots=create_plots,
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
    }[algorithm]


def _completed_row(result: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Rút một result thành một dòng phẳng để ghi CSV."""

    result_payload = _mapping(result["result"], "result")
    fitness = _mapping(result_payload["best_fitness"], "best_fitness")
    metrics = _mapping(result_payload["metrics"], "metrics")
    return {
        "request_id": result["request_id"],
        "algorithm": result["algorithm"],
        "seed": seed,
        "status": result["status"],
        "q_time": fitness["time_stability_score"],
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


def _failed_row(result: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Giữ run thất bại trong dữ liệu gốc thay vì âm thầm loại khỏi thống kê."""

    error = _mapping(result.get("error") or {}, "error")
    return {
        "request_id": result.get("request_id"),
        "algorithm": result.get("algorithm"),
        "seed": seed,
        "status": result.get("status", "FAILED"),
        "q_time": "",
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
    """Xếp hạng theo tuple Q_time → Q_general → Q_lecturer cho từng seed.

    Các lịch có cùng chính xác ba score nhận hạng trung bình của những vị trí
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
                float(row["q_time"]),
                float(row["q_general"]),
                float(row["q_lecturer"]),
            )
        )
        index = 0
        while index < len(completed):
            key = (
                completed[index]["q_time"],
                completed[index]["q_general"],
                completed[index]["q_lecturer"],
            )
            end = index + 1
            while end < len(completed):
                other_key = (
                    completed[end]["q_time"],
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
    """Tổng hợp riêng từng tầng fitness; không cộng ba tầng thành một số."""

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
            "median_q_time": _median(values("q_time")),
            "mean_q_time": _mean(values("q_time")),
            "stdev_q_time": _stdev(values("q_time")),
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
        ("time_stability_score", "Độ không ổn định thứ/tiết (Q_time)"),
        ("general_quality_score", "Chất lượng chung (Q_general)"),
        ("lecturer_preference_score", "Mong muốn giảng viên (Q_lecturer)"),
    )
    colors = {"GA": "#2f66e8", "PO": "#16837a", "GA_PO": "#e03131"}
    figure, axes = pyplot.subplots(3, 1, figsize=(12, 11), sharex=True)

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
    """Vẽ phân bố ba tầng fitness theo thuật toán, không tạo điểm tổng giả."""

    pyplot = _load_plotting_library()
    completed = [row for row in rows if row["status"] == "COMPLETED"]
    algorithms = [item.value for item in ALGORITHM_ORDER if any(
        row["algorithm"] == item.value for row in completed
    )]
    fields = (
        ("q_time", "Q_time"),
        ("q_general", "Q_general"),
        ("q_lecturer", "Q_lecturer"),
    )
    figure, axes = pyplot.subplots(1, 3, figsize=(13, 5))
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
            ("#8bb6ff", "#82d1c6", "#ff9a9a"),
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


def run_experiment(
    config: ExperimentConfig,
    output_directory: Path,
) -> ExperimentPaths:
    """Chạy tuần tự toàn bộ algorithm × seed và tạo artifact kiểm chứng."""

    output_directory.mkdir(parents=True, exist_ok=True)
    runs_directory = output_directory / "runs"
    runs_directory.mkdir(parents=True, exist_ok=True)
    base_payload = _load_base_request(config.base_request_path)

    rows: list[dict[str, Any]] = []
    convergence_rows: list[dict[str, Any]] = []
    completed_results: list[tuple[str, int, Mapping[str, Any]]] = []
    snapshot_checksums: set[str] = set()
    started_at = datetime.now(timezone.utc)

    # Seed nằm ở vòng ngoài để ba thuật toán của cùng điều kiện được chạy gần
    # nhau về thời gian, giảm ảnh hưởng của tải máy thay đổi dài hạn.
    for seed in config.seeds:
        for algorithm in config.algorithms:
            request_payload = deepcopy(base_payload)
            request_payload["request_id"] = (
                f"{config.experiment_id}-{algorithm.value}-seed-{seed}"
            )
            request_payload["algorithm"] = algorithm.value
            request_payload["random_seed"] = seed
            request = parse_run_request(
                request_payload,
                base_directory=config.base_request_path.parent,
            )
            result = execute_run_request(request)

            run_directory = runs_directory / algorithm.value
            run_path = run_directory / f"seed_{seed}.json"
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
        "time_stability_score",
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
        "base_request_path": str(config.base_request_path),
        # Lưu nguyên template request để kết quả vẫn tái lập được ngay cả khi
        # file cấu hình demo bị chỉnh sửa sau ngày thực nghiệm.
        "base_request": base_payload,
        "algorithms": [algorithm.value for algorithm in config.algorithms],
        "seeds": list(config.seeds),
        "planned_run_count": len(config.algorithms) * len(config.seeds),
        "completed_run_count": len(completed_results),
        "snapshot_checksums": sorted(snapshot_checksums),
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "elapsed_seconds": (finished_at - started_at).total_seconds(),
        "fairness_note": (
            "Ở cùng seed, ba optimizer dùng cùng snapshot, cấu hình, quần thể "
            "khởi tạo và ngân sách FE lý thuyết."
        ),
    }
    metadata_json.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    convergence_image = None
    fitness_comparison_image = None
    if config.create_plots and completed_results:
        convergence_image = output_directory / "01_convergence.png"
        fitness_comparison_image = output_directory / "02_fitness_comparison.png"
        _plot_convergence(convergence_image, completed_results)
        _plot_fitness_comparison(fitness_comparison_image, rows)

    return ExperimentPaths(
        output_directory=output_directory,
        runs_directory=runs_directory,
        raw_results_csv=raw_results_csv,
        convergence_csv=convergence_csv,
        summary_csv=summary_csv,
        metadata_json=metadata_json,
        convergence_image=convergence_image,
        fitness_comparison_image=fitness_comparison_image,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chạy thực nghiệm GA, PO và GA-PO trên cùng bài toán lịch.",
    )
    parser.add_argument("config", type=Path, help="File timetable-experiment.v1.")
    parser.add_argument(
        "--output-directory",
        type=Path,
        required=True,
        help="Thư mục lưu JSON gốc, CSV và biểu đồ.",
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
        paths = run_experiment(config, args.output_directory)
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
        "output_directory": str(paths.output_directory.resolve()),
    }, ensure_ascii=False))
    return 0 if metadata["completed_run_count"] == metadata["planned_run_count"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
