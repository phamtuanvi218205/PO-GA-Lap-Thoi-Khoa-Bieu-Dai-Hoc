"""GA–PO entry point: TARGET_PO80, with the legacy ISLAND80 engine retained."""

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
    select_survivors,
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
)


@dataclass(frozen=True, slots=True)
class HybridConfig:
    """Cấu hình cho một lần chạy thuật toán lai GA–PO.

    ``max_fitness_evaluations`` bao gồm cả khởi tạo. ``ga_ratio`` mặc định 0.8
    quyết định số vị trí GA và bộ nhớ PO, mỗi bên ít nhất hai cá thể.
    TARGET_PO80 cần số vị trí PO không lớn hơn số cá thể GA để chọn anchor.
    Chỉ cấu hình 80/20 được đo trong nghiên cứu; tỷ lệ khác cần đánh giá riêng.

    Các tham số toán tử GA có cùng ý nghĩa và giá trị mặc định với
    :class:`gapo_timetabling.core.ga.GAConfig`. Hai nhánh dùng chung giới hạn giải
    mã, sửa và kiểm tra lịch thông qua ``evaluation_config``.
    """

    max_fitness_evaluations: int
    max_offspring_attempts: int
    seed: int
    evaluation_config: CandidateEvaluationConfig
    ga_ratio: float = 0.8
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



ISLAND_HYBRID_MECHANISM = "GA_PO_ISLANDS.v1"
HYBRID_MECHANISM = "GA_PO_TARGET_PO80.v1"
DEFAULT_GA_RATIO = 0.8
PO_ARCHIVE_SIZE = 6
MIGRATION_INTERVAL = 2


def validate_island_sizes(population_size: int, ga_ratio: float) -> int:
    """Reject unsupported splits; never silently clamp the benchmark ratio."""
    if not isfinite(ga_ratio):
        raise ValueError("ga_ratio must be finite.")
    if not 0.0 < ga_ratio < 1.0:
        raise ValueError("ga_ratio must be in the open interval (0, 1).")
    n_ga = round(population_size * ga_ratio)
    if min(n_ga, population_size - n_ga) < 2:
        raise ValueError("Each island needs at least two individuals.")
    return n_ga


def validate_target_sizes(population_size: int, ga_ratio: float) -> int:
    """Validate target memory size against the available GA anchors."""
    n_ga = validate_island_sizes(population_size, ga_ratio)
    if population_size - n_ga > n_ga:
        raise ValueError('TARGET_PO80 needs at least as many GA individuals as PO slots.')
    return n_ga


def _unique_best(items, limit: int) -> tuple[TimetableIndividual, ...]:
    """Archive only; GA survivors still use the original GA selection."""
    result = []
    seen = set()
    for item in sorted(items, key=_individual_order_key):
        if item.selected_options not in seen:
            result.append(item)
            seen.add(item.selected_options)
            if len(result) == limit:
                break
    return tuple(result)


def _migrate(source, destination):
    """One novel schedule replaces the worst non-elite without another FE."""
    existing = {item.selected_options for item in destination}
    migrant = next((item for item in sorted(source, key=_individual_order_key)
                    if item.selected_options not in existing), None)
    if migrant is None:
        return destination, None
    protected = min(range(len(destination)), key=lambda i: _individual_order_key(destination[i]))
    worst = max((i for i in range(len(destination)) if i != protected),
                key=lambda i: _individual_order_key(destination[i]))
    updated = list(destination)
    updated[worst] = migrant
    return tuple(updated), migrant


def run_island_hybrid(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    initialization: PopulationInitializationResult,
    config: HybridConfig,
    *, progress_callback: OptimizationProgressCallback | None = None,
) -> OptimizationResult:
    """Run legacy D155 ISLAND80, preserving its operator and RNG order.

    Other explicit ratios are configurable experiments, not measured ISLAND80.
    No global monkeypatching: concurrent API jobs remain isolated. Progress
    callbacks consume no RNG and can cancel after each offspring slot.
    """
    started_at = perf_counter()
    ga_config, po_config = config.create_ga_config(), config.create_po_config()
    max_iterations = _validate_ga_run_inputs(problem, option_domains, initialization, ga_config)
    population_size = len(initialization.individuals)
    n_ga = validate_island_sizes(population_size, config.ga_ratio)
    indices = list(range(population_size))
    Random(config.seed ^ 0x1548020).shuffle(indices)
    ga_pool = tuple(initialization.individuals[i] for i in indices[:n_ga])
    po_pool = tuple(initialization.individuals[i] for i in indices[n_ga:])
    po_archive = _unique_best(po_pool, PO_ARCHIVE_SIZE)
    po_best = best_individual(po_pool)
    best_so_far = best_individual(initialization.individuals)
    metrics = _initial_metrics(initialization)
    history = [_create_convergence_point(0, metrics, best_so_far)]
    rng = Random(config.seed)

    def accept(item: TimetableIndividual) -> None:
        nonlocal best_so_far
        if _individual_order_key(item) < _individual_order_key(best_so_far):
            best_so_far = item

    def report_progress(iteration: int) -> None:
        if progress_callback is not None:
            progress_callback(OptimizationProgress(
                algorithm=OptimizationAlgorithm.GA_PO,
                iteration=iteration, max_iterations=max_iterations,
                max_fitness_evaluations=config.max_fitness_evaluations, metrics=metrics,
                best_general_quality_score=best_so_far.fitness.general_quality_score,
                best_lecturer_preference_score=best_so_far.fitness.lecturer_preference_score,
            ))

    report_progress(0)
    for generation in range(1, max_iterations + 1):
        children = []
        for _ in range(n_ga):
            child, metrics = _try_create_ga_offspring(
                problem=problem, option_domains=option_domains, ga_population=ga_pool,
                ga_config=ga_config, rng=rng, metrics=metrics,
            )
            if child is not None:
                children.append(child)
                accept(child)
            report_progress(generation - 1)
        ga_pool = select_survivors(ga_pool, tuple(children), n_ga)

        mean = calculate_population_mean(tuple(item.vector for item in po_pool))
        alpha, theta = rng.random() / 5.0, rng.random() * math.pi
        next_po = list(po_pool)
        for index, parent in enumerate(po_pool):
            behavior = PoBehavior(rng.randint(1, 4))
            outcome = _create_and_evaluate_po_offspring(
                problem=problem, option_domains=option_domains,
                current_individual=parent, current_index=index, behavior=behavior,
                best_individual=po_best, population_mean=mean,
                iteration=generation, max_iterations=max_iterations,
                alpha=alpha, theta=theta, rng=rng, config=po_config, metrics=metrics,
            )
            metrics = outcome.metrics
            child = outcome.individual
            if child is not None:
                # Valid PO children replace parents even if worse.
                next_po[index] = child
                accept(child)
                po_archive = _unique_best(po_archive + (child,), PO_ARCHIVE_SIZE)
                if _individual_order_key(child) < _individual_order_key(po_best):
                    po_best = child
            report_progress(generation - 1)
        po_pool = tuple(next_po)

        if generation % MIGRATION_INTERVAL == 0 and generation < max_iterations:
            # Both directions use PRE-migration sources (no ping-pong copy).
            old_ga, old_po = ga_pool, po_pool
            ga_pool, _ = _migrate(po_archive + old_po, old_ga)
            po_pool, from_ga = _migrate(old_ga, old_po)
            if from_ga is not None:
                po_archive = _unique_best(po_archive + (from_ga,), PO_ARCHIVE_SIZE)
                if _individual_order_key(from_ga) < _individual_order_key(po_best):
                    po_best = from_ga

        if len(ga_pool) != n_ga or len(po_pool) != population_size - n_ga:
            raise RuntimeError("Hybrid migration must preserve island sizes.")
        if metrics.fitness_evaluations > config.max_fitness_evaluations:
            raise RuntimeError("Hybrid exceeded its shared FE cap.")
        metrics = replace(metrics, completed_iterations=generation)
        history.append(_create_convergence_point(generation, metrics, best_so_far))
        report_progress(generation)

    return OptimizationResult(
        algorithm=OptimizationAlgorithm.GA_PO, best_individual=best_so_far,
        final_population=ga_pool + po_pool, convergence_history=tuple(history),
        metrics=replace(metrics, runtime_seconds=perf_counter() - started_at),
    )


def run_hybrid(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    initialization: PopulationInitializationResult,
    config: HybridConfig,
    *, progress_callback: OptimizationProgressCallback | None = None,
) -> OptimizationResult:
    """Run the approved full TARGET_PO80 method for all new GA_PO jobs."""
    from .target_hybrid import run_target_hybrid
    return run_target_hybrid(problem, option_domains, initialization, config,
                             progress_callback=progress_callback)
