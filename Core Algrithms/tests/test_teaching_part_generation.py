"""Tests for automatic materialization of term teaching parts."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest

from gapo_timetabling.application.teaching_part_generation import TeachingPartGenerator


class GenerationCursor:
    def __init__(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        existing_part_id: int | None = None,
    ) -> None:
        self.source_rows = list(rows)
        self.description: list[tuple[str]] | None = None
        self.result_rows: list[tuple[Any, ...]] = []
        self.statements: list[str] = []
        self.next_part_id = 100
        self.existing_part_id = existing_part_id

    def execute(self, sql: str, *parameters: Any) -> "GenerationCursor":
        self.statements.append(sql)
        if "FROM CourseSection AS section" in sql:
            self._set(self.source_rows)
        elif "SELECT teaching_part_id, part_code" in sql:
            self._set(
                []
                if self.existing_part_id is None
                else [{"teaching_part_id": self.existing_part_id, "part_code": "JAVA01_LT"}]
            )
        elif "OUTPUT INSERTED.teaching_part_id" in sql:
            self.next_part_id += 1
            self._set([{"teaching_part_id": self.next_part_id}])
        else:
            self.description = None
            self.result_rows = []
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.result_rows[0] if self.result_rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.result_rows)

    def _set(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            self.description = [("empty",)]
            self.result_rows = []
            return
        columns = list(rows[0])
        self.description = [(column,) for column in columns]
        self.result_rows = [tuple(row[column] for column in columns) for row in rows]


def structure_row(part_type: str, structure_id: int) -> dict[str, Any]:
    return {
        "section_code": "JAVA01",
        "course_code": "JAVA",
        "course_structure_id": structure_id,
        "part_type": part_type,
        "total_periods": 45 if part_type == "LECTURE" else 30,
        "required_location_type": "PHYSICAL_ROOM",
        "required_room_type": "LECTURE_ROOM" if part_type == "LECTURE" else "COMPUTER_LAB",
        "max_sessions_per_week": 2,
        "allows_intensive": True,
        "max_candidate_plans": 20,
        "note": None,
    }


def test_generator_materializes_each_structure_and_copies_generation_rules() -> None:
    cursor = GenerationCursor([
        structure_row("LECTURE", 11),
        structure_row("PRACTICE", 12),
    ])

    result = TeachingPartGenerator().generate(
        cursor,
        term_code="2027_HK1",
        number_of_weeks=15,
    )

    assert result.generated_part_count == 2
    assert sum("INSERT INTO TeachingPart(" in sql for sql in cursor.statements) == 2
    assert sum("TeachingPlanGenerationRule" in sql for sql in cursor.statements) == 2
    assert sum("CourseTeachingStructureRequiredEquipment" in sql for sql in cursor.statements) == 2


def test_generator_rejects_open_section_without_course_structure() -> None:
    missing = structure_row("LECTURE", 11)
    missing["course_structure_id"] = None
    cursor = GenerationCursor([missing])

    with pytest.raises(ValueError, match="JAVA01"):
        TeachingPartGenerator().generate(
            cursor,
            term_code="2027_HK1",
            number_of_weeks=15,
        )


def test_generator_updates_existing_part_instead_of_inserting_duplicate() -> None:
    cursor = GenerationCursor(
        [structure_row("LECTURE", 11)], existing_part_id=77
    )

    result = TeachingPartGenerator().generate(
        cursor,
        term_code="2027_HK1",
        number_of_weeks=15,
    )

    assert result.generated_part_count == 1
    assert not any("INSERT INTO TeachingPart(" in sql for sql in cursor.statements)
    assert any("UPDATE TeachingPart" in sql for sql in cursor.statements)


def test_generated_part_code_is_deterministic_and_never_exceeds_database_limit() -> None:
    first = TeachingPartGenerator._make_part_code(
        "SECTION_CODE_LONGER_THAN_DATABASE_LIMIT", "PRACTICE"
    )
    second = TeachingPartGenerator._make_part_code(
        "SECTION_CODE_LONGER_THAN_DATABASE_LIMIT", "PRACTICE"
    )

    assert first == second
    assert first.endswith("_TH")
    assert len(first) <= 30
