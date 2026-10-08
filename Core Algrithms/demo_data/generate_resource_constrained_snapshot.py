"""Generate the deterministic resource-constrained timetable demo snapshot.

The fixture intentionally models scarce resources instead of a convenient
school week. Multiple course sections share each lecturer, only a small
subset of rooms satisfies the required equipment, most room capacities are
below expected enrollment, and recurring/date-specific unavailability
removes many otherwise possible placements.

The generated snapshot remains feasible by construction. It is therefore
suitable for exercising the encoder, decoder, hard-constraint validator and
optimizer without confusing "difficult" with "impossible".
"""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path


OUTPUT_PATH = Path(__file__).with_name("large_timetable_snapshot.json")
FIRST_MONDAY = date(2026, 9, 7)
WEEK_COUNT = 6


COURSE_DEFINITIONS = (
    ("JAVA", "Lập trình Java", "JAVA01", 58, 0, 25),
    ("OOP", "Lập trình hướng đối tượng", "OOP01", 64, 1, 25),
    ("CSDL", "Cơ sở dữ liệu", "CSDL01", 72, 2, 25),
    ("CTDL", "Cấu trúc dữ liệu", "CTDL01", 60, 3, 35),
    ("MMT", "Mạng máy tính", "MMT01", 80, 0, 35),
    ("WEB", "Phát triển Web", "WEB01", 56, 1, 35),
    ("AI", "Trí tuệ nhân tạo", "AI01", 75, 2, 35),
    ("ATTT", "An toàn thông tin", "ATTT01", 68, 3, 35),
    ("CLOUD", "Điện toán đám mây", "CLOUD01", 62, 0, 35),
)


def _availability(
    resource_index: int,
    availability_type: str,
    start_period: int,
    end_period: int,
    *,
    iso_weekday: int | None = None,
    calendar_date: str | None = None,
    preference_weight: float | None = None,
) -> dict[str, object]:
    """Build one availability record in the snapshot contract format."""

    item: dict[str, object] = {
        "resource_index": resource_index,
        "scope_type": "DATE" if calendar_date is not None else "WEEKDAY",
        "calendar_date": calendar_date,
        "iso_weekday": iso_weekday,
        "start_period": start_period,
        "end_period": end_period,
        "availability_type": availability_type,
        "preference_weight": preference_weight,
    }
    return item


def _build_weeks() -> list[dict[str, object]]:
    """Create six numbered academic weeks, Monday through Sunday."""

    weeks: list[dict[str, object]] = []
    for week_number in range(1, WEEK_COUNT + 1):
        start = FIRST_MONDAY + timedelta(days=7 * (week_number - 1))
        weeks.append({
            "week_number": week_number,
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=6)).isoformat(),
        })
    return weeks


def _build_teaching_dates() -> list[dict[str, object]]:
    """Create working dates, holidays, and explicit Saturday makeup dates."""

    holidays = {
        date(2026, 9, 16),  # Week 2 Wednesday.
        date(2026, 10, 5),  # Week 5 Monday.
    }
    makeup_saturdays = {
        date(2026, 9, 19),
        date(2026, 10, 10),
    }

    teaching_dates: list[dict[str, object]] = []
    for week_number in range(1, WEEK_COUNT + 1):
        monday = FIRST_MONDAY + timedelta(days=7 * (week_number - 1))
        weekdays = range(6) if week_number in (2, 5) else range(5)
        for day_offset in weekdays:
            current = monday + timedelta(days=day_offset)
            if current in holidays:
                status = "HOLIDAY"
            elif current in makeup_saturdays:
                status = "MAKEUP_ALLOWED"
            else:
                status = "NORMAL"
            teaching_dates.append({
                "calendar_date": current.isoformat(),
                "week_number": week_number,
                "iso_weekday": current.isoweekday(),
                "status": status,
            })
    return teaching_dates


def _build_time_periods() -> list[dict[str, object]]:
    """Return the twelve period definitions used by the timetable core."""

    times = (
        ("07:00:00", "07:45:00", "MORNING"),
        ("07:50:00", "08:35:00", "MORNING"),
        ("08:40:00", "09:25:00", "MORNING"),
        ("09:35:00", "10:20:00", "MORNING"),
        ("10:25:00", "11:10:00", "MORNING"),
        ("11:15:00", "12:00:00", "MORNING"),
        ("13:00:00", "13:45:00", "AFTERNOON"),
        ("13:50:00", "14:35:00", "AFTERNOON"),
        ("14:40:00", "15:25:00", "AFTERNOON"),
        ("15:35:00", "16:20:00", "AFTERNOON"),
        ("16:25:00", "17:10:00", "AFTERNOON"),
        ("17:15:00", "18:00:00", "AFTERNOON"),
    )
    return [
        {
            "period_number": period_number,
            "start_time": start_time,
            "end_time": end_time,
            "session_type": session_type,
        }
        for period_number, (start_time, end_time, session_type)
        in enumerate(times, start=1)
    ]


def _build_locations() -> list[dict[str, object]]:
    """Create four rooms of which only a subset fits each teaching part.

    The secondary lecture room lacks a projector. The secondary laboratory
    has only 25 computers. Consequently all lecture parts compete for A201,
    while the six high-requirement practice parts compete for LAB-A alone.
    Capacities are deliberately below most expected enrollments; this affects
    soft fitness but does not remove otherwise feasible options.
    """

    return [
        {
            "location_index": 0,
            "location_id": 501,
            "location_code": "A201",
            "location_name": "Phòng lý thuyết A201",
            "location_type": "PHYSICAL_ROOM",
            "active": True,
            "campus_code": "CS1",
            "room_type": "LECTURE_ROOM",
            "capacity": 45,
            "equipment_quantities": [
                {"equipment_code": "PROJECTOR", "quantity": 1},
            ],
        },
        {
            "location_index": 1,
            "location_id": 502,
            "location_code": "A202",
            "location_name": "Phòng lý thuyết A202 chưa có máy chiếu",
            "location_type": "PHYSICAL_ROOM",
            "active": True,
            "campus_code": "CS1",
            "room_type": "LECTURE_ROOM",
            "capacity": 35,
            "equipment_quantities": [],
        },
        {
            "location_index": 2,
            "location_id": 503,
            "location_code": "LAB-A",
            "location_name": "Phòng máy LAB-A",
            "location_type": "PHYSICAL_ROOM",
            "active": True,
            "campus_code": "CS1",
            "room_type": "COMPUTER_LAB",
            "capacity": 40,
            "equipment_quantities": [
                {"equipment_code": "PROJECTOR", "quantity": 1},
                {"equipment_code": "COMPUTER", "quantity": 40},
            ],
        },
        {
            "location_index": 3,
            "location_id": 504,
            "location_code": "LAB-B",
            "location_name": "Phòng máy LAB-B quy mô nhỏ",
            "location_type": "PHYSICAL_ROOM",
            "active": True,
            "campus_code": "CS1",
            "room_type": "COMPUTER_LAB",
            "capacity": 30,
            "equipment_quantities": [
                {"equipment_code": "PROJECTOR", "quantity": 1},
                {"equipment_code": "COMPUTER", "quantity": 25},
            ],
        },
    ]


def _build_academic_objects() -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    """Create courses, sections, parts, plans, sessions, and scenario items."""

    courses: list[dict[str, object]] = []
    sections: list[dict[str, object]] = []
    parts: list[dict[str, object]] = []
    plans: list[dict[str, object]] = []
    sessions: list[dict[str, object]] = []
    scenario_items: list[dict[str, object]] = []
    session_index = 0

    for section_position, definition in enumerate(COURSE_DEFINITIONS):
        (
            course_code,
            course_name,
            section_code,
            expected_enrollment,
            lecturer_index,
            required_computers,
        ) = definition

        courses.append({
            "course_code": course_code,
            "course_name": course_name,
        })
        sections.append({
            "section_code": section_code,
            "course_code": course_code,
            "section_name": f"{course_name} 01",
            "expected_enrollment": expected_enrollment,
        })

        for part_offset, (part_type, duration, room_type) in enumerate((
            ("LECTURE", 3, "LECTURE_ROOM"),
            ("PRACTICE", 5, "COMPUTER_LAB"),
        )):
            part_index = section_position * 2 + part_offset
            part_suffix = "LT" if part_type == "LECTURE" else "TH"
            plan_id = 1001 + part_index
            equipment = [{"equipment_code": "PROJECTOR", "quantity": 1}]
            if part_type == "PRACTICE":
                equipment.append({
                    "equipment_code": "COMPUTER",
                    "quantity": required_computers,
                })

            parts.append({
                "teaching_part_index": part_index,
                "teaching_part_id": 101 + part_index,
                "part_code": f"{section_code}-{part_suffix}",
                "section_code": section_code,
                "part_type": part_type,
                "lecturer_index": lecturer_index,
                "total_periods": WEEK_COUNT * duration,
                "required_location_type": "PHYSICAL_ROOM",
                "required_room_type": room_type,
                "required_equipment": equipment,
            })
            plans.append({
                "teaching_plan_id": plan_id,
                "plan_code": f"PLAN-{section_code}-{part_suffix}-WEEKLY",
                "teaching_part_index": part_index,
                "status": "VALID",
                "allows_intensive": False,
            })
            scenario_items.append({
                "teaching_part_index": part_index,
                "teaching_plan_id": plan_id,
            })

            for week_number in range(1, WEEK_COUNT + 1):
                sessions.append({
                    "session_index": session_index,
                    "class_session_id": 2001 + session_index,
                    "teaching_plan_id": plan_id,
                    "session_number": week_number,
                    "stability_group_no": 1,
                    "week_number": week_number,
                    "duration_periods": duration,
                    "required_location_type": "PHYSICAL_ROOM",
                })
                session_index += 1

    return courses, sections, parts, plans, sessions, scenario_items


def _build_lecturer_availabilities() -> list[dict[str, object]]:
    """Create dense recurring and date-specific lecturer restrictions."""

    windows = [
        # GV001 teaches three sections and is unavailable every Tuesday/Thursday.
        _availability(0, "UNAVAILABLE", 1, 12, iso_weekday=2),
        _availability(0, "UNAVAILABLE", 1, 12, iso_weekday=4),
        _availability(0, "UNAVAILABLE", 10, 12, iso_weekday=3),
        _availability(0, "UNAVAILABLE", 10, 12, iso_weekday=5),
        _availability(0, "PREFERRED", 1, 9, iso_weekday=1, preference_weight=1.0),
        _availability(0, "PREFERRED", 1, 9, iso_weekday=3, preference_weight=0.8),
        _availability(0, "DISCOURAGED", 7, 12, iso_weekday=5, preference_weight=0.6),
        # GV002 has alternating morning/afternoon commitments and no Friday.
        _availability(1, "UNAVAILABLE", 1, 6, iso_weekday=1),
        _availability(1, "UNAVAILABLE", 7, 12, iso_weekday=2),
        _availability(1, "UNAVAILABLE", 1, 6, iso_weekday=3),
        _availability(1, "UNAVAILABLE", 7, 12, iso_weekday=4),
        _availability(1, "UNAVAILABLE", 1, 12, iso_weekday=5),
        _availability(1, "PREFERRED", 7, 12, iso_weekday=1, preference_weight=1.0),
        _availability(1, "PREFERRED", 1, 6, iso_weekday=2, preference_weight=0.8),
        _availability(1, "DISCOURAGED", 7, 12, iso_weekday=3, preference_weight=0.5),
        # GV003 is available mainly on Tuesday/Thursday plus Friday afternoon.
        _availability(2, "UNAVAILABLE", 1, 12, iso_weekday=1),
        _availability(2, "UNAVAILABLE", 1, 12, iso_weekday=3),
        _availability(2, "UNAVAILABLE", 1, 6, iso_weekday=5),
        _availability(2, "UNAVAILABLE", 10, 12, iso_weekday=2),
        _availability(2, "PREFERRED", 1, 9, iso_weekday=2, preference_weight=1.0),
        _availability(2, "PREFERRED", 1, 9, iso_weekday=4, preference_weight=0.9),
        _availability(2, "DISCOURAGED", 7, 12, iso_weekday=5, preference_weight=0.5),
        # GV004 has only four principal half-day windows during a normal week.
        _availability(3, "UNAVAILABLE", 1, 12, iso_weekday=1),
        _availability(3, "UNAVAILABLE", 1, 6, iso_weekday=2),
        _availability(3, "UNAVAILABLE", 7, 12, iso_weekday=3),
        _availability(3, "UNAVAILABLE", 1, 6, iso_weekday=4),
        _availability(3, "UNAVAILABLE", 7, 12, iso_weekday=5),
        _availability(3, "PREFERRED", 7, 12, iso_weekday=2, preference_weight=1.0),
        _availability(3, "PREFERRED", 1, 6, iso_weekday=3, preference_weight=0.9),
        _availability(3, "DISCOURAGED", 7, 12, iso_weekday=4, preference_weight=0.5),
        # One-off duties force schedule exceptions in separate weeks.
        _availability(0, "UNAVAILABLE", 7, 12, calendar_date="2026-10-02"),
        _availability(1, "UNAVAILABLE", 7, 12, calendar_date="2026-09-23"),
        _availability(2, "UNAVAILABLE", 1, 6, calendar_date="2026-10-13"),
        _availability(3, "UNAVAILABLE", 7, 12, calendar_date="2026-09-10"),
    ]
    return windows


def _build_room_availabilities() -> list[dict[str, object]]:
    """Create recurring maintenance and one-off room outages."""

    return [
        _availability(0, "UNAVAILABLE", 1, 6, iso_weekday=1),
        _availability(0, "DISCOURAGED", 1, 12, iso_weekday=5),
        _availability(0, "UNAVAILABLE", 7, 12, calendar_date="2026-09-09"),
        _availability(0, "UNAVAILABLE", 1, 6, calendar_date="2026-09-25"),
        _availability(0, "UNAVAILABLE", 7, 12, calendar_date="2026-10-13"),
        _availability(2, "UNAVAILABLE", 7, 12, iso_weekday=5),
        _availability(2, "DISCOURAGED", 7, 12, iso_weekday=4),
        _availability(2, "UNAVAILABLE", 7, 12, calendar_date="2026-09-10"),
        _availability(2, "UNAVAILABLE", 1, 6, calendar_date="2026-09-23"),
        _availability(2, "UNAVAILABLE", 1, 6, calendar_date="2026-10-02"),
        _availability(2, "UNAVAILABLE", 1, 6, calendar_date="2026-10-13"),
        _availability(3, "UNAVAILABLE", 1, 12, iso_weekday=2),
        _availability(3, "UNAVAILABLE", 1, 12, iso_weekday=4),
        _availability(3, "DISCOURAGED", 1, 12, iso_weekday=1),
    ]


def build_snapshot() -> dict[str, object]:
    """Build the complete canonical demo payload."""

    courses, sections, parts, plans, sessions, scenario_items = (
        _build_academic_objects()
    )
    term_end = FIRST_MONDAY + timedelta(days=7 * WEEK_COUNT - 1)

    return {
        "schema_version": "problem-instance.v1",
        "term": {
            "term_code": "2026_HK1_DEMO_HARD",
            "term_name": "Học kỳ 1 2026-2027 - demo khan hiếm tài nguyên",
            "start_date": FIRST_MONDAY.isoformat(),
            "end_date": term_end.isoformat(),
            "status": "PLANNING",
        },
        "scenario": {
            "scenario_id": 9002,
            "scenario_code": "SCN-DEMO-RESOURCE-CONSTRAINED-2026-HK1",
            "term_code": "2026_HK1_DEMO_HARD",
            "scope_type": "FULL_TERM",
            "status": "LOCKED",
            "items": scenario_items,
        },
        "weeks": _build_weeks(),
        "teaching_dates": _build_teaching_dates(),
        "time_periods": _build_time_periods(),
        "allowed_period_blocks": [
            {"start_period": 1, "duration_periods": 3},
            {"start_period": 4, "duration_periods": 3},
            {"start_period": 7, "duration_periods": 3},
            {"start_period": 10, "duration_periods": 3},
            {"start_period": 1, "duration_periods": 5},
            {"start_period": 7, "duration_periods": 5},
        ],
        "teaching_duration_rules": [
            {"part_type": "LECTURE", "duration_periods": 3, "standard": True},
            {"part_type": "PRACTICE", "duration_periods": 5, "standard": True},
        ],
        "locations": _build_locations(),
        "lecturers": [
            {
                "lecturer_index": 0,
                "lecturer_code": "GV001",
                "full_name": "Nguyễn Trọng Nghĩa",
                "home_campus_code": "CS1",
            },
            {
                "lecturer_index": 1,
                "lecturer_code": "GV002",
                "full_name": "Trần Minh Anh",
                "home_campus_code": "CS1",
            },
            {
                "lecturer_index": 2,
                "lecturer_code": "GV003",
                "full_name": "Lê Hoàng Nam",
                "home_campus_code": "CS1",
            },
            {
                "lecturer_index": 3,
                "lecturer_code": "GV004",
                "full_name": "Phạm Thu Hà",
                "home_campus_code": "CS1",
            },
        ],
        "courses": courses,
        "course_sections": sections,
        "teaching_parts": parts,
        "teaching_plans": plans,
        "class_sessions": sessions,
        "lecturer_availabilities": _build_lecturer_availabilities(),
        "room_availabilities": _build_room_availabilities(),
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
                "constraint_code": "HARD_NO_ROOM_OVERLAP",
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
            {
                "constraint_code": "SOFT_CAPACITY",
                "constraint_type": "SOFT",
                "priority_tier": 2,
                "weight": 0.4091,
                "enabled": True,
            },
            {
                "constraint_code": "SOFT_LECTURER_GAP",
                "constraint_type": "SOFT",
                "priority_tier": 2,
                "weight": 0.2273,
                "enabled": True,
            },
            {
                "constraint_code": "SOFT_LECTURER_CONSECUTIVE",
                "constraint_type": "SOFT",
                "priority_tier": 2,
                "weight": 0.0909,
                "enabled": True,
                "threshold_value": 6,
            },
            {
                "constraint_code": "SOFT_ROOM_DISCOURAGED",
                "constraint_type": "SOFT",
                "priority_tier": 2,
                "weight": 0.1818,
                "enabled": True,
            },
            {
                "constraint_code": "SOFT_ROOM_STABILITY",
                "constraint_type": "SOFT",
                "priority_tier": 2,
                "weight": 0.0909,
                "enabled": True,
            },
        ],
    }


def main() -> None:
    """Write the generated snapshot with stable UTF-8 formatting."""

    OUTPUT_PATH.write_text(
        json.dumps(build_snapshot(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # Keep the standalone generator usable in terminals whose active code page
    # cannot display Vietnamese Unicode output.
    print(f"Generated resource-constrained demo data: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
