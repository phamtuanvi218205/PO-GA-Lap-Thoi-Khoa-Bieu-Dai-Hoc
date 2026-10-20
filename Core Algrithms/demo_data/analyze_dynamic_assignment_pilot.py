"""Kiểm định và trực quan hóa pilot phân công giảng viên động.

Script này đọc lại từng vector tốt nhất từ thư mục thí nghiệm, giải mã trên
đúng snapshot ban đầu và chạy validator độc lập. Kết quả chỉ được dùng làm
pilot kỹ thuật; năm seed chưa đủ để đưa ra kết luận thực nghiệm chính thức.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from types import SimpleNamespace


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
CORE_DIRECTORY = SCRIPT_DIRECTORY.parent
SOURCE_DIRECTORY = CORE_DIRECTORY / "src"
if str(SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIRECTORY))

from gapo_timetabling.constraints import validate_timetable  # noqa: E402
from gapo_timetabling.decoder import decode_vector  # noqa: E402
from gapo_timetabling.reporting import (  # noqa: E402
    _plot_detailed_timetable,
    _write_timetable_csv,
    build_timetable_report_rows,
)
from gapo_timetabling.snapshot import prepare_snapshot_for_optimization  # noqa: E402


ALGORITHM_ORDER = {"GA": 0, "PO": 1, "GA_PO": 2}
ALGORITHM_LABELS = {"GA": "GA", "PO": "PO", "GA_PO": "GA–PO"}


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kiểm định pilot và sinh biểu đồ phân công giảng viên động."
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=SCRIPT_DIRECTORY / "dynamic_assignment_snapshot_v2.json",
    )
    parser.add_argument(
        "--experiment-directory",
        type=Path,
        default=(
            CORE_DIRECTORY
            / "test_results"
            / "timetable_experiment_dynamic_v2_pilot_20261017"
        ),
    )
    parser.add_argument("--max-decode-nodes", type=int, default=20_000)
    return parser.parse_args()


def _load_run_paths(experiment_directory: Path) -> list[Path]:
    paths = list((experiment_directory / "runs").glob("*/seed_*.json"))
    return sorted(
        paths,
        key=lambda path: (
            ALGORITHM_ORDER.get(path.parent.name, 99),
            int(path.stem.removeprefix("seed_")),
        ),
    )


def _section_for_session(problem, session_index: int) -> str:
    session = problem.class_sessions[session_index]
    plan = next(
        item
        for item in problem.teaching_plans
        if item.teaching_plan_id == session.teaching_plan_id
    )
    return problem.teaching_parts[plan.teaching_part_index].section_code


def _course_for_section(problem, section_code: str) -> str:
    return next(
        item.course_code
        for item in problem.course_sections
        if item.section_code == section_code
    )


def _capability_scores(problem) -> dict[tuple[int, str], float]:
    return {
        (item.lecturer_index, item.course_code): item.suitability_score
        for item in problem.lecturer_course_capabilities
    }


def _analyze_runs(prepared, run_paths: list[Path], max_decode_nodes: int):
    problem = prepared.problem
    lecturers = {
        lecturer.lecturer_index: lecturer
        for lecturer in problem.lecturers
    }
    capability_scores = _capability_scores(problem)
    rows: list[dict[str, object]] = []
    run_summaries: list[dict[str, object]] = []

    for path in run_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != "COMPLETED":
            raise RuntimeError(f"Run không hoàn thành: {path}")

        result = payload["result"]
        vector = tuple(float(value) for value in result["best_solution"]["vector"])
        decoded = decode_vector(
            problem,
            prepared.option_domains,
            vector,
            max_decode_nodes=max_decode_nodes,
        )
        if not decoded.is_success:
            raise RuntimeError(f"Không thể giải mã lại nghiệm trong {path}: {decoded.reason}")

        validation = validate_timetable(problem, decoded.selected_options)
        if not validation.is_valid:
            codes = ", ".join(item.code.value for item in validation.violations)
            raise RuntimeError(f"Nghiệm {path} vi phạm điều kiện cứng: {codes}")

        section_lecturers: dict[str, int] = {}
        lecturer_loads: Counter[int] = Counter()
        for option in decoded.selected_options:
            section_code = _section_for_session(problem, option.session_index)
            lecturer_index = problem.option_lecturer_index(option)
            previous = section_lecturers.setdefault(section_code, lecturer_index)
            if previous != lecturer_index:
                raise RuntimeError(
                    f"Lớp {section_code} có nhiều giảng viên trong {path}."
                )
            duration = problem.class_sessions[option.session_index].duration_periods
            lecturer_loads[lecturer_index] += duration

        if len(decoded.selected_options) != problem.session_dimension:
            raise RuntimeError(f"Run {path} không chứa đủ buổi học.")
        if len(section_lecturers) != problem.assignment_dimension:
            raise RuntimeError(f"Run {path} không phân công đủ lớp học phần.")

        algorithm = payload["algorithm"]
        seed = int(payload["request_id"].rsplit("-", 1)[-1])
        metrics = result["metrics"]
        fitness = result["best_fitness"]
        for section_code in sorted(section_lecturers):
            lecturer_index = section_lecturers[section_code]
            lecturer = lecturers[lecturer_index]
            course_code = _course_for_section(problem, section_code)
            rows.append(
                {
                    "algorithm": algorithm,
                    "seed": seed,
                    "section_code": section_code,
                    "course_code": course_code,
                    "lecturer_code": lecturer.lecturer_code,
                    "lecturer_name": lecturer.full_name,
                    "suitability_score": capability_scores[(lecturer_index, course_code)],
                    "lecturer_total_periods": lecturer_loads[lecturer_index],
                    "lecturer_max_periods": lecturer.max_teaching_periods,
                }
            )

        run_summaries.append(
            {
                "algorithm": algorithm,
                "seed": seed,
                "is_valid": True,
                "entry_count": len(decoded.selected_options),
                "assigned_section_count": len(section_lecturers),
                "time_stability_score": fitness["time_stability_score"],
                "general_quality_score": fitness["general_quality_score"],
                "lecturer_preference_score": fitness["lecturer_preference_score"],
                "runtime_seconds": metrics["runtime_seconds"],
                "fitness_evaluations": metrics["fitness_evaluations"],
                "candidate_attempts": metrics["candidate_attempts"],
                "decode_failed_count": metrics["decode_failed_count"],
                "max_lecturer_load": max(lecturer_loads.values()),
            }
        )

    return rows, run_summaries


def _write_assignment_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_validation_summary(
    path: Path,
    prepared,
    assignment_rows: list[dict[str, object]],
    run_summaries: list[dict[str, object]],
) -> None:
    problem = prepared.problem
    section_choices: dict[str, set[str]] = defaultdict(set)
    for row in assignment_rows:
        section_choices[str(row["section_code"])].add(str(row["lecturer_code"]))

    required_periods = sum(
        session.duration_periods for session in problem.class_sessions
    )
    available_periods = sum(
        lecturer.max_teaching_periods for lecturer in problem.lecturers
    )
    payload = {
        "schema_version": "dynamic-assignment-pilot-validation.v1",
        "snapshot_checksum": prepared.snapshot_checksum,
        "dataset": {
            "course_count": len(problem.courses),
            "section_count": len(problem.course_sections),
            "teaching_part_count": len(problem.teaching_parts),
            "session_count": problem.session_dimension,
            "lecturer_count": len(problem.lecturers),
            "location_count": len(problem.locations),
            "assignment_gene_count": problem.assignment_dimension,
            "total_gene_count": problem.dimension,
            "session_option_count": sum(len(domain) for domain in prepared.option_domains),
            "minimum_session_domain": min(map(len, prepared.option_domains)),
            "maximum_session_domain": max(map(len, prepared.option_domains)),
            "required_teaching_periods": required_periods,
            "maximum_teaching_capacity": available_periods,
            "capacity_slack_periods": available_periods - required_periods,
        },
        "validation": {
            "run_count": len(run_summaries),
            "all_runs_completed_and_hard_valid": all(
                bool(item["is_valid"]) for item in run_summaries
            ),
            "expected_entries_per_run": problem.session_dimension,
            "runs": run_summaries,
        },
        "dynamic_assignment_evidence": {
            "distinct_lecturers_selected_by_section": {
                section: sorted(choices)
                for section, choices in sorted(section_choices.items())
            },
            "sections_with_more_than_one_selected_lecturer_across_runs": sum(
                len(choices) > 1 for choices in section_choices.values()
            ),
        },
        "experimental_caution": (
            "Đây là pilot 5 seed. Số fitness evaluation thực tế không bằng nhau "
            "do cá thể giải mã thất bại không được tính là một lần đánh giá fitness; "
            "không dùng kết quả này để kết luận thuật toán tốt nhất."
        ),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as pyplot

    return pyplot


def _plot_assignments(
    path: Path,
    problem,
    rows: list[dict[str, object]],
) -> None:
    pyplot = _load_pyplot()
    sections = sorted(section.section_code for section in problem.course_sections)
    lecturer_codes = [item.lecturer_code for item in problem.lecturers]
    code_to_number = {code: index for index, code in enumerate(lecturer_codes)}
    grouped: dict[tuple[str, int], dict[str, str]] = defaultdict(dict)
    for row in rows:
        grouped[(str(row["algorithm"]), int(row["seed"]))][
            str(row["section_code"])
        ] = str(row["lecturer_code"])
    run_keys = sorted(
        grouped,
        key=lambda key: (ALGORITHM_ORDER.get(key[0], 99), key[1]),
    )
    matrix = [
        [code_to_number[grouped[key][section]] for section in sections]
        for key in run_keys
    ]

    figure, axis = pyplot.subplots(figsize=(14, 7.5))
    image = axis.imshow(matrix, aspect="auto", cmap="tab10", vmin=-0.5)
    for row_index, key in enumerate(run_keys):
        for column_index, section in enumerate(sections):
            code = grouped[key][section]
            axis.text(
                column_index,
                row_index,
                code,
                ha="center",
                va="center",
                color="white",
                fontsize=9,
                fontweight="bold",
            )
    axis.set_xticks(range(len(sections)), sections, rotation=35, ha="right")
    axis.set_yticks(
        range(len(run_keys)),
        [f"{ALGORITHM_LABELS[key[0]]} — seed {key[1]}" for key in run_keys],
    )
    axis.set_title(
        "Giảng viên do thuật toán chọn cho từng lớp học phần\n"
        "Mỗi hàng là một lần chạy độc lập; màu và mã thể hiện giảng viên",
        fontsize=14,
        fontweight="bold",
    )
    axis.set_xlabel("Lớp học phần")
    axis.set_ylabel("Lần chạy")
    axis.set_xticks(
        [value - 0.5 for value in range(1, len(sections))], minor=True
    )
    axis.set_yticks(
        [value - 0.5 for value in range(1, len(run_keys))], minor=True
    )
    axis.grid(which="minor", color="white", linewidth=1.5)
    axis.tick_params(which="minor", bottom=False, left=False)
    figure.colorbar(image, ax=axis, label="Mã số giảng viên", shrink=0.8)
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def _plot_efficiency(path: Path, summaries: list[dict[str, object]]) -> None:
    pyplot = _load_pyplot()
    figure, axes = pyplot.subplots(1, 3, figsize=(15, 5.6))
    fields = (
        ("runtime_seconds", "Thời gian chạy (giây)"),
        ("fitness_evaluations", "Số lần đánh giá fitness thực tế"),
        ("decode_failed_count", "Số cá thể giải mã thất bại"),
    )
    algorithms = ("GA", "PO", "GA_PO")
    colors = ("#2563eb", "#0f766e", "#dc2626")
    for axis, (field, title) in zip(axes, fields):
        for x_index, (algorithm, color) in enumerate(zip(algorithms, colors)):
            values = [
                float(row[field])
                for row in summaries
                if row["algorithm"] == algorithm
            ]
            offsets = [-0.12, -0.06, 0.0, 0.06, 0.12]
            axis.scatter(
                [x_index + offsets[index] for index in range(len(values))],
                values,
                color=color,
                s=42,
                alpha=0.85,
                zorder=3,
            )
            axis.hlines(
                median(values),
                x_index - 0.22,
                x_index + 0.22,
                colors="black",
                linewidth=2.2,
                zorder=4,
            )
        axis.set_xticks(range(3), ["GA", "PO", "GA–PO"])
        axis.set_title(title, fontsize=11, fontweight="bold")
        axis.grid(axis="y", alpha=0.25)
    figure.suptitle(
        "Chi phí thực thi của pilot 5 seed\n"
        "Mỗi chấm là một run; vạch đen là trung vị",
        fontsize=14,
        fontweight="bold",
    )
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def _export_best_timetable(
    experiment_directory: Path,
    prepared,
    run_paths: list[Path],
    max_decode_nodes: int,
) -> None:
    """Xuất bảng và ảnh lịch của nghiệm tốt nhất theo ba tầng lexicographic."""

    completed_payloads = []
    for path in run_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") == "COMPLETED":
            completed_payloads.append((path, payload))
    if not completed_payloads:
        raise RuntimeError("Không có run hoàn thành để xuất thời khóa biểu.")

    def fitness_key(item) -> tuple[float, float, float]:
        fitness = item[1]["result"]["best_fitness"]
        return (
            float(fitness["time_stability_score"]),
            float(fitness["general_quality_score"]),
            float(fitness["lecturer_preference_score"]),
        )

    run_path, payload = min(completed_payloads, key=fitness_key)
    vector = tuple(
        float(value)
        for value in payload["result"]["best_solution"]["vector"]
    )
    decoded = decode_vector(
        prepared.problem,
        prepared.option_domains,
        vector,
        max_decode_nodes=max_decode_nodes,
    )
    if not decoded.is_success:
        raise RuntimeError("Không thể giải mã lại nghiệm tốt nhất để xuất lịch.")

    # Hàm báo cáo chỉ cần thuộc tính selected_options của best_individual.
    # Proxy tối giản tránh dựng lại toàn bộ OptimizationResult và không tính
    # fitness lần thứ hai, nên artifact phản ánh đúng vector đã lưu trong run.
    report_proxy = SimpleNamespace(
        best_individual=SimpleNamespace(selected_options=decoded.selected_options)
    )
    rows = build_timetable_report_rows(prepared.problem, report_proxy)
    _write_timetable_csv(
        experiment_directory / "05_best_timetable.csv",
        rows,
    )
    _plot_detailed_timetable(
        experiment_directory / "05_best_timetable.png",
        rows,
    )

    fitness = payload["result"]["best_fitness"]
    metadata = {
        "schema_version": "best-timetable-selection.v1",
        "selection_rule": "LEXICOGRAPHIC_Q_TIME_Q_GENERAL_Q_LECTURER",
        "source_run": str(run_path.relative_to(experiment_directory)),
        "request_id": payload["request_id"],
        "algorithm": payload["algorithm"],
        "snapshot_checksum": payload["snapshot_checksum"],
        "entry_count": len(rows),
        "best_fitness": fitness,
    }
    (experiment_directory / "05_best_timetable_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    arguments = _parse_arguments()
    prepared = prepare_snapshot_for_optimization(arguments.snapshot)
    if not prepared.is_ready:
        raise RuntimeError("Snapshot có session không sinh được option.")

    run_paths = _load_run_paths(arguments.experiment_directory)
    if not run_paths:
        raise FileNotFoundError("Không tìm thấy kết quả run trong thư mục thí nghiệm.")

    assignments, summaries = _analyze_runs(
        prepared,
        run_paths,
        arguments.max_decode_nodes,
    )
    _write_assignment_csv(
        arguments.experiment_directory / "assignment_results.csv",
        assignments,
    )
    _write_validation_summary(
        arguments.experiment_directory / "validation_summary.json",
        prepared,
        assignments,
        summaries,
    )
    _plot_assignments(
        arguments.experiment_directory / "03_lecturer_assignments.png",
        prepared.problem,
        assignments,
    )
    _plot_efficiency(
        arguments.experiment_directory / "04_runtime_and_failures.png",
        summaries,
    )
    _export_best_timetable(
        arguments.experiment_directory,
        prepared,
        run_paths,
        arguments.max_decode_nodes,
    )
    # Dùng thông báo ASCII để chạy ổn định cả trong terminal Windows còn dùng
    # code page cũ; các tệp JSON, CSV và biểu đồ vẫn giữ đầy đủ tiếng Việt.
    print(
        f"Validated {len(summaries)} runs; all best solutions are hard-valid. "
        f"Artifacts: {arguments.experiment_directory}"
    )


if __name__ == "__main__":
    main()
