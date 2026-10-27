"""Sinh snapshot v2 khó cho bài toán đồng thời phân công và xếp lịch.

Fixture này không gán sẵn giảng viên cho lớp học phần. Nhiều giảng viên có
thể dạy cùng một môn nhưng khác lịch bận, mức phù hợp và giới hạn tải. Phòng
học cũng được cấu hình khan hiếm để một phân công giảng viên hợp lệ cục bộ
chưa chắc ghép thành lịch toàn cục được.

File được sinh có tính xác định và vẫn được thiết kế để tồn tại ít nhất một
lịch hợp lệ. Mục đích là kiểm thử/pilot, không phải dữ liệu HUIT thực tế.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from generate_resource_constrained_snapshot import (
    FIRST_MONDAY,
    WEEK_COUNT,
    _availability,
    _build_locations,
    _build_room_availabilities,
    _build_teaching_dates,
    _build_time_periods,
    _build_weeks,
)


OUTPUT_PATH = Path(__file__).with_name("dynamic_assignment_snapshot_v2.json")

# Chín lớp cùng chia sẻ năm môn. Những cặp JAVA01/JAVA02, WEB01/WEB02,
# CSDL01/CSDL02 và AI01/AI02 buộc optimizer phải quyết định người nào phù hợp
# với lớp nào thay vì xem mỗi môn chỉ có đúng một lớp đã gán sẵn.
SECTION_DEFINITIONS = (
    ("JAVA", "Lập trình Java", "JAVA01", 62, 35),
    ("JAVA", "Lập trình Java", "JAVA02", 58, 25),
    ("WEB", "Phát triển Web", "WEB01", 65, 35),
    ("WEB", "Phát triển Web", "WEB02", 54, 25),
    ("CSDL", "Cơ sở dữ liệu", "CSDL01", 72, 35),
    ("CSDL", "Cơ sở dữ liệu", "CSDL02", 60, 35),
    ("AI", "Trí tuệ nhân tạo", "AI01", 75, 35),
    ("AI", "Trí tuệ nhân tạo", "AI02", 57, 25),
    ("MMT", "Mạng máy tính", "MMT01", 80, 35),
)


def _build_academic_objects() -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    """Tạo 9 lớp, 18 part và 108 session trong sáu tuần."""

    course_names: dict[str, str] = {}
    sections: list[dict[str, object]] = []
    parts: list[dict[str, object]] = []
    plans: list[dict[str, object]] = []
    sessions: list[dict[str, object]] = []
    scenario_items: list[dict[str, object]] = []
    session_index = 0

    for section_position, definition in enumerate(SECTION_DEFINITIONS):
        course_code, course_name, section_code, enrollment, required_computers = (
            definition
        )
        course_names[course_code] = course_name
        sections.append({
            "section_code": section_code,
            "course_code": course_code,
            "section_name": f"{course_name} {section_code[-2:]}",
            "expected_enrollment": enrollment,
        })

        for part_offset, (part_type, duration, room_type) in enumerate((
            ("LECTURE", 3, "LECTURE_ROOM"),
            ("PRACTICE", 5, "COMPUTER_LAB"),
        )):
            part_index = section_position * 2 + part_offset
            suffix = "LT" if part_type == "LECTURE" else "TH"
            plan_id = 5001 + part_index
            required_equipment = [
                {"equipment_code": "PROJECTOR", "quantity": 1}
            ]
            if part_type == "PRACTICE":
                required_equipment.append({
                    "equipment_code": "COMPUTER",
                    "quantity": required_computers,
                })

            parts.append({
                "teaching_part_index": part_index,
                "teaching_part_id": 4001 + part_index,
                "part_code": f"{section_code}-{suffix}",
                "section_code": section_code,
                "part_type": part_type,
                # Snapshot v2 không gán cứng người dạy tại TeachingPart.
                "lecturer_index": None,
                "total_periods": WEEK_COUNT * duration,
                "required_location_type": "PHYSICAL_ROOM",
                "required_room_type": room_type,
                "required_equipment": required_equipment,
            })
            plans.append({
                "teaching_plan_id": plan_id,
                "plan_code": f"PLAN-{section_code}-{suffix}-WEEKLY",
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
                    "class_session_id": 6001 + session_index,
                    "teaching_plan_id": plan_id,
                    "session_number": week_number,
                    "stability_group_no": 1,
                    "week_number": week_number,
                    "duration_periods": duration,
                    "required_location_type": "PHYSICAL_ROOM",
                })
                session_index += 1

    courses = [
        {"course_code": code, "course_name": name}
        for code, name in course_names.items()
    ]
    return courses, sections, parts, plans, sessions, scenario_items


def _build_lecturers() -> list[dict[str, object]]:
    """Tạo năm giảng viên với tổng sức tải chỉ vừa đủ cho chín lớp."""

    names = (
        "Nguyễn Trọng Nghĩa",
        "Trần Minh Anh",
        "Lê Hoàng Nam",
        "Phạm Thu Hà",
        "Võ Thanh Bình",
    )
    return [
        {
            "lecturer_index": index,
            "lecturer_code": f"GV{index + 1:03d}",
            "full_name": name,
            "home_campus_code": "CS1",
            # Mỗi lớp chiếm 48 tiết trong snapshot. Một người chỉ được nhận
            # tối đa hai lớp; tổng sức tải 480 chỉ dư 48 tiết so với nhu cầu.
            "max_teaching_periods": 96,
        }
        for index, name in enumerate(names)
    ]


def _build_capabilities() -> list[dict[str, object]]:
    """Tạo miền năng lực chồng lấn, không có môn nào chỉ một người dạy được."""

    definitions = (
        # lecturer, course, lecture, practice, suitability
        (0, "JAVA", True, True, 0.98),
        (0, "CSDL", True, True, 0.78),
        (0, "AI", True, True, 0.65),
        (1, "JAVA", True, True, 0.86),
        (1, "WEB", True, True, 0.95),
        (1, "CSDL", True, True, 0.70),
        (1, "MMT", True, True, 0.72),
        (2, "WEB", True, True, 0.82),
        (2, "CSDL", True, True, 0.97),
        (2, "AI", True, True, 0.76),
        (3, "CSDL", True, True, 0.84),
        (3, "WEB", True, True, 0.70),
        (3, "AI", True, True, 0.96),
        (3, "MMT", True, True, 0.83),
        (4, "JAVA", True, True, 0.74),
        (4, "WEB", True, True, 0.76),
        (4, "AI", True, True, 0.88),
        (4, "MMT", True, True, 0.97),
        # Capability chỉ có lý thuyết không đủ điều kiện nhận CSDL01/CSDL02
        # vì hai lớp đều có thêm part thực hành. Dòng này kiểm tra bộ lọc loại
        # part thay vì làm rộng giả miền phân công.
        (4, "CSDL", True, False, 0.90),
    )
    return [
        {
            "lecturer_index": lecturer_index,
            "course_code": course_code,
            "can_teach_lecture": can_teach_lecture,
            "can_teach_practice": can_teach_practice,
            "suitability_score": suitability,
        }
        for (
            lecturer_index,
            course_code,
            can_teach_lecture,
            can_teach_practice,
            suitability,
        ) in definitions
    ]


def _build_dynamic_locations() -> list[dict[str, object]]:
    """Giữ bốn phòng nhưng cho cả hai phòng mỗi loại tham gia xếp lịch.

    Hai phòng vẫn thiếu sức chứa so với phần lớn lớp nên tiêu chí capacity có
    ý nghĩa. Việc cho A202 có máy chiếu và LAB-B có 40 máy là mức tài nguyên
    tối thiểu để 18 chuỗi buổi cố định có nghiệm dưới lịch bận dày.
    """

    locations = _build_locations()
    locations[1]["equipment_quantities"] = [
        {"equipment_code": "PROJECTOR", "quantity": 1}
    ]
    locations[3]["equipment_quantities"] = [
        {"equipment_code": "PROJECTOR", "quantity": 1},
        {"equipment_code": "COMPUTER", "quantity": 40},
    ]
    return locations


def _build_lecturer_availabilities() -> list[dict[str, object]]:
    """Tạo lịch bận dày nhưng vẫn có ít nhất một lịch lặp khả thi."""

    return [
        # Mỗi người mất hai ngày trọn vẹn và thêm một khoảng bận theo ngày.
        # Phần còn lại đủ cho tối đa hai lớp, nhưng không dư nhiều lựa chọn.
        _availability(0, "UNAVAILABLE", 1, 12, iso_weekday=2),
        _availability(0, "UNAVAILABLE", 1, 12, iso_weekday=4),
        _availability(0, "PREFERRED", 1, 9, iso_weekday=1, preference_weight=1.0),
        _availability(0, "PREFERRED", 1, 9, iso_weekday=3, preference_weight=0.8),
        _availability(0, "DISCOURAGED", 7, 12, iso_weekday=5, preference_weight=0.6),
        _availability(0, "UNAVAILABLE", 7, 12, calendar_date="2026-10-02"),
        # GV002 không thể dạy thứ Tư và thứ Sáu.
        _availability(1, "UNAVAILABLE", 1, 12, iso_weekday=3),
        _availability(1, "UNAVAILABLE", 1, 12, iso_weekday=5),
        _availability(1, "PREFERRED", 7, 12, iso_weekday=1, preference_weight=1.0),
        _availability(1, "PREFERRED", 1, 6, iso_weekday=2, preference_weight=0.8),
        _availability(1, "DISCOURAGED", 7, 12, iso_weekday=3, preference_weight=0.5),
        _availability(1, "UNAVAILABLE", 7, 12, calendar_date="2026-09-23"),
        # GV003 chủ yếu làm việc thứ Ba, Năm và thứ Sáu.
        _availability(2, "UNAVAILABLE", 1, 12, iso_weekday=1),
        _availability(2, "UNAVAILABLE", 1, 12, iso_weekday=3),
        _availability(2, "PREFERRED", 1, 9, iso_weekday=2, preference_weight=1.0),
        _availability(2, "PREFERRED", 1, 9, iso_weekday=4, preference_weight=0.9),
        _availability(2, "DISCOURAGED", 7, 12, iso_weekday=5, preference_weight=0.5),
        _availability(2, "UNAVAILABLE", 1, 6, calendar_date="2026-10-13"),
        # GV004 không thể dạy thứ Hai và thứ Sáu.
        _availability(3, "UNAVAILABLE", 1, 12, iso_weekday=1),
        _availability(3, "UNAVAILABLE", 1, 12, iso_weekday=5),
        _availability(3, "PREFERRED", 7, 12, iso_weekday=2, preference_weight=1.0),
        _availability(3, "PREFERRED", 1, 6, iso_weekday=3, preference_weight=0.9),
        _availability(3, "DISCOURAGED", 7, 12, iso_weekday=4, preference_weight=0.5),
        _availability(3, "UNAVAILABLE", 7, 12, calendar_date="2026-09-10"),
        # GV005 không thể dạy thứ Ba và thứ Năm.
        _availability(4, "UNAVAILABLE", 1, 12, iso_weekday=2),
        _availability(4, "UNAVAILABLE", 1, 12, iso_weekday=4),
        _availability(4, "PREFERRED", 1, 6, iso_weekday=1, preference_weight=0.9),
        _availability(4, "PREFERRED", 7, 12, iso_weekday=2, preference_weight=1.0),
        _availability(4, "PREFERRED", 7, 12, iso_weekday=4, preference_weight=0.8),
        _availability(4, "DISCOURAGED", 1, 6, iso_weekday=5, preference_weight=0.6),
        _availability(4, "UNAVAILABLE", 1, 6, calendar_date="2026-09-28"),
    ]


def _build_constraint_settings() -> list[dict[str, object]]:
    """Cấu hình hard capacity và hai tầng fitness của mô hình D109."""

    return [
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
            "constraint_code": "HARD_ROOM_CAPACITY",
            "constraint_type": "HARD",
            "priority_tier": 1,
            "weight": None,
            "enabled": True,
        },
        {
            "constraint_code": "SOFT_LECTURER_GAP",
            "constraint_type": "SOFT",
            "priority_tier": 2,
            "weight": 0.3720,
            "enabled": True,
        },
        {
            "constraint_code": "SOFT_LECTURER_CONSECUTIVE",
            "constraint_type": "SOFT",
            "priority_tier": 2,
            "weight": 0.1487,
            "threshold_value": 6,
            "enabled": True,
        },
        {
            "constraint_code": "SOFT_ROOM_DISCOURAGED",
            "constraint_type": "SOFT",
            "priority_tier": 2,
            "weight": 0.2975,
            "enabled": True,
        },
        {
            "constraint_code": "SOFT_WORKLOAD_BALANCE",
            "constraint_type": "SOFT",
            "priority_tier": 2,
            "weight": 0.1818,
            "enabled": True,
        },
        {
            "constraint_code": "SOFT_LECTURER_TIME_PREFERENCE",
            "constraint_type": "SOFT",
            "priority_tier": 3,
            "weight": 0.5000,
            "enabled": True,
        },
        {
            "constraint_code": "SOFT_COURSE_SUITABILITY",
            "constraint_type": "SOFT",
            "priority_tier": 3,
            "weight": 0.5000,
            "enabled": True,
        },
    ]


def build_snapshot() -> dict[str, object]:
    """Dựng toàn bộ payload `problem-instance.v2` theo thứ tự xác định."""

    courses, sections, parts, plans, sessions, scenario_items = (
        _build_academic_objects()
    )
    term_end = FIRST_MONDAY + timedelta(days=7 * WEEK_COUNT - 1)
    return {
        "schema_version": "problem-instance.v2",
        "term": {
            "term_code": "2026_HK1_DYNAMIC_HARD",
            "term_name": "Học kỳ 1 2026-2027 - phân công động khan hiếm",
            "start_date": FIRST_MONDAY.isoformat(),
            "end_date": term_end.isoformat(),
            "status": "PLANNING",
        },
        "scenario": {
            "scenario_id": 9100,
            "scenario_code": "SCN-DYNAMIC-ASSIGNMENT-HARD-2026-HK1",
            "term_code": "2026_HK1_DYNAMIC_HARD",
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
        "locations": _build_dynamic_locations(),
        "lecturers": _build_lecturers(),
        "lecturer_course_capabilities": _build_capabilities(),
        "courses": courses,
        "course_sections": sections,
        "teaching_parts": parts,
        "teaching_plans": plans,
        "class_sessions": sessions,
        "lecturer_availabilities": _build_lecturer_availabilities(),
        "room_availabilities": _build_room_availabilities(),
        "campus_travel_times": [],
        "constraint_settings": _build_constraint_settings(),
    }


def main() -> None:
    """Ghi snapshot UTF-8 ổn định để có thể checksum và tái lập."""

    OUTPUT_PATH.write_text(
        json.dumps(build_snapshot(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Generated dynamic-assignment snapshot: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
