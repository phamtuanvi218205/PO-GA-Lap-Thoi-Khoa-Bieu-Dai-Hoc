"""Xuất báo cáo có cấu trúc và hình ảnh cho một lần tối ưu thời khóa biểu.

Module này chỉ chuyển :class:`OptimizationResult` thành JSON, CSV và PNG. Nó
không chạy lại fitness, không thay đổi nghiệm tốt nhất và không can thiệp vào
GA, PO, decoder hoặc repair. Biểu đồ hội tụ giữ riêng ba tầng mục tiêu theo
đúng thứ tự lexicographic của project thay vì cộng chúng thành một điểm giả.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .metrics import OptimizationResult
from .models import ProblemInstance


WEEKDAY_NAMES = {
    1: "Thứ Hai",
    2: "Thứ Ba",
    3: "Thứ Tư",
    4: "Thứ Năm",
    5: "Thứ Sáu",
    6: "Thứ Bảy",
    7: "Chủ Nhật",
}

WEEKDAY_SHORT_NAMES = {
    1: "T2",
    2: "T3",
    3: "T4",
    4: "T5",
    5: "T6",
    6: "T7",
    7: "CN",
}

PART_TYPE_NAMES = {
    "LECTURE": "Lý thuyết",
    "PRACTICE": "Thực hành",
}


@dataclass(frozen=True, slots=True)
class TimetableReportRow:
    """Một dòng lịch đã bổ sung đủ nhãn nghiệp vụ để xuất báo cáo."""

    session_index: int
    week_number: int
    teaching_date: date
    start_period: int
    end_period: int
    section_code: str
    course_code: str
    course_name: str
    part_type: str
    lecturer_code: str
    lecturer_name: str
    location_code: str


@dataclass(frozen=True, slots=True)
class TimetableReportPaths:
    """Các tệp được tạo cho một lần chạy thành công."""

    output_directory: Path
    summary_json: Path
    convergence_csv: Path
    timetable_csv: Path
    convergence_image: Path
    timetable_image: Path


def build_timetable_report_rows(
    problem: ProblemInstance,
    result: OptimizationResult,
) -> tuple[TimetableReportRow, ...]:
    """Kết hợp option đã chọn với môn, lớp, giảng viên và địa điểm."""

    plans_by_id = {
        plan.teaching_plan_id: plan
        for plan in problem.teaching_plans
    }
    parts_by_index = {
        part.teaching_part_index: part
        for part in problem.teaching_parts
    }
    lecturers_by_index = {
        lecturer.lecturer_index: lecturer
        for lecturer in problem.lecturers
    }
    locations_by_index = {
        location.location_index: location
        for location in problem.locations
    }
    sections_by_code = {
        section.section_code: section
        for section in problem.course_sections
    }
    courses_by_code = {
        course.course_code: course
        for course in problem.courses
    }
    sessions_by_index = {
        session.session_index: session
        for session in problem.class_sessions
    }

    rows: list[TimetableReportRow] = []
    for option in result.best_individual.selected_options:
        session = sessions_by_index[option.session_index]
        plan = plans_by_id[session.teaching_plan_id]
        part = parts_by_index[plan.teaching_part_index]
        section = sections_by_code[part.section_code]
        course = courses_by_code[section.course_code]
        lecturer = lecturers_by_index[part.lecturer_index]
        location = locations_by_index[option.location_index]

        rows.append(
            TimetableReportRow(
                session_index=session.session_index,
                week_number=session.week_number,
                teaching_date=option.teaching_date,
                start_period=option.start_period,
                end_period=option.end_period,
                section_code=part.section_code,
                course_code=course.course_code,
                course_name=course.course_name,
                part_type=PART_TYPE_NAMES[part.part_type.value],
                lecturer_code=lecturer.lecturer_code,
                lecturer_name=lecturer.full_name,
                location_code=location.location_code,
            )
        )

    rows.sort(
        key=lambda row: (
            row.week_number,
            row.teaching_date,
            row.start_period,
            row.section_code,
            row.part_type,
        )
    )
    return tuple(rows)


def _write_summary_json(
    path: Path,
    result: OptimizationResult,
    snapshot_checksum: str,
    seed: int,
    row_count: int,
) -> None:
    """Lưu cấu hình nhận diện run, metrics và breakdown của nghiệm tốt nhất."""

    best_fitness = result.best_individual.fitness
    payload = {
        "schema_version": "timetable-demo-report.v1",
        "algorithm": result.algorithm.value,
        "snapshot_checksum": snapshot_checksum,
        "seed": seed,
        "population_size": len(result.final_population),
        "timetable_entry_count": row_count,
        "best_fitness": {
            "time_stability_score": best_fitness.time_stability_score,
            "general_quality_score": best_fitness.general_quality_score,
            "lecturer_preference_score": best_fitness.lecturer_preference_score,
            "breakdown": asdict(best_fitness.breakdown),
        },
        "metrics": asdict(result.metrics),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_convergence_csv(path: Path, result: OptimizationResult) -> None:
    """Lưu từng mốc hội tụ theo iteration và FE để có thể kiểm tra lại ảnh."""

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=(
                "iteration",
                "fitness_evaluations",
                "time_stability_score",
                "general_quality_score",
                "lecturer_preference_score",
            ),
        )
        writer.writeheader()
        for point in result.convergence_history:
            writer.writerow(asdict(point))


def _write_timetable_csv(
    path: Path,
    rows: tuple[TimetableReportRow, ...],
) -> None:
    """Lưu lịch ở dạng UTF-8 BOM để mở trực tiếp bằng Microsoft Excel."""

    fieldnames = (
        "tuan",
        "ngay",
        "thu",
        "tiet_bat_dau",
        "tiet_ket_thuc",
        "ma_lop_hoc_phan",
        "ma_hoc_phan",
        "ten_hoc_phan",
        "hinh_thuc",
        "ma_giang_vien",
        "ten_giang_vien",
        "phong",
        "session_index",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "tuan": row.week_number,
                    "ngay": row.teaching_date.isoformat(),
                    "thu": WEEKDAY_NAMES[row.teaching_date.isoweekday()],
                    "tiet_bat_dau": row.start_period,
                    "tiet_ket_thuc": row.end_period,
                    "ma_lop_hoc_phan": row.section_code,
                    "ma_hoc_phan": row.course_code,
                    "ten_hoc_phan": row.course_name,
                    "hinh_thuc": row.part_type,
                    "ma_giang_vien": row.lecturer_code,
                    "ten_giang_vien": row.lecturer_name,
                    "phong": row.location_code,
                    "session_index": row.session_index,
                }
            )


def _load_plotting_library():
    """Nạp matplotlib ở chế độ không cần giao diện và báo lỗi cài đặt rõ ràng."""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as pyplot
    except ImportError as error:
        raise RuntimeError(
            "Không thể tạo ảnh vì thiếu matplotlib. "
            "Hãy cài dependency trong benchmark/requirements.txt."
        ) from error

    return pyplot


def _plot_convergence(path: Path, result: OptimizationResult) -> None:
    """Vẽ ba tầng fitness theo FE trên ba trục độc lập."""

    pyplot = _load_plotting_library()
    evaluations = [
        point.fitness_evaluations
        for point in result.convergence_history
    ]
    series = (
        (
            "Độ không ổn định thứ/tiết (Q_time)",
            [point.time_stability_score for point in result.convergence_history],
            "#d62728",
        ),
        (
            "Chất lượng chung (Q_general)",
            [point.general_quality_score for point in result.convergence_history],
            "#1f77b4",
        ),
        (
            "Mong muốn giảng viên (Q_lecturer)",
            [
                point.lecturer_preference_score
                for point in result.convergence_history
            ],
            "#16837a",
        ),
    )

    figure, axes = pyplot.subplots(3, 1, figsize=(11, 10), sharex=True)
    for axis, (title, values, color) in zip(axes, series, strict=True):
        axis.plot(
            evaluations,
            values,
            marker="o",
            linewidth=2.2,
            color=color,
        )
        axis.set_title(title, fontsize=11, fontweight="bold")
        axis.set_ylabel("Điểm phạt")
        axis.grid(True, alpha=0.25)
        for evaluation, value in zip(evaluations, values, strict=True):
            axis.annotate(
                f"{value:.3f}",
                (evaluation, value),
                xytext=(0, 7),
                textcoords="offset points",
                ha="center",
                fontsize=8,
            )

    axes[-1].set_xlabel("Số lần đánh giá fitness (FE)")
    figure.suptitle(
        "Quá trình hội tụ của thuật toán lai GA-PO\n"
        "Mỗi tầng được đọc riêng; điểm càng nhỏ càng tốt",
        fontsize=14,
        fontweight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def _plot_detailed_timetable(
    path: Path,
    rows: tuple[TimetableReportRow, ...],
) -> None:
    """Vẽ toàn bộ thời khóa biểu, mỗi dòng biểu diễn đúng một buổi học.

    Bảng chi tiết ưu tiên khả năng tra cứu hơn việc nén lịch thành heatmap. Mỗi
    dòng giữ tuần, ngày, tiết, lớp, môn, hình thức, phòng và giảng viên nên ảnh
    có thể dùng trực tiếp để kiểm tra một phân công cụ thể.
    """

    pyplot = _load_plotting_library()
    table_rows = [
        (
            row.week_number,
            f"{WEEKDAY_SHORT_NAMES[row.teaching_date.isoweekday()]}\n"
            f"{row.teaching_date.strftime('%d/%m/%Y')}",
            f"{row.start_period}-{row.end_period}",
            row.section_code,
            row.course_name,
            row.part_type,
            row.location_code,
            f"{row.lecturer_code}\n{row.lecturer_name}",
        )
        for row in rows
    ]

    # Chiều cao tăng theo số buổi để chữ không bị ép khi ảnh chứa cả học kỳ.
    # Ảnh có thể dài nhưng vẫn giữ một tệp duy nhất và đọc được khi phóng to.
    figure_height = max(10.0, 3.4 + len(table_rows) * 0.36)
    figure, axis = pyplot.subplots(figsize=(18, figure_height))
    axis.axis("off")
    table = axis.table(
        cellText=table_rows,
        colLabels=(
            "Tuần",
            "Ngày",
            "Tiết",
            "Lớp HP",
            "Tên học phần",
            "Hình thức",
            "Phòng",
            "Giảng viên",
        ),
        loc="upper center",
        cellLoc="center",
        colWidths=(0.055, 0.105, 0.060, 0.085, 0.205, 0.105, 0.075, 0.245),
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.75)

    first_row_of_week: set[int] = set()
    previous_week = None
    for row_index, row in enumerate(rows, start=1):
        if row.week_number != previous_week:
            first_row_of_week.add(row_index)
            previous_week = row.week_number

    for (row_index, column_index), cell in table.get_celld().items():
        cell.set_edgecolor("white")
        if row_index == 0:
            cell.set_facecolor("#16324f")
            cell.set_text_props(color="white", fontweight="bold")
        else:
            source_row = rows[row_index - 1]
            if source_row.part_type == "Lý thuyết":
                background_color = "#e8f2ff"
            else:
                background_color = "#fff2df"
            cell.set_facecolor(background_color)

            if column_index in (0, 2, 3, 5, 6):
                cell.set_text_props(fontweight="bold")

            # Đường viền đậm đánh dấu lúc bắt đầu tuần mới để bảng dài vẫn
            # dễ quét theo từng tuần.
            if row_index in first_row_of_week:
                cell.set_edgecolor("#16324f")
                cell.set_linewidth(1.8)

    figure.suptitle(
        f"THỜI KHÓA BIỂU CHI TIẾT — {len(rows)} BUỔI HỌC",
        fontsize=16,
        fontweight="bold",
        y=0.995,
    )
    figure.text(
        0.5,
        0.977,
        "Mỗi dòng là một buổi — xanh nhạt: lý thuyết; vàng nhạt: thực hành",
        ha="center",
        fontsize=10,
        color="#455a64",
    )
    figure.subplots_adjust(
        left=0.025,
        right=0.975,
        top=0.955,
        bottom=0.02,
    )
    figure.savefig(path, dpi=180, bbox_inches="tight")
    pyplot.close(figure)


def export_timetable_report(
    problem: ProblemInstance,
    result: OptimizationResult,
    snapshot_checksum: str,
    seed: int,
    output_directory: Path,
) -> TimetableReportPaths:
    """Xuất toàn bộ tệp kiểm chứng và hai ảnh trực quan của một run."""

    output_directory.mkdir(parents=True, exist_ok=True)
    paths = TimetableReportPaths(
        output_directory=output_directory,
        summary_json=output_directory / "run_summary.json",
        convergence_csv=output_directory / "convergence.csv",
        timetable_csv=output_directory / "timetable.csv",
        convergence_image=output_directory / "01_convergence.png",
        timetable_image=output_directory / "02_timetable_detail.png",
    )
    rows = build_timetable_report_rows(problem, result)

    _write_summary_json(
        paths.summary_json,
        result,
        snapshot_checksum,
        seed,
        len(rows),
    )
    _write_convergence_csv(paths.convergence_csv, result)
    _write_timetable_csv(paths.timetable_csv, rows)
    _plot_convergence(paths.convergence_image, result)
    # Xóa đúng các tên ảnh lịch của phiên bản cũ để thư mục ``latest`` chỉ
    # chứa một cách trình bày chính thức, tránh người dùng mở nhầm kết quả.
    for legacy_name in (
        "02_timetable_heatmap.png",
        "02_timetable_overview.png",
    ):
        legacy_path = output_directory / legacy_name
        if legacy_path.exists():
            legacy_path.unlink()

    _plot_detailed_timetable(paths.timetable_image, rows)
    return paths

