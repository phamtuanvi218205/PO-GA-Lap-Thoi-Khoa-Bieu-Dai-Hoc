"""Kiểm tra tính đúng đắn và khả năng tái lập trước khi chạy benchmark dài.

Các test bao phủ giá trị chuẩn của hàm mục tiêu, bốn công thức PO, ngân sách FE,
boundary, survivor selection, adapter CEC 2022, checkpoint/resume và dấu vết
giao thức. Đây là lớp bảo vệ để tránh tốn nhiều giờ chạy trên mã sai.
"""

import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import numpy as np


BENCHMARK_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARK_DIRECTORY))

from algorithms import (  # noqa: E402
    ALGORITHMS,
    _po_position,
    levy_flight,
    run_hybrid,
    run_po,
)
from benchmark_functions import (  # noqa: E402
    BenchmarkFunction,
    get_cec2022_suite,
)
from experiment import (  # noqa: E402
    ExperimentConfig,
    _sample_history,
    create_initial_population,
    run_experiment,
)
from run_benchmark import (  # noqa: E402
    BENCHMARK_PROTOCOL,
    _write_or_validate_config,
    get_profile,
    restrict_seed_range,
)
from ordering import function_sort_key  # noqa: E402


def _quadratic_test_objective(population: np.ndarray) -> np.ndarray:
    """Hàm giả tối thiểu dùng để cô lập logic thuật toán trong unit test.

    Hàm này không thuộc bộ benchmark và không tạo kết quả báo cáo. Nó giúp các
    test về FE, seed và survivor selection chạy nhanh mà không phụ thuộc DLL.
    """

    return np.sum(population**2, axis=1)


def _make_quadratic_test_function() -> BenchmarkFunction:
    """Đóng gói hàm giả theo cùng giao diện mà thuật toán yêu cầu."""

    return BenchmarkFunction(
        name="Quadratic test fixture",
        lower_bound=-100.0,
        upper_bound=100.0,
        optimum_value=0.0,
        evaluate_population=_quadratic_test_objective,
        category="Unit test only",
    )


class StubRng:
    """RNG tối thiểu trả giá trị định trước để kiểm tra chính xác công thức PO."""

    def __init__(self, random_values=(), normal_values=()):
        """Nhận hai chuỗi giá trị cho phân phối đều và phân phối chuẩn."""

        self.random_values = iter(random_values)
        self.normal_values = iter(normal_values)

    def random(self):
        """Trả giá trị đều giả lập tiếp theo."""

        return next(self.random_values)

    def standard_normal(self):
        """Trả giá trị Gaussian giả lập tiếp theo."""

        return next(self.normal_values)


class TestBenchmarkFunctions(unittest.TestCase):
    """Kiểm tra khởi tạo quần thể và adapter CEC 2022 chính thức."""


    def test_same_seed_creates_same_initial_population(self) -> None:
        """Cùng seed phải tái tạo chính xác cùng quần thể ban đầu."""

        function = get_cec2022_suite(dimensions=20)[0]
        first = create_initial_population(function, 20, 10, seed=42)
        second = create_initial_population(function, 20, 10, seed=42)
        np.testing.assert_array_equal(first, second)

    def test_all_cec2022_functions_load_and_return_finite_values(self) -> None:
        """Cả 12 hàm CEC phải nạp được và trả giá trị hữu hạn."""

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            suite = get_cec2022_suite(dimensions=20)

        self.assertEqual(len(suite), 12)
        for function in suite:
            with self.subTest(function=function.name):
                midpoint = np.full(
                    (1, 20),
                    (function.lower_bound + function.upper_bound) / 2.0,
                )
                value = function.evaluate_population(midpoint)
                self.assertEqual(value.shape, (1,))
                self.assertTrue(np.all(np.isfinite(value)))

    def test_cec2022_matches_official_d20_zero_vector_values(self) -> None:
        """Adapter phải khớp giá trị tham chiếu chính thức tại vector 0, D=20."""

        expected = (
            9558730232304.59,
            7508.6777109481645,
            760.3132407487321,
            1077.3586217236857,
            10492.485115390029,
            8859205369.3246,
            2691.8786415840423,
            225283.57615173256,
            6618.138143224724,
            10921.290353661823,
            10695.510621014344,
            9228.009396206773,
        )
        population = np.zeros((1, 20), dtype=float)

        for function, expected_value in zip(
            get_cec2022_suite(dimensions=20), expected
        ):
            with self.subTest(function=function.name):
                actual = function.evaluate_population(population)[0]
                self.assertAlmostEqual(
                    actual / expected_value,
                    1.0,
                    places=11,
                )

    def test_cec2022_matches_official_d20_nonzero_vector_values(self) -> None:
        """Adapter phải khớp tham chiếu tại một vector khác 0, tránh test suy biến."""

        expected = (
            2192241464296.4216,
            9334.816898448344,
            733.0946153018267,
            1163.5964331725365,
            22028.76136700086,
            17433695467.732224,
            3109.0077272329045,
            318984.9199191593,
            6225.871559679311,
            5855.534074937044,
            16055.168236772017,
            7759.905879958861,
        )
        population = np.linspace(-50.0, 50.0, 20).reshape(1, 20)

        for function, expected_value in zip(
            get_cec2022_suite(dimensions=20), expected
        ):
            with self.subTest(function=function.name):
                actual = function.evaluate_population(population)[0]
                self.assertAlmostEqual(
                    actual / expected_value,
                    1.0,
                    places=11,
                )


class TestAlgorithms(unittest.TestCase):
    """Kiểm tra công thức và hợp đồng thực thi của ba thuật toán."""

    def test_po_v2_four_behaviors_match_reference_equations(self) -> None:
        """Bốn nhánh PO V2 phải cho đúng kết quả số theo phương trình tham chiếu."""

        current = np.asarray([2.0, -1.0])
        best = np.asarray([0.5, 1.5])
        mean = np.asarray([1.0, 2.0])
        iteration = 4
        max_iterations = 10
        remaining = 1.0 - iteration / max_iterations

        with patch("algorithms.levy_flight", return_value=np.asarray([0.2, -0.4])):
            result = _po_position(
                current, 1, 1, best, mean, iteration, max_iterations,
                0.1, 0.3, StubRng(random_values=(0.25,)),
            )
        expected = (current - best) * np.asarray([0.2, -0.4]) + (
            0.25 * remaining ** (2.0 * iteration / max_iterations) * mean
        )
        np.testing.assert_allclose(result, expected)

        with patch("algorithms.levy_flight", return_value=np.asarray([0.2, -0.4])):
            result = _po_position(
                current, 1, 2, best, mean, iteration, max_iterations,
                0.1, 0.3, StubRng(normal_values=(0.75,)),
            )
        expected = current + best * np.asarray([0.2, -0.4]) + 0.75 * remaining
        np.testing.assert_allclose(result, expected)

        result = _po_position(
            current, 1, 3, best, mean, iteration, max_iterations,
            0.1, 0.3, StubRng(random_values=(0.25,)),
        )
        expected = current + 0.1 * remaining * (current - mean)
        np.testing.assert_allclose(result, expected)

        result = _po_position(
            current, 1, 3, best, mean, iteration, max_iterations,
            0.1, 0.3, StubRng(random_values=(0.75, 0.4)),
        )
        expected = current + 0.1 * remaining * np.exp(
            -2.0 / (0.4 * max_iterations)
        )
        np.testing.assert_allclose(result, expected)

        result = _po_position(
            current, 1, 4, best, mean, iteration, max_iterations,
            0.1, 0.3, StubRng(random_values=(0.2,)),
        )
        expected = (
            current
            + 0.2 * np.cos(np.pi * iteration / (2.0 * max_iterations))
            * (best - current)
            - np.cos(0.3) * (iteration / max_iterations) ** (2.0 / max_iterations)
            * (current - best)
        )
        np.testing.assert_allclose(result, expected)

    def test_levy_flight_has_expected_shape_and_finite_values(self) -> None:
        """Bước Lévy phải có đúng số chiều và không chứa NaN/vô cực."""

        rng = np.random.default_rng(42)
        step = levy_flight(20, rng)
        self.assertEqual(step.shape, (20,))
        self.assertTrue(np.all(np.isfinite(step)))

    def test_every_algorithm_respects_bounds_budget_and_history(self) -> None:
        """Mọi thuật toán phải tuân thủ biên, dùng đủ FE và lưu lịch sử hợp lệ."""

        function = _make_quadratic_test_function()
        population_size = 10
        initial_population = create_initial_population(
            function, dimensions=5, population_size=population_size, seed=7
        )

        for algorithm_name, algorithm in ALGORITHMS.items():
            with self.subTest(algorithm=algorithm_name):
                result = algorithm(
                    objective=function.evaluate_population,
                    initial_population=initial_population,
                    lower_bound=function.lower_bound,
                    upper_bound=function.upper_bound,
                    max_evaluations=100,
                    seed=99,
                )
                self.assertEqual(result.evaluations_used, 100)
                self.assertEqual(result.history_evaluations[-1], 100)
                self.assertEqual(len(result.history_best_values), 10)
                self.assertTrue(
                    np.all(result.best_position >= function.lower_bound)
                )
                self.assertTrue(
                    np.all(result.best_position <= function.upper_bound)
                )
                differences = np.diff(result.history_best_values)
                self.assertTrue(np.all(differences <= 1e-12))

    def test_every_algorithm_is_reproducible_with_the_same_seed(self) -> None:
        """Cùng input và seed phải tạo cùng nghiệm cùng đường hội tụ."""

        function = _make_quadratic_test_function()
        initial_population = create_initial_population(
            function, dimensions=5, population_size=10, seed=7
        )

        for algorithm_name, algorithm in ALGORITHMS.items():
            with self.subTest(algorithm=algorithm_name):
                arguments = {
                    "objective": function.evaluate_population,
                    "initial_population": initial_population,
                    "lower_bound": function.lower_bound,
                    "upper_bound": function.upper_bound,
                    "max_evaluations": 100,
                    "seed": 99,
                }
                first = algorithm(**arguments)
                second = algorithm(**arguments)
                np.testing.assert_array_equal(
                    first.best_position, second.best_position
                )
                self.assertEqual(first.best_value, second.best_value)
                self.assertEqual(
                    first.history_best_values, second.history_best_values
                )

    def test_hybrid_survivor_selection_keeps_a_better_parent(self) -> None:
        """Pipeline lai phải giữ cha tốt nếu toàn bộ con đều kém hơn."""

        function = _make_quadratic_test_function()
        initial_population = np.ones((10, 2), dtype=float)
        initial_population[0] = 0.0

        def bad_ga_children(population, *args, **kwargs):
            """Sinh quần thể GA cố ý kém để cô lập phép chọn survivor."""

            return np.full_like(population, 50.0)

        def bad_po_children(*args, **kwargs):
            """Sinh quần thể PO cố ý kém với đúng hình dạng nhóm nguồn."""

            source_population = kwargs["source_population"]
            return np.full_like(source_population, 50.0)

        with patch(
            "algorithms._create_ga_children", side_effect=bad_ga_children
        ), patch(
            "algorithms._create_po_children", side_effect=bad_po_children
        ):
            result = run_hybrid(
                objective=function.evaluate_population,
                initial_population=initial_population,
                lower_bound=function.lower_bound,
                upper_bound=function.upper_bound,
                max_evaluations=20,
                seed=99,
            )

        self.assertEqual(result.best_value, 0.0)
        np.testing.assert_array_equal(result.best_position, np.zeros(2))

    def test_reference_po_updates_best_inside_the_agent_loop(self) -> None:
        """PO phải cập nhật GBest ngay để cá thể sau dùng được best mới."""

        function = _make_quadratic_test_function()
        initial_population = np.asarray([[2.0], [1.0]])
        observed_best_positions = []

        def controlled_position(*args, **kwargs):
            """Điều khiển cá thể đầu tạo nghiệm 0 và ghi lại best quan sát được."""

            observed_best_positions.append(kwargs["best_position"].copy())
            if kwargs["current_index"] == 0:
                return np.zeros(1)
            return kwargs["current"].copy()

        with patch(
            "algorithms._po_position", side_effect=controlled_position
        ):
            run_po(
                objective=function.evaluate_population,
                initial_population=initial_population,
                lower_bound=function.lower_bound,
                upper_bound=function.upper_bound,
                max_evaluations=4,
                seed=99,
            )

        np.testing.assert_array_equal(observed_best_positions[0], [1.0])
        np.testing.assert_array_equal(observed_best_positions[1], [0.0])


class TestLongRunSafety(unittest.TestCase):
    """Kiểm tra các cơ chế bảo vệ dữ liệu của thí nghiệm dài."""

    def test_function_names_use_natural_numeric_order(self) -> None:
        """Tên CEC phải được sắp theo chỉ số số học thay vì từ điển."""

        names = ["CEC2022-F10", "CEC2022-F2", "CEC2022-F1", "NoSuffix"]

        self.assertEqual(
            sorted(names, key=function_sort_key),
            ["CEC2022-F1", "CEC2022-F2", "CEC2022-F10", "NoSuffix"],
        )

    def test_seed_shard_keeps_only_requested_profile_seeds(self) -> None:
        """Tách shard chỉ được thay tập seed, không đổi ngân sách hay số chiều."""

        full = get_profile("cec2022")
        shard = restrict_seed_range(full, 9, 16)

        self.assertEqual(shard.seeds, tuple(range(9, 17)))
        self.assertEqual(shard.dimensions, full.dimensions)
        self.assertEqual(shard.population_size, full.population_size)
        self.assertEqual(shard.max_evaluations, full.max_evaluations)

    def test_result_below_known_optimum_is_rejected(self) -> None:
        """Runner phải dừng khi evaluator trả giá trị thấp hơn optimum đã biết."""

        invalid_function = BenchmarkFunction(
            name="Invalid optimum",
            lower_bound=-1.0,
            upper_bound=1.0,
            optimum_value=10.0,
            evaluate_population=lambda population: np.zeros(len(population)),
            category="Test",
        )
        config = ExperimentConfig(
            profile_name="invalid_optimum_test",
            dimensions=2,
            population_size=10,
            max_evaluations=20,
            seeds=(1,),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "thap hon optimum"):
                run_experiment(
                    [invalid_function],
                    config,
                    Path(temporary_directory),
                )

    def test_cec2022_pilot_is_small_and_keeps_official_dimension(self) -> None:
        """Pilot giảm FE/seed nhưng vẫn dùng cùng số chiều hợp lệ của CEC."""

        pilot = get_profile("cec2022_pilot")
        official = get_profile("cec2022")

        self.assertEqual(pilot.dimensions, official.dimensions)
        self.assertEqual(pilot.population_size, official.population_size)
        self.assertLess(pilot.max_evaluations, official.max_evaluations)
        self.assertLess(len(pilot.seeds), len(official.seeds))

    def test_history_sampling_keeps_first_last_and_limit(self) -> None:
        """Lấy mẫu hội tụ phải giữ mốc đầu, cuối và không vượt giới hạn."""

        evaluations = list(range(1, 10_001))
        best_values = [float(10_001 - value) for value in evaluations]
        sampled = _sample_history(evaluations, best_values, maximum_points=101)

        self.assertEqual(len(sampled), 101)
        self.assertEqual(sampled[0], (1, 10_000.0))
        self.assertEqual(sampled[-1], (10_000, 1.0))

    def test_resume_skips_completed_runs_without_duplicate_rows(self) -> None:
        """Chạy lại cùng output phải bỏ qua run hoàn tất và không nhân đôi CSV."""

        function = _make_quadratic_test_function()
        config = ExperimentConfig(
            profile_name="resume_test",
            dimensions=5,
            population_size=10,
            max_evaluations=100,
            seeds=(1,),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)
            first_raw, first_convergence = run_experiment(
                [function], config, output_directory
            )
            second_raw, second_convergence = run_experiment(
                [function], config, output_directory
            )

        self.assertEqual(len(first_raw), len(ALGORITHMS))
        self.assertEqual(len(second_raw), len(first_raw))
        self.assertEqual(len(second_convergence), len(first_convergence))

    def test_existing_output_rejects_a_different_config(self) -> None:
        """Không được resume vào thư mục chứa một cấu hình khác."""

        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            _write_or_validate_config(config_path, get_profile("cec2022_pilot"))

            with self.assertRaises(ValueError):
                _write_or_validate_config(config_path, get_profile("cec2022"))

    def test_config_records_the_algorithm_protocol(self) -> None:
        """config.json phải ghi phiên bản, nguồn PO và survivor selection."""

        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            _write_or_validate_config(config_path, get_profile("cec2022_pilot"))
            content = config_path.read_text(encoding="utf-8")

        self.assertIn(BENCHMARK_PROTOCOL["version"], content)
        self.assertIn(BENCHMARK_PROTOCOL["po_reference"]["commit"], content)
        self.assertIn("survivor_selection", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
