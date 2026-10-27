"""Kiểm thử runner so sánh GA, PO và GA–PO trên bài toán lịch."""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gapo_timetabling.application.experiment import (
    EXPERIMENT_SCHEMA_VERSION,
    ExperimentContractError,
    _assign_seed_ranks,
    generate_experiment_plots,
    load_experiment_config,
    run_experiment,
)
from tests.test_run_contract import make_run_request_payload
from tests.test_snapshot import make_snapshot_payload


class TestExperimentContract(unittest.TestCase):
    """Bảo vệ các điều kiện làm cho phép so sánh có thể tái lập."""

    @staticmethod
    def write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_relative_base_request_is_resolved_from_config_directory(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = root / "experiment.json"
            self.write_json(config_path, {
                "schema_version": EXPERIMENT_SCHEMA_VERSION,
                "experiment_id": "contract-test",
                "base_request_path": "input/request.json",
                "algorithms": ["GA", "PO", "GA_PO"],
                "seeds": [1, 2, 3],
            })

            config = load_experiment_config(config_path)

        self.assertEqual(
            config.base_request_path,
            (root / "input/request.json").resolve(),
        )
        self.assertFalse(config.include_greedy_baseline)

    def test_duplicate_seed_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "experiment.json"
            self.write_json(config_path, {
                "schema_version": EXPERIMENT_SCHEMA_VERSION,
                "experiment_id": "duplicate-seed",
                "base_request_path": "request.json",
                "algorithms": ["GA", "PO"],
                "seeds": [7, 7],
            })

            with self.assertRaisesRegex(ExperimentContractError, "trùng"):
                load_experiment_config(config_path)

    def test_official_config_locks_light_protocol_and_greedy_baseline(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        config = load_experiment_config(
            project_root
            / "benchmark_configs"
            / "timetable_benchmark_official_2027_HK1.json"
        )
        request = json.loads(
            config.base_request_path.read_text(encoding="utf-8")
        )

        self.assertEqual(config.seeds, tuple(range(1, 11)))
        self.assertTrue(config.include_greedy_baseline)
        self.assertEqual(
            [item.value for item in config.algorithms],
            ["GA", "PO", "GA_PO"],
        )
        self.assertEqual(request["population_size"], 30)
        self.assertEqual(request["max_fitness_evaluations"], 630)
        self.assertEqual(
            request["snapshot"]["checksum"],
            "5b2f2c87fb1f97cdf484ccc3aec1e27d2548872de6209241c4132d3e38080a65",
        )

    def test_equal_lexicographic_scores_receive_average_rank(self) -> None:
        rows = [
            {
                "algorithm": "GA",
                "seed": 9,
                "status": "COMPLETED",
                "q_general": 0.2,
                "q_lecturer": 0.3,
                "rank": "",
            },
            {
                "algorithm": "PO",
                "seed": 9,
                "status": "COMPLETED",
                "q_general": 0.2,
                "q_lecturer": 0.3,
                "rank": "",
            },
            {
                "algorithm": "GA_PO",
                "seed": 9,
                "status": "COMPLETED",
                "q_general": 0.0,
                "q_lecturer": 0.0,
                "rank": "",
            },
        ]

        _assign_seed_ranks(rows)

        self.assertEqual(rows[0]["rank"], 2.5)
        self.assertEqual(rows[1]["rank"], 2.5)
        self.assertEqual(rows[2]["rank"], 1.0)


class TestExperimentExecution(unittest.TestCase):
    """Chạy thật ba optimizer và kiểm chứng toàn bộ artifact đầu ra."""

    @staticmethod
    def write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_runner_saves_baseline_and_three_optimizer_results(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot_path = root / "snapshot.json"
            request_path = root / "request.json"
            config_path = root / "experiment.json"
            output_directory = root / "results"

            self.write_json(snapshot_path, make_snapshot_payload())
            self.write_json(
                request_path,
                make_run_request_payload(snapshot_path.name),
            )
            self.write_json(config_path, {
                "schema_version": EXPERIMENT_SCHEMA_VERSION,
                "experiment_id": "end-to-end-test",
                "base_request_path": request_path.name,
                "algorithms": ["GA", "PO", "GA_PO"],
                "seeds": [11],
                "include_greedy_baseline": True,
                "create_plots": True,
            })

            config = load_experiment_config(config_path)
            paths = run_experiment(config, output_directory)

            with paths.raw_results_csv.open(encoding="utf-8-sig") as file:
                raw_results = list(csv.DictReader(file))
            with paths.summary_csv.open(encoding="utf-8-sig") as file:
                summary = list(csv.DictReader(file))
            metadata = json.loads(paths.metadata_json.read_text(encoding="utf-8"))

            for algorithm in ("GA", "PO", "GA_PO"):
                run_path = paths.runs_directory / algorithm / "seed_11.json"
                result = json.loads(run_path.read_text(encoding="utf-8"))
                self.assertEqual(result["status"], "COMPLETED")
                self.assertEqual(result["algorithm"], algorithm)
                self.assertEqual(
                    result["result"]["metrics"]["fitness_evaluations"],
                    4,
                )

            self.assertIsNotNone(paths.baseline_result_json)
            baseline = json.loads(
                paths.baseline_result_json.read_text(encoding="utf-8")
            )
            self.assertEqual(baseline["status"], "COMPLETED")
            self.assertEqual(
                baseline["algorithm"],
                "GREEDY_FIRST_FEASIBLE",
            )
            self.assertEqual(
                baseline["result"]["metrics"]["fitness_evaluations"],
                1,
            )
            self.assertIsNotNone(paths.plot_manifest_json)
            plot_manifest = json.loads(
                paths.plot_manifest_json.read_text(encoding="utf-8")
            )
            self.assertEqual(plot_manifest["failed"], [])
            self.assertEqual(len(paths.plot_images), 12)
            self.assertEqual(
                {path.name for path in paths.plot_images},
                {
                    "01_convergence.png",
                    "02_fitness_comparison.png",
                    "03_runtime_and_fe.png",
                    "04_search_diagnostics.png",
                    "05_rank_and_wins.png",
                    "06_objective_space.png",
                    "07_per_seed_scores.png",
                    "08_success_rate.png",
                    "09_best_timetable_GA.png",
                    "09_best_timetable_PO.png",
                    "09_best_timetable_GA_PO.png",
                    "09_best_timetable_GREEDY_FIRST_FEASIBLE.png",
                },
            )
            self.assertTrue(all(path.exists() for path in paths.plot_images))

            # Ảnh phải có thể được tạo lại chỉ từ artifact đã lưu, không gọi
            # lại bất kỳ optimizer nào.
            for image_path in paths.plot_images:
                image_path.unlink()
            regenerated, regenerated_manifest = generate_experiment_plots(
                config,
                output_directory,
            )
            self.assertEqual(len(regenerated), 12)
            self.assertTrue(regenerated_manifest.exists())
            self.assertTrue(all(path.exists() for path in regenerated))

        self.assertEqual(len(raw_results), 4)
        self.assertTrue(all(row["status"] == "COMPLETED" for row in raw_results))
        self.assertEqual(len(summary), 4)
        self.assertEqual(metadata["planned_optimizer_run_count"], 3)
        self.assertEqual(metadata["planned_baseline_run_count"], 1)
        self.assertEqual(metadata["planned_run_count"], 4)
        self.assertEqual(metadata["completed_run_count"], 4)
        self.assertEqual(metadata["base_request"]["population_size"], 2)
        self.assertEqual(len(metadata["snapshot_checksums"]), 1)


if __name__ == "__main__":
    unittest.main()
