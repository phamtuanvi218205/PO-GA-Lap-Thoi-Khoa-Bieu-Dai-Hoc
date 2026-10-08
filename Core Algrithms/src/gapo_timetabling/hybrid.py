"""Thuật toán lai GA–PO cho bài toán thời khóa biểu dùng random-key.

Mỗi iteration chia quần thể hiện tại thành hai nhóm không rỗng. Nhóm thứ nhất
sinh cá thể con bằng các toán tử của Genetic Algorithm; nhóm thứ hai sinh cá
thể con bằng các hành vi của Parrot Optimizer V2. Hai nhánh dùng chung pipeline
đánh giá ứng viên:

``random-key vector -> decoder -> optional repair -> validator -> fitness``

Các cá thể con hợp lệ của hai nhánh được hợp với toàn bộ quần thể cha. Thuật
toán giữ ``N`` cá thể tốt nhất theo thứ tự mục tiêu lexicographic của thời khóa
biểu rồi xáo trộn trước lần chia nhóm tiếp theo. Việc giữ cha trong tập chọn
lọc bảo toàn quần thể khi một cá thể con không thể giải mã, đồng thời không cần
gán điểm phạt giả cho lịch không hợp lệ.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path
from random import Random
from time import perf_counter
from typing import Sequence

from .constraints import validate_timetable
from .ga import (
    GAConfig,
    _create_offspring_vector,
    _validate_ga_run_inputs,
)
from .metrics import (
    ConvergencePoint,
    OptimizationMetrics,
    OptimizationResult,
    accumulate_candidate_evaluation,
)
from .models import (
    OptimizationAlgorithm,
    ProblemInstance,
    SessionOption,
)
from .po import (
    PoBehavior,
    PoConfig,
    _create_and_evaluate_po_offspring,
    calculate_population_mean,
)
from .population import (
    CandidateEvaluationConfig,
    PopulationInitializationResult,
    PopulationInitializationStatus,
    TimetableIndividual,
    best_individual,
    evaluate_candidate,
    initialize_population,
    sort_individuals,
)
from .reporting import (
    WEEKDAY_NAMES,
    build_timetable_report_rows,
    export_timetable_report,
)
from .snapshot import prepare_snapshot_for_optimization


@dataclass(frozen=True, slots=True)
class HybridConfig:
    """Cấu hình cho một lần chạy thuật toán lai GA–PO.

    ``max_fitness_evaluations`` bao gồm cả số lần đánh giá đã dùng để tạo quần
    thể ban đầu. ``ga_ratio`` quy định số vị trí được giao cho nhánh GA trong
    mỗi iteration; các vị trí còn lại thuộc nhánh PO. Mỗi nhánh phải nhận ít
    nhất một vị trí để lần chạy thực sự là thuật toán lai.

    Các tham số toán tử GA có cùng ý nghĩa và giá trị mặc định với
    :class:`gapo_timetabling.ga.GAConfig`. Hai nhánh dùng chung giới hạn giải
    mã, sửa và kiểm tra lịch thông qua ``evaluation_config``.
    """

    max_fitness_evaluations: int
    max_offspring_attempts: int
    seed: int
    evaluation_config: CandidateEvaluationConfig
    ga_ratio: float = 0.5
    tournament_size: int = 3
    crossover_probability: float = 0.9
    crossover_distribution_index: float = 15.0
    mutation_probability: float | None = None
    mutation_distribution_index: float = 20.0

    def __post_init__(self) -> None:
        """Từ chối giá trị không thể mô tả một lần chạy hybrid hợp lệ."""

        if self.max_fitness_evaluations < 1:
            raise ValueError(
                "max_fitness_evaluations must be greater than or equal to 1."
            )

        if self.max_offspring_attempts < 1:
            raise ValueError(
                "max_offspring_attempts must be greater than or equal to 1."
            )

        if not isfinite(self.ga_ratio):
            raise ValueError("ga_ratio must be finite.")

        if not 0.0 < self.ga_ratio < 1.0:
            raise ValueError("ga_ratio must be in the open interval (0, 1).")

        # Khởi tạo cấu hình nhánh để tái sử dụng các quy tắc kiểm tra hiện có,
        # tránh duy trì hai bản kiểm tra tham số giống nhau trong hybrid.
        self.create_ga_config()
        self.create_po_config()

    def create_ga_config(self) -> GAConfig:
        """Tạo cấu hình GA được dùng bởi nhánh GA của hybrid."""

        return GAConfig(
            max_fitness_evaluations=self.max_fitness_evaluations,
            max_offspring_attempts=self.max_offspring_attempts,
            seed=self.seed,
            evaluation_config=self.evaluation_config,
            tournament_size=self.tournament_size,
            crossover_probability=self.crossover_probability,
            crossover_distribution_index=(
                self.crossover_distribution_index
            ),
            mutation_probability=self.mutation_probability,
            mutation_distribution_index=self.mutation_distribution_index,
        )

    def create_po_config(self) -> PoConfig:
        """Tạo cấu hình PO được dùng bởi nhánh PO của hybrid."""

        return PoConfig(
            max_fitness_evaluations=self.max_fitness_evaluations,
            max_offspring_attempts=self.max_offspring_attempts,
            seed=self.seed,
            evaluation_config=self.evaluation_config,
        )


def _initial_metrics(
    initialization: PopulationInitializationResult,
) -> OptimizationMetrics:
    """Sao chép số liệu khởi tạo vào metrics dùng chung của optimizer."""

    return OptimizationMetrics(
        completed_iterations=0,
        candidate_attempts=initialization.candidate_attempts,
        fitness_evaluations=initialization.fitness_evaluations,
        decode_failed_count=initialization.decode_failed_count,
        validation_failed_count=initialization.validation_failed_count,
        repaired_individual_count=(
            initialization.repaired_individual_count
        ),
        failed_repair_count=initialization.failed_repair_count,
        total_repair_attempts=initialization.total_repair_attempts,
        discarded_offspring_count=0,
        total_decode_nodes=initialization.total_decode_nodes,
        total_decode_backtracks=initialization.total_decode_backtracks,
        runtime_seconds=0.0,
    )


def _create_convergence_point(
    iteration: int,
    metrics: OptimizationMetrics,
    best_so_far: TimetableIndividual,
) -> ConvergencePoint:
    """Ghi nghiệm tốt nhất hiện tại mà không thực hiện thêm một FE."""

    fitness = best_so_far.fitness
    return ConvergencePoint(
        iteration=iteration,
        fitness_evaluations=metrics.fitness_evaluations,
        time_stability_score=fitness.time_stability_score,
        general_quality_score=fitness.general_quality_score,
        lecturer_preference_score=fitness.lecturer_preference_score,
    )


def _individual_order_key(
    individual: TimetableIndividual,
) -> tuple[
    tuple[float, float, float],
    tuple[float, ...],
]:
    """Tạo khóa gồm thứ tự mục tiêu và tie-break xác định bằng vector."""

    return individual.fitness_key, individual.vector


def _try_create_ga_offspring(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    ga_population: tuple[TimetableIndividual, ...],
    ga_config: GAConfig,
    rng: Random,
    metrics: OptimizationMetrics,
) -> tuple[
    TimetableIndividual | None,
    OptimizationMetrics,
]:
    """Sinh một cá thể con GA hợp lệ trong giới hạn số lần thử.

    Các toán tử GA chỉ đề xuất vector random-key. Tính hợp lệ và chất lượng
    thời khóa biểu được xác định hoàn toàn bởi pipeline đánh giá chung. Ứng
    viên thất bại vẫn được ghi nhận số liệu nhưng không nhận fitness giả.
    """

    updated_metrics = metrics

    for _attempt_number in range(
        1,
        ga_config.max_offspring_attempts + 1,
    ):
        proposed_vector = _create_offspring_vector(
            population=ga_population,
            config=ga_config,
            dimension=problem.dimension,
            rng=rng,
        )

        evaluation = evaluate_candidate(
            problem,
            option_domains,
            proposed_vector,
            ga_config.evaluation_config,
        )

        updated_metrics = accumulate_candidate_evaluation(
            updated_metrics,
            evaluation,
        )

        if evaluation.is_success:
            if evaluation.individual is None:
                raise RuntimeError(
                    "A successful evaluation must return an individual."
                )

            return evaluation.individual, updated_metrics

    # Một offspring bị loại đại diện cho toàn bộ chuỗi retry đã dùng hết, không
    # phải cho từng vector ứng viên bị từ chối trong chuỗi đó.
    updated_metrics = replace(
        updated_metrics,
        discarded_offspring_count=(
            updated_metrics.discarded_offspring_count + 1
        ),
    )

    return None, updated_metrics


def run_hybrid(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    initialization: PopulationInitializationResult,
    config: HybridConfig,
) -> OptimizationResult:
    """Chạy hybrid GA–PO từ một quần thể ban đầu hợp lệ.

    Đầu mỗi iteration, thuật toán chụp mean của toàn bộ quần thể cha và nghiệm
    tốt nhất toàn cục. Chỉ số quần thể được xáo trộn rồi chia thành nhánh GA và
    PO. Mỗi nhánh tạo tối đa một cá thể con hợp lệ cho từng vị trí được giao.

    Quần thể kế tiếp được chọn từ ``parents + valid_offspring``. Cách chọn từ
    hợp cha–con này khác PO thuần, nơi một con PO hợp lệ thay trực tiếp vị trí
    cha. Trong hybrid, cha đã có sẵn trong hợp nên bước survivor selection có
    thể so sánh nhất quán toàn bộ ứng viên hợp lệ.
    """

    started_at = perf_counter()
    ga_config = config.create_ga_config()
    po_config = config.create_po_config()

    # GA và hybrid dùng cùng bất biến đầu vào: quần thể khởi tạo SUCCESS, miền
    # option không rỗng và đúng thứ tự, random-key hữu hạn, cùng ngân sách FE
    # biểu diễn được một số nguyên iteration đầy đủ.
    max_iterations = _validate_ga_run_inputs(
        problem=problem,
        option_domains=option_domains,
        initialization=initialization,
        config=ga_config,
    )

    population = tuple(initialization.individuals)
    population_size = len(population)
    number_of_ga_agents = int(round(population_size * config.ga_ratio))

    if (
        number_of_ga_agents <= 0
        or number_of_ga_agents >= population_size
    ):
        raise ValueError(
            "ga_ratio must assign at least one individual to each branch."
        )

    best_so_far = best_individual(population)
    metrics = _initial_metrics(initialization)
    convergence_history: list[ConvergencePoint] = [
        _create_convergence_point(
            iteration=0,
            metrics=metrics,
            best_so_far=best_so_far,
        )
    ]
    rng = Random(config.seed)

    for iteration in range(1, max_iterations + 1):
        # Mean được giữ cố định trong khi sinh toàn bộ con PO của iteration;
        # không tính lại từ dữ liệu đã được cập nhật một phần.
        population_mean = calculate_population_mean(
            tuple(individual.vector for individual in population)
        )

        # Toàn bộ con PO trong iteration dùng chung best tham chiếu, alpha và
        # theta để giữ đúng cấu trúc cập nhật theo iteration.
        po_best_reference = best_so_far
        alpha = rng.random() / 5.0
        theta = rng.random() * math.pi

        shuffled_indices = list(range(population_size))
        rng.shuffle(shuffled_indices)
        ga_indices = tuple(shuffled_indices[:number_of_ga_agents])
        po_indices = tuple(shuffled_indices[number_of_ga_agents:])
        ga_population = tuple(population[index] for index in ga_indices)
        valid_offspring: list[TimetableIndividual] = []

        # Nhánh GA tạo một vị trí offspring cho mỗi cá thể được giao. Tournament
        # selection chỉ chọn cha mẹ trong nhóm GA hiện tại.
        for _offspring_index in range(len(ga_indices)):
            ga_offspring, metrics = _try_create_ga_offspring(
                problem=problem,
                option_domains=option_domains,
                ga_population=ga_population,
                ga_config=ga_config,
                rng=rng,
                metrics=metrics,
            )

            if ga_offspring is not None:
                valid_offspring.append(ga_offspring)

        # Mỗi vị trí nhánh PO bốc độc lập một hành vi, nhưng vẫn dùng các tham
        # chiếu đã cố định ở cấp iteration.
        for population_index in po_indices:
            current_individual = population[population_index]
            behavior = PoBehavior(
                rng.randint(
                    PoBehavior.FORAGING.value,
                    PoBehavior.FEAR_OF_STRANGERS.value,
                )
            )

            po_result = _create_and_evaluate_po_offspring(
                problem=problem,
                option_domains=option_domains,
                current_individual=current_individual,
                current_index=population_index,
                behavior=behavior,
                best_individual=po_best_reference,
                population_mean=population_mean,
                iteration=iteration,
                max_iterations=max_iterations,
                alpha=alpha,
                theta=theta,
                rng=rng,
                config=po_config,
                metrics=metrics,
            )
            metrics = po_result.metrics

            if po_result.is_success:
                if po_result.individual is None:
                    raise RuntimeError(
                        "A successful PO result must return an individual."
                    )
                valid_offspring.append(po_result.individual)

        # Cha luôn nằm trong tập ứng viên. Một offspring thất bại chỉ làm giảm
        # mức khám phá trong iteration, không làm quần thể mất tính hợp lệ hoặc
        # thay đổi kích thước yêu cầu.
        candidate_population = population + tuple(valid_offspring)
        population = sort_individuals(
            candidate_population
        )[:population_size]

        if len(population) != population_size:
            raise RuntimeError(
                "Hybrid survivor selection must preserve population size."
            )

        generation_best = best_individual(population)
        if (
            _individual_order_key(generation_best)
            < _individual_order_key(best_so_far)
        ):
            best_so_far = generation_best

        # Chỉ xáo trộn sau survivor selection để bước chọn lọc vẫn xác định,
        # đồng thời tránh một vị trí luôn thuộc cố định cùng một nhánh.
        shuffled_population = list(population)
        rng.shuffle(shuffled_population)
        population = tuple(shuffled_population)

        metrics = replace(
            metrics,
            completed_iterations=iteration,
        )
        convergence_history.append(
            _create_convergence_point(
                iteration=iteration,
                metrics=metrics,
                best_so_far=best_so_far,
            )
        )

    final_metrics = replace(
        metrics,
        runtime_seconds=perf_counter() - started_at,
    )

    return OptimizationResult(
        algorithm=OptimizationAlgorithm.GA_PO,
        best_individual=best_so_far,
        final_population=population,
        convergence_history=tuple(convergence_history),
        metrics=final_metrics,
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
            "Chạy thuật toán lai GA-PO từ snapshot problem-instance.v1 "
            "và in thời khóa biểu tốt nhất."
        )
    )
    parser.add_argument(
        "snapshot",
        type=Path,
        help="Đường dẫn đến snapshot JSON problem-instance.v1.",
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
    print(f"  Độ không ổn định thứ/tiết : {best.fitness.time_stability_score:.6f}")
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
