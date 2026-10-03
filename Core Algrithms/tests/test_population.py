"""Kiểm thử cổng đánh giá chung và quá trình tạo quần thể ban đầu."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from gapo_timetabling.constraints import (
    HardConstraintViolation,
    HardViolationCode,
    ValidationResult,
    validate_timetable,
)
from gapo_timetabling.encoder import build_option_domains
from gapo_timetabling.models import SessionOption
from gapo_timetabling.population import (
    CandidateEvaluationConfig,
    CandidateEvaluationStatus,
    PopulationInitializationStatus,
    best_individual,
    evaluate_candidate,
    initialize_population,
    sort_individuals,
)
from tests.test_constraints import ConstraintFixture


class TestPopulation(ConstraintFixture):
    """Xác nhận mọi optimizer sau này sẽ dùng cùng một quy trình đánh giá."""

    def singleton_domains(self) -> tuple[tuple[SessionOption, ...], ...]:
        """Tạo miền đơn giản có đúng một lịch hợp lệ đã biết."""

        return tuple((option,) for option in self.valid_options)

    def make_backtracking_case(self):
        """Tạo nhánh cụt để kiểm tra population có gọi repair đúng lúc."""

        same_lecturer_part = replace(self.parts[2], lecturer_index=0)
        problem = replace(
            self.problem,
            teaching_parts=(
                self.parts[0],
                self.parts[1],
                same_lecturer_part,
                self.parts[3],
            ),
        )
        domains = (
            (
                SessionOption(0, 0, self.tuesday.calendar_date, 1, 3),
                SessionOption(0, 0, self.tuesday.calendar_date, 4, 6),
            ),
            (
                SessionOption(1, 0, self.tuesday.calendar_date, 4, 6),
                SessionOption(1, 0, self.tuesday.calendar_date, 7, 9),
            ),
            (
                SessionOption(2, 0, self.tuesday.calendar_date, 4, 6),
                SessionOption(2, 0, self.tuesday.calendar_date, 7, 9),
            ),
            (self.valid_options[3],),
        )
        vector = (0.75, 0.25, 0.25, 0.0)
        return problem, domains, vector

    def test_evaluate_candidate_runs_complete_pipeline(self) -> None:
        """Một vector hợp lệ phải đi đến Fitness và trở thành individual."""

        vector = (0.0, 0.0, 0.0, 0.0)
        config = CandidateEvaluationConfig(
            max_decode_nodes=20,
            enable_repair=False,
            max_repair_attempts=0,
        )

        result = evaluate_candidate(
            self.problem,
            self.singleton_domains(),
            vector,
            config,
        )

        self.assertEqual(result.status, CandidateEvaluationStatus.SUCCESS)
        self.assertEqual(result.fitness_evaluations, 1)
        self.assertIsNotNone(result.validation_result)
        self.assertTrue(result.validation_result.is_valid)
        self.assertIsNotNone(result.individual)
        self.assertEqual(result.individual.vector, vector)
        self.assertEqual(result.individual.selected_options, self.valid_options)
        self.assertFalse(result.individual.was_repaired)
        self.assertEqual(
            result.individual.fitness_key,
            result.individual.fitness.fitness_key,
        )

    def test_decode_failed_candidate_never_reaches_fitness(self) -> None:
        """Hết ngân sách decoder chỉ loại vector, không gán fitness giả."""

        config = CandidateEvaluationConfig(
            max_decode_nodes=1,
            enable_repair=False,
            max_repair_attempts=0,
        )

        result = evaluate_candidate(
            self.problem,
            self.singleton_domains(),
            (0.0, 0.0, 0.0, 0.0),
            config,
        )

        self.assertEqual(result.status, CandidateEvaluationStatus.DECODE_FAILED)
        self.assertEqual(result.fitness_evaluations, 0)
        self.assertIsNone(result.individual)
        self.assertIsNone(result.validation_result)

    def test_population_uses_thin_repair_before_fitness(self) -> None:
        """Repair thành công phải đồng bộ vector rồi mới tạo individual."""

        problem, domains, vector = self.make_backtracking_case()
        config = CandidateEvaluationConfig(
            max_decode_nodes=4,
            enable_repair=True,
            max_repair_attempts=2,
            max_decode_nodes_per_repair_attempt=4,
        )

        result = evaluate_candidate(problem, domains, vector, config)

        self.assertEqual(result.status, CandidateEvaluationStatus.SUCCESS)
        self.assertIsNotNone(result.individual)
        self.assertTrue(result.individual.was_repaired)
        self.assertEqual(result.individual.repair_attempts, 2)
        self.assertEqual(result.individual.vector[0], 0.25)
        self.assertEqual(result.fitness_evaluations, 1)
        self.assertTrue(
            validate_timetable(
                problem,
                result.individual.selected_options,
            ).is_valid
        )

    def test_no_option_is_reported_without_fitness(self) -> None:
        """Miền rỗng là lỗi đầu vào, không phải một cá thể fitness rất xấu."""

        domains = list(self.singleton_domains())
        domains[1] = ()
        config = CandidateEvaluationConfig(max_decode_nodes=20)

        result = evaluate_candidate(
            self.problem,
            tuple(domains),
            (0.0, 0.0, 0.0, 0.0),
            config,
        )

        self.assertEqual(result.status, CandidateEvaluationStatus.NO_OPTION)
        self.assertEqual(result.fitness_evaluations, 0)
        self.assertIsNone(result.individual)

    def test_independent_validator_can_block_fitness(self) -> None:
        """Fitness không được gọi nếu lớp Validator độc lập phát hiện lỗi."""

        forced_violation = HardConstraintViolation(
            code=HardViolationCode.ROOM_CONFLICT,
            session_indices=(0, 1),
            message="Lỗi giả lập để kiểm tra lớp bảo vệ độc lập.",
        )
        rejected = ValidationResult((forced_violation,))
        config = CandidateEvaluationConfig(
            max_decode_nodes=20,
            enable_repair=False,
            max_repair_attempts=0,
        )

        with (
            patch(
                "gapo_timetabling.population.validate_timetable",
                return_value=rejected,
            ),
            patch("gapo_timetabling.population.calculate_fitness") as fitness,
        ):
            result = evaluate_candidate(
                self.problem,
                self.singleton_domains(),
                (0.0, 0.0, 0.0, 0.0),
                config,
            )

        self.assertEqual(
            result.status,
            CandidateEvaluationStatus.VALIDATION_FAILED,
        )
        self.assertEqual(result.fitness_evaluations, 0)
        self.assertIsNone(result.individual)
        fitness.assert_not_called()

    def test_initialization_creates_exactly_n_valid_individuals(self) -> None:
        """Khởi tạo thành công phải có đủ N lịch hợp lệ và đúng N FE."""

        domains = build_option_domains(self.problem)
        config = CandidateEvaluationConfig(
            max_decode_nodes=100,
            enable_repair=False,
            max_repair_attempts=0,
        )

        result = initialize_population(
            self.problem,
            domains,
            population_size=5,
            max_initialization_attempts=20,
            seed=42,
            evaluation_config=config,
        )

        self.assertEqual(result.status, PopulationInitializationStatus.SUCCESS)
        self.assertEqual(len(result.individuals), 5)
        self.assertEqual(result.fitness_evaluations, 5)
        self.assertEqual(result.candidate_attempts, 5)
        for individual in result.individuals:
            self.assertTrue(
                validate_timetable(
                    self.problem,
                    individual.selected_options,
                ).is_valid
            )

    def test_same_seed_recreates_same_initial_population(self) -> None:
        """Cùng snapshot, cấu hình và seed phải tái lập quần thể ban đầu."""

        domains = build_option_domains(self.problem)
        config = CandidateEvaluationConfig(
            max_decode_nodes=100,
            enable_repair=False,
            max_repair_attempts=0,
        )

        first = initialize_population(
            self.problem,
            domains,
            4,
            20,
            2026,
            config,
        )
        second = initialize_population(
            self.problem,
            domains,
            4,
            20,
            2026,
            config,
        )

        self.assertEqual(first, second)

    def test_empty_domain_stops_before_random_attempts(self) -> None:
        """D051 yêu cầu NO_OPTION xảy ra trước khi sinh quần thể ngẫu nhiên."""

        domains = list(self.singleton_domains())
        domains[2] = ()

        result = initialize_population(
            self.problem,
            tuple(domains),
            population_size=3,
            max_initialization_attempts=10,
            seed=1,
            evaluation_config=CandidateEvaluationConfig(max_decode_nodes=20),
        )

        self.assertEqual(result.status, PopulationInitializationStatus.NO_OPTION)
        self.assertEqual(result.candidate_attempts, 0)
        self.assertEqual(result.fitness_evaluations, 0)
        self.assertEqual(result.individuals, ())
        self.assertIsNotNone(result.terminal_evaluation)

    def test_attempt_exhaustion_uses_non_infeasible_status(self) -> None:
        """Không ghép được trong giới hạn phải dùng đúng tên trạng thái D054."""

        conflicting = replace(self.valid_options[1], start_period=1, end_period=3)
        domains = (
            (self.valid_options[0],),
            (conflicting,),
            (self.valid_options[2],),
            (self.valid_options[3],),
        )
        config = CandidateEvaluationConfig(
            max_decode_nodes=20,
            enable_repair=False,
            max_repair_attempts=0,
        )

        result = initialize_population(
            self.problem,
            domains,
            population_size=2,
            max_initialization_attempts=3,
            seed=7,
            evaluation_config=config,
        )

        self.assertEqual(
            result.status,
            PopulationInitializationStatus.NO_FEASIBLE_SOLUTION_FOUND,
        )
        self.assertEqual(result.candidate_attempts, 3)
        self.assertEqual(result.decode_failed_count, 3)
        self.assertEqual(result.fitness_evaluations, 0)
        self.assertEqual(result.individuals, ())
        self.assertNotIn("INFEASIBLE", result.status.value)

    def test_sort_uses_lexicographic_gate_f_order(self) -> None:
        """Q_general tốt không được bù cho Q_time kém hơn."""

        config = CandidateEvaluationConfig(
            max_decode_nodes=20,
            enable_repair=False,
            max_repair_attempts=0,
        )
        evaluated = evaluate_candidate(
            self.problem,
            self.singleton_domains(),
            (0.0, 0.0, 0.0, 0.0),
            config,
        )
        base = evaluated.individual
        self.assertIsNotNone(base)

        stable = replace(
            base,
            vector=(0.9, 0.9, 0.9, 0.9),
            fitness=replace(
                base.fitness,
                time_stability_score=0.0,
                general_quality_score=10.0,
                lecturer_preference_score=10.0,
            ),
        )
        unstable = replace(
            base,
            vector=(0.1, 0.1, 0.1, 0.1),
            fitness=replace(
                base.fitness,
                time_stability_score=0.1,
                general_quality_score=0.0,
                lecturer_preference_score=0.0,
            ),
        )

        ordered = sort_individuals((unstable, stable))

        self.assertIs(ordered[0], stable)
        self.assertIs(best_individual((unstable, stable)), stable)

    def test_invalid_configuration_is_rejected(self) -> None:
        """Các giới hạn sai phải bị phát hiện trước khi tạo quần thể."""

        with self.assertRaisesRegex(ValueError, "max_decode_nodes"):
            CandidateEvaluationConfig(max_decode_nodes=0)

        with self.assertRaisesRegex(ValueError, "max_repair_attempts"):
            CandidateEvaluationConfig(
                max_decode_nodes=10,
                enable_repair=True,
                max_repair_attempts=0,
            )

        with self.assertRaisesRegex(ValueError, "max_initialization_attempts"):
            initialize_population(
                self.problem,
                self.singleton_domains(),
                population_size=3,
                max_initialization_attempts=2,
                seed=1,
                evaluation_config=CandidateEvaluationConfig(
                    max_decode_nodes=10,
                    enable_repair=False,
                    max_repair_attempts=0,
                ),
            )

    def test_best_individual_rejects_empty_population(self) -> None:
        """Không che lỗi pipeline bằng cách trả một cá thể giả cho tập rỗng."""

        with self.assertRaisesRegex(ValueError, "quần thể rỗng"):
            best_individual(())


if __name__ == "__main__":
    unittest.main()
