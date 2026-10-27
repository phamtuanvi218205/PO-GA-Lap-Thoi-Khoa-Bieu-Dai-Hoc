"""Tạo ``problem-instance.v2`` trực tiếp từ SQL Server bằng Python.

Builder giữ thứ tự index xác định như implementation Java trước đây. Kết quả
được serialize bằng cùng hàm canonical JSON của
:mod:`gapo_timetabling.core.snapshot`
nên checksum có thể được lưu và kiểm tra lại trong ``OptimizationRun``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from hashlib import sha256
from typing import Any, Iterable, Sequence

from .database import ConnectionProtocol, fetch_all_dicts, fetch_one_dict
from ..core.snapshot import SNAPSHOT_SCHEMA_VERSION, canonical_json


@dataclass(frozen=True, slots=True)
class BuiltProblemInstanceSnapshot:
    """Snapshot dạng object, JSON canonical và checksum SHA-256."""

    payload: dict[str, Any]
    canonical_json: str
    sha256_checksum: str


def _json_value(value: Any) -> Any:
    """Chuyển các kiểu ngày/giờ và Decimal từ driver thành kiểu JSON ổn định."""

    if isinstance(value, (date, time)):
        return value.isoformat()
    return value


class ProblemInstanceSnapshotBuilder:
    """Chụp toàn bộ dữ liệu cần thiết của một scenario đã ``LOCKED``."""

    def __init__(self, connection: ConnectionProtocol) -> None:
        self._connection = connection

    def build(self, scenario_id: int) -> BuiltProblemInstanceSnapshot:
        cursor = self._connection.cursor()
        scenario = fetch_one_dict(cursor.execute(
            """
            SELECT s.scenario_id, s.scenario_code, s.term_code, s.scope_type,
                   s.status, t.term_name, t.start_date, t.end_date,
                   t.status AS term_status
            FROM PlanningScenario AS s
            JOIN AcademicTerm AS t ON t.term_code = s.term_code
            WHERE s.scenario_id = ?
            """,
            scenario_id,
        ))
        if scenario is None:
            raise ValueError(f"Không tìm thấy PlanningScenario {scenario_id}.")
        if str(scenario["status"]) != "LOCKED":
            raise RuntimeError(
                "Chỉ PlanningScenario LOCKED mới được tạo snapshot production."
            )

        item_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT item.teaching_part_id, item.teaching_plan_id,
                   part.part_code, part.section_code, part.part_type,
                   part.total_periods, part.required_location_type,
                   part.required_room_type,
                   selected_plan.plan_code, selected_plan.status AS plan_status,
                   selected_plan.allows_intensive,
                   section.term_code, section.course_code,
                   section.section_name, section.expected_enrollment,
                   course.course_name
            FROM PlanningScenarioItem AS item
            JOIN TeachingPart AS part
              ON part.teaching_part_id = item.teaching_part_id
            JOIN TeachingPlan AS selected_plan
              ON selected_plan.teaching_plan_id = item.teaching_plan_id
             AND selected_plan.teaching_part_id = item.teaching_part_id
            JOIN CourseSection AS section
              ON section.section_code = part.section_code
            JOIN Course AS course ON course.course_code = section.course_code
            WHERE item.scenario_id = ?
            ORDER BY part.part_code
            """,
            scenario_id,
        ))
        if not item_rows:
            raise RuntimeError("Scenario LOCKED không có TeachingPart nào.")
        for item in item_rows:
            if str(item["plan_status"]) != "VALID":
                raise RuntimeError("Scenario LOCKED chỉ được tham chiếu TeachingPlan VALID.")
            if str(item["term_code"]) != str(scenario["term_code"]):
                raise RuntimeError("TeachingPart không thuộc học kỳ của scenario.")

        part_index_by_id = {
            int(item["teaching_part_id"]): index
            for index, item in enumerate(item_rows)
        }
        plan_order = {
            int(item["teaching_plan_id"]): index
            for index, item in enumerate(item_rows)
        }
        term_code = str(scenario["term_code"])
        course_codes = tuple(sorted({str(item["course_code"]) for item in item_rows}))

        capabilities = self._load_capabilities(course_codes)
        self._validate_capabilities(item_rows, capabilities)
        lecturer_codes = tuple(sorted({str(item["lecturer_code"]) for item in capabilities}))
        lecturer_index = {code: index for index, code in enumerate(lecturer_codes)}

        locations = fetch_all_dicts(cursor.execute(
            """
            SELECT location_id, location_code, location_name, location_type,
                   is_active
            FROM TeachingLocation
            ORDER BY location_code, location_id
            """
        ))
        location_index = {
            int(item["location_id"]): index for index, item in enumerate(locations)
        }

        payload: dict[str, Any] = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "term": {
                "term_code": term_code,
                "term_name": str(scenario["term_name"]),
                "start_date": _json_value(scenario["start_date"]),
                "end_date": _json_value(scenario["end_date"]),
                "status": str(scenario["term_status"]),
            },
            "scenario": {
                "scenario_id": int(scenario["scenario_id"]),
                "scenario_code": str(scenario["scenario_code"]),
                "term_code": term_code,
                "scope_type": str(scenario["scope_type"]),
                "status": str(scenario["status"]),
                "items": [
                    {
                        "teaching_part_index": part_index_by_id[int(item["teaching_part_id"])],
                        "teaching_plan_id": int(item["teaching_plan_id"]),
                    }
                    for item in item_rows
                ],
            },
            "weeks": self._simple_rows(
                """
                SELECT week_number, start_date, end_date FROM TermWeek
                WHERE term_code = ? ORDER BY week_number
                """,
                term_code,
            ),
            "teaching_dates": self._simple_rows(
                """
                SELECT calendar_date, week_number, iso_weekday,
                       date_status AS status
                FROM TeachingDate WHERE term_code = ? ORDER BY calendar_date
                """,
                term_code,
            ),
            "time_periods": self._simple_rows(
                """
                SELECT period_number, start_time, end_time,
                       session_name AS session_type
                FROM TimePeriod ORDER BY period_number
                """
            ),
            "allowed_period_blocks": self._simple_rows(
                """
                SELECT start_period, duration_periods FROM AllowedPeriodBlock
                WHERE is_active = 1 ORDER BY start_period, duration_periods
                """
            ),
            "teaching_duration_rules": [
                {
                    "part_type": str(row["part_type"]),
                    "duration_periods": int(row["duration_periods"]),
                    "standard": bool(row["is_standard"]),
                }
                for row in fetch_all_dicts(cursor.execute(
                    """
                    SELECT part_type, duration_periods, is_standard
                    FROM TeachingDurationRule
                    ORDER BY part_type, duration_periods
                    """
                ))
            ],
            "locations": self._map_locations(locations, location_index),
            "lecturers": self._map_lecturers(lecturer_codes, lecturer_index),
            "lecturer_course_capabilities": [
                {
                    "lecturer_index": lecturer_index[str(row["lecturer_code"])],
                    "course_code": str(row["course_code"]),
                    "can_teach_lecture": bool(row["can_teach_lecture"]),
                    "can_teach_practice": bool(row["can_teach_practice"]),
                    "suitability_score": float(row["suitability_score"]),
                }
                for row in capabilities
            ],
            "courses": [
                {"course_code": code, "course_name": self._course_name(code, item_rows)}
                for code in course_codes
            ],
            "course_sections": self._map_sections(item_rows),
            "teaching_parts": self._map_parts(item_rows, part_index_by_id),
            "teaching_plans": [
                {
                    "teaching_plan_id": int(item["teaching_plan_id"]),
                    "plan_code": str(item["plan_code"]),
                    "teaching_part_index": part_index_by_id[int(item["teaching_part_id"])],
                    "status": str(item["plan_status"]),
                    "allows_intensive": bool(item["allows_intensive"]),
                }
                for item in item_rows
            ],
            "class_sessions": self._map_sessions(tuple(plan_order), plan_order),
            "lecturer_availabilities": self._map_lecturer_availability(
                term_code, lecturer_codes, lecturer_index
            ),
            "room_availabilities": self._map_room_availability(
                term_code, location_index
            ),
            "campus_travel_times": self._simple_rows(
                """
                SELECT from_campus_code, to_campus_code, travel_minutes
                FROM CampusTravelTime ORDER BY from_campus_code, to_campus_code
                """
            ),
            "constraint_settings": [
                {
                    "constraint_code": str(row["constraint_code"]),
                    "constraint_type": str(row["constraint_kind"]),
                    "priority_tier": int(row["priority_tier"]),
                    "weight": None if row["weight"] is None else float(row["weight"]),
                    "threshold_value": (
                        None
                        if row["threshold_value"] is None
                        else float(row["threshold_value"])
                    ),
                    "enabled": bool(row["is_enabled"]),
                }
                for row in fetch_all_dicts(cursor.execute(
                    """
                    SELECT constraint_code, constraint_kind, priority_tier,
                           weight, threshold_value, is_enabled
                    FROM ConstraintSetting ORDER BY constraint_code
                    """
                ))
            ],
        }
        snapshot_json = canonical_json(payload)
        return BuiltProblemInstanceSnapshot(
            payload=payload,
            canonical_json=snapshot_json,
            sha256_checksum=sha256(snapshot_json.encode("utf-8")).hexdigest(),
        )

    def _load_capabilities(self, course_codes: Sequence[str]) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in course_codes)
        return fetch_all_dicts(self._connection.cursor().execute(
            f"""
            SELECT capability.lecturer_code, capability.course_code,
                   capability.can_teach_lecture,
                   capability.can_teach_practice,
                   capability.suitability_score
            FROM LecturerCourseCapability AS capability
            JOIN Lecturer AS lecturer
              ON lecturer.lecturer_code = capability.lecturer_code
            WHERE capability.course_code IN ({placeholders})
              AND lecturer.is_active = 1
            ORDER BY capability.course_code, capability.lecturer_code
            """,
            *course_codes,
        ))

    @staticmethod
    def _validate_capabilities(
        items: Sequence[dict[str, Any]], capabilities: Sequence[dict[str, Any]]
    ) -> None:
        by_section: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_section.setdefault(str(item["section_code"]), []).append(item)
        for section_code, parts in by_section.items():
            course_code = str(parts[0]["course_code"])
            requires_lecture = any(str(part["part_type"]) == "LECTURE" for part in parts)
            requires_practice = any(str(part["part_type"]) == "PRACTICE" for part in parts)
            has_candidate = any(
                str(capability["course_code"]) == course_code
                and (not requires_lecture or bool(capability["can_teach_lecture"]))
                and (not requires_practice or bool(capability["can_teach_practice"]))
                for capability in capabilities
            )
            if not has_candidate:
                raise RuntimeError(
                    f"CourseSection {section_code} không có giảng viên đủ khả năng "
                    "dạy mọi phần học."
                )

    def _simple_rows(self, sql: str, *parameters: object) -> list[dict[str, Any]]:
        return [
            {key: _json_value(value) for key, value in row.items()}
            for row in fetch_all_dicts(self._connection.cursor().execute(sql, *parameters))
        ]

    def _map_locations(
        self,
        locations: Sequence[dict[str, Any]],
        indexes: dict[int, int],
    ) -> list[dict[str, Any]]:
        cursor = self._connection.cursor()
        rooms = {
            int(row["location_id"]): row
            for row in fetch_all_dicts(cursor.execute(
                "SELECT location_id, campus_code, room_type, capacity FROM Room"
            ))
        }
        online = {
            int(row["location_id"]): row
            for row in fetch_all_dicts(cursor.execute(
                "SELECT location_id, platform_name FROM OnlineLocation"
            ))
        }
        equipment_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT room_location_id, equipment_code, quantity
            FROM RoomEquipment ORDER BY room_location_id, equipment_code
            """
        ))
        equipment_by_room: dict[int, list[dict[str, Any]]] = {}
        for row in equipment_rows:
            equipment_by_room.setdefault(int(row["room_location_id"]), []).append({
                "equipment_code": str(row["equipment_code"]),
                "quantity": int(row["quantity"]),
            })

        result = []
        for location in locations:
            location_id = int(location["location_id"])
            common = {
                "location_index": indexes[location_id],
                "location_id": location_id,
                "location_code": str(location["location_code"]),
                "location_name": str(location["location_name"]),
                "location_type": str(location["location_type"]),
                "active": bool(location["is_active"]),
            }
            if common["location_type"] == "PHYSICAL_ROOM":
                room = rooms.get(location_id)
                if room is None:
                    raise RuntimeError(
                        f"TeachingLocation {common['location_code']} thiếu bản ghi Room."
                    )
                result.append({
                    **common,
                    "campus_code": str(room["campus_code"]),
                    "room_type": str(room["room_type"]),
                    "capacity": None if room["capacity"] is None else int(room["capacity"]),
                    "equipment_quantities": equipment_by_room.get(location_id, []),
                    "platform_name": None,
                })
            else:
                online_location = online.get(location_id)
                if online_location is None:
                    raise RuntimeError(
                        f"TeachingLocation {common['location_code']} thiếu OnlineLocation."
                    )
                result.append({
                    **common,
                    "campus_code": None,
                    "room_type": None,
                    "capacity": None,
                    "equipment_quantities": [],
                    "platform_name": str(online_location["platform_name"]),
                })
        return result

    def _map_lecturers(
        self, codes: Sequence[str], indexes: dict[str, int]
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in codes)
        rows = fetch_all_dicts(self._connection.cursor().execute(
            f"""
            SELECT lecturer_code, full_name, home_campus_code,
                   max_teaching_periods
            FROM Lecturer WHERE lecturer_code IN ({placeholders})
            ORDER BY lecturer_code
            """,
            *codes,
        ))
        return [
            {
                "lecturer_index": indexes[str(row["lecturer_code"])],
                "lecturer_code": str(row["lecturer_code"]),
                "full_name": str(row["full_name"]),
                "home_campus_code": row["home_campus_code"],
                "max_teaching_periods": (
                    None
                    if row["max_teaching_periods"] is None
                    else int(row["max_teaching_periods"])
                ),
            }
            for row in rows
        ]

    @staticmethod
    def _course_name(code: str, items: Sequence[dict[str, Any]]) -> str:
        return str(next(item["course_name"] for item in items if item["course_code"] == code))

    @staticmethod
    def _map_sections(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        unique = {str(item["section_code"]): item for item in items}
        return [
            {
                "section_code": code,
                "course_code": str(item["course_code"]),
                "section_name": "" if item["section_name"] is None else str(item["section_name"]),
                "expected_enrollment": (
                    None
                    if item["expected_enrollment"] is None
                    else int(item["expected_enrollment"])
                ),
            }
            for code, item in sorted(unique.items())
        ]

    def _map_parts(
        self,
        items: Sequence[dict[str, Any]],
        indexes: dict[int, int],
    ) -> list[dict[str, Any]]:
        part_ids = tuple(int(item["teaching_part_id"]) for item in items)
        placeholders = ",".join("?" for _ in part_ids)
        equipment_rows = fetch_all_dicts(self._connection.cursor().execute(
            f"""
            SELECT teaching_part_id, equipment_code, minimum_quantity
            FROM TeachingPartRequiredEquipment
            WHERE teaching_part_id IN ({placeholders})
            ORDER BY teaching_part_id, equipment_code
            """,
            *part_ids,
        ))
        equipment: dict[int, list[dict[str, Any]]] = {}
        for row in equipment_rows:
            equipment.setdefault(int(row["teaching_part_id"]), []).append({
                "equipment_code": str(row["equipment_code"]),
                "quantity": int(row["minimum_quantity"]),
            })
        return [
            {
                "teaching_part_index": indexes[int(item["teaching_part_id"])],
                "teaching_part_id": int(item["teaching_part_id"]),
                "part_code": str(item["part_code"]),
                "section_code": str(item["section_code"]),
                "part_type": str(item["part_type"]),
                "lecturer_index": None,
                "total_periods": int(item["total_periods"]),
                "required_location_type": str(item["required_location_type"]),
                "required_room_type": item["required_room_type"],
                "required_equipment": equipment.get(int(item["teaching_part_id"]), []),
            }
            for item in items
        ]

    def _map_sessions(
        self,
        plan_ids: Sequence[int],
        plan_order: dict[int, int],
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in plan_ids)
        rows = fetch_all_dicts(self._connection.cursor().execute(
            f"""
            SELECT class_session_id, teaching_plan_id, session_number,
                   stability_group_no, week_number, duration_periods,
                   required_location_type
            FROM ClassSession WHERE teaching_plan_id IN ({placeholders})
            """,
            *plan_ids,
        ))
        rows.sort(key=lambda row: (
            plan_order[int(row["teaching_plan_id"])], int(row["session_number"])
        ))
        counts = {plan_id: 0 for plan_id in plan_ids}
        for row in rows:
            counts[int(row["teaching_plan_id"])] += 1
        missing = [plan_id for plan_id, count in counts.items() if count == 0]
        if missing:
            raise RuntimeError(f"Các TeachingPlan không có ClassSession: {missing}.")
        return [
            {
                "session_index": index,
                "class_session_id": int(row["class_session_id"]),
                "teaching_plan_id": int(row["teaching_plan_id"]),
                "session_number": int(row["session_number"]),
                "stability_group_no": int(row["stability_group_no"]),
                "week_number": int(row["week_number"]),
                "duration_periods": int(row["duration_periods"]),
                "required_location_type": str(row["required_location_type"]),
            }
            for index, row in enumerate(rows)
        ]

    def _map_lecturer_availability(
        self,
        term_code: str,
        lecturer_codes: Sequence[str],
        lecturer_index: dict[str, int],
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in lecturer_codes)
        rows = fetch_all_dicts(self._connection.cursor().execute(
            f"""
            SELECT lecturer_code, scope_type, start_period, end_period,
                   availability_type, calendar_date, iso_weekday,
                   preference_weight
            FROM LecturerAvailability
            WHERE term_code = ? AND lecturer_code IN ({placeholders})
            """,
            term_code,
            *lecturer_codes,
        ))
        return self._sorted_availability(rows, "lecturer_code", lecturer_index)

    def _map_room_availability(
        self, term_code: str, location_index: dict[int, int]
    ) -> list[dict[str, Any]]:
        rows = fetch_all_dicts(self._connection.cursor().execute(
            """
            SELECT room_location_id, scope_type, start_period, end_period,
                   availability_type, calendar_date, iso_weekday
            FROM RoomAvailability WHERE term_code = ?
            """,
            term_code,
        ))
        filtered = [row for row in rows if int(row["room_location_id"]) in location_index]
        return self._sorted_availability(
            filtered, "room_location_id", location_index, room=True
        )

    @staticmethod
    def _sorted_availability(
        rows: Iterable[dict[str, Any]],
        resource_field: str,
        indexes: dict[Any, int],
        *,
        room: bool = False,
    ) -> list[dict[str, Any]]:
        result = [
            {
                "resource_index": indexes[row[resource_field]],
                "scope_type": str(row["scope_type"]),
                "start_period": int(row["start_period"]),
                "end_period": int(row["end_period"]),
                "availability_type": str(row["availability_type"]),
                "calendar_date": _json_value(row["calendar_date"]),
                "iso_weekday": None if row["iso_weekday"] is None else int(row["iso_weekday"]),
                "preference_weight": (
                    None
                    if room or row.get("preference_weight") is None
                    else float(row["preference_weight"])
                ),
            }
            for row in rows
        ]
        result.sort(key=lambda item: (
            item["resource_index"],
            item["scope_type"],
            item["calendar_date"] or "",
            -1 if item["iso_weekday"] is None else item["iso_weekday"],
            item["start_period"],
            item["end_period"],
            item["availability_type"],
        ))
        return result
