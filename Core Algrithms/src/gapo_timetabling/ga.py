"""Genetic Algorithm cho bài toán xếp thời khóa biểu random-key.

Module này chỉ chịu trách nhiệm sinh vector mới bằng:
- tournament selection
- SBX crossover
- polynomial mutation
- survivor selection

Mọi vector mới vẫn phải đi qua pipeline chung trong population.py:
Decoder -> Repair -> Validator -> Fitness.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from random import Random

from .models import ProblemInstance, SessionOption
from .population import (
    CandidateEvaluationConfig,
    CandidateEvaluationStatus,
    PopulationInitializationResult,
    PopulationInitializationStatus,
    TimetableIndividual,
    best_individual,
    evaluate_candidate,
    initialize_population,
    sort_individuals,
)
from .repair import RepairStatus


class GAOptimizationStatus(str, Enum):
    """Trạng thái kết thúc của một lần chạy GA."""

    SUCCESS = "SUCCESS"
    NO_OPTION = "NO_OPTION"
    NO_FEASIBLE_SOLUTION_FOUND = "NO_FEASIBLE_SOLUTION_FOUND"
    STALLED = "STALLED"


@dataclass(frozen=True, slots=True)
class GAConfig:
    """Cấu hình của Genetic Algorithm."""

    population_size: int
    max_fitness_evaluations: int
    max_initialization_attempts: int
    max_offspring_attempts: int
    seed: int
    evaluation_config: CandidateEvaluationConfig

    tournament_size: int = 3
    crossover_probability: float = 0.9
    crossover_distribution_index: float = 15.0

    mutation_probability: float | None = None
    mutation_distribution_index: float = 20.0

    def __post_init__(self) -> None:
        """Kiểm tra cấu hình GA hợp lệ."""

        if self.population_size < 2:
            raise ValueError(
                "population_size phải lớn hơn hoặc bằng 2."
            )

        if self.max_fitness_evaluations < self.population_size:
            raise ValueError(
                "max_fitness_evaluations phải ít nhất bằng population_size."
            )

        if self.max_initialization_attempts < self.population_size:
            raise ValueError(
                "max_initialization_attempts phải ít nhất bằng population_size."
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

        if self.crossover_distribution_index <= 0:
            raise ValueError(
                "crossover_distribution_index phải dương."
            )

        if self.mutation_probability is not None:
            if not 0.0 <= self.mutation_probability <= 1.0:
                raise ValueError(
                    "mutation_probability phải nằm trong [0,1]."
                )

        if self.mutation_distribution_index <= 0:
            raise ValueError(
                "mutation_distribution_index phải dương."
            )

    def resolved_mutation_probability(
        self,
        dimension: int,
    ) -> float:
        """Nếu không cấu hình mutation probability thì dùng 1/D."""

        if dimension < 1:
            raise ValueError(
                "dimension phải lớn hơn hoặc bằng 1."
            )

        if self.mutation_probability is not None:
            return self.mutation_probability

        return 1.0 / dimension


@dataclass(frozen=True, slots=True)
class GAConvergencePoint:
    """Một điểm trên lịch sử hội tụ của GA."""

    fitness_evaluations: int
    generation: int
    best_fitness_key: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class GAOptimizationResult:
    """Kết quả cuối cùng của một lần chạy GA."""

    status: GAOptimizationStatus

    best_individual: TimetableIndividual | None

    final_population: tuple[TimetableIndividual, ...]

    initialization: PopulationInitializationResult

    convergence_history: tuple[GAConvergencePoint, ...]

    fitness_evaluations: int

    generations_completed: int

    offspring_attempts: int

    accepted_offspring: int

    decode_failed_count: int

    validation_failed_count: int

    repaired_individual_count: int

    failed_repair_count: int

    total_decode_nodes: int

    total_decode_backtracks: int

    reason: str

    @property
    def is_success(self) -> bool:
        """Cho biết GA đã kết thúc thành công hay chưa."""

        return self.status == GAOptimizationStatus.SUCCESS


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


def run_ga(
    problem: ProblemInstance,
    option_domains: tuple[
        tuple[SessionOption, ...],
        ...,
    ],
    config: GAConfig,
) -> GAOptimizationResult:
    """Chạy Genetic Algorithm cho một ProblemInstance đã cố định.

    Quy trình:
    1. Khởi tạo population hợp lệ.
    2. Chọn cha mẹ bằng tournament selection.
    3. SBX crossover.
    4. Polynomial mutation.
    5. Đánh giá offspring bằng evaluate_candidate().
    6. Survivor selection theo fitness lexicographic.
    7. Theo dõi best-so-far, FE và convergence history.

    FE chỉ tăng khi Fitness thực sự được gọi.
    """

    # ------------------------------------------------------------
    # 1. Khởi tạo quần thể
    # ------------------------------------------------------------

    initialization = initialize_population(
        problem=problem,
        option_domains=option_domains,
        population_size=config.population_size,
        max_initialization_attempts=(
            config.max_initialization_attempts
        ),
        seed=config.seed,
        evaluation_config=config.evaluation_config,
    )

    # ------------------------------------------------------------
    # 2. Nếu miền có session không có option thì dừng ngay
    # ------------------------------------------------------------

    if (
        initialization.status
        == PopulationInitializationStatus.NO_OPTION
    ):
        return GAOptimizationResult(
            status=GAOptimizationStatus.NO_OPTION,
            best_individual=None,
            final_population=initialization.individuals,
            initialization=initialization,
            convergence_history=(),
            fitness_evaluations=(
                initialization.fitness_evaluations
            ),
            generations_completed=0,
            offspring_attempts=0,
            accepted_offspring=0,
            decode_failed_count=(
                initialization.decode_failed_count
            ),
            validation_failed_count=(
                initialization.validation_failed_count
            ),
            repaired_individual_count=(
                initialization.repaired_individual_count
            ),
            failed_repair_count=(
                initialization.failed_repair_count
            ),
            total_decode_nodes=(
                initialization.total_decode_nodes
            ),
            total_decode_backtracks=(
                initialization.total_decode_backtracks
            ),
            reason=initialization.reason,
        )

    # ------------------------------------------------------------
    # 3. Nếu không tạo đủ population ban đầu thì GA không được chạy
    # ------------------------------------------------------------

    if (
        initialization.status
        != PopulationInitializationStatus.SUCCESS
    ):
        partial_best = None

        if initialization.individuals:
            partial_best = best_individual(
                initialization.individuals
            )

        return GAOptimizationResult(
            status=(
                GAOptimizationStatus
                .NO_FEASIBLE_SOLUTION_FOUND
            ),
            best_individual=partial_best,
            final_population=initialization.individuals,
            initialization=initialization,
            convergence_history=(),
            fitness_evaluations=(
                initialization.fitness_evaluations
            ),
            generations_completed=0,
            offspring_attempts=0,
            accepted_offspring=0,
            decode_failed_count=(
                initialization.decode_failed_count
            ),
            validation_failed_count=(
                initialization.validation_failed_count
            ),
            repaired_individual_count=(
                initialization.repaired_individual_count
            ),
            failed_repair_count=(
                initialization.failed_repair_count
            ),
            total_decode_nodes=(
                initialization.total_decode_nodes
            ),
            total_decode_backtracks=(
                initialization.total_decode_backtracks
            ),
            reason=initialization.reason,
        )

    # ------------------------------------------------------------
    # 4. Population ban đầu hợp lệ
    # ------------------------------------------------------------

    population = sort_individuals(
        initialization.individuals
    )

    best_so_far = best_individual(
        population
    )

    # ------------------------------------------------------------
    # 5. Khởi tạo bộ đếm
    # ------------------------------------------------------------

    fitness_evaluations = (
        initialization.fitness_evaluations
    )

    decode_failed_count = (
        initialization.decode_failed_count
    )

    validation_failed_count = (
        initialization.validation_failed_count
    )

    repaired_individual_count = (
        initialization.repaired_individual_count
    )

    failed_repair_count = (
        initialization.failed_repair_count
    )

    total_decode_nodes = (
        initialization.total_decode_nodes
    )

    total_decode_backtracks = (
        initialization.total_decode_backtracks
    )

    offspring_attempts = 0
    accepted_offspring = 0
    generations_completed = 0

    # ------------------------------------------------------------
    # 6. Lịch sử hội tụ
    # ------------------------------------------------------------

    convergence_history: list[
        GAConvergencePoint
    ] = [
        GAConvergencePoint(
            fitness_evaluations=fitness_evaluations,
            generation=0,
            best_fitness_key=(
                best_so_far.fitness_key
            ),
        )
    ]

    # ------------------------------------------------------------
    # 7. RNG
    # ------------------------------------------------------------

    rng = Random(config.seed)

    # initialize_population() đã dùng cùng seed để sinh các
    # random-key ban đầu.
    #
    # Ta tiến RNG của GA qua đúng số random number mà phần
    # initialization đã sử dụng để offspring tiếp tục một chuỗi
    # pseudo-random xác định thay vì khởi động lại từ đầu.
    initialization_random_values = (
        initialization.candidate_attempts
        * problem.dimension
    )

    for _ in range(
        initialization_random_values
    ):
        rng.random()

    # ------------------------------------------------------------
    # 8. Vòng lặp GA
    # ------------------------------------------------------------

    while (
        fitness_evaluations
        < config.max_fitness_evaluations
    ):

        offspring: list[
            TimetableIndividual
        ] = []

        attempts_this_generation = 0

        # --------------------------------------------------------
        # Sinh offspring
        # --------------------------------------------------------

        while (
            len(offspring)
            < config.population_size
            and attempts_this_generation
            < config.max_offspring_attempts
            and fitness_evaluations
            < config.max_fitness_evaluations
        ):

            offspring_vector = (
                _create_offspring_vector(
                    population=population,
                    config=config,
                    dimension=problem.dimension,
                    rng=rng,
                )
            )

            offspring_attempts += 1
            attempts_this_generation += 1

            # ----------------------------------------------------
            # Đánh giá offspring bằng pipeline CHUNG
            # ----------------------------------------------------

            evaluation = evaluate_candidate(
                problem=problem,
                option_domains=option_domains,
                vector=offspring_vector,
                config=config.evaluation_config,
            )

            # FE chỉ tăng nếu calculate_fitness()
            # thực sự đã chạy.
            fitness_evaluations += (
                evaluation.fitness_evaluations
            )

            total_decode_nodes += (
                evaluation.total_decode_nodes
            )

            total_decode_backtracks += (
                evaluation.total_decode_backtracks
            )

            # ----------------------------------------------------
            # Thống kê repair
            # ----------------------------------------------------

            if evaluation.repair_result is not None:

                if (
                    evaluation.repair_result.status
                    == RepairStatus.REPAIRED
                ):
                    repaired_individual_count += 1

                elif (
                    evaluation.repair_result.status
                    == RepairStatus.FAILED
                ):
                    failed_repair_count += 1

            # ----------------------------------------------------
            # NO_OPTION là lỗi miền đầu vào
            # ----------------------------------------------------

            if (
                evaluation.status
                == CandidateEvaluationStatus.NO_OPTION
            ):
                return GAOptimizationResult(
                    status=GAOptimizationStatus.NO_OPTION,
                    best_individual=best_so_far,
                    final_population=population,
                    initialization=initialization,
                    convergence_history=tuple(
                        convergence_history
                    ),
                    fitness_evaluations=fitness_evaluations,
                    generations_completed=(
                        generations_completed
                    ),
                    offspring_attempts=offspring_attempts,
                    accepted_offspring=accepted_offspring,
                    decode_failed_count=(
                        decode_failed_count
                    ),
                    validation_failed_count=(
                        validation_failed_count
                    ),
                    repaired_individual_count=(
                        repaired_individual_count
                    ),
                    failed_repair_count=(
                        failed_repair_count
                    ),
                    total_decode_nodes=(
                        total_decode_nodes
                    ),
                    total_decode_backtracks=(
                        total_decode_backtracks
                    ),
                    reason=evaluation.reason,
                )

            # ----------------------------------------------------
            # Decode fail
            # ----------------------------------------------------

            if (
                evaluation.status
                == CandidateEvaluationStatus.DECODE_FAILED
            ):
                decode_failed_count += 1

                # Không có fitness giả.
                # Không thêm vào offspring.
                continue

            # ----------------------------------------------------
            # Validation fail
            # ----------------------------------------------------

            if (
                evaluation.status
                == CandidateEvaluationStatus.VALIDATION_FAILED
            ):
                validation_failed_count += 1
                continue

            # ----------------------------------------------------
            # SUCCESS phải có individual
            # ----------------------------------------------------

            if evaluation.individual is None:
                raise RuntimeError(
                    "Evaluation SUCCESS nhưng không có "
                    "TimetableIndividual."
                )

            offspring.append(
                evaluation.individual
            )

            accepted_offspring += 1

        # --------------------------------------------------------
        # 9. Không sinh được offspring hợp lệ nào
        # --------------------------------------------------------

        if not offspring:

            # Nếu FE đã hết đúng lúc thì đây vẫn là kết thúc hợp lệ.
            if (
                fitness_evaluations
                >= config.max_fitness_evaluations
            ):
                break

            return GAOptimizationResult(
                status=GAOptimizationStatus.STALLED,
                best_individual=best_so_far,
                final_population=population,
                initialization=initialization,
                convergence_history=tuple(
                    convergence_history
                ),
                fitness_evaluations=fitness_evaluations,
                generations_completed=(
                    generations_completed
                ),
                offspring_attempts=offspring_attempts,
                accepted_offspring=accepted_offspring,
                decode_failed_count=(
                    decode_failed_count
                ),
                validation_failed_count=(
                    validation_failed_count
                ),
                repaired_individual_count=(
                    repaired_individual_count
                ),
                failed_repair_count=(
                    failed_repair_count
                ),
                total_decode_nodes=(
                    total_decode_nodes
                ),
                total_decode_backtracks=(
                    total_decode_backtracks
                ),
                reason=(
                    "Đã hết max_offspring_attempts "
                    "nhưng không tạo được offspring "
                    "hợp lệ trong thế hệ hiện tại."
                ),
            )

        # --------------------------------------------------------
        # 10. Survivor Selection
        # --------------------------------------------------------

        population = select_survivors(
            parents=population,
            offspring=tuple(offspring),
            population_size=config.population_size,
        )

        generations_completed += 1

        # --------------------------------------------------------
        # 11. Best của population hiện tại
        # --------------------------------------------------------

        generation_best = best_individual(
            population
        )

        # Best-so-far tuyệt đối không được xấu đi.
        if (
            _individual_order_key(
                generation_best
            )
            <
            _individual_order_key(
                best_so_far
            )
        ):
            best_so_far = generation_best

        # --------------------------------------------------------
        # 12. Lưu convergence history
        # --------------------------------------------------------

        convergence_history.append(
            GAConvergencePoint(
                fitness_evaluations=(
                    fitness_evaluations
                ),
                generation=(
                    generations_completed
                ),
                best_fitness_key=(
                    best_so_far.fitness_key
                ),
            )
        )

    # ------------------------------------------------------------
    # 13. Kết thúc do hết ngân sách FE
    # ------------------------------------------------------------

    return GAOptimizationResult(
        status=GAOptimizationStatus.SUCCESS,
        best_individual=best_so_far,
        final_population=population,
        initialization=initialization,
        convergence_history=tuple(
            convergence_history
        ),
        fitness_evaluations=fitness_evaluations,
        generations_completed=(
            generations_completed
        ),
        offspring_attempts=offspring_attempts,
        accepted_offspring=accepted_offspring,
        decode_failed_count=decode_failed_count,
        validation_failed_count=(
            validation_failed_count
        ),
        repaired_individual_count=(
            repaired_individual_count
        ),
        failed_repair_count=(
            failed_repair_count
        ),
        total_decode_nodes=(
            total_decode_nodes
        ),
        total_decode_backtracks=(
            total_decode_backtracks
        ),
        reason=(
            "GA kết thúc sau khi sử dụng hết "
            "ngân sách fitness evaluation."
        ),
    )