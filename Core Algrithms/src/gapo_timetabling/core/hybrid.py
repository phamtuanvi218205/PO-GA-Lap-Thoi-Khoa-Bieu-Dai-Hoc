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

import math
from dataclasses import dataclass, replace
from math import isfinite
from random import Random
from time import perf_counter

from .ga import (
    GAConfig,
    _create_offspring_vector,
    _validate_ga_run_inputs,
)
from .metrics import (
    ConvergencePoint,
    OptimizationMetrics,
    OptimizationProgress,
    OptimizationProgressCallback,
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
    TimetableIndividual,
    best_individual,
    evaluate_candidate,
    sort_individuals,
)


@dataclass(frozen=True, slots=True)
class HybridConfig:
    """Cấu hình cho một lần chạy thuật toán lai GA–PO.

    ``max_fitness_evaluations`` bao gồm cả số lần đánh giá đã dùng để tạo quần
    thể ban đầu. ``ga_ratio`` quy định số vị trí được giao cho nhánh GA trong
    mỗi iteration; các vị trí còn lại thuộc nhánh PO. Mỗi nhánh phải nhận ít
    nhất một vị trí để lần chạy thực sự là thuật toán lai.

    Các tham số toán tử GA có cùng ý nghĩa và giá trị mặc định với
    :class:`gapo_timetabling.core.ga.GAConfig`. Hai nhánh dùng chung giới hạn giải
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
        general_quality_score=fitness.general_quality_score,
        lecturer_preference_score=fitness.lecturer_preference_score,
    )


def _individual_order_key(
    individual: TimetableIndividual,
) -> tuple[
    tuple[float, float],
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
    *,
    progress_callback: OptimizationProgressCallback | None = None,
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

    def report_progress(iteration: int) -> None:
        if progress_callback is None:
            return
        progress_callback(OptimizationProgress(
            algorithm=OptimizationAlgorithm.GA_PO,
            iteration=iteration,
            max_iterations=max_iterations,
            max_fitness_evaluations=config.max_fitness_evaluations,
            metrics=metrics,
            best_general_quality_score=best_so_far.fitness.general_quality_score,
            best_lecturer_preference_score=(
                best_so_far.fitness.lecturer_preference_score
            ),
        ))

    report_progress(0)

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
            report_progress(iteration - 1)

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
            report_progress(iteration - 1)

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
        report_progress(iteration)

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
