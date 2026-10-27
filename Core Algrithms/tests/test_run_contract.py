"""Kiểm thử hợp đồng JSON và CLI dùng chung cho ba optimizer lịch."""

from __future__ import annotations

import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from gapo_timetabling.application.run_cli import main
from gapo_timetabling.application.run_contract import (
    REQUEST_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    RunContractError,
    RunErrorCode,
    execute_run_request,
    parse_run_request,
)
from tests.test_snapshot import make_snapshot_payload


def make_run_request_payload(
    snapshot_path: str,
    *,
    algorithm: str = "GA_PO",
) -> dict:
    """Tạo request nhỏ nhưng đi qua đúng pipeline production của Python."""

    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "request_id": f"test-{algorithm.lower()}",
        "algorithm": algorithm,
        "snapshot": {"path": snapshot_path},
        "population_size": 2,
        "max_fitness_evaluations": 4,
        "random_seed": 73,
        "max_initialization_attempts": 20,
        "max_offspring_attempts": 2,
        "evaluation": {
            "max_decode_nodes": 100,
            "enable_repair": False,
            "max_repair_attempts": 0,
        },
        "ga": {
            "tournament_size": 2,
            "crossover_probability": 0.9,
            "crossover_distribution_index": 15.0,
            "mutation_probability": None,
            "mutation_distribution_index": 20.0,
        },
        "hybrid": {"ga_ratio": 0.5},
    }


class TestRunRequestContract(unittest.TestCase):
    """Bảo vệ version, đường dẫn và các giới hạn dùng chung của request."""

    def test_relative_snapshot_path_is_resolved_from_request_directory(self) -> None:
        base_directory = Path("C:/temporary/run-42")
        request = parse_run_request(
            make_run_request_payload("input/problem-instance.json"),
            base_directory=base_directory,
        )

        self.assertEqual(request.algorithm.value, "GA_PO")
        self.assertEqual(
            request.snapshot.path,
            (base_directory / "input/problem-instance.json").resolve(),
        )
        self.assertFalse(request.evaluation_config.enable_repair)

    def test_unknown_contract_version_is_rejected(self) -> None:
        payload = make_run_request_payload("snapshot.json")
        payload["schema_version"] = "optimization-run-request.v2"

        with self.assertRaises(RunContractError) as context:
            parse_run_request(payload, base_directory=Path.cwd())

        self.assertEqual(context.exception.code, RunErrorCode.INVALID_REQUEST)

    def test_fe_after_initialization_must_form_complete_iterations(self) -> None:
        payload = make_run_request_payload("snapshot.json")
        payload["max_fitness_evaluations"] = 5

        with self.assertRaisesRegex(RunContractError, "chia hết"):
            parse_run_request(payload, base_directory=Path.cwd())

    def test_hybrid_requires_two_non_empty_branches(self) -> None:
        payload = make_run_request_payload("snapshot.json")
        payload["population_size"] = 1
        payload["max_fitness_evaluations"] = 2
        payload["max_initialization_attempts"] = 2

        with self.assertRaisesRegex(RunContractError, "hai nhánh không rỗng"):
            parse_run_request(payload, base_directory=Path.cwd())

    def test_non_finite_operator_parameter_is_rejected(self) -> None:
        payload = make_run_request_payload("snapshot.json")
        payload["ga"]["crossover_probability"] = float("nan")

        with self.assertRaisesRegex(RunContractError, "hữu hạn"):
            parse_run_request(payload, base_directory=Path.cwd())


class TestRunExecutionContract(unittest.TestCase):
    """Chạy thật GA, PO và GA–PO rồi kiểm tra result JSON thống nhất."""

    @staticmethod
    def write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_all_algorithms_return_the_same_result_shape(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot_path = root / "snapshot.json"
            self.write_json(snapshot_path, make_snapshot_payload())

            for algorithm in ("GA", "PO", "GA_PO"):
                with self.subTest(algorithm=algorithm):
                    request = parse_run_request(
                        make_run_request_payload(snapshot_path.name, algorithm=algorithm),
                        base_directory=root,
                    )
                    result = execute_run_request(request)

                    self.assertEqual(result["schema_version"], RESULT_SCHEMA_VERSION)
                    self.assertEqual(result["status"], "COMPLETED")
                    self.assertEqual(result["algorithm"], algorithm)
                    self.assertIsNone(result["error"])
                    self.assertEqual(
                        len(result["result"]["timetable_entries"]),
                        1,
                    )
                    self.assertEqual(
                        result["result"]["metrics"]["fitness_evaluations"],
                        4,
                    )
                    self.assertEqual(
                        result["result"]["timetable_entries"][0]["class_session_id"],
                        1001,
                    )

    def test_no_option_is_returned_as_a_structured_failure(self) -> None:
        payload = deepcopy(make_snapshot_payload())
        payload["teaching_dates"] = []

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot_path = root / "snapshot.json"
            self.write_json(snapshot_path, payload)
            request = parse_run_request(
                make_run_request_payload(snapshot_path.name),
                base_directory=root,
            )

            result = execute_run_request(request)

        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["error"]["code"], "NO_OPTION")
        self.assertEqual(result["error"]["details"][0]["class_session_id"], 1001)

    def test_cli_writes_machine_readable_result_file(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot_path = root / "snapshot.json"
            request_path = root / "request.json"
            result_path = root / "result.json"
            self.write_json(snapshot_path, make_snapshot_payload())
            self.write_json(
                request_path,
                make_run_request_payload(snapshot_path.name, algorithm="PO"),
            )
            standard_output = StringIO()
            standard_error = StringIO()

            with redirect_stdout(standard_output), redirect_stderr(standard_error):
                exit_code = main([
                    str(request_path),
                    "--result",
                    str(result_path),
                ])

            payload = json.loads(result_path.read_text(encoding="utf-8"))
            final_event = json.loads(standard_output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(standard_error.getvalue(), "")
        self.assertEqual(payload["status"], "COMPLETED")
        self.assertEqual(payload["algorithm"], "PO")
        self.assertEqual(final_event["event"], "COMPLETED")
        self.assertEqual(final_event["request_id"], "test-po")

    def test_cli_writes_invalid_request_error_instead_of_crashing(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            request_path = root / "request.json"
            result_path = root / "result.json"
            self.write_json(request_path, {"schema_version": "unknown"})

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = main([
                    str(request_path),
                    "--result",
                    str(result_path),
                ])

            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
