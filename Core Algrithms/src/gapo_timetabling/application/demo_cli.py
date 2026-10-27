"""CLI demo chạy GA–PO trên snapshot và xuất kết quả dễ đọc.

Module này thuộc tầng ứng dụng. Nó chuẩn bị dữ liệu, gọi lõi GA–PO và xuất
terminal/JSON/CSV/PNG; không chứa công thức cập nhật của thuật toán.
"""

from __future__ import annotations

import argparse
import sys
from math import isfinite
from pathlib import Path
from typing import Sequence

from ..core.constraints import validate_timetable
from ..core.hybrid import HybridConfig, run_hybrid
from ..core.metrics import OptimizationResult
from ..core.models import ProblemInstance
from ..core.population import (
    CandidateEvaluationConfig,
    PopulationInitializationStatus,
    initialize_population,
)
from ..core.snapshot import prepare_snapshot_for_optimization
from .reporting import (
    WEEKDAY_NAMES,
    build_timetable_report_rows,
    export_timetable_report,
)
def _positive_integer(value: str) -> int:
    """Chuyển tham số CLI thành số nguyên dương với thông báo lỗi rõ ràng."""

    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(
            f"Cần một số nguyên dương, nhưng nhận được {value}."
        )
    return parsed


def _ratio(value: str) -> float:
    """Chuyển tham số CLI thành tỉ lệ nằm trong khoảng mở ``(0, 1)``."""

    parsed = float(value)
    if not isfinite(parsed) or not 0.0 < parsed < 1.0:
        raise argparse.ArgumentTypeError(
            f"Cần một tỉ lệ hữu hạn trong khoảng (0, 1), nhưng nhận được {value}."
        )
    return parsed


def _build_argument_parser() -> argparse.ArgumentParser:
    """Tạo giao diện dòng lệnh tối thiểu để chạy trực tiếp hybrid."""

    parser = argparse.ArgumentParser(
        description=(
            "Chạy thuật toán lai GA-PO từ snapshot problem-instance.v2 "
            "và in thời khóa biểu tốt nhất."
        )
    )
    parser.add_argument(
        "snapshot",
        type=Path,
        help="Đường dẫn đến snapshot JSON problem-instance.v2 (v1 vẫn được đọc).",
    )
    parser.add_argument(
        "--population-size",
        type=_positive_integer,
        default=20,
        help="Số cá thể hợp lệ trong quần thể (mặc định: 20).",
    )
    parser.add_argument(
        "--iterations",
        type=_positive_integer,
        default=20,
        help="Số vòng lặp hybrid hoàn chỉnh (mặc định: 20).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed ngẫu nhiên dùng để khởi tạo và tối ưu (mặc định: 42).",
    )
    parser.add_argument(
        "--ga-ratio",
        type=_ratio,
        default=0.5,
        help="Tỉ lệ quần thể giao cho nhánh GA (mặc định: 0.5).",
    )
    parser.add_argument(
        "--max-initialization-attempts",
        type=_positive_integer,
        default=1000,
        help="Số ứng viên tối đa được thử khi tạo quần thể ban đầu.",
    )
    parser.add_argument(
        "--max-offspring-attempts",
        type=_positive_integer,
        default=5,
        help="Số lần thử tối đa cho mỗi vị trí cá thể con (mặc định: 5).",
    )
    parser.add_argument(
        "--max-decode-nodes",
        type=_positive_integer,
        default=10000,
        help="Ngân sách node decoder cho một ứng viên (mặc định: 10000).",
    )
    parser.add_argument(
        "--max-repair-attempts",
        type=_positive_integer,
        default=3,
        help="Số lần repair một gene tối đa cho mỗi ứng viên (mặc định: 3).",
    )
    parser.add_argument(
        "--disable-repair",
        action="store_true",
        help="Tắt bước repair một gene tùy chọn.",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("test_results/timetable_demo/latest"),
        help=(
            "Thư mục lưu JSON, CSV và PNG "
            "(mặc định: test_results/timetable_demo/latest)."
        ),
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Chỉ in terminal, không tạo JSON, CSV hoặc ảnh báo cáo.",
    )
    return parser


def _print_timetable_result(
    problem: ProblemInstance,
    result: OptimizationResult,
    snapshot_checksum: str,
    seed: int,
) -> None:
    """In kết quả tiếng Việt theo cấu trúc tuần, ngày và buổi học.

    Lịch được nhóm theo tuần rồi theo ngày để người dùng đọc như một thời khóa
    biểu thay vì phải tự diễn giải danh sách kỹ thuật gồm các option rời rạc.
    """

    best = result.best_individual
    validation = validate_timetable(problem, best.selected_options)

    weeks_by_number = {
        week.week_number: week
        for week in problem.weeks
    }
    rows = build_timetable_report_rows(problem, result)

    print("KẾT QUẢ XẾP THỜI KHÓA BIỂU BẰNG THUẬT TOÁN LAI GA-PO")
    print("=" * 108)
    print("THÔNG TIN LẦN CHẠY")
    print(f"  Mã kiểm tra snapshot      : {snapshot_checksum}")
    print(f"  Seed ngẫu nhiên           : {seed}")
    print(f"  Kích thước quần thể       : {len(result.final_population)}")
    print(f"  Số vòng lặp đã hoàn thành : {result.metrics.completed_iterations}")
    print(f"  Số lần đánh giá (FE)      : {result.metrics.fitness_evaluations}")
    print(f"  Thời gian chạy            : {result.metrics.runtime_seconds:.6f} giây")
    print(f"  Số vi phạm bắt buộc       : {len(validation.violations)}")
    print()
    print("ĐIỂM CỦA LỊCH TỐT NHẤT (càng nhỏ càng tốt)")
    print(f"  Chất lượng chung          : {best.fitness.general_quality_score:.6f}")
    print(
        "  Mong muốn giảng viên      : "
        f"{best.fitness.lecturer_preference_score:.6f}"
    )
    print()
    print(f"THỜI KHÓA BIỂU TỐT NHẤT — {len(rows)} BUỔI HỌC")
    print("=" * 108)

    current_week_number = None
    current_date = None
    for row in rows:
        if row.week_number != current_week_number:
            week = weeks_by_number[row.week_number]
            print()
            print(
                f"TUẦN {row.week_number}: "
                f"{week.start_date.strftime('%d/%m/%Y')} - "
                f"{week.end_date.strftime('%d/%m/%Y')}"
            )
            print("-" * 108)
            current_week_number = row.week_number
            current_date = None

        if row.teaching_date != current_date:
            print()
            print(
                f"{WEEKDAY_NAMES[row.teaching_date.isoweekday()]}, "
                f"ngày {row.teaching_date.strftime('%d/%m/%Y')}"
            )
            print(
                f"{'Tiết':<7} {'Lớp HP':<10} {'Hình thức':<12} "
                f"{'Tên học phần':<33} {'Phòng':<10} "
                f"{'Mã GV':<9} Giảng viên"
            )
            print("-" * 108)
            current_date = row.teaching_date

        period_range = f"{row.start_period}-{row.end_period}"
        print(
            f"{period_range:<7} "
            f"{row.section_code:<10} "
            f"{row.part_type:<12} "
            f"{row.course_name:<33} "
            f"{row.location_code:<10} "
            f"{row.lecturer_code:<9} "
            f"{row.lecturer_name}"
        )

    print()
    print("=" * 108)
    print(
        f"KẾT LUẬN: Đã xếp đủ {len(rows)} buổi học; "
        f"số vi phạm bắt buộc = {len(validation.violations)}."
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Nạp snapshot, chạy hybrid và in lịch tốt nhất ra terminal.

    Hàm trả mã thoát thay vì gọi ``sys.exit`` trực tiếp để có thể kiểm thử mà
    không kết thúc tiến trình test. Mã ``0`` biểu thị chạy thành công; các mã
    khác mô tả lỗi snapshot, khởi tạo hoặc validation cuối.
    """

    # Snapshot nghiệp vụ có thể chứa tên học phần và giảng viên bằng Unicode.
    # Ép hai luồng CLI sang UTF-8 để Windows không dừng chương trình khi bảng
    # mã mặc định của terminal không biểu diễn được tiếng Việt. Các stream giả
    # trong unit test có thể không hỗ trợ ``reconfigure`` nên được giữ nguyên.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    try:
        prepared = prepare_snapshot_for_optimization(args.snapshot)
    except (OSError, TypeError, ValueError) as error:
        print(f"Không thể chuẩn bị snapshot: {error}", file=sys.stderr)
        return 2

    if not prepared.is_ready:
        print("Snapshot có buổi học không có phương án hợp lệ.", file=sys.stderr)
        for issue in prepared.no_option_issues:
            print(
                f"  chỉ số buổi={issue.session_index}, "
                f"mã buổi={issue.class_session_id}: {issue.reason}",
                file=sys.stderr,
            )
        return 3

    evaluation_config = CandidateEvaluationConfig(
        max_decode_nodes=args.max_decode_nodes,
        enable_repair=not args.disable_repair,
        max_repair_attempts=(
            0 if args.disable_repair else args.max_repair_attempts
        ),
    )
    initialization = initialize_population(
        prepared.problem,
        prepared.option_domains,
        population_size=args.population_size,
        max_initialization_attempts=args.max_initialization_attempts,
        seed=args.seed,
        evaluation_config=evaluation_config,
    )

    if initialization.status != PopulationInitializationStatus.SUCCESS:
        print(
            "Không thể tạo đủ quần thể ban đầu hợp lệ: "
            f"{initialization.reason}",
            file=sys.stderr,
        )
        return 4

    # A successful initialization performs exactly one FE per individual.
    # Allocating N additional FE per iteration keeps the theoretical budget
    # identical across complete hybrid iterations.
    max_fitness_evaluations = (
        initialization.fitness_evaluations
        + args.iterations * args.population_size
    )
    result = run_hybrid(
        prepared.problem,
        prepared.option_domains,
        initialization,
        HybridConfig(
            max_fitness_evaluations=max_fitness_evaluations,
            max_offspring_attempts=args.max_offspring_attempts,
            seed=args.seed,
            evaluation_config=evaluation_config,
            ga_ratio=args.ga_ratio,
        ),
    )

    validation = validate_timetable(
        prepared.problem,
        result.best_individual.selected_options,
    )
    if not validation.is_valid:
        print(
            "Thuật toán trả về thời khóa biểu còn vi phạm bắt buộc.",
            file=sys.stderr,
        )
        for violation in validation.violations:
            print(
                f"  {violation.code.value}: {violation.message}",
                file=sys.stderr,
            )
        return 5

    _print_timetable_result(
        prepared.problem,
        result,
        prepared.snapshot_checksum,
        args.seed,
    )

    if not args.no_report:
        try:
            report_paths = export_timetable_report(
                prepared.problem,
                result,
                prepared.snapshot_checksum,
                args.seed,
                args.output_directory,
            )
        except (OSError, RuntimeError, ValueError) as error:
            print(f"Không thể xuất báo cáo: {error}", file=sys.stderr)
            return 6

        print()
        print("CÁC TỆP KẾT QUẢ ĐÃ TẠO")
        print(f"  Thư mục                 : {report_paths.output_directory.resolve()}")
        print(f"  Tổng hợp JSON           : {report_paths.summary_json.name}")
        print(f"  Dữ liệu hội tụ CSV      : {report_paths.convergence_csv.name}")
        print(f"  Thời khóa biểu CSV      : {report_paths.timetable_csv.name}")
        print(f"  Ảnh hội tụ              : {report_paths.convergence_image.name}")
        print(f"  Ảnh thời khóa biểu       : {report_paths.timetable_image.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
