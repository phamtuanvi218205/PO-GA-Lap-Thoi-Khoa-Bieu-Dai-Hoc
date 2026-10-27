"""Kiểm tra ba snapshot dùng cho thực nghiệm khả năng mở rộng sau này."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.greedy_baseline import (
    GreedyBaselineStatus,
    run_greedy_first_feasible,
)
from gapo_timetabling.core.population import CandidateEvaluationConfig
from gapo_timetabling.core.snapshot import (
    SnapshotPreparationStatus,
    checksum_json,
    prepare_snapshot_for_optimization,
)


DATA_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "demo_data"
    / "scalability"
)
MANIFEST_PATH = DATA_DIRECTORY / "manifest.json"
EXPECTED_PROFILES = {
    "small": {
        "section_count": 3,
        "teaching_part_count": 6,
        "class_session_count": 58,
        "dimension": 9,
    },
    "medium": {
        "section_count": 7,
        "teaching_part_count": 14,
        "class_session_count": 132,
        "dimension": 21,
    },
    "large": {
        "section_count": 10,
        "teaching_part_count": 20,
        "class_session_count": 190,
        "dimension": 30,
    },
}


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _profile_rows() -> list[dict]:
    return _load_manifest()["profiles"]


def test_manifest_records_increasing_problem_size_without_benchmark_results() -> None:
    manifest = _load_manifest()

    assert manifest["benchmark_executed"] is False
    assert [item["profile"] for item in manifest["profiles"]] == [
        "small",
        "medium",
        "large",
    ]
    for row in manifest["profiles"]:
        expected = EXPECTED_PROFILES[row["profile"]]
        for key, value in expected.items():
            assert row[key] == value

    assert [item["dimension"] for item in manifest["profiles"]] == [9, 21, 30]
    assert [item["load_pressure_ratio"] for item in manifest["profiles"]] == [
        0.291667,
        0.666667,
        0.766667,
    ]


@pytest.mark.parametrize("profile", ["small", "medium", "large"])
def test_scalability_snapshot_is_d109_ready_and_checksum_matches(
    profile: str,
) -> None:
    row = next(item for item in _profile_rows() if item["profile"] == profile)
    path = DATA_DIRECTORY / row["file"]
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert checksum_json(payload) == row["snapshot_sha256"]
    constraint_codes = {
        item["constraint_code"] for item in payload["constraint_settings"]
    }
    assert "HARD_ROOM_CAPACITY" in constraint_codes
    assert "SOFT_CAPACITY" not in constraint_codes

    prepared = prepare_snapshot_for_optimization(path)
    assert prepared.status == SnapshotPreparationStatus.READY
    assert prepared.no_option_issues == ()
    assert prepared.problem.dimension == EXPECTED_PROFILES[profile]["dimension"]


@pytest.mark.parametrize("profile", ["small", "medium", "large"])
def test_scalability_snapshot_contains_at_least_one_valid_timetable(
    profile: str,
) -> None:
    """Feasibility smoke dùng đúng một Greedy run, không phải benchmark."""

    row = next(item for item in _profile_rows() if item["profile"] == profile)
    prepared = prepare_snapshot_for_optimization(DATA_DIRECTORY / row["file"])
    result = run_greedy_first_feasible(
        prepared.problem,
        prepared.option_domains,
        CandidateEvaluationConfig(
            max_decode_nodes=200_000,
            enable_repair=False,
            max_repair_attempts=0,
        ),
    )

    assert result.status == GreedyBaselineStatus.COMPLETED
    assert result.individual is not None
    assert len(result.individual.selected_options) == row["class_session_count"]
    assert validate_timetable(
        prepared.problem,
        result.individual.selected_options,
    ).is_valid
