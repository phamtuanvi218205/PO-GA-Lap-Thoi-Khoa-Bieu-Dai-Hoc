"""Test cac thanh phan quan trong truoc khi chay benchmark dai."""

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
    get_classical_suite,
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


class StubRng:
    """RNG toi thieu de khoa ket qua tung cong thuc PO trong unit test."""

    def __init__(self, random_values=(), normal_values=()):
        self.random_values = iter(random_values)
        self.normal_values = iter(normal_values)

    def random(self):
        return next(self.random_values)

    def standard_normal(self):
        return next(self.normal_values)


class TestBenchmarkFunctions(unittest.TestCase):
    def test_known_optimum_of_every_classical_function(self) -> None:
        dimensions = 5
        known_positions = {
            "Sphere": np.zeros(dimensions),
            "Bent Cigar": np.zeros(dimensions),
            "Rosenbrock": np.ones(dimensions),
            "Rastrigin": np.zeros(dimensions),
            "Ackley": np.zeros(dimensions),
            "Griewank": np.zeros(dimensions),
            "Schwefel": np.full(dimensions, 420.9687462275036),
            "Levy": np.ones(dimensions),
            "Zakharov": np.zeros(dimensions),
        }

        for function in get_classical_suite():
            with self.subTest(function=function.name):
                population = known_positions[function.name].reshape(1, -1)
                value = function.evaluate_population(population)[0]
                self.assertAlmostEqual(value, function.optimum_value, places=5)

    def test_same_seed_creates_same_initial_population(self) -> None:
        function = get_classical_suite()[0]
        first = create_initial_population(function, 5, 10, seed=42)
        second = create_initial_population(function, 5, 10, seed=42)
        np.testing.assert_array_equal(first, second)

    def test_all_cec2022_functions_load_and_return_finite_values(self) -> None:
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
    def test_po_v2_four_behaviors_match_reference_equations(self) -> None:
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
        rng = np.random.default_rng(42)
        step = levy_flight(20, rng)
        self.assertEqual(step.shape, (20,))
        self.assertTrue(np.all(np.isfinite(step)))

    def test_every_algorithm_respects_bounds_budget_and_history(self) -> None:
        function = get_classical_suite()[0]
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
        function = get_classical_suite()[0]
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
        function = get_classical_suite()[0]
        initial_population = np.ones((10, 2), dtype=float)
        initial_population[0] = 0.0

        def bad_ga_children(population, *args, **kwargs):
            return np.full_like(population, 50.0)

        def bad_po_children(*args, **kwargs):
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
        function = get_classical_suite()[0]
        initial_population = np.asarray([[2.0], [1.0]])
        observed_best_positions = []

        def controlled_position(*args, **kwargs):
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
    def test_function_names_use_natural_numeric_order(self) -> None:
        names = ["CEC2022-F10", "CEC2022-F2", "CEC2022-F1", "Sphere"]

        self.assertEqual(
            sorted(names, key=function_sort_key),
            ["CEC2022-F1", "CEC2022-F2", "CEC2022-F10", "Sphere"],
        )

    def test_seed_shard_keeps_only_requested_profile_seeds(self) -> None:
        full = get_profile("cec2022")
        shard = restrict_seed_range(full, 9, 16)

        self.assertEqual(shard.seeds, tuple(range(9, 17)))
        self.assertEqual(shard.dimensions, full.dimensions)
        self.assertEqual(shard.population_size, full.population_size)
        self.assertEqual(shard.max_evaluations, full.max_evaluations)

    def test_result_below_known_optimum_is_rejected(self) -> None:
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
        pilot = get_profile("cec2022_pilot")
        official = get_profile("cec2022")

        self.assertEqual(pilot.dimensions, official.dimensions)
        self.assertEqual(pilot.population_size, official.population_size)
        self.assertLess(pilot.max_evaluations, official.max_evaluations)
        self.assertLess(len(pilot.seeds), len(official.seeds))

    def test_history_sampling_keeps_first_last_and_limit(self) -> None:
        evaluations = list(range(1, 10_001))
        best_values = [float(10_001 - value) for value in evaluations]
        sampled = _sample_history(evaluations, best_values, maximum_points=101)

        self.assertEqual(len(sampled), 101)
        self.assertEqual(sampled[0], (1, 10_000.0))
        self.assertEqual(sampled[-1], (10_000, 1.0))

    def test_resume_skips_completed_runs_without_duplicate_rows(self) -> None:
        function = get_classical_suite()[0]
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
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            _write_or_validate_config(config_path, get_profile("smoke"))

            with self.assertRaises(ValueError):
                _write_or_validate_config(config_path, get_profile("standard"))

    def test_config_records_the_algorithm_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            _write_or_validate_config(config_path, get_profile("smoke"))
            content = config_path.read_text(encoding="utf-8")

        self.assertIn(BENCHMARK_PROTOCOL["version"], content)
        self.assertIn(BENCHMARK_PROTOCOL["po_reference"]["commit"], content)
        self.assertIn("survivor_selection", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
