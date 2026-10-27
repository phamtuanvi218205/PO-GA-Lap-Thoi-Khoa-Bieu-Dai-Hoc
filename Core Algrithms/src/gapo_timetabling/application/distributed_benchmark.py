"""Chạy và hợp nhất benchmark thời khóa biểu trên nhiều máy.

Mỗi máy phụ trách trọn một phương pháp để người dùng chỉ cần chuyển nguyên
thư mục kết quả. GA, PO và GA–PO dùng cùng danh sách seed; Greedy xác định
được chạy kèm worker GA–PO. Lệnh merge kiểm tra suite, fingerprint giao thức,
checksum snapshot, thuật toán và số seed trước khi tạo CSV và biểu đồ.

Runtime vẫn được lưu để truy vết nhưng không dùng để xếp hạng vì các worker có
thể chạy trên phần cứng khác nhau. Ngân sách và trục so sánh chính là số vòng,
population, FE thực tế và chất lượng nghiệm.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..core.greedy_baseline import GREEDY_BASELINE_NAME
from ..core.models import OptimizationAlgorithm
from .experiment import (
    EXPERIMENT_METADATA_SCHEMA_VERSION,
    ExperimentConfig,
    ExperimentContractError,
    ExperimentPaths,
    _algorithm_label,
    _assign_seed_ranks,
    _build_baseline_summary,
    _build_summary,
    _completed_row,
    _failed_row,
    _load_base_request,
    _load_plotting_library,
    _mapping,
    _write_csv,
    generate_experiment_plots,
    load_experiment_config,
    run_experiment,
)


SUITE_SCHEMA_VERSION = "distributed-benchmark-suite.v1"
WORKER_MANIFEST_SCHEMA_VERSION = "distributed-benchmark-worker.v1"
MERGED_MANIFEST_SCHEMA_VERSION = "distributed-benchmark-merged.v1"


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """Một mức quy mô trong bộ đánh giá khả năng mở rộng."""

    case_id: str
    label: str
    experiment_config_path: Path
    dimension: int
    class_session_count: int


@dataclass(frozen=True, slots=True)
class DistributedBenchmarkSuite:
    """Danh sách bài toán được chạy bằng cùng một giao thức."""

    suite_id: str
    cases: tuple[BenchmarkCase, ...]


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _protocol_fingerprint(config: ExperimentConfig) -> str:
    """Khóa mọi tham số phải giống nhau giữa các worker của cùng case."""

    return _canonical_hash({
        "base_request": _load_base_request(config.base_request_path),
        "seeds": list(config.seeds),
    })


def _git_source_state() -> dict[str, Any]:
    """Ghi revision để ba máy chứng minh đã chạy cùng một phiên bản code."""

    try:
        revision = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ("git", "status", "--porcelain"),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {"git_revision": None, "git_dirty": None}
    return {"git_revision": revision or None, "git_dirty": bool(status.strip())}


def load_suite(path: Path) -> DistributedBenchmarkSuite:
    """Đọc suite và giải đường dẫn config theo vị trí file suite."""

    try:
        payload = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "suite",
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentContractError(
            f"Không thể đọc cấu hình benchmark phân tán: {error}"
        ) from error
    if payload.get("schema_version") != SUITE_SCHEMA_VERSION:
        raise ExperimentContractError(
            f"schema_version phải là {SUITE_SCHEMA_VERSION}."
        )
    suite_id = payload.get("suite_id")
    if not isinstance(suite_id, str) or not suite_id.strip():
        raise ExperimentContractError("suite_id phải là chuỗi không rỗng.")
    case_values = payload.get("cases")
    if not isinstance(case_values, list) or not case_values:
        raise ExperimentContractError("cases phải là danh sách không rỗng.")

    cases: list[BenchmarkCase] = []
    case_ids: set[str] = set()
    for index, value in enumerate(case_values):
        item = _mapping(value, f"cases[{index}]")
        case_id = item.get("case_id")
        label = item.get("label")
        config_value = item.get("experiment_config_path")
        dimension = item.get("dimension")
        class_session_count = item.get("class_session_count")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ExperimentContractError(f"cases[{index}].case_id không hợp lệ.")
        if case_id in case_ids:
            raise ExperimentContractError(f"case_id bị trùng: {case_id}")
        if not isinstance(label, str) or not label.strip():
            raise ExperimentContractError(f"cases[{index}].label không hợp lệ.")
        if not isinstance(config_value, str) or not config_value.strip():
            raise ExperimentContractError(
                f"cases[{index}].experiment_config_path không hợp lệ."
            )
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
            raise ExperimentContractError(f"cases[{index}].dimension không hợp lệ.")
        if (
            isinstance(class_session_count, bool)
            or not isinstance(class_session_count, int)
            or class_session_count <= 0
        ):
            raise ExperimentContractError(
                f"cases[{index}].class_session_count không hợp lệ."
            )
        config_path = Path(config_value)
        if not config_path.is_absolute():
            config_path = (path.resolve().parent / config_path).resolve()
        cases.append(BenchmarkCase(
            case_id=case_id.strip(),
            label=label.strip(),
            experiment_config_path=config_path,
            dimension=dimension,
            class_session_count=class_session_count,
        ))
        case_ids.add(case_id)
    return DistributedBenchmarkSuite(suite_id=suite_id.strip(), cases=tuple(cases))


def _worker_manifest_payload(
    suite: DistributedBenchmarkSuite,
    worker: OptimizationAlgorithm,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for case in suite.cases:
        config = load_experiment_config(case.experiment_config_path)
        cases.append({
            "case_id": case.case_id,
            "experiment_id": config.experiment_id,
            "protocol_fingerprint": _protocol_fingerprint(config),
            "seeds": list(config.seeds),
            "snapshot_checksum": _mapping(
                _load_base_request(config.base_request_path)["snapshot"],
                "snapshot",
            )["checksum"],
            "status": "PENDING",
        })
    source_state = _git_source_state()
    return {
        "schema_version": WORKER_MANIFEST_SCHEMA_VERSION,
        "suite_id": suite.suite_id,
        "worker": worker.value,
        "includes_greedy_baseline": worker is OptimizationAlgorithm.GA_PO,
        "status": "RUNNING",
        "runtime_comparison_valid": False,
        "runtime_note": (
            "Các worker có thể dùng phần cứng khác nhau; runtime chỉ để truy "
            "vết, không dùng để kết luận thuật toán nào nhanh hơn."
        ),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "node": platform.node(),
            **source_state,
        },
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "finished_at_utc": None,
        "cases": cases,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_worker_suite(
    suite: DistributedBenchmarkSuite,
    worker: OptimizationAlgorithm,
    output_root: Path,
) -> Path:
    """Chạy một thuật toán trên mọi case và tự tiếp tục run đã hoàn thành."""

    source_state = _git_source_state()
    if not source_state["git_revision"]:
        raise ExperimentContractError(
            "Không xác định được Git revision; phải chạy từ repository đã commit."
        )
    if source_state["git_dirty"]:
        raise ExperimentContractError(
            "Source còn thay đổi chưa commit. Hãy commit/push rồi chạy benchmark "
            "từ đúng commit để ba máy có kết quả có thể hợp nhất."
        )

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "worker_manifest.json"
    manifest = _worker_manifest_payload(suite, worker)
    _write_json(manifest_path, manifest)

    for case_index, case in enumerate(suite.cases):
        master = load_experiment_config(case.experiment_config_path)
        if worker not in master.algorithms:
            raise ExperimentContractError(
                f"Case {case.case_id} không cấu hình thuật toán {worker.value}."
            )
        partial = replace(
            master,
            experiment_id=f"{master.experiment_id}-worker-{worker.value}",
            algorithms=(worker,),
            include_greedy_baseline=(
                worker is OptimizationAlgorithm.GA_PO
                and master.include_greedy_baseline
            ),
            create_plots=False,
            runtime_comparison_valid=False,
        )
        paths = run_experiment(
            partial,
            output_root / case.case_id,
            resume_completed=True,
        )
        metadata = json.loads(paths.metadata_json.read_text(encoding="utf-8"))
        manifest["cases"][case_index]["status"] = (
            "COMPLETED"
            if metadata["completed_run_count"] == metadata["planned_run_count"]
            else "INCOMPLETE"
        )
        manifest["cases"][case_index]["output_directory"] = str(
            paths.output_directory.resolve()
        )
        manifest["cases"][case_index]["completed_run_count"] = metadata[
            "completed_run_count"
        ]
        manifest["cases"][case_index]["planned_run_count"] = metadata[
            "planned_run_count"
        ]
        _write_json(manifest_path, manifest)

    manifest["status"] = (
        "COMPLETED"
        if all(item["status"] == "COMPLETED" for item in manifest["cases"])
        else "INCOMPLETE"
    )
    manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(manifest_path, manifest)
    return manifest_path


def _load_worker_manifests(
    suite: DistributedBenchmarkSuite,
    part_roots: Sequence[Path],
) -> dict[str, tuple[Path, Mapping[str, Any]]]:
    workers: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    for root in part_roots:
        manifest_path = root / "worker_manifest.json"
        try:
            manifest = _mapping(
                json.loads(manifest_path.read_text(encoding="utf-8")),
                "worker_manifest",
            )
        except (OSError, json.JSONDecodeError) as error:
            raise ExperimentContractError(
                f"Không thể đọc {manifest_path}: {error}"
            ) from error
        if manifest.get("schema_version") != WORKER_MANIFEST_SCHEMA_VERSION:
            raise ExperimentContractError(f"Sai schema worker: {manifest_path}")
        if manifest.get("suite_id") != suite.suite_id:
            raise ExperimentContractError(
                f"Worker {root} thuộc suite khác: {manifest.get('suite_id')}"
            )
        if manifest.get("status") != "COMPLETED":
            raise ExperimentContractError(
                f"Worker chưa hoàn thành đầy đủ: {root}"
            )
        worker = manifest.get("worker")
        if worker not in {item.value for item in OptimizationAlgorithm}:
            raise ExperimentContractError(f"Worker không hợp lệ trong {manifest_path}.")
        if worker in workers:
            raise ExperimentContractError(f"Có hai thư mục cùng worker {worker}.")
        workers[str(worker)] = (root, manifest)

    expected = {item.value for item in OptimizationAlgorithm}
    missing = sorted(expected - set(workers))
    if missing:
        raise ExperimentContractError(
            "Thiếu thư mục kết quả của worker: " + ", ".join(missing)
        )
    revision_values = [
        manifest.get("environment", {}).get("git_revision")
        for _, manifest in workers.values()
    ]
    if any(not revision for revision in revision_values):
        raise ExperimentContractError(
            "Không xác định được Git revision của đủ ba worker."
        )
    revisions = {str(revision) for revision in revision_values}
    if len(revisions) > 1:
        raise ExperimentContractError(
            "Ba worker được chạy từ các Git revision khác nhau: "
            + ", ".join(sorted(str(item) for item in revisions))
        )
    dirty_workers = sorted(
        worker
        for worker, (_, manifest) in workers.items()
        if manifest.get("environment", {}).get("git_dirty") is True
    )
    if dirty_workers:
        raise ExperimentContractError(
            "Worker đã chạy khi source còn thay đổi chưa commit: "
            + ", ".join(dirty_workers)
        )
    return workers


def _copy_result(source: Path, target: Path) -> Mapping[str, Any]:
    try:
        payload = _mapping(
            json.loads(source.read_text(encoding="utf-8")),
            "optimization_result",
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentContractError(f"Không thể đọc kết quả {source}: {error}") from error
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != source.read_bytes():
        raise ExperimentContractError(
            f"Đích đã có kết quả khác nội dung, không ghi đè: {target}"
        )
    if not target.exists():
        shutil.copy2(source, target)
    return payload


def _validate_worker_case(
    case: BenchmarkCase,
    master: ExperimentConfig,
    worker_manifest: Mapping[str, Any],
) -> None:
    entries = [
        item for item in worker_manifest.get("cases", [])
        if isinstance(item, Mapping) and item.get("case_id") == case.case_id
    ]
    if len(entries) != 1:
        raise ExperimentContractError(
            f"Worker không có đúng một metadata cho case {case.case_id}."
        )
    if entries[0].get("protocol_fingerprint") != _protocol_fingerprint(master):
        raise ExperimentContractError(
            f"Case {case.case_id} khác snapshot, seed hoặc cấu hình chạy."
        )


def merge_case_results(
    case: BenchmarkCase,
    part_roots: Mapping[str, tuple[Path, Mapping[str, Any]]],
    output_directory: Path,
) -> ExperimentPaths:
    """Ghép ba worker của một case và tạo lại artifact tổng hợp."""

    config = load_experiment_config(case.experiment_config_path)
    base_payload = _load_base_request(config.base_request_path)
    expected_checksum = str(_mapping(base_payload["snapshot"], "snapshot")["checksum"])
    output_directory.mkdir(parents=True, exist_ok=True)
    runs_directory = output_directory / "runs"
    rows: list[dict[str, Any]] = []
    convergence_rows: list[dict[str, Any]] = []
    completed_results: list[tuple[str, int, Mapping[str, Any]]] = []
    snapshot_checksums: set[str] = set()

    for algorithm in config.algorithms:
        root, worker_manifest = part_roots[algorithm.value]
        _validate_worker_case(case, config, worker_manifest)
        for seed in config.seeds:
            relative = Path("runs") / algorithm.value / f"seed_{seed}.json"
            source = root / case.case_id / relative
            if not source.exists():
                raise ExperimentContractError(f"Thiếu kết quả: {source}")
            result = _copy_result(source, output_directory / relative)
            if result.get("algorithm") != algorithm.value:
                raise ExperimentContractError(f"Sai thuật toán trong {source}.")
            if str(result.get("snapshot_checksum")) != expected_checksum:
                raise ExperimentContractError(f"Sai checksum snapshot trong {source}.")
            if result.get("status") == "COMPLETED":
                row = _completed_row(result, seed)
                completed_results.append((algorithm.value, seed, result))
                snapshot_checksums.add(expected_checksum)
                for point in result["result"]["convergence_history"]:
                    convergence_rows.append({
                        "algorithm": algorithm.value,
                        "seed": seed,
                        **point,
                    })
            else:
                row = _failed_row(result, seed)
            rows.append(row)

    baseline_result_json: Path | None = None
    baseline_row: dict[str, Any] | None = None
    if config.include_greedy_baseline:
        baseline_root, worker_manifest = part_roots[OptimizationAlgorithm.GA_PO.value]
        _validate_worker_case(case, config, worker_manifest)
        relative = Path("runs") / GREEDY_BASELINE_NAME / "result.json"
        source = baseline_root / case.case_id / relative
        if not source.exists():
            raise ExperimentContractError(f"Thiếu Greedy baseline: {source}")
        baseline_result_json = output_directory / relative
        baseline_result = _copy_result(source, baseline_result_json)
        if baseline_result.get("algorithm") != GREEDY_BASELINE_NAME:
            raise ExperimentContractError(f"Sai thuật toán trong {source}.")
        if str(baseline_result.get("snapshot_checksum")) != expected_checksum:
            raise ExperimentContractError(f"Sai checksum snapshot trong {source}.")
        baseline_row = (
            _completed_row(baseline_result, "DETERMINISTIC")
            if baseline_result.get("status") == "COMPLETED"
            else _failed_row(baseline_result, "DETERMINISTIC")
        )
        if baseline_result.get("status") == "COMPLETED":
            snapshot_checksums.add(expected_checksum)

    _assign_seed_ranks(rows)
    summary_rows = _build_summary(rows, config.algorithms)
    if baseline_row is not None:
        rows.append(baseline_row)
        summary_rows.append(_build_baseline_summary(baseline_row))

    raw_results_csv = output_directory / "raw_results.csv"
    convergence_csv = output_directory / "convergence.csv"
    summary_csv = output_directory / "summary.csv"
    metadata_json = output_directory / "experiment_metadata.json"
    _write_csv(raw_results_csv, rows, tuple(rows[0].keys()))
    _write_csv(
        convergence_csv,
        convergence_rows,
        (
            "algorithm",
            "seed",
            "iteration",
            "fitness_evaluations",
            "general_quality_score",
            "lecturer_preference_score",
        ),
    )
    _write_csv(summary_csv, summary_rows, tuple(summary_rows[0].keys()))

    completed_baseline = int(
        baseline_row is not None and baseline_row["status"] == "COMPLETED"
    )
    metadata = {
        "schema_version": EXPERIMENT_METADATA_SCHEMA_VERSION,
        "experiment_id": config.experiment_id,
        "execution_mode": "DISTRIBUTED_BY_ALGORITHM",
        "case_id": case.case_id,
        "base_request_path": str(config.base_request_path),
        "base_request": base_payload,
        "algorithms": [item.value for item in config.algorithms],
        "seeds": list(config.seeds),
        "include_greedy_baseline": config.include_greedy_baseline,
        "runtime_comparison_valid": False,
        "runtime_note": (
            "Các thuật toán chạy trên các máy khác nhau. Runtime được giữ để "
            "truy vết nhưng không dùng để xếp hạng hoặc kết luận tốc độ."
        ),
        "planned_optimizer_run_count": len(config.algorithms) * len(config.seeds),
        "planned_baseline_run_count": int(config.include_greedy_baseline),
        "planned_run_count": (
            len(config.algorithms) * len(config.seeds)
            + int(config.include_greedy_baseline)
        ),
        "completed_optimizer_run_count": len(completed_results),
        "completed_baseline_run_count": completed_baseline,
        "completed_run_count": len(completed_results) + completed_baseline,
        "snapshot_checksums": sorted(snapshot_checksums),
        "merged_at_utc": datetime.now(timezone.utc).isoformat(),
        "fairness_note": (
            "GA, PO và GA_PO dùng cùng snapshot, seed, population, số vòng, "
            "Decoder, Repair, Validator và Fitness. So sánh chính dựa trên "
            "chất lượng nghiệm, success rate, hội tụ theo FE và FE thực tế."
        ),
    }
    _write_json(metadata_json, metadata)

    merged_config = replace(config, runtime_comparison_valid=False)
    plot_images, plot_manifest_json = generate_experiment_plots(
        merged_config,
        output_directory,
    )
    plot_manifest = json.loads(plot_manifest_json.read_text(encoding="utf-8"))
    metadata["generated_plot_files"] = plot_manifest["generated"]
    metadata["plot_failures"] = plot_manifest["failed"]
    _write_json(metadata_json, metadata)
    convergence_image = output_directory / "01_convergence.png"
    fitness_image = output_directory / "02_fitness_comparison.png"
    return ExperimentPaths(
        output_directory=output_directory,
        runs_directory=runs_directory,
        raw_results_csv=raw_results_csv,
        convergence_csv=convergence_csv,
        summary_csv=summary_csv,
        metadata_json=metadata_json,
        baseline_result_json=baseline_result_json,
        convergence_image=(
            convergence_image if convergence_image in plot_images else None
        ),
        fitness_comparison_image=(fitness_image if fitness_image in plot_images else None),
        plot_manifest_json=plot_manifest_json,
        plot_images=plot_images,
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _create_scalability_artifacts(
    suite: DistributedBenchmarkSuite,
    output_root: Path,
) -> tuple[Path, tuple[Path, ...]]:
    """Tạo bảng và ảnh xuyên ba quy mô; cố ý không tổng hợp runtime."""

    rows: list[dict[str, Any]] = []
    for case in suite.cases:
        for row in _read_csv(output_root / case.case_id / "summary.csv"):
            rows.append({
                "case_id": case.case_id,
                "case_label": case.label,
                "dimension": case.dimension,
                "class_session_count": case.class_session_count,
                **row,
            })
    csv_path = output_root / "scalability_summary.csv"
    _write_csv(csv_path, rows, tuple(rows[0].keys()))

    pyplot = _load_plotting_library()
    algorithms = [
        OptimizationAlgorithm.GA.value,
        OptimizationAlgorithm.PO.value,
        OptimizationAlgorithm.GA_PO.value,
        GREEDY_BASELINE_NAME,
    ]
    colors = {
        "GA": "#2d75b6",
        "PO": "#159a86",
        "GA_PO": "#d94b4b",
        GREEDY_BASELINE_NAME: "#555555",
    }
    quality_path = output_root / "10_scalability_quality.png"
    figure, axes = pyplot.subplots(1, 2, figsize=(13, 5.5))
    for algorithm in algorithms:
        selected = [row for row in rows if row["algorithm"] == algorithm]
        axes[0].plot(
            [int(row["dimension"]) for row in selected],
            [float(row["median_q_general"]) for row in selected],
            marker="o",
            color=colors[algorithm],
            label=_algorithm_label(algorithm),
        )
        axes[1].plot(
            [int(row["dimension"]) for row in selected],
            [float(row["median_q_lecturer"]) for row in selected],
            marker="o",
            color=colors[algorithm],
            label=_algorithm_label(algorithm),
        )
    axes[0].set_title("Q_general theo quy mô", fontweight="bold")
    axes[1].set_title("Q_lecturer theo quy mô", fontweight="bold")
    for axis in axes:
        axis.set_xlabel("Số chiều vector")
        axis.set_ylabel("Điểm phạt trung vị (nhỏ hơn tốt hơn)")
        axis.grid(True, alpha=0.25)
        axis.legend()
    figure.suptitle("Chất lượng nghiệm khi quy mô bài toán tăng", fontweight="bold")
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    figure.savefig(quality_path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)

    success_path = output_root / "11_scalability_success_rate.png"
    figure, axis = pyplot.subplots(figsize=(9.5, 5.5))
    for algorithm in algorithms:
        selected = [row for row in rows if row["algorithm"] == algorithm]
        axis.plot(
            [int(row["dimension"]) for row in selected],
            [100 * float(row["success_rate"]) for row in selected],
            marker="o",
            color=colors[algorithm],
            label=_algorithm_label(algorithm),
        )
    axis.set_title("Tỷ lệ tìm được lịch hợp lệ theo quy mô", fontweight="bold")
    axis.set_xlabel("Số chiều vector")
    axis.set_ylabel("Tỷ lệ hoàn thành (%)")
    axis.set_ylim(0, 105)
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(success_path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)

    fe_path = output_root / "12_scalability_fitness_evaluations.png"
    figure, axis = pyplot.subplots(figsize=(9.5, 5.5))
    for algorithm in algorithms:
        selected = [row for row in rows if row["algorithm"] == algorithm]
        axis.plot(
            [int(row["dimension"]) for row in selected],
            [float(row["median_fitness_evaluations"]) for row in selected],
            marker="o",
            color=colors[algorithm],
            label=_algorithm_label(algorithm),
        )
    axis.set_title("Số lần đánh giá fitness thực tế theo quy mô", fontweight="bold")
    axis.set_xlabel("Số chiều vector")
    axis.set_ylabel("FE trung vị")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(fe_path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)
    return csv_path, (quality_path, success_path, fe_path)


def merge_worker_suites(
    suite: DistributedBenchmarkSuite,
    part_roots: Sequence[Path],
    output_root: Path,
) -> Path:
    """Hợp nhất ba worker, tạo ảnh từng case và ảnh khả năng mở rộng."""

    workers = _load_worker_manifests(suite, part_roots)
    case_artifacts: list[dict[str, Any]] = []
    for case in suite.cases:
        paths = merge_case_results(case, workers, output_root / case.case_id)
        metadata = json.loads(paths.metadata_json.read_text(encoding="utf-8"))
        case_artifacts.append({
            "case_id": case.case_id,
            "completed_run_count": metadata["completed_run_count"],
            "planned_run_count": metadata["planned_run_count"],
            "output_directory": str(paths.output_directory.resolve()),
            "plot_files": [path.name for path in paths.plot_images],
        })
    scalability_csv, scalability_images = _create_scalability_artifacts(
        suite,
        output_root,
    )
    manifest_path = output_root / "merged_manifest.json"
    _write_json(manifest_path, {
        "schema_version": MERGED_MANIFEST_SCHEMA_VERSION,
        "suite_id": suite.suite_id,
        "status": "COMPLETED",
        "runtime_comparison_valid": False,
        "merged_at_utc": datetime.now(timezone.utc).isoformat(),
        "part_roots": [str(path.resolve()) for path in part_roots],
        "cases": case_artifacts,
        "scalability_summary": scalability_csv.name,
        "scalability_images": [path.name for path in scalability_images],
    })
    return manifest_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chạy và hợp nhất benchmark GA, PO, GA–PO trên nhiều máy.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Chạy một worker trên toàn bộ suite.")
    run.add_argument("suite", type=Path)
    run.add_argument(
        "--worker",
        required=True,
        choices=tuple(item.value for item in OptimizationAlgorithm),
    )
    run.add_argument("--output-root", type=Path, required=True)

    merge = commands.add_parser(
        "merge",
        help="Kiểm tra và hợp nhất ba thư mục worker rồi sinh CSV/ảnh.",
    )
    merge.add_argument("suite", type=Path)
    merge.add_argument(
        "--part-root",
        type=Path,
        action="append",
        required=True,
        help="Thư mục kết quả của một worker; truyền đúng ba lần.",
    )
    merge.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    args = _build_parser().parse_args(argv)
    try:
        suite = load_suite(args.suite)
        if args.command == "run":
            manifest_path = run_worker_suite(
                suite,
                OptimizationAlgorithm(args.worker),
                args.output_root,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            print(json.dumps({
                "event": "WORKER_COMPLETED",
                "suite_id": suite.suite_id,
                "worker": args.worker,
                "status": manifest["status"],
                "manifest": str(manifest_path.resolve()),
            }, ensure_ascii=False))
            return 0 if manifest["status"] == "COMPLETED" else 3
        if len(args.part_root) != 3:
            raise ExperimentContractError(
                "Lệnh merge cần đúng ba --part-root: GA, PO và GA_PO."
            )
        manifest_path = merge_worker_suites(
            suite,
            args.part_root,
            args.output_root,
        )
        print(json.dumps({
            "event": "MERGE_COMPLETED",
            "suite_id": suite.suite_id,
            "manifest": str(manifest_path.resolve()),
            "output_root": str(args.output_root.resolve()),
        }, ensure_ascii=False))
        return 0
    except (ExperimentContractError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"Không thể xử lý benchmark phân tán: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
