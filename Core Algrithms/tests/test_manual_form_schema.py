"""Biểu mẫu phải nhận đầy đủ schema và chặn loại phòng không được core hỗ trợ."""

import pytest
from pydantic import ValidationError

from gapo_timetabling.application.input_data import (
    RoomInput,
    CourseTeachingStructureInput,
)
from tests.test_api import make_client


def test_manual_form_schema_covers_all_source_groups_and_room_types():
    client, _, _ = make_client()
    response = client.get("/api/input-data/form-schema")
    assert response.status_code == 200
    schema = response.json()
    assert set(schema["properties"]) == {
        "term",
        "campuses",
        "courses",
        "lecturers",
        "lecturer_capabilities",
        "rooms",
        "online_locations",
        "equipment",
        "room_equipment",
        "course_sections",
        "course_teaching_structures",
        "course_structure_equipment",
        "lecturer_availability",
        "room_availability",
    }
    assert schema["$defs"]["RoomInput"]["properties"]["room_type"]["enum"] == [
        "LECTURE_ROOM",
        "COMPUTER_LAB",
    ]


def test_unsupported_room_type_is_rejected_at_input_not_delayed_to_optimizer():
    with pytest.raises(ValidationError):
        RoomInput(
            room_code="A1",
            room_name="A1",
            campus_code="CS1",
            room_type="UNKNOWN",
            capacity=60,
        )
    with pytest.raises(ValidationError):
        CourseTeachingStructureInput(
            course_code="JAVA",
            part_type="LECTURE",
            total_periods=45,
            required_room_type="UNKNOWN",
            max_sessions_per_week=1,
        )
