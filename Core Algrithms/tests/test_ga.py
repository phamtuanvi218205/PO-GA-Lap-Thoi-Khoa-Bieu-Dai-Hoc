"""Kiểm thử Genetic Algorithm theo hợp đồng optimizer dùng chung của project."""

import unittest
from dataclasses import FrozenInstanceError, replace
from math import nan
from random import Random
from unittest.mock import patch

import gapo_timetabling.ga as ga_module
from gapo_timetabling.constraints import validate_timetable
from gapo_timetabling.encoder import build_option_domains
from gapo_timetabling.ga import (
    GAConfig,
    _validate_ga_run_inputs,
    clamp_vector,
    polynomial_mutation,
    run_ga,
    select_survivors,
    simulated_binary_crossover,
    tournament_select,
)
from gapo_timetabling.metrics import OptimizationResult
from gapo_timetabling.models import OptimizationAlgorithm
from gapo_timetabling.population import (
    CandidateEvaluationConfig,
    CandidateEvaluationStatus,
    PopulationInitializationStatus,
    evaluate_candidate as population_evaluate_candidate,
    initialize_population,
)
from gapo_timetabling.repair import RepairResult, RepairStatus
from tests.test_constraints import ConstraintFixture


class _SequenceRandom:
    """RNG tối giản để ép tournament lấy đúng chuỗi chỉ số mong muốn."""

    def __init__(self, indices: tuple[int, ...]):
        self.indices = iter(indices)

    def randrange(self, stop: int) -> int:
        value = next(self.indices)
        if not 0 <= value < stop:
            raise ValueError("Chỉ số RNG fixture nằm ngoài quần thể.")
        return value


class TestGAConfig(unittest.TestCase):
    """Kiểm tra cấu hình GA độc lập với kích thước quần thể khởi tạo."""

    @staticmethod
    def make_evaluation_config() -> CandidateEvaluationConfig:
        return CandidateEvaluationConfig(
            max_decode_nodes=100,
            enable_repair=False,
            max_repair_attempts=0,
        )

    def test_valid_configuration_keeps_operator_parameters(self) -> None:
        config = GAConfig(
            max_fitness_evaluations=100,
            max_offspring_attempts=3,
            seed=2026,
            evaluation_config=self.make_evaluation_config(),
            tournament_size=4,
            crossover_probability=0.8,
            crossover_distribution_index=12.0,
            mutation_probability=0.2,
            mutation_distribution_index=18.0,
        )

        self.assertEqual(config.max_fitness_evaluations, 100)
        self.assertEqual(config.max_offspring_attempts, 3)
        self.assertEqual(config.tournament_size, 4)
        self.assertEqual(config.resolved_mutation_probability(5), 0.2)

    def test_invalid_configuration_is_rejected(self) -> None:
        base = GAConfig(
            max_fitness_evaluations=10,
            max_offspring_attempts=2,
            seed=1,
            evaluation_config=self.make_evaluation_config(),
        )

        for field_name, invalid_value in (
            ("max_fitness_evaluations", 0),
            ("max_offspring_attempts", 0),
            ("tournament_size", 1),
            ("crossover_probability", 1.1),
            ("crossover_distribution_index", 0.0),
            ("mutation_probability", -0.1),
            ("mutation_distribution_index", 0.0),
        ):
            with self.subTest(field_name=field_name):
                with self.assertRaises(ValueError):
                    replace(base, **{field_name: invalid_value})

    def test_configuration_is_immutable(self) -> None:
        config = GAConfig(
            max_fitness_evaluations=10,
            max_offspring_attempts=2,
            seed=1,
            evaluation_config=self.make_evaluation_config(),
        )

        with self.assertRaises(FrozenInstanceError):
            config.seed = 9


class TestGeneticAlgorithm(ConstraintFixture):
    """Bảo vệ toán tử GA, pipeline chung, metrics và ngân sách thực nghiệm."""

    def setUp(self) -> None:
        super().setUp()
        self.domains = build_option_domains(self.problem)
        self.evaluation_config = CandidateEvaluationConfig(
            max_decode_nodes=100,
            enable_repair=False,
            max_repair_attempts=0,
        )

    def make_initialization(
        self,
        population_size: int = 4,
        seed: int = 42,
    ):
        """Tạo quần thể SUCCESS bằng đúng pipeline thật của project."""

        result = initialize_population(
            self.problem,
            self.domains,
            population_size=population_size,
            max_initialization_attempts=40,
            seed=seed,
            evaluation_config=self.evaluation_config,
        )
        self.assertEqual(result.status, PopulationInitializationStatus.SUCCESS)
        return result

    def make_config(
        self,
        initialization,
        *,
        generations: int = 1,
        max_offspring_attempts: int = 1,
        seed: int = 2026,
        max_fitness_evaluations: int | None = None,
    ) -> GAConfig:
        """Tạo ngân sách lý thuyết bằng N FE cho mỗi thế hệ đầy đủ."""

        if max_fitness_evaluations is None:
            max_fitness_evaluations = (
                initialization.fitness_evaluations
                + generations * len(initialization.individuals)
            )

        return GAConfig(
            max_fitness_evaluations=max_fitness_evaluations,
            max_offspring_attempts=max_offspring_attempts,
            seed=seed,
            evaluation_config=self.evaluation_config,
        )

    def singleton_domains(self):
        """Tạo mỗi session đúng một option hợp lệ để tạo evaluation xác định."""

        return tuple((option,) for option in self.valid_options)

    def base_individual(self):
        """Tạo một cá thể hợp lệ làm fixture cho test selection."""

        evaluation = population_evaluate_candidate(
            self.problem,
            self.singleton_domains(),
            tuple(0.0 for _ in range(self.problem.dimension)),
            CandidateEvaluationConfig(
                max_decode_nodes=20,
                enable_repair=False,
                max_repair_attempts=0,
            ),
        )
        self.assertTrue(evaluation.is_success)
        self.assertIsNotNone(evaluation.individual)
        return evaluation.individual

    def successful_evaluation(self):
        """Tạo evaluation SUCCESS có đúng một FE."""

        evaluation = population_evaluate_candidate(
            self.problem,
            self.singleton_domains(),
            tuple(0.0 for _ in range(self.problem.dimension)),
            CandidateEvaluationConfig(
                max_decode_nodes=20,
                enable_repair=False,
                max_repair_attempts=0,
            ),
        )
        self.assertTrue(evaluation.is_success)
        self.assertEqual(evaluation.fitness_evaluations, 1)
        return evaluation

    def decode_failed_evaluation(self):
        """Tạo evaluation DECODE_FAILED không có fitness giả."""

        evaluation = population_evaluate_candidate(
            self.problem,
            self.singleton_domains(),
            tuple(0.0 for _ in range(self.problem.dimension)),
            CandidateEvaluationConfig(
                max_decode_nodes=1,
                enable_repair=False,
                max_repair_attempts=0,
            ),
        )
        self.assertEqual(
            evaluation.status,
            CandidateEvaluationStatus.DECODE_FAILED,
        )
        self.assertEqual(evaluation.fitness_evaluations, 0)
        return evaluation

    def validation_failed_evaluation(self):
        """Tạo fixture VALIDATION_FAILED để kiểm tra counter dùng chung."""

        return replace(
            self.decode_failed_evaluation(),
            status=CandidateEvaluationStatus.VALIDATION_FAILED,
            reason="Fixture validation failure.",
        )

    def no_option_evaluation(self):
        """Tạo NO_OPTION thật để kiểm tra lỗi dữ liệu đầu vào giữa run."""

        domains = list(self.domains)
        domains[0] = ()
        evaluation = population_evaluate_candidate(
            self.problem,
            tuple(domains),
            tuple(0.5 for _ in range(self.problem.dimension)),
            self.evaluation_config,
        )
        self.assertEqual(evaluation.status, CandidateEvaluationStatus.NO_OPTION)
        return evaluation

    # ------------------------------------------------------------------
    # Các toán tử GA đã đúng từ phiên bản trước và phải tiếp tục được giữ.
    # ------------------------------------------------------------------

    def test_boundary_helper_clamps_without_changing_dimension(self) -> None:
        vector = (-0.4, 0.2, 1.4, 0.8)
        clamped = clamp_vector(vector)

        self.assertEqual(clamped, (0.0, 0.2, 1.0, 0.8))
        self.assertEqual(len(clamped), len(vector))

    def test_crossover_and_mutation_keep_vector_dimension_and_boundary(self) -> None:
        first = (0.1, 0.2, 0.3, 0.4)
        second = (0.9, 0.8, 0.7, 0.6)
        rng = Random(12)

        child_a, child_b = simulated_binary_crossover(
            first,
            second,
            crossover_probability=1.0,
            distribution_index=15.0,
            rng=rng,
        )
        mutated = polynomial_mutation(
            child_a,
            mutation_probability=1.0,
            distribution_index=20.0,
            rng=rng,
        )

        self.assertEqual(len(child_a), len(first))
        self.assertEqual(len(child_b), len(first))
        self.assertEqual(len(mutated), len(first))
        self.assertTrue(all(0.0 <= gene <= 1.0 for gene in child_a))
        self.assertTrue(all(0.0 <= gene <= 1.0 for gene in child_b))
        self.assertTrue(all(0.0 <= gene <= 1.0 for gene in mutated))

    def test_operators_do_not_modify_parent_vectors(self) -> None:
        first = (0.1, 0.2, 0.3, 0.4)
        second = (0.9, 0.8, 0.7, 0.6)
        original_first = tuple(first)
        original_second = tuple(second)

        simulated_binary_crossover(first, second, 1.0, 15.0, Random(1))
        polynomial_mutation(first, 1.0, 20.0, Random(2))

        self.assertEqual(first, original_first)
        self.assertEqual(second, original_second)

    def test_tournament_selection_uses_lexicographic_gate_f_order(self) -> None:
        base = self.base_individual()
        better = replace(
            base,
            vector=(0.9,) * self.problem.dimension,
            fitness=replace(
                base.fitness,
                time_stability_score=0.0,
                general_quality_score=100.0,
                lecturer_preference_score=100.0,
            ),
        )
        worse = replace(
            base,
            vector=(0.1,) * self.problem.dimension,
            fitness=replace(
                base.fitness,
                time_stability_score=0.01,
                general_quality_score=0.0,
                lecturer_preference_score=0.0,
            ),
        )

        winner = tournament_select(
            (worse, better),
            tournament_size=2,
            rng=_SequenceRandom((0, 1)),
        )
        self.assertIs(winner, better)

    def test_survivor_selection_keeps_elite_parent(self) -> None:
        base = self.base_individual()
        elite = replace(
            base,
            vector=(0.1,) * self.problem.dimension,
            fitness=replace(
                base.fitness,
                time_stability_score=0.0,
                general_quality_score=0.0,
                lecturer_preference_score=0.0,
            ),
        )
        worse = replace(
            base,
            vector=(0.9,) * self.problem.dimension,
            fitness=replace(
                base.fitness,
                time_stability_score=1.0,
                general_quality_score=1.0,
                lecturer_preference_score=1.0,
            ),
        )

        survivors = select_survivors(
            parents=(elite, worse),
            offspring=(worse, worse),
            population_size=2,
        )

        self.assertIn(elite, survivors)
        self.assertIs(survivors[0], elite)

    # ------------------------------------------------------------------
    # Input validation và ngân sách thế hệ đầy đủ.
    # ------------------------------------------------------------------

    def test_run_requires_successful_complete_initialization(self) -> None:
        initialization = self.make_initialization(population_size=2)
        config = self.make_config(initialization)

        with self.assertRaisesRegex(ValueError, "SUCCESS"):
            _validate_ga_run_inputs(
                self.problem,
                self.domains,
                replace(
                    initialization,
                    status=PopulationInitializationStatus.NO_FEASIBLE_SOLUTION_FOUND,
                ),
                config,
            )

        with self.assertRaisesRegex(ValueError, "không được rỗng"):
            _validate_ga_run_inputs(
                self.problem,
                self.domains,
                replace(
                    initialization,
                    individuals=(),
                    requested_population_size=0,
                    fitness_evaluations=0,
                ),
                config,
            )

    def test_run_validates_population_counters_vectors_and_domains(self) -> None:
        initialization = self.make_initialization(population_size=2)
        config = self.make_config(initialization)

        with self.assertRaisesRegex(ValueError, "requested_population_size"):
            _validate_ga_run_inputs(
                self.problem,
                self.domains,
                replace(initialization, requested_population_size=3),
                config,
            )

        with self.assertRaisesRegex(ValueError, "FE khởi tạo"):
            _validate_ga_run_inputs(
                self.problem,
                self.domains,
                replace(initialization, fitness_evaluations=1),
                config,
            )

        with self.assertRaisesRegex(ValueError, "candidate attempts"):
            _validate_ga_run_inputs(
                self.problem,
                self.domains,
                replace(initialization, candidate_attempts=1),
                config,
            )

        invalid_individual = replace(
            initialization.individuals[0],
            vector=initialization.individuals[0].vector[:-1],
        )
        with self.assertRaisesRegex(ValueError, "đúng .* gene"):
            _validate_ga_run_inputs(
                self.problem,
                self.domains,
                replace(
                    initialization,
                    individuals=(invalid_individual, initialization.individuals[1]),
                ),
                config,
            )

        non_finite_individual = replace(
            initialization.individuals[0],
            vector=(nan,) + initialization.individuals[0].vector[1:],
        )
        with self.assertRaisesRegex(ValueError, "hữu hạn"):
            _validate_ga_run_inputs(
                self.problem,
                self.domains,
                replace(
                    initialization,
                    individuals=(non_finite_individual, initialization.individuals[1]),
                ),
                config,
            )

        outside_individual = replace(
            initialization.individuals[0],
            vector=(1.1,) + initialization.individuals[0].vector[1:],
        )
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            _validate_ga_run_inputs(
                self.problem,
                self.domains,
                replace(
                    initialization,
                    individuals=(outside_individual, initialization.individuals[1]),
                ),
                config,
            )

        with self.assertRaisesRegex(ValueError, "Số miền option"):
            _validate_ga_run_inputs(
                self.problem,
                self.domains[:-1],
                initialization,
                config,
            )

    def test_budget_must_cover_initialization_and_full_generations(self) -> None:
        initialization = self.make_initialization(population_size=4)

        with self.assertRaisesRegex(ValueError, "chia hết"):
            run_ga(
                self.problem,
                self.domains,
                initialization,
                self.make_config(
                    initialization,
                    max_fitness_evaluations=(
                        initialization.fitness_evaluations + 5
                    ),
                ),
            )

        with self.assertRaisesRegex(ValueError, "không được nhỏ hơn"):
            run_ga(
                self.problem,
                self.domains,
                initialization,
                self.make_config(
                    initialization,
                    max_fitness_evaluations=(
                        initialization.fitness_evaluations - 1
                    ),
                ),
            )

    # ------------------------------------------------------------------
    # Yêu cầu mới: max_offspring_attempts áp dụng cho từng vị trí offspring.
    # ------------------------------------------------------------------

    def test_one_attempt_is_applied_to_each_offspring_position(self) -> None:
        """N=4 và một generation phải đánh giá bốn offspring, không phải bốn generation."""

        initialization = self.make_initialization(population_size=4)
        success = self.successful_evaluation()
        config = self.make_config(
            initialization,
            generations=1,
            max_offspring_attempts=1,
        )

        with patch(
            "gapo_timetabling.ga.evaluate_candidate",
            return_value=success,
        ) as evaluation_mock:
            result = run_ga(
                self.problem,
                self.domains,
                initialization,
                config,
            )

        self.assertEqual(result.metrics.completed_iterations, 1)
        self.assertEqual(evaluation_mock.call_count, 4)
        self.assertEqual(
            result.metrics.fitness_evaluations,
            initialization.fitness_evaluations + 4,
        )
        self.assertEqual(result.metrics.discarded_offspring_count, 0)

    def test_all_retries_fail_for_every_position_but_parents_survive(self) -> None:
        """N=4, ba retry mỗi vị trí phải tạo 12 candidate attempts và bốn discard."""

        initialization = self.make_initialization(population_size=4)
        failed = self.decode_failed_evaluation()
        config = self.make_config(
            initialization,
            generations=1,
            max_offspring_attempts=3,
        )

        with patch(
            "gapo_timetabling.ga.evaluate_candidate",
            return_value=failed,
        ) as evaluation_mock:
            result = run_ga(
                self.problem,
                self.domains,
                initialization,
                config,
            )

        self.assertEqual(evaluation_mock.call_count, 12)
        self.assertEqual(
            result.metrics.candidate_attempts,
            initialization.candidate_attempts + 12,
        )
        self.assertEqual(result.metrics.discarded_offspring_count, 4)
        self.assertEqual(
            result.metrics.fitness_evaluations,
            initialization.fitness_evaluations,
        )
        self.assertEqual(result.final_population, initialization.individuals)
        self.assertEqual(result.metrics.completed_iterations, 1)
        self.assertEqual(
            result.convergence_history[-1].fitness_evaluations,
            result.convergence_history[0].fitness_evaluations,
        )

    def test_failed_attempts_then_success_are_counted_for_one_position(self) -> None:
        """Decode fail và validation fail được retry trước khi nhận offspring SUCCESS."""

        initialization = self.make_initialization(population_size=2)
        decode_failed = self.decode_failed_evaluation()
        validation_failed = self.validation_failed_evaluation()
        success = self.successful_evaluation()
        config = self.make_config(
            initialization,
            generations=1,
            max_offspring_attempts=3,
        )

        with patch(
            "gapo_timetabling.ga.evaluate_candidate",
            side_effect=(decode_failed, validation_failed, success, success),
        ):
            result = run_ga(
                self.problem,
                self.domains,
                initialization,
                config,
            )

        self.assertEqual(
            result.metrics.candidate_attempts,
            initialization.candidate_attempts + 4,
        )
        self.assertEqual(
            result.metrics.fitness_evaluations,
            initialization.fitness_evaluations + 2,
        )
        self.assertEqual(
            result.metrics.decode_failed_count,
            initialization.decode_failed_count + 1,
        )
        self.assertEqual(
            result.metrics.validation_failed_count,
            initialization.validation_failed_count + 1,
        )
        self.assertEqual(result.metrics.discarded_offspring_count, 0)

    # ------------------------------------------------------------------
    # Result và metrics dùng chung giữa GA, PO và GA–PO.
    # ------------------------------------------------------------------

    def test_run_returns_common_optimization_result_for_ga(self) -> None:
        initialization = self.make_initialization(population_size=4)
        result = run_ga(
            self.problem,
            self.domains,
            initialization,
            self.make_config(initialization),
        )

        self.assertIsInstance(result, OptimizationResult)
        self.assertEqual(result.algorithm, OptimizationAlgorithm.GA)
        self.assertFalse(hasattr(ga_module, "GAOptimizationResult"))
        self.assertFalse(hasattr(ga_module, "GAConvergencePoint"))

    def test_metrics_include_initialization_and_offspring_repair_costs(self) -> None:
        """Metrics phải cộng init, repair thực tế, lỗi và discard bằng helper chung."""

        initialization = self.make_initialization(population_size=2)
        success = self.successful_evaluation()
        failed = self.decode_failed_evaluation()

        repaired_result = RepairResult(
            status=RepairStatus.REPAIRED,
            decode_result=success.final_decode_result,
            attempts=2,
            total_nodes_explored=3,
            total_backtracks=1,
            changed_session_index=0,
            requested_option_index=0,
            reason="Fixture repaired.",
        )
        repaired_success = replace(
            success,
            repair_result=repaired_result,
        )

        failed_repair_result = RepairResult(
            status=RepairStatus.FAILED,
            decode_result=failed.final_decode_result,
            attempts=3,
            total_nodes_explored=4,
            total_backtracks=2,
            changed_session_index=0,
            requested_option_index=0,
            reason="Fixture failed repair.",
        )
        failed_with_repair = replace(
            failed,
            repair_result=failed_repair_result,
        )

        config = self.make_config(
            initialization,
            generations=1,
            max_offspring_attempts=1,
        )

        with patch(
            "gapo_timetabling.ga.evaluate_candidate",
            side_effect=(repaired_success, failed_with_repair),
        ):
            result = run_ga(
                self.problem,
                self.domains,
                initialization,
                config,
            )

        metrics = result.metrics
        self.assertEqual(metrics.completed_iterations, 1)
        self.assertEqual(
            metrics.candidate_attempts,
            initialization.candidate_attempts + 2,
        )
        self.assertEqual(
            metrics.fitness_evaluations,
            initialization.fitness_evaluations + 1,
        )
        self.assertEqual(
            metrics.decode_failed_count,
            initialization.decode_failed_count + 1,
        )
        self.assertEqual(
            metrics.validation_failed_count,
            initialization.validation_failed_count,
        )
        self.assertEqual(
            metrics.repaired_individual_count,
            initialization.repaired_individual_count + 1,
        )
        self.assertEqual(
            metrics.failed_repair_count,
            initialization.failed_repair_count + 1,
        )
        self.assertEqual(
            metrics.total_repair_attempts,
            initialization.total_repair_attempts + 5,
        )
        self.assertEqual(metrics.discarded_offspring_count, 1)
        self.assertGreaterEqual(
            metrics.total_decode_nodes,
            initialization.total_decode_nodes,
        )
        self.assertGreaterEqual(
            metrics.total_decode_backtracks,
            initialization.total_decode_backtracks,
        )
        self.assertGreaterEqual(metrics.runtime_seconds, 0.0)

    def test_convergence_starts_at_zero_and_best_so_far_never_worsens(self) -> None:
        initialization = self.make_initialization(population_size=4)
        result = run_ga(
            self.problem,
            self.domains,
            initialization,
            self.make_config(initialization, generations=2),
        )

        history = result.convergence_history
        self.assertEqual(history[0].iteration, 0)
        self.assertEqual(
            tuple(point.iteration for point in history),
            (0, 1, 2),
        )
        self.assertTrue(
            all(
                next_point.fitness_evaluations >= current.fitness_evaluations
                for current, next_point in zip(history, history[1:])
            )
        )
        self.assertTrue(
            all(
                next_point.fitness_key <= current.fitness_key
                for current, next_point in zip(history, history[1:])
            )
        )

    def test_same_seed_recreates_all_deterministic_outputs(self) -> None:
        initialization = self.make_initialization(population_size=4)
        config = self.make_config(initialization, generations=2, seed=73)

        first = run_ga(self.problem, self.domains, initialization, config)
        second = run_ga(self.problem, self.domains, initialization, config)

        self.assertEqual(first.best_individual, second.best_individual)
        self.assertEqual(first.final_population, second.final_population)
        self.assertEqual(first.convergence_history, second.convergence_history)
        self.assertEqual(
            replace(first.metrics, runtime_seconds=0.0),
            replace(second.metrics, runtime_seconds=0.0),
        )

    def test_every_offspring_attempt_uses_population_evaluation_pipeline(self) -> None:
        initialization = self.make_initialization(population_size=4)
        config = self.make_config(
            initialization,
            generations=1,
            max_offspring_attempts=1,
        )

        with patch(
            "gapo_timetabling.ga.evaluate_candidate",
            wraps=population_evaluate_candidate,
        ) as shared_pipeline:
            run_ga(self.problem, self.domains, initialization, config)

        self.assertEqual(shared_pipeline.call_count, 4)

    def test_run_does_not_modify_problem_domains_initialization_or_parents(self) -> None:
        initialization = self.make_initialization(population_size=4)
        original_problem = self.problem
        original_domains = self.domains
        original_initialization = initialization
        original_individuals = initialization.individuals
        original_vectors = tuple(
            individual.vector for individual in initialization.individuals
        )

        run_ga(
            self.problem,
            self.domains,
            initialization,
            self.make_config(initialization, generations=2),
        )

        self.assertIs(self.problem, original_problem)
        self.assertIs(self.domains, original_domains)
        self.assertIs(initialization, original_initialization)
        self.assertEqual(initialization.individuals, original_individuals)
        self.assertEqual(
            tuple(individual.vector for individual in initialization.individuals),
            original_vectors,
        )

    def test_actual_fe_never_exceeds_configured_upper_bound(self) -> None:
        initialization = self.make_initialization(population_size=4)
        config = self.make_config(
            initialization,
            generations=3,
            max_offspring_attempts=3,
        )
        result = run_ga(self.problem, self.domains, initialization, config)

        self.assertLessEqual(
            result.metrics.fitness_evaluations,
            config.max_fitness_evaluations,
        )
        self.assertEqual(result.metrics.completed_iterations, 3)

    def test_unexpected_no_option_stops_without_retry(self) -> None:
        initialization = self.make_initialization(population_size=4)
        no_option = self.no_option_evaluation()
        config = self.make_config(
            initialization,
            generations=1,
            max_offspring_attempts=3,
        )

        with patch(
            "gapo_timetabling.ga.evaluate_candidate",
            return_value=no_option,
        ) as evaluation_mock:
            with self.assertRaisesRegex(ValueError, "NO_OPTION"):
                run_ga(
                    self.problem,
                    self.domains,
                    initialization,
                    config,
                )

        self.assertEqual(evaluation_mock.call_count, 1)

    def test_final_best_solution_passes_independent_validator(self) -> None:
        initialization = self.make_initialization(population_size=4)
        result = run_ga(
            self.problem,
            self.domains,
            initialization,
            self.make_config(initialization, generations=2),
        )

        validation = validate_timetable(
            self.problem,
            result.best_individual.selected_options,
        )
        self.assertTrue(validation.is_valid)


if __name__ == "__main__":
    unittest.main()
