"""Tests for the hybrid GA–PO timetable optimizer."""

import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from io import StringIO
import json
from math import nan
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import gapo_timetabling.hybrid as hybrid_module
from gapo_timetabling.constraints import validate_timetable
from gapo_timetabling.encoder import build_option_domains
from gapo_timetabling.hybrid import HybridConfig, main, run_hybrid
from gapo_timetabling.metrics import OptimizationResult
from gapo_timetabling.models import OptimizationAlgorithm
from gapo_timetabling.po import PoOffspringResult
from gapo_timetabling.population import (
    CandidateEvaluationConfig,
    CandidateEvaluationStatus,
    PopulationInitializationStatus,
    best_individual,
    evaluate_candidate,
    initialize_population,
)
from tests.test_constraints import ConstraintFixture
from tests.test_snapshot import make_snapshot_payload


class TestHybridConfig(unittest.TestCase):
    """Validate hybrid configuration independently of a timetable fixture."""

    @staticmethod
    def make_evaluation_config() -> CandidateEvaluationConfig:
        return CandidateEvaluationConfig(
            max_decode_nodes=100,
            enable_repair=False,
            max_repair_attempts=0,
        )

    def test_valid_configuration_builds_matching_branch_configs(self) -> None:
        config = HybridConfig(
            max_fitness_evaluations=100,
            max_offspring_attempts=3,
            seed=2026,
            evaluation_config=self.make_evaluation_config(),
            ga_ratio=0.4,
            tournament_size=4,
            crossover_probability=0.8,
            crossover_distribution_index=12.0,
            mutation_probability=0.2,
            mutation_distribution_index=18.0,
        )

        ga_config = config.create_ga_config()
        po_config = config.create_po_config()

        self.assertEqual(ga_config.max_fitness_evaluations, 100)
        self.assertEqual(ga_config.max_offspring_attempts, 3)
        self.assertEqual(ga_config.tournament_size, 4)
        self.assertEqual(ga_config.mutation_probability, 0.2)
        self.assertEqual(po_config.max_fitness_evaluations, 100)
        self.assertEqual(po_config.max_offspring_attempts, 3)
        self.assertEqual(po_config.seed, 2026)

    def test_invalid_configuration_is_rejected(self) -> None:
        base = HybridConfig(
            max_fitness_evaluations=10,
            max_offspring_attempts=2,
            seed=1,
            evaluation_config=self.make_evaluation_config(),
        )

        invalid_values = (
            ("max_fitness_evaluations", 0),
            ("max_offspring_attempts", 0),
            ("ga_ratio", 0.0),
            ("ga_ratio", 1.0),
            ("ga_ratio", nan),
            ("tournament_size", 1),
            ("crossover_probability", 1.1),
            ("crossover_distribution_index", 0.0),
            ("mutation_probability", -0.1),
            ("mutation_distribution_index", 0.0),
        )

        for field_name, invalid_value in invalid_values:
            with self.subTest(field_name=field_name, value=invalid_value):
                with self.assertRaises(ValueError):
                    replace(base, **{field_name: invalid_value})

    def test_configuration_is_immutable(self) -> None:
        config = HybridConfig(
            max_fitness_evaluations=10,
            max_offspring_attempts=2,
            seed=1,
            evaluation_config=self.make_evaluation_config(),
        )

        with self.assertRaises(FrozenInstanceError):
            config.seed = 9


class TestHybridRun(ConstraintFixture):
    """Protect branch allocation, survivor selection, metrics, and output."""

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
        """Create a valid initial population through the production pipeline."""

        initialization = initialize_population(
            self.problem,
            self.domains,
            population_size=population_size,
            max_initialization_attempts=50,
            seed=seed,
            evaluation_config=self.evaluation_config,
        )
        self.assertEqual(
            initialization.status,
            PopulationInitializationStatus.SUCCESS,
        )
        return initialization

    def make_config(
        self,
        initialization,
        *,
        iterations: int,
        max_offspring_attempts: int = 2,
        seed: int = 2026,
        ga_ratio: float = 0.5,
    ) -> HybridConfig:
        """Allocate at most one successful FE per population position."""

        return HybridConfig(
            max_fitness_evaluations=(
                initialization.fitness_evaluations
                + iterations * len(initialization.individuals)
            ),
            max_offspring_attempts=max_offspring_attempts,
            seed=seed,
            evaluation_config=self.evaluation_config,
            ga_ratio=ga_ratio,
        )

    def successful_evaluation(self):
        """Create a successful candidate result for controlled branch tests."""

        domains = tuple((option,) for option in self.valid_options)
        evaluation = evaluate_candidate(
            self.problem,
            domains,
            tuple(0.0 for _ in range(self.problem.dimension)),
            CandidateEvaluationConfig(
                max_decode_nodes=20,
                enable_repair=False,
                max_repair_attempts=0,
            ),
        )
        self.assertTrue(evaluation.is_success)
        self.assertIsNotNone(evaluation.individual)
        return evaluation

    def failed_evaluation(self):
        """Create a genuine decode failure that consumes no fitness evaluation."""

        domains = tuple((option,) for option in self.valid_options)
        evaluation = evaluate_candidate(
            self.problem,
            domains,
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
        return evaluation

    @staticmethod
    def with_fitness_score(individual, score: float):
        """Return a fixture individual with equal values in all score tiers."""

        return replace(
            individual,
            fitness=replace(
                individual.fitness,
                time_stability_score=score,
                general_quality_score=score,
                lecturer_preference_score=score,
            ),
        )

    def test_zero_iteration_returns_initial_population(self) -> None:
        initialization = self.make_initialization()
        result = run_hybrid(
            self.problem,
            self.domains,
            initialization,
            self.make_config(initialization, iterations=0),
        )

        self.assertIsInstance(result, OptimizationResult)
        self.assertEqual(result.algorithm, OptimizationAlgorithm.GA_PO)
        self.assertEqual(result.final_population, initialization.individuals)
        self.assertEqual(
            result.best_individual,
            best_individual(initialization.individuals),
        )
        self.assertEqual(result.metrics.completed_iterations, 0)
        self.assertEqual(len(result.convergence_history), 1)

    def test_each_branch_receives_the_expected_number_of_positions(self) -> None:
        initialization = self.make_initialization(population_size=4)
        config = self.make_config(initialization, iterations=1, ga_ratio=0.5)

        with patch(
            "gapo_timetabling.hybrid._try_create_ga_offspring",
            wraps=hybrid_module._try_create_ga_offspring,
        ) as ga_helper, patch(
            "gapo_timetabling.hybrid._create_and_evaluate_po_offspring",
            wraps=hybrid_module._create_and_evaluate_po_offspring,
        ) as po_helper:
            run_hybrid(
                self.problem,
                self.domains,
                initialization,
                config,
            )

        self.assertEqual(ga_helper.call_count, 2)
        self.assertEqual(po_helper.call_count, 2)

    def test_parent_union_rejects_valid_but_worse_offspring(self) -> None:
        initialization = self.make_initialization(population_size=4)
        initial_best = best_individual(initialization.individuals)
        worse_child = self.with_fitness_score(initial_best, score=10.0)
        evaluation = self.successful_evaluation()

        def ga_child(**kwargs):
            metrics = replace(
                kwargs["metrics"],
                candidate_attempts=kwargs["metrics"].candidate_attempts + 1,
                fitness_evaluations=(
                    kwargs["metrics"].fitness_evaluations + 1
                ),
            )
            return worse_child, metrics

        def po_child(**kwargs):
            metrics = replace(
                kwargs["metrics"],
                candidate_attempts=kwargs["metrics"].candidate_attempts + 1,
                fitness_evaluations=(
                    kwargs["metrics"].fitness_evaluations + 1
                ),
            )
            return PoOffspringResult(
                individual=worse_child,
                metrics=metrics,
                attempts_used=1,
                last_evaluation=replace(
                    evaluation,
                    individual=worse_child,
                ),
            )

        with patch(
            "gapo_timetabling.hybrid._try_create_ga_offspring",
            side_effect=ga_child,
        ), patch(
            "gapo_timetabling.hybrid._create_and_evaluate_po_offspring",
            side_effect=po_child,
        ):
            result = run_hybrid(
                self.problem,
                self.domains,
                initialization,
                self.make_config(initialization, iterations=1),
            )

        self.assertCountEqual(
            result.final_population,
            initialization.individuals,
        )
        self.assertEqual(result.best_individual, initial_best)

    def test_failed_offspring_leave_parent_population_available(self) -> None:
        initialization = self.make_initialization(population_size=4)
        failed_evaluation = self.failed_evaluation()

        def failed_ga_child(**kwargs):
            metrics = replace(
                kwargs["metrics"],
                candidate_attempts=kwargs["metrics"].candidate_attempts + 1,
                decode_failed_count=kwargs["metrics"].decode_failed_count + 1,
                discarded_offspring_count=(
                    kwargs["metrics"].discarded_offspring_count + 1
                ),
            )
            return None, metrics

        def failed_po_child(**kwargs):
            metrics = replace(
                kwargs["metrics"],
                candidate_attempts=kwargs["metrics"].candidate_attempts + 1,
                decode_failed_count=kwargs["metrics"].decode_failed_count + 1,
                discarded_offspring_count=(
                    kwargs["metrics"].discarded_offspring_count + 1
                ),
            )
            return PoOffspringResult(
                individual=None,
                metrics=metrics,
                attempts_used=1,
                last_evaluation=failed_evaluation,
            )

        with patch(
            "gapo_timetabling.hybrid._try_create_ga_offspring",
            side_effect=failed_ga_child,
        ), patch(
            "gapo_timetabling.hybrid._create_and_evaluate_po_offspring",
            side_effect=failed_po_child,
        ):
            result = run_hybrid(
                self.problem,
                self.domains,
                initialization,
                self.make_config(initialization, iterations=1),
            )

        self.assertCountEqual(
            result.final_population,
            initialization.individuals,
        )
        self.assertEqual(
            result.metrics.discarded_offspring_count,
            len(initialization.individuals),
        )
        self.assertEqual(
            result.metrics.fitness_evaluations,
            initialization.fitness_evaluations,
        )

    def test_real_run_is_reproducible_and_returns_a_valid_timetable(self) -> None:
        initialization = self.make_initialization(population_size=4)
        config = self.make_config(
            initialization,
            iterations=2,
            max_offspring_attempts=2,
            seed=73,
        )

        first = run_hybrid(
            self.problem,
            self.domains,
            initialization,
            config,
        )
        second = run_hybrid(
            self.problem,
            self.domains,
            initialization,
            config,
        )

        self.assertEqual(first.best_individual, second.best_individual)
        self.assertEqual(first.final_population, second.final_population)
        self.assertEqual(first.convergence_history, second.convergence_history)
        self.assertEqual(
            replace(first.metrics, runtime_seconds=0.0),
            replace(second.metrics, runtime_seconds=0.0),
        )
        self.assertEqual(len(first.convergence_history), 3)
        self.assertLessEqual(
            first.metrics.fitness_evaluations,
            config.max_fitness_evaluations,
        )

        validation = validate_timetable(
            self.problem,
            first.best_individual.selected_options,
        )
        self.assertTrue(validation.is_valid)

    def test_run_rejects_a_ratio_that_creates_an_empty_branch(self) -> None:
        initialization = self.make_initialization(population_size=2)
        config = self.make_config(
            initialization,
            iterations=0,
            ga_ratio=0.1,
        )

        with self.assertRaisesRegex(ValueError, "at least one individual"):
            run_hybrid(
                self.problem,
                self.domains,
                initialization,
                config,
            )

    def test_run_rejects_misaligned_option_domains(self) -> None:
        initialization = self.make_initialization()
        config = self.make_config(initialization, iterations=0)

        with self.assertRaisesRegex(ValueError, "Số miền option"):
            run_hybrid(
                self.problem,
                self.domains[:-1],
                initialization,
                config,
            )


class TestHybridCommandLine(unittest.TestCase):
    """Exercise the executable entry point with snapshot JSON files."""

    @staticmethod
    def write_snapshot(directory: Path, payload: dict) -> Path:
        path = directory / "problem-instance.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_main_runs_hybrid_and_prints_a_valid_timetable(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            snapshot_path = self.write_snapshot(
                Path(temporary_directory),
                make_snapshot_payload(),
            )
            standard_output = StringIO()
            standard_error = StringIO()
            report_directory = Path(temporary_directory) / "report"

            with redirect_stdout(standard_output), redirect_stderr(standard_error):
                exit_code = main([
                    str(snapshot_path),
                    "--population-size",
                    "2",
                    "--iterations",
                    "1",
                    "--max-initialization-attempts",
                    "20",
                    "--max-offspring-attempts",
                    "2",
                    "--max-decode-nodes",
                    "100",
                    "--seed",
                    "73",
                    "--output-directory",
                    str(report_directory),
                ])

            generated_report_files = {
                path.name
                for path in report_directory.iterdir()
            }

        output = standard_output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(standard_error.getvalue(), "")
        self.assertIn("KẾT QUẢ XẾP THỜI KHÓA BIỂU", output)
        self.assertIn("Số vi phạm bắt buộc       : 0", output)
        self.assertIn("TUẦN 1", output)
        self.assertIn("Thứ Hai, ngày 07/09/2026", output)
        self.assertIn("Lớp HP", output)
        self.assertIn("Lý thuyết", output)
        self.assertIn("KẾT LUẬN: Đã xếp đủ 1 buổi học", output)
        self.assertIn("CÁC TỆP KẾT QUẢ ĐÃ TẠO", output)
        self.assertIn("JAVA01", output)
        self.assertIn("B304", output)
        self.assertEqual(
            generated_report_files,
            {
                "run_summary.json",
                "convergence.csv",
                "timetable.csv",
                "01_convergence.png",
                "02_timetable_detail.png",
            },
        )

    def test_main_reports_no_option_before_initialization(self) -> None:
        payload = deepcopy(make_snapshot_payload())
        for teaching_date in payload["teaching_dates"]:
            teaching_date["status"] = "HOLIDAY"

        with TemporaryDirectory() as temporary_directory:
            snapshot_path = self.write_snapshot(
                Path(temporary_directory),
                payload,
            )
            standard_output = StringIO()
            standard_error = StringIO()

            with redirect_stdout(standard_output), redirect_stderr(standard_error):
                exit_code = main([
                    str(snapshot_path),
                    "--population-size",
                    "2",
                    "--iterations",
                    "1",
                ])

        self.assertEqual(exit_code, 3)
        self.assertEqual(standard_output.getvalue(), "")
        self.assertIn("không có phương án hợp lệ", standard_error.getvalue())

    def test_main_reports_an_unreadable_snapshot(self) -> None:
        standard_output = StringIO()
        standard_error = StringIO()

        with redirect_stdout(standard_output), redirect_stderr(standard_error):
            exit_code = main(["missing-problem-instance.json"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(standard_output.getvalue(), "")
        self.assertIn("Không thể chuẩn bị snapshot", standard_error.getvalue())


if __name__ == "__main__":
    unittest.main()
