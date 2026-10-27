"""Kiểm thử chạy riêng từng thuật toán và hợp nhất artifact benchmark."""

from __future__ import annotations

import csv
import json
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from gapo_timetabling.application.distributed_benchmark import (
    load_suite,
    merge_worker_suites,
    run_worker_suite,
)
from gapo_timetabling.application.experiment import ExperimentContractError
from gapo_timetabling.application.experiment import load_experiment_config
from gapo_timetabling.core.models import OptimizationAlgorithm
from gapo_timetabling.core.snapshot import checksum_json
from tests.test_run_contract import make_run_request_payload
from tests.test_snapshot import make_snapshot_payload


class TestDistributedBenchmark(unittest.TestCase):
    @staticmethod
    def write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def create_suite(self, root: Path) -> Path:
        snapshot_path = root / "snapshot.json"
        request_path = root / "request.json"
        experiment_path = root / "experiment.json"
        suite_path = root / "suite.json"
        snapshot_payload = make_snapshot_payload()
        self.write_json(snapshot_path, snapshot_payload)
        request_payload = make_run_request_payload(snapshot_path.name)
        request_payload["snapshot"]["checksum"] = checksum_json(snapshot_payload)
        self.write_json(
            request_path,
            request_payload,
        )
        self.write_json(experiment_path, {
            "schema_version": "timetable-experiment.v1",
            "experiment_id": "distributed-test",
            "base_request_path": request_path.name,
            "algorithms": ["GA", "PO", "GA_PO"],
            "seeds": [11],
            "include_greedy_baseline": True,
            "create_plots": True,
            "runtime_comparison_valid": False,
        })
        self.write_json(suite_path, {
            "schema_version": "distributed-benchmark-suite.v1",
            "suite_id": "distributed-test-suite",
            "cases": [{
                "case_id": "tiny",
                "label": "Tiny",
                "experiment_config_path": experiment_path.name,
                "dimension": 2,
                "class_session_count": 2,
            }],
        })
        return suite_path

    def test_official_suite_locks_three_scales_and_common_protocol(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        suite = load_suite(
            project_root
            / "benchmark_configs"
            / "distributed"
            / "timetable_scalability_suite_2027_HK1.json"
        )

        self.assertEqual(
            [(case.case_id, case.dimension, case.class_session_count) for case in suite.cases],
            [("small", 9, 58), ("medium", 21, 132), ("large", 30, 190)],
        )
        for case in suite.cases:
            config = load_experiment_config(case.experiment_config_path)
            request = json.loads(config.base_request_path.read_text(encoding="utf-8"))
            self.assertEqual(config.seeds, tuple(range(1, 11)))
            self.assertEqual(
                [algorithm.value for algorithm in config.algorithms],
                ["GA", "PO", "GA_PO"],
            )
            self.assertTrue(config.include_greedy_baseline)
            self.assertFalse(config.runtime_comparison_valid)
            self.assertEqual(request["population_size"], 30)
            self.assertEqual(request["max_fitness_evaluations"], 630)

    @patch(
        "gapo_timetabling.application.distributed_benchmark._git_source_state",
        return_value={"git_revision": "test-revision", "git_dirty": False},
    )
    def test_three_workers_can_be_merged_without_rerunning_optimizer(
        self,
        _source_state,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            suite = load_suite(self.create_suite(root))
            part_roots: list[Path] = []
            for algorithm in OptimizationAlgorithm:
                part_root = root / f"part_{algorithm.value}"
                manifest_path = run_worker_suite(suite, algorithm, part_root)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], "COMPLETED")
                part_roots.append(part_root)

            ga_result = part_roots[0] / "tiny" / "runs" / "GA" / "seed_11.json"
            original_timestamp = ga_result.stat().st_mtime_ns
            run_worker_suite(suite, OptimizationAlgorithm.GA, part_roots[0])
            self.assertEqual(ga_result.stat().st_mtime_ns, original_timestamp)

            output_root = root / "merged"
            merged_manifest_path = merge_worker_suites(
                suite,
                part_roots,
                output_root,
            )
            merged_manifest = json.loads(
                merged_manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(merged_manifest["status"], "COMPLETED")
            self.assertFalse(merged_manifest["runtime_comparison_valid"])
            self.assertEqual(len(merged_manifest["scalability_images"]), 3)

            with (output_root / "tiny" / "raw_results.csv").open(
                encoding="utf-8-sig",
                newline="",
            ) as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 4)
            self.assertEqual(
                {row["algorithm"] for row in rows},
                {"GA", "PO", "GA_PO", "GREEDY_FIRST_FEASIBLE"},
            )
            self.assertTrue(
                (output_root / "tiny" / "01_convergence.png").exists()
            )
            self.assertTrue(
                (output_root / "10_scalability_quality.png").exists()
            )

    @patch(
        "gapo_timetabling.application.distributed_benchmark._git_source_state",
        return_value={"git_revision": "test-revision", "git_dirty": False},
    )
    def test_merge_rejects_missing_worker(self, _source_state) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            suite = load_suite(self.create_suite(root))
            ga_root = root / "part_GA"
            run_worker_suite(suite, OptimizationAlgorithm.GA, ga_root)

            with self.assertRaisesRegex(ExperimentContractError, "Thiếu"):
                merge_worker_suites(suite, [ga_root], root / "merged")


if __name__ == "__main__":
    unittest.main()
