"""Xuất báo cáo có cấu trúc và hình ảnh cho một lần tối ưu thời khóa biểu.

Module này chỉ chuyển :class:`OptimizationResult` thành JSON, CSV và PNG. Nó
không chạy lại fitness, không thay đổi nghiệm tốt nhất và không can thiệp vào
GA, PO, decoder hoặc repair. Biểu đồ hội tụ giữ riêng ba tầng mục tiêu theo
đúng thứ tự lexicographic của project thay vì cộng chúng thành một điểm giả.
"""

from __future__ import annotations

import csv
import json
import textwrap
from dataclasses import asdict, dataclass
from datetime import date, timedelta
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
        lecturer = lecturers_by_index[problem.option_lecturer_index(option)]
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


def _select_representative_week_rows(
    rows: tuple[TimetableReportRow, ...],
) -> tuple[TimetableReportRow, ...]:
    """Chọn một tuần đại diện để vẽ ảnh thời khóa biểu dễ đọc.

    File CSV vẫn lưu toàn bộ các tuần. Ảnh chỉ trình bày một tuần vì lịch
    production dùng mẫu lặp cố định. Hàm ưu tiên tuần có nhiều buổi nhất để
    tránh chọn một tuần đầu hoặc cuối kỳ chỉ có một phần lịch; nếu nhiều tuần
    có cùng số buổi thì chọn tuần có số thứ tự nhỏ nhất để kết quả xác định.
    """

    if not rows:
        return ()

    rows_by_week: dict[int, list[TimetableReportRow]] = {}
    for row in rows:
        rows_by_week.setdefault(row.week_number, []).append(row)

    representative_week = min(
        rows_by_week,
        key=lambda week_number: (
            -len(rows_by_week[week_number]),
            week_number,
        ),
    )
    return tuple(rows_by_week[representative_week])


def _assign_parallel_lanes(
    rows: tuple[TimetableReportRow, ...],
) -> tuple[tuple[TimetableReportRow, int, int], ...]:
    """Xếp các buổi trùng giờ vào các làn song song trong cùng một ngày.

    Hai buổi chỉ dùng chung một làn khi buổi trước kết thúc trước tiết bắt đầu
    của buổi sau. Cách xếp này không thay đổi lịch; nó chỉ ngăn các khối trên
    ảnh che lẫn nhau khi nhiều lớp học đồng thời ở các phòng khác nhau.
    """

    ordered_rows = sorted(
        rows,
        key=lambda row: (
            row.start_period,
            row.end_period,
            row.section_code,
            row.part_type,
        ),
    )

    # Tách thành các thành phần giao nhau. Một buổi đứng riêng ở đầu ngày sẽ
    # được dùng toàn bộ chiều rộng dù phía sau ngày đó có nhóm khác bị trùng.
    components: list[list[TimetableReportRow]] = []
    component_end_period = -1
    for row in ordered_rows:
        if not components or row.start_period > component_end_period:
            components.append([row])
            component_end_period = row.end_period
        else:
            components[-1].append(row)
            component_end_period = max(component_end_period, row.end_period)

    placements: list[tuple[TimetableReportRow, int, int]] = []
    for component in components:
        lane_end_periods: list[int] = []
        component_placements: list[tuple[TimetableReportRow, int]] = []
        for row in component:
            lane_index = next(
                (
                    index
                    for index, end_period in enumerate(lane_end_periods)
                    if end_period < row.start_period
                ),
                len(lane_end_periods),
            )
            if lane_index == len(lane_end_periods):
                lane_end_periods.append(row.end_period)
            else:
                lane_end_periods[lane_index] = row.end_period
            component_placements.append((row, lane_index))

        lane_count = len(lane_end_periods)
        placements.extend(
            (row, lane_index, lane_count)
            for row, lane_index in component_placements
        )

    return tuple(placements)


def _plot_detailed_timetable(
    path: Path,
    rows: tuple[TimetableReportRow, ...],
) -> None:
    """Vẽ một tuần dưới dạng lưới thứ/ngày và ca học.

    Lịch đầy đủ vẫn được lưu trong ``timetable.csv``. Ảnh PNG chỉ lấy một tuần
    để tránh lặp lại cùng mẫu thứ, tiết và phòng ở mọi tuần hoạt động. Mỗi buổi
    là một khối đặt đúng ngày và khoảng tiết; các buổi trùng giờ được chia làn.
    """

    pyplot = _load_plotting_library()
    from matplotlib.patches import Patch, Rectangle

    display_rows = _select_representative_week_rows(rows)
    if not display_rows:
        raise ValueError("Không thể vẽ thời khóa biểu khi kết quả không có buổi học.")

    week_number = display_rows[0].week_number
    week_start = min(
        row.teaching_date - timedelta(days=row.teaching_date.isoweekday() - 1)
        for row in display_rows
    )
    # Luôn hiển thị tối thiểu thứ Hai đến thứ Sáu. Thứ Bảy hoặc Chủ Nhật chỉ
    # được thêm khi tuần đại diện thực sự có buổi học, tránh hai cột trống làm
    # các khối trong ngày thường bị thu hẹp không cần thiết.
    last_visible_weekday = max(
        5,
        max(row.teaching_date.isoweekday() for row in display_rows),
    )
    visible_weekdays = tuple(range(1, last_visible_weekday + 1))
    rows_by_weekday = {
        weekday: tuple(
            row
            for row in display_rows
            if row.teaching_date.isoweekday() == weekday
        )
        for weekday in visible_weekdays
    }

    header_height = 1.45
    period_count = max(16, max(row.end_period for row in display_rows))
    left_column_width = 0.70
    day_column_width = 1.0
    total_width = left_column_width + len(visible_weekdays) * day_column_width
    total_height = header_height + period_count

    figure, axis = pyplot.subplots(figsize=(22, 12))
    axis.set_xlim(0, total_width)
    axis.set_ylim(total_height, 0)
    axis.axis("off")

    # Header bên trái và bảy cột ngày giữ cấu trúc quen thuộc của một lịch tuần.
    axis.add_patch(
        Rectangle(
            (0, 0),
            left_column_width,
            header_height,
            facecolor="#eef3f7",
            edgecolor="#c8d2dc",
            linewidth=1.0,
        )
    )
    axis.text(
        left_column_width / 2,
        header_height / 2,
        "Ca học",
        ha="center",
        va="center",
        fontsize=11,
        fontweight="bold",
        color="#1686d9",
    )

    for column_index, weekday in enumerate(visible_weekdays):
        x = left_column_width + column_index * day_column_width
        teaching_date = week_start + timedelta(days=weekday - 1)
        axis.add_patch(
            Rectangle(
                (x, 0),
                day_column_width,
                header_height,
                facecolor="#eef3f7",
                edgecolor="#c8d2dc",
                linewidth=1.0,
            )
        )
        axis.text(
            x + day_column_width / 2,
            header_height / 2,
            f"{WEEKDAY_NAMES[weekday]}\n{teaching_date.strftime('%d/%m/%Y')}",
            ha="center",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color="#1686d9",
        )

    session_top = header_height
    # Nền và lưới tiết giúp nhận biết vị trí tương đối của từng khối học.
    for column_index, weekday in enumerate(visible_weekdays):
        x = left_column_width + column_index * day_column_width
        axis.add_patch(
            Rectangle(
                (x, session_top),
                day_column_width,
                period_count,
                facecolor="#ffffff",
                edgecolor="#c8d2dc",
                linewidth=1.0,
            )
        )
        for subdivision in range(1, 5):
            inner_x = x + subdivision * day_column_width / 5
            axis.plot(
                [inner_x, inner_x],
                [session_top, total_height],
                color="#edf1f4",
                linewidth=0.45,
                zorder=1,
            )

    for period_offset in range(period_count + 1):
        y = session_top + period_offset
        is_shift_boundary = period_offset in (0, 6, 12, 16)
        axis.plot(
            [left_column_width, total_width],
            [y, y],
            color="#c8d2dc" if is_shift_boundary else "#edf1f4",
            linewidth=1.0 if is_shift_boundary else 0.45,
            zorder=1,
        )

    shifts = (
        ("Sáng", 1, 6),
        ("Chiều", 7, 12),
        ("Tối", 13, period_count),
    )
    for shift_name, start_period, end_period in shifts:
        if start_period > period_count:
            continue
        bounded_end = min(end_period, period_count)
        y = session_top + start_period - 1
        height = bounded_end - start_period + 1
        axis.add_patch(
            Rectangle(
                (0, y),
                left_column_width,
                height,
                facecolor="#fffecb",
                edgecolor="#c8d2dc",
                linewidth=1.0,
            )
        )
        axis.text(
            left_column_width / 2,
            y + height / 2,
            shift_name,
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            color="#52647a",
        )

    theory_color = "#cfe8ff"
    practice_color = "#6bd234"
    for column_index, weekday in enumerate(visible_weekdays):
        placements = _assign_parallel_lanes(rows_by_weekday[weekday])
        if not placements:
            continue

        day_x = left_column_width + column_index * day_column_width
        outer_padding = 0.045
        lane_gap = 0.025
        usable_width = day_column_width - 2 * outer_padding

        for row, lane_index, lane_count in placements:
            lane_width = (
                usable_width - max(0, lane_count - 1) * lane_gap
            ) / lane_count
            x = day_x + outer_padding + lane_index * (lane_width + lane_gap)
            y = session_top + row.start_period - 1 + 0.06
            height = row.end_period - row.start_period + 1 - 0.12
            is_theory = row.part_type == "Lý thuyết"
            axis.add_patch(
                Rectangle(
                    (x, y),
                    lane_width,
                    height,
                    facecolor=theory_color if is_theory else practice_color,
                    edgecolor="#8ba0b3" if is_theory else "#4aaa22",
                    linewidth=0.8,
                    zorder=3,
                )
            )

            wrap_width = 20 if lane_count == 1 else 11
            course_name = "\n".join(
                textwrap.wrap(row.course_name, width=wrap_width)
            )
            lecturer_name = "\n".join(
                textwrap.wrap(row.lecturer_name, width=wrap_width)
            )
            part_abbreviation = "LT" if is_theory else "TH"
            label = (
                f"{row.section_code} ({part_abbreviation})\n"
                f"{course_name}\n"
                f"Tiết {row.start_period}–{row.end_period}, {row.location_code}\n"
                f"{lecturer_name}"
            )
            axis.text(
                x + 0.025,
                y + 0.16,
                label,
                ha="left",
                va="top",
                fontsize=7.4 if lane_count == 1 else 6.3,
                fontweight="bold" if lane_count == 1 else "normal",
                color="#08253d",
                linespacing=1.1,
                clip_on=True,
                zorder=4,
            )

    figure.suptitle(
        f"THỜI KHÓA BIỂU TUẦN {week_number} — {len(display_rows)} BUỔI HỌC",
        fontsize=17,
        fontweight="bold",
        y=0.982,
    )
    figure.legend(
        handles=(
            Patch(facecolor=theory_color, edgecolor="#8ba0b3", label="Lịch lý thuyết"),
            Patch(facecolor=practice_color, edgecolor="#4aaa22", label="Lịch thực hành"),
        ),
        loc="lower center",
        bbox_to_anchor=(0.5, 0.012),
        ncol=2,
        frameon=False,
        fontsize=10,
    )
    figure.subplots_adjust(
        left=0.025,
        right=0.985,
        top=0.925,
        bottom=0.075,
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

