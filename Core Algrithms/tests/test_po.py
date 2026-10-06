"""Kiểm thử phần toán học nền tảng của Parrot Optimizer V2."""

import math
import unittest
from dataclasses import FrozenInstanceError
from random import Random
from unittest.mock import patch

from gapo_timetabling.po import (
    PoBehavior,
    PoConfig,
    calculate_population_mean,
    clip_vector_to_unit_interval,
    create_po_position,
    levy_flight,
)
from gapo_timetabling.population import CandidateEvaluationConfig


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
