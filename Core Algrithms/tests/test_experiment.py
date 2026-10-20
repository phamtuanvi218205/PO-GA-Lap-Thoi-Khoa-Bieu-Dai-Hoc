"""Kiểm thử runner so sánh GA, PO và GA–PO trên bài toán lịch."""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gapo_timetabling.experiment import (
    EXPERIMENT_SCHEMA_VERSION,
    ExperimentContractError,
    _assign_seed_ranks,
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

    def test_equal_lexicographic_scores_receive_average_rank(self) -> None:
        rows = [
            {
                "algorithm": "GA",
                "seed": 9,
                "status": "COMPLETED",
                "q_time": 0.0,
                "q_general": 0.2,
                "q_lecturer": 0.3,
                "rank": "",
            },
            {
                "algorithm": "PO",
                "seed": 9,
                "status": "COMPLETED",
                "q_time": 0.0,
                "q_general": 0.2,
                "q_lecturer": 0.3,
                "rank": "",
            },
            {
                "algorithm": "GA_PO",
                "seed": 9,
                "status": "COMPLETED",
                "q_time": 0.1,
                "q_general": 0.0,
                "q_lecturer": 0.0,
                "rank": "",
            },
        ]

        _assign_seed_ranks(rows)

        self.assertEqual(rows[0]["rank"], 1.5)
        self.assertEqual(rows[1]["rank"], 1.5)
        self.assertEqual(rows[2]["rank"], 3.0)


class TestExperimentExecution(unittest.TestCase):
    """Chạy thật ba optimizer và kiểm chứng toàn bộ artifact đầu ra."""

    @staticmethod
    def write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_runner_saves_three_raw_results_and_aggregate_files(self) -> None:
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
                "create_plots": False,
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

        self.assertEqual(len(raw_results), 3)
        self.assertTrue(all(row["status"] == "COMPLETED" for row in raw_results))
        self.assertEqual(len(summary), 3)
        self.assertEqual(metadata["planned_run_count"], 3)
        self.assertEqual(metadata["completed_run_count"], 3)
        self.assertEqual(metadata["base_request"]["population_size"], 2)
        self.assertEqual(len(metadata["snapshot_checksums"]), 1)


if __name__ == "__main__":
    unittest.main()
