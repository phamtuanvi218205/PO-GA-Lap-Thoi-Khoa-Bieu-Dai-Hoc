"""Kiểm thử Genetic Algorithm timetable trên pipeline population dùng chung."""

import unittest
from dataclasses import replace
from random import Random
from unittest.mock import patch

from gapo_timetabling.constraints import validate_timetable
from gapo_timetabling.encoder import build_option_domains
from gapo_timetabling.ga import (
    GAConfig,
    GAOptimizationStatus,
    clamp_vector,
    polynomial_mutation,
    run_ga,
    select_survivors,
    simulated_binary_crossover,
    tournament_select,
)
from gapo_timetabling.population import (
    CandidateEvaluationConfig,
    CandidateEvaluationStatus,
    evaluate_candidate as population_evaluate_candidate,
    initialize_population,
)
from tests.test_constraints import ConstraintFixture


class _SequenceRandom:
    """RNG tối giản để ép tournament lấy đúng chuỗi chỉ số mong muốn."""

    def __init__(self, indices: tuple[int, ...]):
        self.indices = iter(indices)

    def randrange(self, stop: int) -> int:
        value = next(self.indices)

        if not 0 <= value < stop:
            raise ValueError(
                "Chỉ số RNG fixture nằm ngoài quần thể."
            )

        return value


class TestGeneticAlgorithm(ConstraintFixture):
    """Bảo vệ các hợp đồng GA đã chốt trong prompt và ProjectContext."""

    def setUp(self) -> None:
        super().setUp()

        self.domains = build_option_domains(
            self.problem
        )

        self.evaluation_config = CandidateEvaluationConfig(
            max_decode_nodes=100,
            enable_repair=False,
            max_repair_attempts=0,
        )

    def make_config(
        self,
        *,
        seed: int = 2026,
        max_fitness_evaluations: int = 12,
        max_offspring_attempts: int = 20,
    ) -> GAConfig:
        """Tạo cấu hình GA nhỏ dùng chung cho các test."""

        return GAConfig(
            population_size=4,
            max_fitness_evaluations=max_fitness_evaluations,
            max_initialization_attempts=20,
            max_offspring_attempts=max_offspring_attempts,
            seed=seed,
            evaluation_config=self.evaluation_config,
        )

    def singleton_domains(
        self,
    ):
        """Tạo mỗi session đúng một option hợp lệ."""

        return tuple(
            (option,)
            for option in self.valid_options
        )

    def base_individual(
        self,
    ):
        """Tạo một cá thể hợp lệ làm fixture cho test selection."""

        result = population_evaluate_candidate(
            self.problem,
            self.singleton_domains(),
            (0.0, 0.0, 0.0, 0.0),
            CandidateEvaluationConfig(
                max_decode_nodes=20,
                enable_repair=False,
                max_repair_attempts=0,
            ),
        )

        self.assertEqual(
            result.status,
            CandidateEvaluationStatus.SUCCESS,
        )

        self.assertIsNotNone(
            result.individual
        )

        return result.individual

    def failed_evaluation(
        self,
    ):
        """Tạo một kết quả decode fail không có fitness."""

        result = population_evaluate_candidate(
            self.problem,
            self.singleton_domains(),
            (0.0, 0.0, 0.0, 0.0),
            CandidateEvaluationConfig(
                max_decode_nodes=1,
                enable_repair=False,
                max_repair_attempts=0,
            ),
        )

        self.assertEqual(
            result.status,
            CandidateEvaluationStatus.DECODE_FAILED,
        )

        self.assertEqual(
            result.fitness_evaluations,
            0,
        )

        return result

    def successful_evaluation(
        self,
    ):
        """Tạo một evaluation thành công có đúng một FE."""

        return population_evaluate_candidate(
            self.problem,
            self.singleton_domains(),
            (0.0, 0.0, 0.0, 0.0),
            CandidateEvaluationConfig(
                max_decode_nodes=20,
                enable_repair=False,
                max_repair_attempts=0,
            ),
        )

    # ------------------------------------------------------------
    # 1. Cùng seed phải cho cùng kết quả
    # ------------------------------------------------------------

    def test_same_seed_recreates_same_ga_result(
        self,
    ) -> None:

        first = run_ga(
            self.problem,
            self.domains,
            self.make_config(seed=73),
        )

        second = run_ga(
            self.problem,
            self.domains,
            self.make_config(seed=73),
        )

        self.assertEqual(
            first,
            second,
        )

        self.assertEqual(
            first.status,
            GAOptimizationStatus.SUCCESS,
        )

    # ------------------------------------------------------------
    # 2. Gene luôn nằm trong [0,1]
    # ------------------------------------------------------------

    def test_all_genes_remain_inside_random_key_boundary(
        self,
    ) -> None:

        result = run_ga(
            self.problem,
            self.domains,
            self.make_config(),
        )

        self.assertTrue(
            result.final_population
        )

        for individual in result.final_population:

            self.assertTrue(
                all(
                    0.0 <= gene <= 1.0
                    for gene in individual.vector
                )
            )

    # ------------------------------------------------------------
    # 3. Crossover và mutation không đổi dimension
    # ------------------------------------------------------------

    def test_crossover_and_mutation_keep_vector_dimension(
        self,
    ) -> None:

        first = (
            0.1,
            0.2,
            0.3,
            0.4,
        )

        second = (
            0.9,
            0.8,
            0.7,
            0.6,
        )

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

        self.assertEqual(
            len(child_a),
            len(first),
        )

        self.assertEqual(
            len(child_b),
            len(first),
        )

        self.assertEqual(
            len(mutated),
            len(first),
        )

    # ------------------------------------------------------------
    # 4. Không sửa vector cha
    # ------------------------------------------------------------

    def test_operators_do_not_modify_parent_vectors(
        self,
    ) -> None:

        first = (
            0.1,
            0.2,
            0.3,
            0.4,
        )

        second = (
            0.9,
            0.8,
            0.7,
            0.6,
        )

        original_first = tuple(
            first
        )

        original_second = tuple(
            second
        )

        simulated_binary_crossover(
            first,
            second,
            1.0,
            15.0,
            Random(1),
        )

        polynomial_mutation(
            first,
            1.0,
            20.0,
            Random(2),
        )

        self.assertEqual(
            first,
            original_first,
        )

        self.assertEqual(
            second,
            original_second,
        )

    # ------------------------------------------------------------
    # 5. Không sửa ProblemInstance
    # ------------------------------------------------------------

    def test_run_ga_does_not_modify_problem_instance(
        self,
    ) -> None:

        original_problem = (
            self.problem
        )

        original_sessions = (
            self.problem.class_sessions
        )

        original_parts = (
            self.problem.teaching_parts
        )

        run_ga(
            self.problem,
            self.domains,
            self.make_config(),
        )

        self.assertIs(
            self.problem,
            original_problem,
        )

        self.assertEqual(
            self.problem.class_sessions,
            original_sessions,
        )

        self.assertEqual(
            self.problem.teaching_parts,
            original_parts,
        )

    # ------------------------------------------------------------
    # 6. Tournament ưu tiên fitness tốt hơn
    # ------------------------------------------------------------

    def test_tournament_selection_prefers_better_lexicographic_fitness(
        self,
    ) -> None:

        base = self.base_individual()

        better = replace(
            base,
            vector=(
                0.9,
                0.9,
                0.9,
                0.9,
            ),
            fitness=replace(
                base.fitness,
                time_stability_score=0.0,
                general_quality_score=10.0,
                lecturer_preference_score=10.0,
            ),
        )

        worse = replace(
            base,
            vector=(
                0.1,
                0.1,
                0.1,
                0.1,
            ),
            fitness=replace(
                base.fitness,
                time_stability_score=0.1,
                general_quality_score=0.0,
                lecturer_preference_score=0.0,
            ),
        )

        winner = tournament_select(
            (
                worse,
                better,
            ),
            tournament_size=2,
            rng=_SequenceRandom(
                (
                    0,
                    1,
                )
            ),
        )

        self.assertIs(
            winner,
            better,
        )

    # ------------------------------------------------------------
    # 7. Tầng thấp không được lấn át tầng cao
    # ------------------------------------------------------------

    def test_lower_fitness_tier_cannot_override_higher_tier(
        self,
    ) -> None:

        base = self.base_individual()

        high_priority_better = replace(
            base,
            vector=(
                0.8,
                0.8,
                0.8,
                0.8,
            ),
            fitness=replace(
                base.fitness,
                time_stability_score=0.0,
                general_quality_score=100.0,
                lecturer_preference_score=100.0,
            ),
        )

        low_priority_better = replace(
            base,
            vector=(
                0.2,
                0.2,
                0.2,
                0.2,
            ),
            fitness=replace(
                base.fitness,
                time_stability_score=0.01,
                general_quality_score=0.0,
                lecturer_preference_score=0.0,
            ),
        )

        survivors = select_survivors(
            (
                low_priority_better,
                high_priority_better,
            ),
            (),
            population_size=1,
        )

        self.assertIs(
            survivors[0],
            high_priority_better,
        )

    # ------------------------------------------------------------
    # 8. Offspring decode fail không có fitness giả
    # ------------------------------------------------------------

    def test_failed_offspring_has_no_fake_fitness(
        self,
    ) -> None:

        failed = self.failed_evaluation()

        config = self.make_config(
            max_fitness_evaluations=8,
            max_offspring_attempts=3,
        )

        with patch(
            "gapo_timetabling.ga.evaluate_candidate",
            return_value=failed,
        ):
            result = run_ga(
                self.problem,
                self.domains,
                config,
            )

        self.assertEqual(
            result.status,
            GAOptimizationStatus.STALLED,
        )

        self.assertEqual(
            result.fitness_evaluations,
            config.population_size,
        )

        self.assertEqual(
            result.accepted_offspring,
            0,
        )

        self.assertEqual(
            result.decode_failed_count,
            3,
        )

    # ------------------------------------------------------------
    # 9. Offspring lỗi không làm mất parent tốt
    # ------------------------------------------------------------

        # ------------------------------------------------------------
    # 9. Offspring lỗi không làm mất parent tốt
    # ------------------------------------------------------------

    def test_failed_offspring_does_not_remove_good_parents(
        self,
    ) -> None:

        config = self.make_config(
            max_fitness_evaluations=8,
            max_offspring_attempts=2,
        )

        expected_initialization = initialize_population(
            self.problem,
            self.domains,
            config.population_size,
            config.max_initialization_attempts,
            config.seed,
            config.evaluation_config,
        )

        failed = self.failed_evaluation()

        with patch(
            "gapo_timetabling.ga.evaluate_candidate",
            return_value=failed,
        ):
            result = run_ga(
                self.problem,
                self.domains,
                config,
            )

        expected_population = tuple(
            sorted(
                expected_initialization.individuals,
                key=lambda item: (
                    item.fitness_key,
                    item.vector,
                ),
            )
        )

        self.assertEqual(
            result.final_population,
            expected_population,
        )

        self.assertEqual(
            result.best_individual,
            expected_population[0],
        )

    # ------------------------------------------------------------
    # 10. FE chỉ tăng khi Fitness chạy
    # ------------------------------------------------------------

    def test_fe_increases_only_for_successful_fitness_evaluation(
        self,
    ) -> None:

        failed = self.failed_evaluation()

        success = self.successful_evaluation()

        config = self.make_config(
            max_fitness_evaluations=5,
            max_offspring_attempts=4,
        )

        with patch(
            "gapo_timetabling.ga.evaluate_candidate",
            side_effect=(
                failed,
                success,
            ),
        ):
            result = run_ga(
                self.problem,
                self.domains,
                config,
            )

        self.assertEqual(
            result.fitness_evaluations,
            5,
        )

        self.assertEqual(
            result.offspring_attempts,
            2,
        )

        self.assertEqual(
            result.accepted_offspring,
            1,
        )

        self.assertEqual(
            result.decode_failed_count,
            1,
        )

    # ------------------------------------------------------------
    # 11. Không vượt ngân sách FE
    # ------------------------------------------------------------

    def test_ga_never_exceeds_fe_budget(
        self,
    ) -> None:

        config = self.make_config(
            max_fitness_evaluations=7
        )

        result = run_ga(
            self.problem,
            self.domains,
            config,
        )

        self.assertEqual(
            result.status,
            GAOptimizationStatus.SUCCESS,
        )

        self.assertEqual(
            result.fitness_evaluations,
            7,
        )

        self.assertLessEqual(
            result.fitness_evaluations,
            config.max_fitness_evaluations,
        )

    # ------------------------------------------------------------
    # 12. Elitism giữ nghiệm tốt nhất
    # ------------------------------------------------------------

    def test_survivor_selection_keeps_elite_parent(
        self,
    ) -> None:

        base = self.base_individual()

        elite = replace(
            base,
            vector=(
                0.1,
                0.1,
                0.1,
                0.1,
            ),
            fitness=replace(
                base.fitness,
                time_stability_score=0.0,
                general_quality_score=0.0,
                lecturer_preference_score=0.0,
            ),
        )

        worse = replace(
            base,
            vector=(
                0.9,
                0.9,
                0.9,
                0.9,
            ),
            fitness=replace(
                base.fitness,
                time_stability_score=1.0,
                general_quality_score=1.0,
                lecturer_preference_score=1.0,
            ),
        )

        survivors = select_survivors(
            (
                elite,
                worse,
            ),
            (
                worse,
                worse,
            ),
            population_size=2,
        )

        self.assertIn(
            elite,
            survivors,
        )

        self.assertIs(
            survivors[0],
            elite,
        )

    # ------------------------------------------------------------
    # 13. Best-so-far không được xấu đi
    # ------------------------------------------------------------

    def test_best_so_far_history_never_gets_worse(
        self,
    ) -> None:

        result = run_ga(
            self.problem,
            self.domains,
            self.make_config(),
        )

        keys = [
            point.best_fitness_key
            for point in result.convergence_history
        ]

        self.assertGreaterEqual(
            len(keys),
            1,
        )

        self.assertTrue(
            all(
                next_key <= current_key
                for current_key, next_key
                in zip(
                    keys,
                    keys[1:],
                )
            )
        )

    # ------------------------------------------------------------
    # 14. GA phải dùng đúng evaluate_candidate của population
    # ------------------------------------------------------------

    def test_ga_calls_population_evaluation_pipeline_for_offspring(
        self,
    ) -> None:

        config = self.make_config(
            max_fitness_evaluations=5
        )

        with patch(
            "gapo_timetabling.ga.evaluate_candidate",
            wraps=population_evaluate_candidate,
        ) as shared_pipeline:

            result = run_ga(
                self.problem,
                self.domains,
                config,
            )

        self.assertEqual(
            result.status,
            GAOptimizationStatus.SUCCESS,
        )

        self.assertGreaterEqual(
            shared_pipeline.call_count,
            1,
        )

    # ------------------------------------------------------------
    # 15. Không đủ offspring hợp lệ phải trả STALLED
    # ------------------------------------------------------------

    def test_not_enough_valid_offspring_returns_stalled_with_best_solution(
        self,
    ) -> None:

        failed = self.failed_evaluation()

        config = self.make_config(
            max_fitness_evaluations=10,
            max_offspring_attempts=1,
        )

        with patch(
            "gapo_timetabling.ga.evaluate_candidate",
            return_value=failed,
        ):

            result = run_ga(
                self.problem,
                self.domains,
                config,
            )

        self.assertEqual(
            result.status,
            GAOptimizationStatus.STALLED,
        )

        self.assertIsNotNone(
            result.best_individual
        )

        self.assertEqual(
            len(result.final_population),
            config.population_size,
        )

    # ------------------------------------------------------------
    # 16. Nghiệm cuối cùng phải qua Validator
    # ------------------------------------------------------------

    def test_final_best_solution_passes_independent_validator(
        self,
    ) -> None:

        result = run_ga(
            self.problem,
            self.domains,
            self.make_config(),
        )

        self.assertIsNotNone(
            result.best_individual
        )

        validation = validate_timetable(
            self.problem,
            result.best_individual.selected_options,
        )

        self.assertTrue(
            validation.is_valid
        )

    # ------------------------------------------------------------
    # Test bổ sung: NO_OPTION phải dừng trước optimizer
    # ------------------------------------------------------------

    def test_empty_domain_returns_no_option_before_optimizer_generations(
        self,
    ) -> None:

        domains = list(
            self.domains
        )

        domains[0] = ()

        result = run_ga(
            self.problem,
            tuple(domains),
            self.make_config(
                max_fitness_evaluations=8
            ),
        )

        self.assertEqual(
            result.status,
            GAOptimizationStatus.NO_OPTION,
        )

        self.assertEqual(
            result.generations_completed,
            0,
        )

        self.assertEqual(
            result.offspring_attempts,
            0,
        )

        self.assertEqual(
            result.fitness_evaluations,
            0,
        )

    # ------------------------------------------------------------
    # Test bổ sung: clamp boundary
    # ------------------------------------------------------------

    def test_boundary_helper_clamps_without_changing_dimension(
        self,
    ) -> None:

        vector = (
            -0.4,
            0.2,
            1.4,
            0.8,
        )

        clamped = clamp_vector(
            vector
        )

        self.assertEqual(
            clamped,
            (
                0.0,
                0.2,
                1.0,
                0.8,
            ),
        )

        self.assertEqual(
            len(clamped),
            len(vector),
        )

    # ------------------------------------------------------------
    # Test bổ sung: cấu hình sai phải bị từ chối
    # ------------------------------------------------------------

    def test_invalid_ga_configuration_is_rejected(
        self,
    ) -> None:

        with self.assertRaisesRegex(
            ValueError,
            "population_size",
        ):
            replace(
                self.make_config(),
                population_size=1,
            )

        with self.assertRaisesRegex(
            ValueError,
            "max_fitness_evaluations",
        ):
            replace(
                self.make_config(),
                max_fitness_evaluations=3,
            )

        with self.assertRaisesRegex(
            ValueError,
            "max_offspring_attempts",
        ):
            replace(
                self.make_config(),
                max_offspring_attempts=0,
            )


if __name__ == "__main__":
    unittest.main()