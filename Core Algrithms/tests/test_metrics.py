"""Kiểm thử các hợp đồng metrics dùng chung cho optimizer thời khóa biểu."""

import unittest
from dataclasses import FrozenInstanceError

from gapo_timetabling.metrics import (
    ConvergencePoint,
    OptimizationMetrics,
    OptimizationResult,
)
from gapo_timetabling.models import (
    FitnessBreakdown,
    FitnessResult,
    OptimizationAlgorithm,
)
from gapo_timetabling.population import TimetableIndividual


class TestConvergencePoint(unittest.TestCase):
    """Kiểm tra dữ liệu một mốc hội tụ và thứ tự fitness Gate F."""

    def test_valid_point_exposes_lexicographic_fitness_key(self) -> None:
        """Mốc hợp lệ phải giữ ba score riêng theo đúng thứ tự ưu tiên."""

        point = ConvergencePoint(
            iteration=3,
            fitness_evaluations=120,
            time_stability_score=0.1,
            general_quality_score=0.2,
            lecturer_preference_score=0.3,
        )

        self.assertEqual(point.iteration, 3)
        self.assertEqual(point.fitness_evaluations, 120)
        self.assertEqual(point.fitness_key, (0.1, 0.2, 0.3))

    def test_initial_population_can_use_iteration_zero(self) -> None:
        """Quần thể đã đánh giá trước vòng đầu được phép ghi tại iteration 0."""

        point = ConvergencePoint(
            iteration=0,
            fitness_evaluations=30,
            time_stability_score=0.0,
            general_quality_score=0.0,
            lecturer_preference_score=0.0,
        )

        self.assertEqual(point.iteration, 0)
        self.assertEqual(point.fitness_evaluations, 30)

    def test_negative_iteration_is_rejected(self) -> None:
        """Iteration âm không biểu diễn một thời điểm hợp lệ của optimizer."""

        with self.assertRaises(ValueError):
            ConvergencePoint(
                iteration=-1,
                fitness_evaluations=30,
                time_stability_score=0.0,
                general_quality_score=0.0,
                lecturer_preference_score=0.0,
            )

    def test_non_positive_fitness_evaluations_are_rejected(self) -> None:
        """Không tạo mốc hội tụ giả trước lần đánh giá Fitness đầu tiên."""

        for invalid_evaluations in (0, -1):
            with self.subTest(fitness_evaluations=invalid_evaluations):
                with self.assertRaises(ValueError):
                    ConvergencePoint(
                        iteration=0,
                        fitness_evaluations=invalid_evaluations,
                        time_stability_score=0.0,
                        general_quality_score=0.0,
                        lecturer_preference_score=0.0,
                    )

    def test_negative_score_is_rejected_in_every_tier(self) -> None:
        """Không tầng fitness nào được nhận score âm."""

        invalid_scores = (
            (-0.1, 0.0, 0.0),
            (0.0, -0.1, 0.0),
            (0.0, 0.0, -0.1),
        )

        for scores in invalid_scores:
            with self.subTest(scores=scores):
                with self.assertRaises(ValueError):
                    ConvergencePoint(
                        iteration=1,
                        fitness_evaluations=30,
                        time_stability_score=scores[0],
                        general_quality_score=scores[1],
                        lecturer_preference_score=scores[2],
                    )

    def test_non_finite_score_is_rejected_in_every_tier(self) -> None:
        """NaN và vô cực không được đi vào dữ liệu convergence."""

        for invalid_value in (float("nan"), float("inf"), float("-inf")):
            for score_index in range(3):
                scores = [0.0, 0.0, 0.0]
                scores[score_index] = invalid_value

                with self.subTest(
                    invalid_value=invalid_value,
                    score_index=score_index,
                ):
                    with self.assertRaises(ValueError):
                        ConvergencePoint(
                            iteration=1,
                            fitness_evaluations=30,
                            time_stability_score=scores[0],
                            general_quality_score=scores[1],
                            lecturer_preference_score=scores[2],
                        )

    def test_time_stability_remains_the_first_comparison_tier(self) -> None:
        """Q_general tốt hơn không được bù cho Q_time kém hơn."""

        stable_schedule = ConvergencePoint(
            iteration=1,
            fitness_evaluations=30,
            time_stability_score=0.0,
            general_quality_score=1.0,
            lecturer_preference_score=1.0,
        )
        unstable_schedule = ConvergencePoint(
            iteration=1,
            fitness_evaluations=30,
            time_stability_score=0.1,
            general_quality_score=0.0,
            lecturer_preference_score=0.0,
        )

        self.assertLess(
            stable_schedule.fitness_key,
            unstable_schedule.fitness_key,
        )

    def test_point_is_immutable(self) -> None:
        """Lịch sử hội tụ không được thay đổi sau khi mốc đã được ghi."""

        point = ConvergencePoint(
            iteration=1,
            fitness_evaluations=30,
            time_stability_score=0.0,
            general_quality_score=0.0,
            lecturer_preference_score=0.0,
        )

        with self.assertRaises(FrozenInstanceError):
            point.iteration = 2


class TestOptimizationMetrics(unittest.TestCase):
    """Kiểm tra số liệu tổng hợp dùng chung cho một lần chạy optimizer."""

    @staticmethod
    def create_valid_metrics(**overrides: int | float) -> OptimizationMetrics:
        """Tạo dữ liệu hợp lệ, cho phép từng test thay đúng trường cần xét."""

        values: dict[str, int | float] = {
            "completed_iterations": 10,
            "candidate_attempts": 420,
            "fitness_evaluations": 300,
            "decode_failed_count": 80,
            "validation_failed_count": 40,
            "repaired_individual_count": 25,
            "failed_repair_count": 15,
            "total_repair_attempts": 40,
            "discarded_offspring_count": 4,
            "total_decode_nodes": 4_500,
            "total_decode_backtracks": 700,
            "runtime_seconds": 1.25,
        }
        values.update(overrides)
        return OptimizationMetrics(**values)

    def test_valid_metrics_keep_all_run_counters(self) -> None:
        """Số liệu hợp lệ phải giữ nguyên các bộ đếm đã được tổng hợp."""

        metrics = self.create_valid_metrics()

        self.assertEqual(metrics.completed_iterations, 10)
        self.assertEqual(metrics.candidate_attempts, 420)
        self.assertEqual(metrics.fitness_evaluations, 300)
        self.assertEqual(metrics.total_decode_nodes, 4_500)
        self.assertEqual(metrics.runtime_seconds, 1.25)

    def test_rejected_candidate_count_combines_two_failure_stages(self) -> None:
        """Tổng bị loại gồm decode thất bại và validation thất bại."""

        metrics = self.create_valid_metrics(
            decode_failed_count=7,
            validation_failed_count=5,
        )

        self.assertEqual(metrics.rejected_candidate_count, 12)

    def test_zero_counts_and_zero_runtime_are_allowed(self) -> None:
        """Kết quả rỗng ban đầu vẫn được biểu diễn mà không tạo số âm giả."""

        metrics = self.create_valid_metrics(
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

        self.assertEqual(metrics.rejected_candidate_count, 0)

    def test_negative_integer_count_is_rejected_for_every_field(self) -> None:
        """Mỗi bộ đếm nguyên đều phải từ 0 trở lên."""

        integer_fields = (
            "completed_iterations",
            "candidate_attempts",
            "fitness_evaluations",
            "decode_failed_count",
            "validation_failed_count",
            "repaired_individual_count",
            "failed_repair_count",
            "total_repair_attempts",
            "discarded_offspring_count",
            "total_decode_nodes",
            "total_decode_backtracks",
        )

        for field_name in integer_fields:
            with self.subTest(field_name=field_name):
                with self.assertRaises(ValueError):
                    self.create_valid_metrics(**{field_name: -1})

    def test_fitness_evaluations_cannot_exceed_candidate_attempts(self) -> None:
        """Một ứng viên không thể tạo ra nhiều hơn một FE trong pipeline."""

        with self.assertRaises(ValueError):
            self.create_valid_metrics(
                candidate_attempts=9,
                fitness_evaluations=10,
            )

    def test_invalid_runtime_is_rejected(self) -> None:
        """Thời gian âm, NaN và vô cực không được lưu vào kết quả run."""

        for invalid_runtime in (
            -0.1,
            float("nan"),
            float("inf"),
            float("-inf"),
        ):
            with self.subTest(runtime_seconds=invalid_runtime):
                with self.assertRaises(ValueError):
                    self.create_valid_metrics(runtime_seconds=invalid_runtime)

    def test_metrics_are_immutable(self) -> None:
        """Không được sửa số liệu sau khi kết quả run đã được tạo."""

        metrics = self.create_valid_metrics()

        with self.assertRaises(FrozenInstanceError):
            metrics.fitness_evaluations = 301


class TestOptimizationResult(unittest.TestCase):
    """Kiểm tra hợp đồng kết quả chuẩn hóa của các optimizer."""

    @staticmethod
    def create_individual(
        fitness_key: tuple[float, float, float],
    ) -> TimetableIndividual:
        """Tạo cá thể tối giản có FitnessResult hợp lệ cho test hợp đồng."""

        breakdown = FitnessBreakdown(
            weekday_change_count=0,
            start_period_change_count=0,
            room_change_count=0,
            valid_time_exception_count=0,
            comparable_time_session_count=0,
            comparable_physical_session_count=0,
            capacity_component=0.0,
            gap_component=0.0,
            room_discouraged_component=0.0,
            room_stability_component=0.0,
            lecturer_breakdown=(),
        )
        fitness = FitnessResult(
            time_stability_score=fitness_key[0],
            general_quality_score=fitness_key[1],
            lecturer_preference_score=fitness_key[2],
            breakdown=breakdown,
        )
        return TimetableIndividual(
            vector=(0.5,),
            selected_options=(),
            selected_option_indices=(),
            fitness=fitness,
            decode_nodes_explored=1,
            decode_backtracks=0,
            repair_attempts=0,
            was_repaired=False,
        )

    @staticmethod
    def create_metrics(
        completed_iterations: int = 1,
        fitness_evaluations: int = 20,
    ) -> OptimizationMetrics:
        """Tạo metrics nhất quán với lịch sử mặc định của test."""

        return OptimizationMetrics(
            completed_iterations=completed_iterations,
            candidate_attempts=fitness_evaluations,
            fitness_evaluations=fitness_evaluations,
            decode_failed_count=0,
            validation_failed_count=0,
            repaired_individual_count=0,
            failed_repair_count=0,
            total_repair_attempts=0,
            discarded_offspring_count=0,
            total_decode_nodes=fitness_evaluations,
            total_decode_backtracks=0,
            runtime_seconds=0.1,
        )

    @staticmethod
    def create_point(
        iteration: int,
        fitness_evaluations: int,
        fitness_key: tuple[float, float, float],
    ) -> ConvergencePoint:
        """Chuyển một khóa Gate F thành mốc hội tụ tương ứng."""

        return ConvergencePoint(
            iteration=iteration,
            fitness_evaluations=fitness_evaluations,
            time_stability_score=fitness_key[0],
            general_quality_score=fitness_key[1],
            lecturer_preference_score=fitness_key[2],
        )

    def create_valid_result(self) -> OptimizationResult:
        """Tạo kết quả có best tốt dần và khớp metrics cuối."""

        best = self.create_individual((1.0, 2.0, 3.0))
        history = (
            self.create_point(0, 10, (2.0, 0.0, 0.0)),
            self.create_point(1, 20, best.fitness_key),
        )
        return OptimizationResult(
            algorithm=OptimizationAlgorithm.PO,
            best_individual=best,
            final_population=(best,),
            convergence_history=history,
            metrics=self.create_metrics(),
        )

    def test_valid_result_keeps_all_common_outputs(self) -> None:
        """Kết quả hợp lệ phải giữ thuật toán, best, population và metrics."""

        result = self.create_valid_result()

        self.assertEqual(result.algorithm, OptimizationAlgorithm.PO)
        self.assertEqual(result.best_individual.fitness_key, (1.0, 2.0, 3.0))
        self.assertEqual(len(result.final_population), 1)
        self.assertEqual(len(result.convergence_history), 2)
        self.assertEqual(result.metrics.fitness_evaluations, 20)

    def test_result_requires_population_and_convergence_history(self) -> None:
        """Kết quả thành công không được thiếu quần thể hoặc lịch sử."""

        valid = self.create_valid_result()

        with self.assertRaisesRegex(ValueError, "final_population"):
            OptimizationResult(
                algorithm=valid.algorithm,
                best_individual=valid.best_individual,
                final_population=(),
                convergence_history=valid.convergence_history,
                metrics=valid.metrics,
            )

        with self.assertRaisesRegex(ValueError, "convergence_history"):
            OptimizationResult(
                algorithm=valid.algorithm,
                best_individual=valid.best_individual,
                final_population=valid.final_population,
                convergence_history=(),
                metrics=valid.metrics,
            )

    def test_history_must_start_at_iteration_zero(self) -> None:
        """Mốc đầu tiên luôn đại diện cho quần thể ban đầu."""

        best = self.create_individual((1.0, 0.0, 0.0))

        with self.assertRaisesRegex(ValueError, "iteration bằng 0"):
            OptimizationResult(
                algorithm=OptimizationAlgorithm.PO,
                best_individual=best,
                final_population=(best,),
                convergence_history=(
                    self.create_point(1, 20, best.fitness_key),
                ),
                metrics=self.create_metrics(),
            )

    def test_history_order_and_best_so_far_cannot_regress(self) -> None:
        """Iteration, FE và best-so-far phải tiến triển đúng hướng."""

        best = self.create_individual((1.0, 0.0, 0.0))
        metrics = self.create_metrics()
        invalid_histories = (
            (
                self.create_point(0, 10, (2.0, 0.0, 0.0)),
                self.create_point(0, 20, best.fitness_key),
            ),
            (
                self.create_point(0, 21, (2.0, 0.0, 0.0)),
                self.create_point(1, 20, best.fitness_key),
            ),
            (
                self.create_point(0, 10, (0.5, 0.0, 0.0)),
                self.create_point(1, 20, best.fitness_key),
            ),
        )

        for history in invalid_histories:
            with self.subTest(history=history):
                with self.assertRaises(ValueError):
                    OptimizationResult(
                        algorithm=OptimizationAlgorithm.PO,
                        best_individual=best,
                        final_population=(best,),
                        convergence_history=history,
                        metrics=metrics,
                    )

    def test_last_point_must_match_metrics_and_best_individual(self) -> None:
        """Mốc cuối phải đồng nhất với counters và nghiệm tốt nhất trả về."""

        valid = self.create_valid_result()

        with self.assertRaisesRegex(ValueError, "completed_iterations"):
            OptimizationResult(
                algorithm=valid.algorithm,
                best_individual=valid.best_individual,
                final_population=valid.final_population,
                convergence_history=valid.convergence_history,
                metrics=self.create_metrics(completed_iterations=2),
            )

        with self.assertRaisesRegex(ValueError, "FE cuối"):
            OptimizationResult(
                algorithm=valid.algorithm,
                best_individual=valid.best_individual,
                final_population=valid.final_population,
                convergence_history=valid.convergence_history,
                metrics=self.create_metrics(fitness_evaluations=21),
            )

        other_best = self.create_individual((0.5, 0.0, 0.0))
        with self.assertRaisesRegex(ValueError, "best_individual"):
            OptimizationResult(
                algorithm=valid.algorithm,
                best_individual=other_best,
                final_population=valid.final_population,
                convergence_history=valid.convergence_history,
                metrics=valid.metrics,
            )

    def test_result_is_immutable(self) -> None:
        """Không được đổi nghiệm tốt nhất sau khi run đã trả kết quả."""

        result = self.create_valid_result()

        with self.assertRaises(FrozenInstanceError):
            result.algorithm = OptimizationAlgorithm.GA


if __name__ == "__main__":
    unittest.main()
