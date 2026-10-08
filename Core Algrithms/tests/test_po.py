"""Kiểm thử phần toán học nền tảng của Parrot Optimizer V2."""

import math
import unittest
from dataclasses import FrozenInstanceError, replace
from random import Random
from unittest.mock import patch

from gapo_timetabling.encoder import build_option_domains
from gapo_timetabling.metrics import (
    OptimizationMetrics,
    accumulate_candidate_evaluation,
)
from gapo_timetabling.models import SessionOption
from gapo_timetabling.po import (
    PoBehavior,
    PoConfig,
    _create_and_evaluate_po_offspring,
    _create_convergence_point,
    _validate_po_run_inputs,
    calculate_population_mean,
    clip_vector_to_unit_interval,
    create_po_position,
    levy_flight,
)
from gapo_timetabling.population import (
    CandidateEvaluationConfig,
    CandidateEvaluationStatus,
    PopulationInitializationStatus,
    evaluate_candidate,
    initialize_population,
)
from tests.test_constraints import ConstraintFixture


class StubRandom:
    """Nguồn số giả có thứ tự cố định để kiểm tra chính xác từng công thức.

    Đây chỉ là test double. Thuật toán thật vẫn sử dụng ``random.Random`` và
    seed do cấu hình lần chạy cung cấp.
    """

    def __init__(
        self,
        random_values: tuple[float, ...] = (),
        gaussian_values: tuple[float, ...] = (),
    ) -> None:
        self.random_values = list(random_values)
        self.gaussian_values = list(gaussian_values)

    def random(self) -> float:
        """Trả giá trị đồng đều tiếp theo đã chuẩn bị cho test."""

        if not self.random_values:
            raise AssertionError("Test đã dùng hết random_values.")
        return self.random_values.pop(0)

    def gauss(self, mean: float, standard_deviation: float) -> float:
        """Trả giá trị Gaussian tiếp theo đã chuẩn bị cho test."""

        del mean, standard_deviation
        if not self.gaussian_values:
            raise AssertionError("Test đã dùng hết gaussian_values.")
        return self.gaussian_values.pop(0)


class TestPoConfig(unittest.TestCase):
    """Kiểm tra hợp đồng cấu hình trước khi vòng lặp PO được triển khai."""

    def make_evaluation_config(self) -> CandidateEvaluationConfig:
        """Tạo cấu hình đánh giá tối thiểu hợp lệ dùng chung trong các test."""

        return CandidateEvaluationConfig(
            max_decode_nodes=100,
            enable_repair=True,
            max_repair_attempts=2,
        )

    def test_valid_configuration_keeps_all_values(self) -> None:
        """Cấu hình hợp lệ phải lưu nguyên ngân sách, seed và cấu hình đánh giá."""

        evaluation_config = self.make_evaluation_config()
        config = PoConfig(
            max_fitness_evaluations=300,
            max_offspring_attempts=5,
            seed=42,
            evaluation_config=evaluation_config,
        )

        self.assertEqual(config.max_fitness_evaluations, 300)
        self.assertEqual(config.max_offspring_attempts, 5)
        self.assertEqual(config.seed, 42)
        self.assertIs(config.evaluation_config, evaluation_config)

    def test_non_positive_fitness_budget_is_rejected(self) -> None:
        """Ngân sách FE bằng 0 hoặc âm không thể bắt đầu một lần chạy PO."""

        for invalid_budget in (0, -1):
            with self.subTest(max_fitness_evaluations=invalid_budget):
                with self.assertRaises(ValueError):
                    PoConfig(
                        max_fitness_evaluations=invalid_budget,
                        max_offspring_attempts=5,
                        seed=42,
                        evaluation_config=self.make_evaluation_config(),
                    )

    def test_non_positive_offspring_attempt_limit_is_rejected(self) -> None:
        """Mỗi vị trí con phải được phép thử sinh ít nhất một vector."""

        for invalid_limit in (0, -1):
            with self.subTest(max_offspring_attempts=invalid_limit):
                with self.assertRaises(ValueError):
                    PoConfig(
                        max_fitness_evaluations=300,
                        max_offspring_attempts=invalid_limit,
                        seed=42,
                        evaluation_config=self.make_evaluation_config(),
                    )

    def test_configuration_is_immutable(self) -> None:
        """Cấu hình không được thay đổi giữa chừng khi thuật toán đang chạy."""

        config = PoConfig(
            max_fitness_evaluations=300,
            max_offspring_attempts=5,
            seed=42,
            evaluation_config=self.make_evaluation_config(),
        )

        with self.assertRaises(FrozenInstanceError):
            config.seed = 99


class TestPoRunInputValidation(ConstraintFixture):
    """Kiểm tra dữ liệu trước khi vòng lặp PO được phép bắt đầu."""

    def make_initialization(self, population_size: int = 2):
        """Tạo quần thể thành công bằng pipeline thật của project."""

        return initialize_population(
            self.problem,
            build_option_domains(self.problem),
            population_size=population_size,
            max_initialization_attempts=20,
            seed=42,
            evaluation_config=CandidateEvaluationConfig(
                max_decode_nodes=100,
                enable_repair=False,
                max_repair_attempts=0,
            ),
        )

    @staticmethod
    def make_config(max_fitness_evaluations: int) -> PoConfig:
        """Tạo cấu hình PO có ngân sách cần kiểm tra."""

        return PoConfig(
            max_fitness_evaluations=max_fitness_evaluations,
            max_offspring_attempts=3,
            seed=2026,
            evaluation_config=CandidateEvaluationConfig(
                max_decode_nodes=100,
                enable_repair=False,
                max_repair_attempts=0,
            ),
        )

    def test_valid_input_returns_number_of_full_iterations(self) -> None:
        """FE còn lại chia đều cho N phải tạo đúng số iteration."""

        initialization = self.make_initialization(population_size=2)

        max_iterations = _validate_po_run_inputs(
            self.problem,
            initialization,
            self.make_config(max_fitness_evaluations=6),
        )

        self.assertEqual(max_iterations, 2)

    def test_budget_equal_to_initial_fe_allows_zero_iterations(self) -> None:
        """Run được phép trả ngay quần thể đầu khi không còn FE tìm kiếm."""

        initialization = self.make_initialization(population_size=2)

        max_iterations = _validate_po_run_inputs(
            self.problem,
            initialization,
            self.make_config(max_fitness_evaluations=2),
        )

        self.assertEqual(max_iterations, 0)

    def test_unsuccessful_or_empty_initialization_is_rejected(self) -> None:
        """PO không nhận kết quả khởi tạo lỗi hoặc quần thể rỗng giả."""

        initialization = self.make_initialization(population_size=2)
        config = self.make_config(max_fitness_evaluations=6)

        with self.assertRaisesRegex(ValueError, "SUCCESS"):
            _validate_po_run_inputs(
                self.problem,
                replace(
                    initialization,
                    status=(
                        PopulationInitializationStatus
                        .NO_FEASIBLE_SOLUTION_FOUND
                    ),
                ),
                config,
            )

        with self.assertRaisesRegex(ValueError, "không được rỗng"):
            _validate_po_run_inputs(
                self.problem,
                replace(
                    initialization,
                    individuals=(),
                    requested_population_size=0,
                    fitness_evaluations=0,
                ),
                config,
            )

    def test_population_size_and_initial_counters_must_be_consistent(self) -> None:
        """SUCCESS không được che sai kích thước, FE hoặc candidate attempts."""

        initialization = self.make_initialization(population_size=2)
        config = self.make_config(max_fitness_evaluations=6)
        invalid_initializations = (
            replace(initialization, requested_population_size=3),
            replace(initialization, fitness_evaluations=1),
            replace(initialization, candidate_attempts=1),
        )

        for invalid_initialization in invalid_initializations:
            with self.subTest(initialization=invalid_initialization):
                with self.assertRaises(ValueError):
                    _validate_po_run_inputs(
                        self.problem,
                        invalid_initialization,
                        config,
                    )

    def test_each_vector_must_match_problem_dimension(self) -> None:
        """Mỗi ClassSession phải tiếp tục có đúng một gene trong PO."""

        initialization = self.make_initialization(population_size=2)
        invalid_individual = replace(
            initialization.individuals[0],
            vector=(0.5,),
        )

        with self.assertRaisesRegex(ValueError, "đúng 4 gene"):
            _validate_po_run_inputs(
                self.problem,
                replace(
                    initialization,
                    individuals=(
                        invalid_individual,
                        initialization.individuals[1],
                    ),
                ),
                self.make_config(max_fitness_evaluations=6),
            )

    def test_each_gene_must_be_finite_and_inside_unit_interval(self) -> None:
        """NaN, vô cực và random-key ngoài [0,1] phải bị từ chối."""

        initialization = self.make_initialization(population_size=2)
        invalid_genes = (float("nan"), float("inf"), -0.1, 1.1)

        for invalid_gene in invalid_genes:
            invalid_vector = list(initialization.individuals[0].vector)
            invalid_vector[0] = invalid_gene
            invalid_individual = replace(
                initialization.individuals[0],
                vector=tuple(invalid_vector),
            )

            with self.subTest(gene=invalid_gene):
                with self.assertRaises(ValueError):
                    _validate_po_run_inputs(
                        self.problem,
                        replace(
                            initialization,
                            individuals=(
                                invalid_individual,
                                initialization.individuals[1],
                            ),
                        ),
                        self.make_config(max_fitness_evaluations=6),
                    )

    def test_budget_must_cover_initialization_and_full_iterations(self) -> None:
        """Ngân sách phải đủ cho quần thể đầu và chia hết phần còn lại."""

        initialization = self.make_initialization(population_size=2)

        with self.assertRaisesRegex(ValueError, "nhỏ hơn FE khởi tạo"):
            _validate_po_run_inputs(
                self.problem,
                initialization,
                self.make_config(max_fitness_evaluations=1),
            )

        with self.assertRaisesRegex(ValueError, "chia hết"):
            _validate_po_run_inputs(
                self.problem,
                initialization,
                self.make_config(max_fitness_evaluations=5),
            )

    def test_convergence_point_copies_existing_best_fitness(self) -> None:
        """Mốc hội tụ phải dùng score sẵn có và không đánh giá Fitness lại."""

        initialization = self.make_initialization(population_size=2)
        best_individual = min(
            initialization.individuals,
            key=lambda individual: individual.fitness_key,
        )

        point = _create_convergence_point(
            iteration=0,
            fitness_evaluations=initialization.fitness_evaluations,
            best_individual=best_individual,
        )

        self.assertEqual(point.iteration, 0)
        self.assertEqual(
            point.fitness_evaluations,
            initialization.fitness_evaluations,
        )
        self.assertEqual(point.fitness_key, best_individual.fitness_key)

    def test_convergence_point_reuses_contract_validation(self) -> None:
        """Iteration và FE sai phải bị ConvergencePoint từ chối."""

        initialization = self.make_initialization(population_size=1)
        best_individual = initialization.individuals[0]

        with self.assertRaisesRegex(ValueError, "iteration"):
            _create_convergence_point(
                iteration=-1,
                fitness_evaluations=1,
                best_individual=best_individual,
            )

        with self.assertRaisesRegex(ValueError, "fitness_evaluations"):
            _create_convergence_point(
                iteration=0,
                fitness_evaluations=0,
                best_individual=best_individual,
            )


class TestCandidateMetricAccumulation(ConstraintFixture):
    """Kiểm tra cách PO sẽ cộng số liệu của từng lần thử offspring."""

    @staticmethod
    def empty_metrics() -> OptimizationMetrics:
        """Tạo ảnh chụp metrics rỗng trước lần đánh giá đầu tiên."""

        return OptimizationMetrics(
            completed_iterations=0,
            candidate_attempts=0,
            fitness_evaluations=0,
            decode_failed_count=0,
            validation_failed_count=0,
            repaired_individual_count=0,
            failed_repair_count=0,
            total_repair_attempts=0,
            discarded_offspring_count=0,
            total_decode_nodes=0,
            total_decode_backtracks=0,
            runtime_seconds=0.0,
        )

    def singleton_domains(self):
        """Tạo miền một option để chủ động điều khiển nhánh decode."""

        return tuple((option,) for option in self.valid_options)

    def make_repair_case(self):
        """Tạo vector cần đúng hai lần thử repair để giải mã thành công."""

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

    def test_success_adds_one_attempt_one_fe_and_decode_cost(self) -> None:
        """Ứng viên hợp lệ phải tăng attempt, FE, node và backtrack thực tế."""

        evaluation = evaluate_candidate(
            self.problem,
            self.singleton_domains(),
            (0.0, 0.0, 0.0, 0.0),
            CandidateEvaluationConfig(
                max_decode_nodes=20,
                enable_repair=False,
                max_repair_attempts=0,
            ),
        )
        before = self.empty_metrics()

        after = accumulate_candidate_evaluation(before, evaluation)

        self.assertEqual(evaluation.status, CandidateEvaluationStatus.SUCCESS)
        self.assertEqual(after.candidate_attempts, 1)
        self.assertEqual(after.fitness_evaluations, 1)
        self.assertEqual(after.total_decode_nodes, evaluation.total_decode_nodes)
        self.assertEqual(
            after.total_decode_backtracks,
            evaluation.total_decode_backtracks,
        )
        self.assertEqual(after.decode_failed_count, 0)
        self.assertEqual(after.validation_failed_count, 0)
        self.assertEqual(after.completed_iterations, 0)
        self.assertEqual(after.discarded_offspring_count, 0)
        self.assertEqual(after.runtime_seconds, 0.0)

        # Helper trả ảnh chụp mới, không được sửa metrics đã truyền vào.
        self.assertEqual(before.candidate_attempts, 0)
        self.assertEqual(before.fitness_evaluations, 0)

    def test_decode_and_validation_failures_are_counted_separately(self) -> None:
        """Hai tầng lỗi phải tăng đúng bộ đếm và không làm tăng FE."""

        decode_failed = evaluate_candidate(
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
            decode_failed.status,
            CandidateEvaluationStatus.DECODE_FAILED,
        )

        # Helper chỉ đọc status để phân loại. Bản sao này cô lập nhánh
        # VALIDATION_FAILED mà không gọi lại toàn bộ validator trong unit test.
        validation_failed = replace(
            decode_failed,
            status=CandidateEvaluationStatus.VALIDATION_FAILED,
        )

        after_decode = accumulate_candidate_evaluation(
            self.empty_metrics(),
            decode_failed,
        )
        after_validation = accumulate_candidate_evaluation(
            after_decode,
            validation_failed,
        )

        self.assertEqual(after_validation.candidate_attempts, 2)
        self.assertEqual(after_validation.fitness_evaluations, 0)
        self.assertEqual(after_validation.decode_failed_count, 1)
        self.assertEqual(after_validation.validation_failed_count, 1)

    def test_repair_statistics_use_actual_attempt_count(self) -> None:
        """Repair thành công phải cộng đúng số lần gọi lại decoder thực tế."""

        problem, domains, vector = self.make_repair_case()
        evaluation = evaluate_candidate(
            problem,
            domains,
            vector,
            CandidateEvaluationConfig(
                max_decode_nodes=4,
                enable_repair=True,
                max_repair_attempts=2,
                max_decode_nodes_per_repair_attempt=4,
            ),
        )

        after = accumulate_candidate_evaluation(
            self.empty_metrics(),
            evaluation,
        )

        self.assertTrue(evaluation.is_success)
        self.assertIsNotNone(evaluation.repair_result)
        self.assertEqual(evaluation.repair_result.attempts, 2)
        self.assertEqual(after.repaired_individual_count, 1)
        self.assertEqual(after.failed_repair_count, 0)
        self.assertEqual(after.total_repair_attempts, 2)
        self.assertEqual(after.fitness_evaluations, 1)

    def test_failed_repair_is_counted_without_increasing_fe(self) -> None:
        """Hết giới hạn repair phải tăng lỗi repair và decode, không tăng FE."""

        problem, domains, vector = self.make_repair_case()
        evaluation = evaluate_candidate(
            problem,
            domains,
            vector,
            CandidateEvaluationConfig(
                max_decode_nodes=4,
                enable_repair=True,
                max_repair_attempts=1,
                max_decode_nodes_per_repair_attempt=4,
            ),
        )

        after = accumulate_candidate_evaluation(
            self.empty_metrics(),
            evaluation,
        )

        self.assertEqual(
            evaluation.status,
            CandidateEvaluationStatus.DECODE_FAILED,
        )
        self.assertIsNotNone(evaluation.repair_result)
        self.assertEqual(evaluation.repair_result.attempts, 1)
        self.assertEqual(after.decode_failed_count, 1)
        self.assertEqual(after.failed_repair_count, 1)
        self.assertEqual(after.repaired_individual_count, 0)
        self.assertEqual(after.total_repair_attempts, 1)
        self.assertEqual(after.fitness_evaluations, 0)

    def test_no_option_must_stop_instead_of_being_counted(self) -> None:
        """Miền rỗng giữa run là lỗi dữ liệu, không phải offspring bị loại."""

        domains = list(self.singleton_domains())
        domains[0] = ()
        evaluation = evaluate_candidate(
            self.problem,
            tuple(domains),
            (0.0, 0.0, 0.0, 0.0),
            CandidateEvaluationConfig(max_decode_nodes=20),
        )

        with self.assertRaisesRegex(ValueError, "NO_OPTION"):
            accumulate_candidate_evaluation(
                self.empty_metrics(),
                evaluation,
            )


class TestPoOffspringCreation(ConstraintFixture):
    """Kiểm tra cầu nối từ công thức PO tới pipeline đánh giá lịch."""

    @staticmethod
    def empty_metrics() -> OptimizationMetrics:
        """Tạo metrics rỗng để quan sát chính xác số liệu helper cộng thêm."""

        return OptimizationMetrics(
            completed_iterations=0,
            candidate_attempts=0,
            fitness_evaluations=0,
            decode_failed_count=0,
            validation_failed_count=0,
            repaired_individual_count=0,
            failed_repair_count=0,
            total_repair_attempts=0,
            discarded_offspring_count=0,
            total_decode_nodes=0,
            total_decode_backtracks=0,
            runtime_seconds=0.0,
        )

    @staticmethod
    def evaluation_config(max_decode_nodes: int = 100):
        """Tạo cấu hình pipeline có thể thay riêng ngân sách decoder."""

        return CandidateEvaluationConfig(
            max_decode_nodes=max_decode_nodes,
            enable_repair=False,
            max_repair_attempts=0,
        )

    def make_po_config(
        self,
        max_offspring_attempts: int,
        max_decode_nodes: int = 100,
    ) -> PoConfig:
        """Tạo cấu hình PO vừa đủ cho test helper offspring."""

        return PoConfig(
            max_fitness_evaluations=10,
            max_offspring_attempts=max_offspring_attempts,
            seed=2026,
            evaluation_config=self.evaluation_config(max_decode_nodes),
        )

    def make_parent_and_domains(self):
        """Tạo một cá thể cha hợp lệ bằng pipeline thật của project."""

        domains = build_option_domains(self.problem)
        initialization = initialize_population(
            self.problem,
            domains,
            population_size=1,
            max_initialization_attempts=10,
            seed=42,
            evaluation_config=self.evaluation_config(),
        )
        self.assertTrue(initialization.is_success)
        return initialization.individuals[0], domains

    def call_helper(
        self,
        parent,
        domains,
        config,
        metrics,
        behavior: PoBehavior = PoBehavior.FORAGING,
    ):
        """Gọi helper với các tham số iteration cố định, dễ kiểm tra."""

        return _create_and_evaluate_po_offspring(
            problem=self.problem,
            option_domains=domains,
            current_individual=parent,
            current_index=0,
            behavior=behavior,
            best_individual=parent,
            population_mean=parent.vector,
            iteration=1,
            max_iterations=2,
            alpha=0.1,
            theta=0.2,
            rng=Random(2026),
            config=config,
            metrics=metrics,
        )

    def test_first_valid_vector_is_clipped_evaluated_and_returned(self) -> None:
        """Vector đầu hợp lệ phải được chặn biên rồi trả ngay thành offspring."""

        parent, domains = self.make_parent_and_domains()
        before = self.empty_metrics()
        proposed = (-0.25, 0.25, 1.25, 0.75)

        with (
            patch(
                "gapo_timetabling.po.create_po_position",
                return_value=proposed,
            ),
            patch(
                "gapo_timetabling.po.evaluate_candidate",
                wraps=evaluate_candidate,
            ) as evaluator,
        ):
            result = self.call_helper(
                parent,
                domains,
                self.make_po_config(max_offspring_attempts=3),
                before,
            )

        self.assertTrue(result.is_success)
        self.assertIsNotNone(result.individual)
        self.assertEqual(result.attempts_used, 1)
        self.assertEqual(result.metrics.candidate_attempts, 1)
        self.assertEqual(result.metrics.fitness_evaluations, 1)
        self.assertEqual(result.metrics.discarded_offspring_count, 0)

        # Đối số thứ ba của evaluate_candidate là vector sau boundary control.
        evaluated_vector = evaluator.call_args.args[2]
        self.assertEqual(evaluated_vector, (0.0, 0.25, 1.0, 0.75))

        # Helper trả metrics mới thay vì sửa ảnh chụp đầu vào.
        self.assertEqual(before.candidate_attempts, 0)
        self.assertEqual(before.fitness_evaluations, 0)

    def test_failed_attempt_can_be_retried_then_succeed(self) -> None:
        """Decode lỗi lần đầu phải được đếm rồi thử lại đến cá thể hợp lệ."""

        parent, _ = self.make_parent_and_domains()
        domains = tuple((option,) for option in self.valid_options)
        vector = (0.0, 0.0, 0.0, 0.0)
        failed = evaluate_candidate(
            self.problem,
            domains,
            vector,
            self.evaluation_config(max_decode_nodes=1),
        )
        succeeded = evaluate_candidate(
            self.problem,
            domains,
            vector,
            self.evaluation_config(max_decode_nodes=20),
        )
        self.assertFalse(failed.is_success)
        self.assertTrue(succeeded.is_success)

        with (
            patch(
                "gapo_timetabling.po.create_po_position",
                side_effect=(vector, vector),
            ) as position_creator,
            patch(
                "gapo_timetabling.po.evaluate_candidate",
                side_effect=(failed, succeeded),
            ),
        ):
            result = self.call_helper(
                parent,
                domains,
                self.make_po_config(max_offspring_attempts=3),
                self.empty_metrics(),
                behavior=PoBehavior.STAYING,
            )

        self.assertTrue(result.is_success)
        self.assertEqual(result.individual, succeeded.individual)
        self.assertEqual(result.attempts_used, 2)
        self.assertEqual(result.metrics.candidate_attempts, 2)
        self.assertEqual(result.metrics.decode_failed_count, 1)
        self.assertEqual(result.metrics.fitness_evaluations, 1)
        self.assertEqual(result.metrics.discarded_offspring_count, 0)

        # Hành vi đã bốc cho cá thể được giữ cố định trong mọi lần thử lại.
        self.assertEqual(position_creator.call_count, 2)
        for call in position_creator.call_args_list:
            self.assertEqual(call.kwargs["behavior"], PoBehavior.STAYING)
            self.assertEqual(call.kwargs["alpha"], 0.1)
            self.assertEqual(call.kwargs["theta"], 0.2)

    def test_attempt_exhaustion_discards_one_offspring_not_each_attempt(self) -> None:
        """Ba lần lỗi chỉ tạo một offspring bị bỏ và không tạo FE giả."""

        parent, _ = self.make_parent_and_domains()
        domains = tuple((option,) for option in self.valid_options)
        vector = (0.0, 0.0, 0.0, 0.0)
        failed = evaluate_candidate(
            self.problem,
            domains,
            vector,
            self.evaluation_config(max_decode_nodes=1),
        )
        self.assertFalse(failed.is_success)

        with (
            patch(
                "gapo_timetabling.po.create_po_position",
                return_value=vector,
            ),
            patch(
                "gapo_timetabling.po.evaluate_candidate",
                return_value=failed,
            ) as evaluator,
        ):
            result = self.call_helper(
                parent,
                domains,
                self.make_po_config(max_offspring_attempts=3),
                self.empty_metrics(),
            )

        self.assertFalse(result.is_success)
        self.assertIsNone(result.individual)
        self.assertEqual(result.attempts_used, 3)
        self.assertEqual(evaluator.call_count, 3)
        self.assertEqual(result.metrics.candidate_attempts, 3)
        self.assertEqual(result.metrics.decode_failed_count, 3)
        self.assertEqual(result.metrics.fitness_evaluations, 0)
        self.assertEqual(result.metrics.discarded_offspring_count, 1)

    def test_no_option_stops_retry_loop_immediately(self) -> None:
        """NO_OPTION phải dừng run, không được thử như lỗi decode bình thường."""

        parent, domains = self.make_parent_and_domains()
        domains_with_empty_item = list(domains)
        domains_with_empty_item[0] = ()

        with patch(
            "gapo_timetabling.po.create_po_position",
            return_value=parent.vector,
        ):
            with self.assertRaisesRegex(ValueError, "NO_OPTION"):
                self.call_helper(
                    parent,
                    tuple(domains_with_empty_item),
                    self.make_po_config(max_offspring_attempts=3),
                    self.empty_metrics(),
                )

    def test_helper_rejects_call_after_fe_budget_is_exhausted(self) -> None:
        """Không được sinh thêm vector nếu một success sẽ vượt ngân sách FE."""

        parent, domains = self.make_parent_and_domains()
        exhausted_metrics = replace(
            self.empty_metrics(),
            candidate_attempts=10,
            fitness_evaluations=10,
        )

        with patch("gapo_timetabling.po.create_po_position") as creator:
            with self.assertRaisesRegex(ValueError, "ngân sách"):
                self.call_helper(
                    parent,
                    domains,
                    self.make_po_config(max_offspring_attempts=3),
                    exhausted_metrics,
                )

        creator.assert_not_called()


class TestPoMath(unittest.TestCase):
    """Đối chiếu helper và bốn hành vi với phương trình PO V2 tham chiếu."""

    def assert_vector_almost_equal(
        self,
        actual: tuple[float, ...],
        expected: tuple[float, ...],
    ) -> None:
        """So sánh hai vector số thực theo từng chiều."""

        self.assertEqual(len(actual), len(expected))
        for actual_value, expected_value in zip(actual, expected):
            self.assertAlmostEqual(actual_value, expected_value)

    def test_clip_vector_to_unit_interval(self) -> None:
        """Gene ngoài biên phải được đưa về 0 hoặc 1; gene hợp lệ giữ nguyên."""

        result = clip_vector_to_unit_interval((-0.2, 0.0, 0.4, 1.0, 1.8))

        self.assertEqual(result, (0.0, 0.0, 0.4, 1.0, 1.0))

    def test_population_mean_is_calculated_by_dimension(self) -> None:
        """Mean phải được tính riêng trên từng chiều của quần thể."""

        result = calculate_population_mean(
            (
                (0.0, 0.5, 1.0),
                (1.0, 0.5, 0.0),
            )
        )

        self.assertEqual(result, (0.5, 0.5, 0.5))

    def test_population_mean_rejects_inconsistent_dimensions(self) -> None:
        """Không được âm thầm tính mean khi các cá thể khác số chiều."""

        with self.assertRaises(ValueError):
            calculate_population_mean(((0.0, 1.0), (0.5,)))

    def test_levy_flight_is_reproducible_and_finite(self) -> None:
        """Cùng seed phải sinh cùng bước Lévy hữu hạn và đúng số chiều."""

        first = levy_flight(20, Random(42))
        second = levy_flight(20, Random(42))

        self.assertEqual(first, second)
        self.assertEqual(len(first), 20)
        self.assertTrue(all(math.isfinite(value) for value in first))

    def test_levy_flight_matches_mantegna_equation(self) -> None:
        """Bước Lévy phải dùng đúng sigma, u và mẫu |v| mũ 1/beta."""

        beta = 1.5
        sigma = (
            math.gamma(1.0 + beta)
            * math.sin(math.pi * beta / 2.0)
            / (
                math.gamma((1.0 + beta) / 2.0)
                * beta
                * 2.0 ** ((beta - 1.0) / 2.0)
            )
        ) ** (1.0 / beta)

        result = levy_flight(
            dimensions=2,
            rng=StubRandom(
                gaussian_values=(1.25, -0.5, -0.75, 2.0),
            ),
        )

        expected = (
            (1.25 * sigma) / (abs(-0.5) ** (1.0 / beta)),
            (-0.75 * sigma) / (abs(2.0) ** (1.0 / beta)),
        )
        self.assert_vector_almost_equal(result, expected)

    def test_foraging_matches_reference_equation(self) -> None:
        """Hành vi kiếm ăn phải khớp phương trình tham chiếu theo từng chiều."""

        current = (2.0, -1.0)
        best = (0.5, 1.5)
        population_mean = (1.0, 2.0)
        iteration = 4
        max_iterations = 10
        progress = iteration / max_iterations
        remaining = 1.0 - progress

        with patch(
            "gapo_timetabling.po.levy_flight",
            return_value=(0.2, -0.4),
        ):
            result = create_po_position(
                current=current,
                current_index=1,
                behavior=PoBehavior.FORAGING,
                best_position=best,
                population_mean=population_mean,
                iteration=iteration,
                max_iterations=max_iterations,
                alpha=0.1,
                theta=0.3,
                rng=StubRandom(random_values=(0.25,)),
            )

        mean_factor = 0.25 * remaining ** (2.0 * progress)
        expected = (
            (current[0] - best[0]) * 0.2 + mean_factor * population_mean[0],
            (current[1] - best[1]) * -0.4 + mean_factor * population_mean[1],
        )
        self.assert_vector_almost_equal(result, expected)

    def test_staying_matches_reference_equation(self) -> None:
        """Lưu trú dùng một Gaussian scalar chung cho tất cả các chiều."""

        current = (2.0, -1.0)
        best = (0.5, 1.5)
        iteration = 4
        max_iterations = 10
        remaining = 1.0 - iteration / max_iterations

        with patch(
            "gapo_timetabling.po.levy_flight",
            return_value=(0.2, -0.4),
        ):
            result = create_po_position(
                current=current,
                current_index=1,
                behavior=PoBehavior.STAYING,
                best_position=best,
                population_mean=(1.0, 2.0),
                iteration=iteration,
                max_iterations=max_iterations,
                alpha=0.1,
                theta=0.3,
                rng=StubRandom(gaussian_values=(0.75,)),
            )

        expected = (
            current[0] + best[0] * 0.2 + 0.75 * remaining,
            current[1] + best[1] * -0.4 + 0.75 * remaining,
        )
        self.assert_vector_almost_equal(result, expected)

    def test_first_communicating_branch_matches_reference_equation(self) -> None:
        """Nhánh giao tiếp thứ nhất phải dịch chuyển theo current trừ mean."""

        current = (2.0, -1.0)
        population_mean = (1.0, 2.0)
        remaining = 1.0 - 4.0 / 10.0

        result = create_po_position(
            current=current,
            current_index=1,
            behavior=PoBehavior.COMMUNICATING,
            best_position=(0.5, 1.5),
            population_mean=population_mean,
            iteration=4,
            max_iterations=10,
            alpha=0.1,
            theta=0.3,
            rng=StubRandom(random_values=(0.25,)),
        )

        expected = (
            current[0] + 0.1 * remaining * (current[0] - population_mean[0]),
            current[1] + 0.1 * remaining * (current[1] - population_mean[1]),
        )
        self.assert_vector_almost_equal(result, expected)

    def test_second_communicating_branch_matches_reference_equation(self) -> None:
        """Nhánh giao tiếp thứ hai phải dùng đúng chỉ số cá thể và mẫu ngẫu nhiên."""

        current = (2.0, -1.0)
        remaining = 1.0 - 4.0 / 10.0
        exponential_term = math.exp(-2.0 / (0.4 * 10.0))
        movement = 0.1 * remaining * exponential_term

        result = create_po_position(
            current=current,
            current_index=1,
            behavior=PoBehavior.COMMUNICATING,
            best_position=(0.5, 1.5),
            population_mean=(1.0, 2.0),
            iteration=4,
            max_iterations=10,
            alpha=0.1,
            theta=0.3,
            rng=StubRandom(random_values=(0.75, 0.4)),
        )

        expected = (current[0] + movement, current[1] + movement)
        self.assert_vector_almost_equal(result, expected)

    def test_fear_of_strangers_matches_reference_equation(self) -> None:
        """Hành vi sợ người lạ phải khớp đủ hai thành phần hút và đẩy."""

        current = (2.0, -1.0)
        best = (0.5, 1.5)
        iteration = 4
        max_iterations = 10
        progress = iteration / max_iterations
        attraction = 0.2 * math.cos(
            math.pi * iteration / (2.0 * max_iterations)
        )
        repulsion = math.cos(0.3) * progress ** (2.0 / max_iterations)

        result = create_po_position(
            current=current,
            current_index=1,
            behavior=PoBehavior.FEAR_OF_STRANGERS,
            best_position=best,
            population_mean=(1.0, 2.0),
            iteration=iteration,
            max_iterations=max_iterations,
            alpha=0.1,
            theta=0.3,
            rng=StubRandom(random_values=(0.2,)),
        )

        expected = (
            current[0]
            + attraction * (best[0] - current[0])
            - repulsion * (current[0] - best[0]),
            current[1]
            + attraction * (best[1] - current[1])
            - repulsion * (current[1] - best[1]),
        )
        self.assert_vector_almost_equal(result, expected)


if __name__ == "__main__":
    unittest.main()
