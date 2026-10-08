"""Kiểm thử hợp đồng snapshot JSON giữa Java và Python."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from gapo_timetabling.snapshot import (  # noqa: E402
    MAPPING_SCHEMA_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    SnapshotContractError,
    SnapshotPreparationStatus,
    canonical_json,
    checksum_json,
    load_problem_instance_snapshot,
    prepare_snapshot_for_optimization,
)


def make_snapshot_payload() -> dict:
    """Tạo fixture nhỏ nhưng đi qua đủ scenario → session → option."""

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "term": {
            "term_code": "2026_HK1",
            "term_name": "Học kỳ 1 năm học 2026-2027",
            "start_date": "2026-09-07",
            "end_date": "2026-09-13",
            "status": "PLANNING",
        },
        "scenario": {
            "scenario_id": 1,
            "scenario_code": "SCN-FIXTURE",
            "term_code": "2026_HK1",
            "scope_type": "FULL_TERM",
            "status": "LOCKED",
            "items": [
                {"teaching_part_index": 0, "teaching_plan_id": 101},
            ],
        },
        "weeks": [
            {
                "week_number": 1,
                "start_date": "2026-09-07",
                "end_date": "2026-09-13",
            },
        ],
        "teaching_dates": [
            {
                "calendar_date": "2026-09-07",
                "week_number": 1,
                "iso_weekday": 1,
                "status": "NORMAL",
            },
            {
                "calendar_date": "2026-09-09",
                "week_number": 1,
                "iso_weekday": 3,
                "status": "NORMAL",
            },
        ],
        "time_periods": [
            {
                "period_number": 1,
                "start_time": "07:00:00",
                "end_time": "07:45:00",
                "session_type": "MORNING",
            },
            {
                "period_number": 2,
                "start_time": "07:50:00",
                "end_time": "08:35:00",
                "session_type": "MORNING",
            },
            {
                "period_number": 3,
                "start_time": "08:40:00",
                "end_time": "09:25:00",
                "session_type": "MORNING",
            },
        ],
        "allowed_period_blocks": [
            {"start_period": 1, "duration_periods": 3},
        ],
        "teaching_duration_rules": [
            {"part_type": "LECTURE", "duration_periods": 3, "standard": True},
        ],
        "locations": [
            {
                "location_index": 0,
                "location_id": 501,
                "location_code": "B304",
                "location_name": "Phòng B304",
                "location_type": "PHYSICAL_ROOM",
                "active": True,
                "campus_code": "CS1",
                "room_type": "LECTURE_ROOM",
                "capacity": 50,
                "equipment_quantities": [
                    {"equipment_code": "PROJECTOR", "quantity": 1},
                ],
                "platform_name": None,
            },
        ],
        "lecturers": [
            {
                "lecturer_index": 0,
                "lecturer_code": "GV001",
                "full_name": "Giảng viên 1",
                "home_campus_code": "CS1",
            },
        ],
        "courses": [
            {"course_code": "JAVA", "course_name": "Lập trình Java"},
        ],
        "course_sections": [
            {
                "section_code": "JAVA01",
                "course_code": "JAVA",
                "section_name": "Lập trình Java 01",
                "expected_enrollment": 60,
            },
        ],
        "teaching_parts": [
            {
                "teaching_part_index": 0,
                "teaching_part_id": 11,
                "part_code": "JAVA01-LT",
                "section_code": "JAVA01",
                "part_type": "LECTURE",
                "lecturer_index": 0,
                "total_periods": 3,
                "required_location_type": "PHYSICAL_ROOM",
                "required_room_type": "LECTURE_ROOM",
                "required_equipment": [
                    {"equipment_code": "PROJECTOR", "quantity": 1},
                ],
            },
        ],
        "teaching_plans": [
            {
                "teaching_plan_id": 101,
                "plan_code": "PLAN-JAVA01-LT-01",
                "teaching_part_index": 0,
                "status": "VALID",
                "allows_intensive": False,
            },
        ],
        "class_sessions": [
            {
                "session_index": 0,
                "class_session_id": 1001,
                "teaching_plan_id": 101,
                "session_number": 1,
                "stability_group_no": 1,
                "week_number": 1,
                "duration_periods": 3,
                "required_location_type": "PHYSICAL_ROOM",
            },
        ],
        "lecturer_availabilities": [],
        "room_availabilities": [],
        "campus_travel_times": [],
        "constraint_settings": [
            {
                "constraint_code": "HARD_NO_LECTURER_OVERLAP",
                "constraint_type": "HARD",
                "priority_tier": 1,
                "weight": None,
                "enabled": True,
            },
            {
                "constraint_code": "SOFT_TIME_STABILITY",
                "constraint_type": "SOFT",
                "priority_tier": 1,
                "weight": 1.0,
                "enabled": True,
            },
        ],
    }


class TestSnapshotLoader(unittest.TestCase):
    """Bảo vệ version, checksum và ánh xạ domain qua biên JSON."""

    def test_loads_v1_snapshot_into_problem_instance(self) -> None:
        payload = make_snapshot_payload()

        problem, actual_checksum = load_problem_instance_snapshot(payload)

        self.assertEqual(problem.dimension, 1)
        self.assertEqual(problem.class_sessions[0].session_index, 0)
        self.assertEqual(problem.locations[0].location_index, 0)
        self.assertEqual(problem.teaching_parts[0].part_code, "JAVA01-LT")
        self.assertEqual(actual_checksum, checksum_json(payload))

    def test_checksum_is_independent_of_object_key_order(self) -> None:
        payload = make_snapshot_payload()
        reversed_payload = dict(reversed(list(payload.items())))

        self.assertEqual(checksum_json(payload), checksum_json(reversed_payload))
        self.assertEqual(canonical_json(payload), canonical_json(reversed_payload))

    def test_wrong_expected_checksum_is_rejected(self) -> None:
        with self.assertRaisesRegex(SnapshotContractError, "Checksum"):
            load_problem_instance_snapshot(
                make_snapshot_payload(),
                expected_checksum="0" * 64,
            )

    def test_unknown_schema_version_is_rejected(self) -> None:
        payload = make_snapshot_payload()
        payload["schema_version"] = "problem-instance.v99"

        with self.assertRaisesRegex(SnapshotContractError, "schema version"):
            load_problem_instance_snapshot(payload)

    def test_snapshot_rejects_different_lecturers_in_same_course_section(self) -> None:
        """Hợp đồng JSON không được đưa phân công mâu thuẫn vào optimizer."""

        payload = deepcopy(make_snapshot_payload())
        payload["lecturers"].append({
            "lecturer_index": 1,
            "lecturer_code": "GV002",
            "full_name": "Giảng viên 2",
            "home_campus_code": "CS1",
        })
        second_part = deepcopy(payload["teaching_parts"][0])
        second_part.update({
            "teaching_part_index": 1,
            "teaching_part_id": 12,
            "part_code": "JAVA01-TH",
            "lecturer_index": 1,
        })
        payload["teaching_parts"].append(second_part)

        second_plan = deepcopy(payload["teaching_plans"][0])
        second_plan.update({
            "teaching_plan_id": 102,
            "plan_code": "PLAN-JAVA01-TH-01",
            "teaching_part_index": 1,
        })
        payload["teaching_plans"].append(second_plan)

        second_session = deepcopy(payload["class_sessions"][0])
        second_session.update({
            "session_index": 1,
            "class_session_id": 1002,
            "teaching_plan_id": 102,
        })
        payload["class_sessions"].append(second_session)
        payload["scenario"]["items"].append({
            "teaching_part_index": 1,
            "teaching_plan_id": 102,
        })

        with self.assertRaisesRegex(ValueError, "phải dùng chung một giảng viên"):
            load_problem_instance_snapshot(payload)

    def test_ready_preflight_builds_deterministic_gene_option_mapping(self) -> None:
        payload = make_snapshot_payload()

        first = prepare_snapshot_for_optimization(payload)
        second = prepare_snapshot_for_optimization(
            json.dumps(payload, ensure_ascii=False)
        )

        self.assertEqual(first.status, SnapshotPreparationStatus.READY)
        self.assertTrue(first.is_ready)
        self.assertEqual(len(first.option_domains[0]), 2)
        self.assertEqual(
            first.gene_option_mapping["schema_version"],
            MAPPING_SCHEMA_VERSION,
        )
        self.assertEqual(first.gene_option_mapping["dimension"], 1)
        self.assertEqual(
            first.gene_option_mapping["genes"][0]["options"][0]["location_code"],
            "B304",
        )
        self.assertEqual(
            first.gene_option_mapping_json,
            second.gene_option_mapping_json,
        )
        self.assertEqual(
            first.gene_option_mapping_checksum,
            second.gene_option_mapping_checksum,
        )

    def test_empty_domain_stops_preflight_with_no_option(self) -> None:
        payload = deepcopy(make_snapshot_payload())
        for teaching_date in payload["teaching_dates"]:
            teaching_date["status"] = "HOLIDAY"

        prepared = prepare_snapshot_for_optimization(payload)

        self.assertEqual(prepared.status, SnapshotPreparationStatus.NO_OPTION)
        self.assertFalse(prepared.is_ready)
        self.assertIsNone(prepared.gene_option_mapping)
        self.assertEqual(prepared.no_option_issues[0].session_index, 0)
        self.assertIn("không có TeachingDate", prepared.no_option_issues[0].reason)


if __name__ == "__main__":
    unittest.main()
