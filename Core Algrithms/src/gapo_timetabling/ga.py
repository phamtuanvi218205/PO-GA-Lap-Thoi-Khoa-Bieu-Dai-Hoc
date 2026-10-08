"""Genetic Algorithm cho bài toán xếp thời khóa biểu random-key.

Module này chỉ chịu trách nhiệm tối ưu các vector random-key bằng các toán tử
GA. Mỗi gene tương ứng đúng một ``ClassSession`` và chỉ biểu diễn mức ưu tiên
của ``SessionOption``; gene không lưu trực tiếp ngày, phòng hoặc tiết học.

Mọi offspring bắt buộc đi qua cổng đánh giá chung của ``population.py``:

``Vector -> Decoder -> Repair tùy chọn -> Validator -> Fitness``.

GA không tự cài lại decoder, repair, validator, fitness hoặc metrics. Các chỉ
số thực nghiệm và kiểu kết quả dùng trực tiếp hợp đồng chung trong
``metrics.py`` để có thể so sánh công bằng với PO và GA–PO.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from random import Random
from time import perf_counter

from .metrics import (
    ConvergencePoint,
    OptimizationMetrics,
    OptimizationResult,
    accumulate_candidate_evaluation,
)
from .models import OptimizationAlgorithm, ProblemInstance, SessionOption
from .population import (
    CandidateEvaluationConfig,
    PopulationInitializationResult,
    PopulationInitializationStatus,
    TimetableIndividual,
    best_individual,
    evaluate_candidate,
    sort_individuals,
)


@dataclass(frozen=True, slots=True)
class GAConfig:
    """Cấu hình kỹ thuật cho một lần chạy Genetic Algorithm.

    ``max_fitness_evaluations`` là ngân sách FE chung của cả khởi tạo và tối
    ưu. ``max_offspring_attempts`` là số vector tối đa được thử cho *mỗi vị trí
    offspring* trong một thế hệ, không phải giới hạn tổng số lần thử của cả
    thế hệ. Kích thước quần thể không nằm trong config vì được lấy trực tiếp
    từ ``PopulationInitializationResult`` đã tạo trước đó.
    """

    max_fitness_evaluations: int
    max_offspring_attempts: int
    seed: int
    evaluation_config: CandidateEvaluationConfig

    tournament_size: int = 3
    crossover_probability: float = 0.9
    crossover_distribution_index: float = 15.0
    mutation_probability: float | None = None
    mutation_distribution_index: float = 20.0

    def __post_init__(self) -> None:
        """Từ chối cấu hình không thể tạo một lần chạy GA hợp lệ."""

        if self.max_fitness_evaluations < 1:
            raise ValueError(
                "max_fitness_evaluations phải lớn hơn hoặc bằng 1."
            )

        if self.max_offspring_attempts < 1:
            raise ValueError(
                "max_offspring_attempts phải lớn hơn hoặc bằng 1."
            )

        if self.tournament_size < 2:
            raise ValueError(
                "tournament_size phải lớn hơn hoặc bằng 2."
            )

        if not 0.0 <= self.crossover_probability <= 1.0:
            raise ValueError(
                "crossover_probability phải nằm trong [0,1]."
            )

        if self.crossover_distribution_index <= 0.0:
            raise ValueError(
                "crossover_distribution_index phải dương."
            )

        if self.mutation_probability is not None:
            if not 0.0 <= self.mutation_probability <= 1.0:
                raise ValueError(
                    "mutation_probability phải nằm trong [0,1]."
                )

        if self.mutation_distribution_index <= 0.0:
            raise ValueError(
                "mutation_distribution_index phải dương."
            )

    def resolved_mutation_probability(self, dimension: int) -> float:
        """Trả xác suất mutation cấu hình hoặc mặc định ``1 / D``."""

        if dimension < 1:
            raise ValueError("dimension phải lớn hơn hoặc bằng 1.")

        if self.mutation_probability is not None:
            return self.mutation_probability

        return 1.0 / dimension


def _individual_order_key(
    individual: TimetableIndividual,
) -> tuple[
    tuple[float, float, float],
    tuple[float, ...],
]:
    """Khóa dùng để so sánh hai cá thể theo đúng Gate F.

    Fitness được ưu tiên theo:
    Q_time -> Q_general -> Q_lecturer.

    Vector chỉ dùng để phá hòa khi hai fitness hoàn toàn giống nhau.
    """

    return individual.fitness_key, individual.vector


def clamp_vector(
    vector: tuple[float, ...],
) -> tuple[float, ...]:
    """Đưa mọi gene của chromosome về miền random-key [0,1]."""

    if not vector:
        raise ValueError(
            "Vector GA không được rỗng."
        )

    if any(
        not isfinite(value)
        for value in vector
    ):
        raise ValueError(
            "Vector GA chỉ được chứa các giá trị hữu hạn."
        )

    return tuple(
        min(
            1.0,
            max(
                0.0,
                value,
            ),
        )
        for value in vector
    )


def tournament_select(
    population: tuple[TimetableIndividual, ...],
    tournament_size: int,
    rng: Random,
) -> TimetableIndividual:
    """Chọn một cha/mẹ bằng tournament selection.

    Lấy ngẫu nhiên tournament_size cá thể,
    sau đó cá thể tốt nhất theo fitness lexicographic thắng.
    """

    if not population:
        raise ValueError(
            "Không thể tournament selection từ quần thể rỗng."
        )

    if tournament_size < 2:
        raise ValueError(
            "tournament_size phải lớn hơn hoặc bằng 2."
        )

    competitors = tuple(
        population[
            rng.randrange(
                len(population)
            )
        ]
        for _ in range(
            tournament_size
        )
    )

    return min(
        competitors,
        key=_individual_order_key,
    )


def simulated_binary_crossover(
    first_parent: tuple[float, ...],
    second_parent: tuple[float, ...],
    crossover_probability: float,
    distribution_index: float,
    rng: Random,
) -> tuple[
    tuple[float, ...],
    tuple[float, ...],
]:
    """Simulated Binary Crossover cho hai chromosome random-key."""

    if (
        not first_parent
        or len(first_parent) != len(second_parent)
    ):
        raise ValueError(
            "Hai vector cha mẹ phải cùng chiều và không rỗng."
        )

    if not 0.0 <= crossover_probability <= 1.0:
        raise ValueError(
            "crossover_probability phải nằm trong [0,1]."
        )

    if distribution_index <= 0.0:
        raise ValueError(
            "distribution_index phải dương."
        )

    first = clamp_vector(
        first_parent
    )

    second = clamp_vector(
        second_parent
    )

    # Không crossover thì trả bản sao của cha mẹ.
    if rng.random() > crossover_probability:
        return (
            tuple(first),
            tuple(second),
        )

    first_child: list[float] = []
    second_child: list[float] = []

    exponent = 1.0 / (
        distribution_index + 1.0
    )

    for (
        first_gene,
        second_gene,
    ) in zip(
        first,
        second,
    ):
        random_value = rng.random()

        if random_value <= 0.5:
            beta = (
                2.0
                * random_value
            ) ** exponent

        else:
            beta = (
                1.0
                / (
                    2.0
                    * (
                        1.0
                        - random_value
                    )
                )
            ) ** exponent

        child_gene_1 = 0.5 * (
            (
                1.0 + beta
            )
            * first_gene
            +
            (
                1.0 - beta
            )
            * second_gene
        )

        child_gene_2 = 0.5 * (
            (
                1.0 - beta
            )
            * first_gene
            +
            (
                1.0 + beta
            )
            * second_gene
        )

        first_child.append(
            child_gene_1
        )

        second_child.append(
            child_gene_2
        )

    return (
        clamp_vector(
            tuple(first_child)
        ),
        clamp_vector(
            tuple(second_child)
        ),
    )


def polynomial_mutation(
    vector: tuple[float, ...],
    mutation_probability: float,
    distribution_index: float,
    rng: Random,
) -> tuple[float, ...]:
    """Polynomial mutation theo từng gene của chromosome."""

    if not 0.0 <= mutation_probability <= 1.0:
        raise ValueError(
            "mutation_probability phải nằm trong [0,1]."
        )

    if distribution_index <= 0.0:
        raise ValueError(
            "distribution_index phải dương."
        )

    source = clamp_vector(
        vector
    )

    mutation_power = 1.0 / (
        distribution_index + 1.0
    )

    mutated: list[float] = []

    for gene in source:

        # Gene này không mutation.
        if (
            rng.random()
            > mutation_probability
        ):
            mutated.append(
                gene
            )
            continue

        random_value = rng.random()

        distance_to_lower = gene

        distance_to_upper = (
            1.0 - gene
        )

        if random_value <= 0.5:

            expression = (
                2.0
                * random_value
                +
                (
                    1.0
                    - 2.0
                    * random_value
                )
                *
                (
                    1.0
                    - distance_to_lower
                )
                ** (
                    distribution_index
                    + 1.0
                )
            )

            change = (
                expression
                ** mutation_power
                - 1.0
            )

        else:

            expression = (
                2.0
                * (
                    1.0
                    - random_value
                )
                +
                2.0
                * (
                    random_value
                    - 0.5
                )
                *
                (
                    1.0
                    - distance_to_upper
                )
                ** (
                    distribution_index
                    + 1.0
                )
            )

            change = (
                1.0
                - expression
                ** mutation_power
            )

        mutated.append(
            gene + change
        )

    return clamp_vector(
        tuple(mutated)
    )


def select_survivors(
    parents: tuple[TimetableIndividual, ...],
    offspring: tuple[TimetableIndividual, ...],
    population_size: int,
) -> tuple[TimetableIndividual, ...]:
    """Giữ lại N cá thể tốt nhất từ quần thể cha và con."""

    if population_size < 1:
        raise ValueError(
            "population_size phải lớn hơn hoặc bằng 1."
        )

    combined = (
        parents
        + offspring
    )

    if len(combined) < population_size:
        raise ValueError(
            "Không đủ cá thể hợp lệ để survivor selection."
        )

    return sort_individuals(
        combined
    )[:population_size]


def _create_offspring_vector(
    population: tuple[TimetableIndividual, ...],
    config: GAConfig,
    dimension: int,
    rng: Random,
) -> tuple[float, ...]:
    """Sinh một chromosome con từ population hiện tại."""

    first_parent = tournament_select(
        population,
        config.tournament_size,
        rng,
    )

    second_parent = tournament_select(
        population,
        config.tournament_size,
        rng,
    )

    (
        first_child,
        second_child,
    ) = simulated_binary_crossover(
        first_parent.vector,
        second_parent.vector,
        config.crossover_probability,
        config.crossover_distribution_index,
        rng,
    )

    # SBX tạo hai con.
    # Mỗi candidate attempt của timetable chỉ đánh giá một vector
    # để dễ kiểm soát chính xác FE.
    if rng.random() < 0.5:
        selected_child = (
            first_child
        )
    else:
        selected_child = (
            second_child
        )

    return polynomial_mutation(
        selected_child,
        config.resolved_mutation_probability(
            dimension
        ),
        config.mutation_distribution_index,
        rng,
    )

def _validate_ga_run_inputs(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    initialization: PopulationInitializationResult,
    config: GAConfig,
) -> int:
    """Kiểm tra đầu vào và tính số thế hệ GA được phép thực hiện.

    Quần thể ban đầu phải được tạo và đánh giá trước khi gọi GA để GA, PO và
    GA–PO có thể dùng bản sao của cùng một quần thể. Phần FE còn lại phải chia
    hết cho kích thước quần thể, vì mỗi thế hệ xử lý đủ ``N`` vị trí offspring
    và mỗi vị trí có thể tạo tối đa một cá thể hợp lệ, tức tối đa một FE.

    Returns:
        Số thế hệ đầy đủ được xác định trước từ ngân sách FE lý thuyết.
    """

    if initialization.status != PopulationInitializationStatus.SUCCESS:
        raise ValueError(
            "GA chỉ nhận quần thể có trạng thái khởi tạo SUCCESS."
        )

    population = initialization.individuals
    population_size = len(population)

    if population_size == 0:
        raise ValueError("Quần thể ban đầu của GA không được rỗng.")

    if population_size != initialization.requested_population_size:
        raise ValueError(
            "Số cá thể khởi tạo phải bằng requested_population_size."
        )

    if initialization.fitness_evaluations != population_size:
        raise ValueError(
            "FE khởi tạo phải bằng số cá thể hợp lệ trong quần thể."
        )

    if initialization.fitness_evaluations > initialization.candidate_attempts:
        raise ValueError(
            "FE khởi tạo không được lớn hơn số candidate attempts."
        )

    if len(option_domains) != problem.dimension:
        raise ValueError("Số miền option phải bằng số ClassSession.")

    for session_index, domain in enumerate(option_domains):
        # Một miền rỗng tương đương NO_OPTION và phải bị chặn trước optimizer.
        if not domain:
            raise ValueError(
                "GA không thể chạy khi có ClassSession không có SessionOption."
            )

        if any(option.session_index != session_index for option in domain):
            raise ValueError(
                "Option phải nằm trong miền của đúng session_index."
            )

    for individual_index, individual in enumerate(population):
        vector = individual.vector

        if len(vector) != problem.dimension:
            raise ValueError(
                "Vector của cá thể "
                f"{individual_index} phải có đúng {problem.dimension} gene."
            )

        for gene_index, gene in enumerate(vector):
            if not isfinite(gene):
                raise ValueError(
                    "Gene "
                    f"{gene_index} của cá thể {individual_index} "
                    "phải là số hữu hạn."
                )

            if gene < 0.0 or gene > 1.0:
                raise ValueError(
                    "Gene "
                    f"{gene_index} của cá thể {individual_index} "
                    "phải nằm trong [0, 1]."
                )

    remaining_fitness_evaluations = (
        config.max_fitness_evaluations
        - initialization.fitness_evaluations
    )

    if remaining_fitness_evaluations < 0:
        raise ValueError(
            "max_fitness_evaluations không được nhỏ hơn FE khởi tạo."
        )

    if remaining_fitness_evaluations % population_size != 0:
        raise ValueError(
            "Phần FE còn lại phải chia hết cho kích thước quần thể."
        )

    return remaining_fitness_evaluations // population_size


def _create_convergence_point(
    iteration: int,
    metrics: OptimizationMetrics,
    best_so_far: TimetableIndividual,
) -> ConvergencePoint:
    """Tạo mốc hội tụ từ fitness đã có mà không gọi lại Fitness."""

    fitness = best_so_far.fitness
    return ConvergencePoint(
        iteration=iteration,
        fitness_evaluations=metrics.fitness_evaluations,
        time_stability_score=fitness.time_stability_score,
        general_quality_score=fitness.general_quality_score,
        lecturer_preference_score=fitness.lecturer_preference_score,
    )


def _initial_metrics(
    initialization: PopulationInitializationResult,
) -> OptimizationMetrics:
    """Sao chép đầy đủ số liệu khởi tạo vào hợp đồng metrics dùng chung."""

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


def run_ga(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    initialization: PopulationInitializationResult,
    config: GAConfig,
) -> OptimizationResult:
    """Chạy Genetic Algorithm từ một quần thể ban đầu đã hợp lệ.

    Mỗi thế hệ xử lý đúng ``N`` vị trí offspring. Với từng vị trí, GA thử tối
    đa ``max_offspring_attempts`` vector và dừng tại vector hợp lệ đầu tiên.
    Một lần thử thất bại chỉ loại vector hiện tại; chỉ khi cả giới hạn của vị
    trí đã hết mới tăng ``discarded_offspring_count`` một lần.

    Vector con luôn được đánh giá qua ``population.evaluate_candidate`` và số
    liệu của từng lần gọi được cộng bằng ``accumulate_candidate_evaluation``.
    Không tạo fitness phạt giả, không sao chép cha thành con khi thất bại và
    không dừng toàn bộ run chỉ vì một thế hệ không tạo được offspring hợp lệ.
    """

    started_at = perf_counter()

    max_generations = _validate_ga_run_inputs(
        problem,
        option_domains,
        initialization,
        config,
    )

    # Giữ nguyên tuple khởi tạo ở thời điểm bắt đầu để mọi optimizer có thể sử
    # dụng cùng một quần thể đầu. Survivor selection chỉ thay tuple cục bộ.
    population = tuple(initialization.individuals)
    population_size = len(population)
    best_so_far = best_individual(population)

    metrics = _initial_metrics(initialization)
    convergence_history: list[ConvergencePoint] = [
        _create_convergence_point(
            iteration=0,
            metrics=metrics,
            best_so_far=best_so_far,
        )
    ]

    # GA có RNG riêng. Không cố đuổi kịp RNG của initialize_population vì bước
    # khởi tạo được thực hiện bên ngoài và có thể dùng quy trình sinh khác.
    rng = Random(config.seed)

    for generation in range(1, max_generations + 1):
        valid_offspring: list[TimetableIndividual] = []

        # Mỗi generation luôn duyệt đủ N vị trí, kể cả khi các vị trí trước đó
        # thất bại. Đây là khác biệt quan trọng với cách cũ giới hạn attempts
        # cho toàn bộ generation.
        for offspring_index in range(population_size):
            accepted_child: TimetableIndividual | None = None

            for attempt_number in range(
                1,
                config.max_offspring_attempts + 1,
            ):
                proposed_vector = _create_offspring_vector(
                    population=population,
                    config=config,
                    dimension=problem.dimension,
                    rng=rng,
                )

                evaluation = evaluate_candidate(
                    problem,
                    option_domains,
                    proposed_vector,
                    config.evaluation_config,
                )

                # Helper dùng chung chịu trách nhiệm cộng candidate attempt,
                # FE thực tế, decode/validation failure, repair và decoder cost.
                # Nếu evaluation bất ngờ là NO_OPTION, helper phát ValueError
                # ngay tại đây; không retry và không tính offspring bị bỏ.
                metrics = accumulate_candidate_evaluation(
                    metrics,
                    evaluation,
                )

                if evaluation.is_success:
                    if evaluation.individual is None:
                        raise RuntimeError(
                            "Evaluation SUCCESS nhưng không có individual."
                        )

                    accepted_child = evaluation.individual
                    break

            if accepted_child is not None:
                valid_offspring.append(accepted_child)
            else:
                # Chỉ một vị trí đã dùng hết toàn bộ số lần thử mới được tính
                # là một offspring bị bỏ; từng candidate thất bại không làm
                # tăng bộ đếm này.
                metrics = replace(
                    metrics,
                    discarded_offspring_count=(
                        metrics.discarded_offspring_count + 1
                    ),
                )

        # Cha luôn nằm trong survivor union. Nếu không có con hợp lệ, giữ nguyên
        # population cha thay vì coi thế hệ là STALLED hoặc INFEASIBLE.
        if valid_offspring:
            population = select_survivors(
                parents=population,
                offspring=tuple(valid_offspring),
                population_size=population_size,
            )

        generation_best = best_individual(population)
        if _individual_order_key(generation_best) < _individual_order_key(
            best_so_far
        ):
            best_so_far = generation_best

        metrics = replace(
            metrics,
            completed_iterations=generation,
        )

        convergence_history.append(
            _create_convergence_point(
                iteration=generation,
                metrics=metrics,
                best_so_far=best_so_far,
            )
        )

    final_metrics = replace(
        metrics,
        runtime_seconds=perf_counter() - started_at,
    )

    return OptimizationResult(
        algorithm=OptimizationAlgorithm.GA,
        best_individual=best_so_far,
        final_population=population,
        convergence_history=tuple(convergence_history),
        metrics=final_metrics,
    )
