"""Kiểm thử hợp đồng chuẩn dùng chung cho nhập tay và Excel."""

from datetime import date

import pytest
from pydantic import ValidationError

from gapo_timetabling.application.input_data import SemesterInputBundle, SemesterInputService


class RecordingCursor:
    def __init__(self, *, locked: bool = False) -> None:
        self.locked = locked
        self.description = None
        self.rows: list[tuple[object, ...]] = []
        self.statements: list[str] = []

    def execute(self, sql: str, *parameters: object) -> "RecordingCursor":
        self.statements.append(sql)
        if "FROM PlanningScenario" in sql:
            self.description = [("scenario_id",)]
            self.rows = [(99,)] if self.locked else []
        elif "FROM AcademicTerm WHERE term_code" in sql:
            self.description = [("start_date",), ("end_date",)]
            self.rows = []
        else:
            self.description = None
            self.rows = []
        return self

    def executemany(self, sql: str, parameters: object) -> "RecordingCursor":
        self.statements.append(sql)
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class RecordingConnection:
    def __init__(self, *, locked: bool = False) -> None:
        self.recorder = RecordingCursor(locked=locked)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> RecordingCursor:
        return self.recorder

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        pass


def valid_payload() -> dict[str, object]:
    return {
        "term": {
            "term_code": "2026_HK1",
            "term_name": "Học kỳ 1",
            "start_date": "2026-08-17",
            "number_of_weeks": 15,
        },
        "campuses": [{"campus_code": "CS1", "campus_name": "Cơ sở 1"}],
        "courses": [{"course_code": "JAVA", "course_name": "Lập trình Java"}],
        "lecturers": [{"lecturer_code": "GV01", "full_name": "Nguyễn Văn A"}],
        "lecturer_capabilities": [{
            "lecturer_code": "GV01",
            "course_code": "JAVA",
            "can_teach_lecture": True,
            "can_teach_practice": True,
        }],
        "rooms": [{
            "room_code": "A101",
            "room_name": "Phòng A101",
            "campus_code": "CS1",
            "room_type": "LECTURE_ROOM",
            "capacity": 60,
        }],
        "course_sections": [{"section_code": "JAVA01", "course_code": "JAVA"}],
        "course_teaching_structures": [{
            "course_code": "JAVA",
            "part_type": "LECTURE",
            "total_periods": 45,
            "required_room_type": "LECTURE_ROOM",
            "max_sessions_per_week": 1,
        }],
    }


def test_bundle_derives_term_end_and_accepts_dynamic_lecturer_capability() -> None:
    bundle = SemesterInputBundle.model_validate(valid_payload())

    assert bundle.term.end_date == date(2026, 11, 29)
    assert bundle.lecturer_capabilities[0].can_teach_practice is True
    assert bundle.course_teaching_structures[0].course_code == "JAVA"


def test_bundle_rejects_duplicate_codes_and_duplicate_course_structure() -> None:
    duplicate = valid_payload()
    duplicate["courses"] = [
        {"course_code": "JAVA", "course_name": "Java"},
        {"course_code": "java", "course_name": "Trùng không phân biệt hoa thường"},
    ]
    with pytest.raises(ValidationError, match="trùng course_code"):
        SemesterInputBundle.model_validate(duplicate)

    duplicated_structure = valid_payload()
    duplicated_structure["course_teaching_structures"].append({  # type: ignore[union-attr]
        "course_code": "java",
        "part_type": "LECTURE",
        "total_periods": 30,
        "required_room_type": "LECTURE_ROOM",
        "max_sessions_per_week": 1,
    })
    with pytest.raises(ValidationError, match="trùng.*course_code.*part_type"):
        SemesterInputBundle.model_validate(duplicated_structure)


def test_bundle_rejects_capability_without_supported_part_type() -> None:
    payload = valid_payload()
    payload["lecturer_capabilities"][0].update({  # type: ignore[index,union-attr]
        "can_teach_lecture": False,
        "can_teach_practice": False,
    })

    with pytest.raises(ValidationError, match="ít nhất lý thuyết hoặc thực hành"):
        SemesterInputBundle.model_validate(payload)


def test_availability_requires_exactly_one_scope_dimension() -> None:
    payload = valid_payload()
    payload["lecturer_availability"] = [{
        "lecturer_code": "GV01",
        "scope_type": "WEEKDAY",
        "calendar_date": "2026-08-17",
        "iso_weekday": 1,
        "start_period": 1,
        "end_period": 3,
        "availability_type": "UNAVAILABLE",
    }]

    with pytest.raises(ValidationError, match="không nhận calendar_date"):
        SemesterInputBundle.model_validate(payload)


def test_input_service_commits_calendar_as_one_transaction() -> None:
    connection = RecordingConnection()
    bundle = SemesterInputBundle.model_validate({
        "term": {
            "term_code": "2026_HK1",
            "term_name": "Học kỳ 1",
            "start_date": "2026-08-17",
            "number_of_weeks": 2,
        }
    })

    result = SemesterInputService(connection).apply(bundle)  # type: ignore[arg-type]

    assert result.term_code == "2026_HK1"
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert sum("INSERT INTO TeachingDate" in sql for sql in connection.recorder.statements) == 14


def test_input_service_rolls_back_when_term_has_locked_scenario() -> None:
    connection = RecordingConnection(locked=True)
    bundle = SemesterInputBundle.model_validate({
        "term": {
            "term_code": "2026_HK1",
            "term_name": "Học kỳ 1",
            "start_date": "2026-08-17",
            "number_of_weeks": 2,
        }
    })

    with pytest.raises(ValueError, match="scenario LOCKED"):
        SemesterInputService(connection).apply(bundle)  # type: ignore[arg-type]

    assert connection.commits == 0
    assert connection.rollbacks == 1
