"""Generate teaching parts from reusable course structures.

The input contract describes a course once (for example, 45 lecture periods
and 30 practice periods).  This service materializes that structure only for
course sections opened in the selected academic term.  It is intentionally
separate from ``TeachingPlanGenerator``: this service creates the parts that
must be taught, while plan generation decides how each part is divided into
weekly sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .database import fetch_all_dicts, fetch_one_dict


@dataclass(frozen=True, slots=True)
class TeachingPartGenerationResult:
    """Summary of one idempotent materialization operation."""

    term_code: str
    generated_part_count: int


class TeachingPartGenerator:
    """Materialize ``TeachingPart`` rows for active course sections in a term."""

    _PART_SUFFIX = {"LECTURE": "LT", "PRACTICE": "TH"}

    def generate(
        self,
        cursor: Any,
        *,
        term_code: str,
        number_of_weeks: int,
    ) -> TeachingPartGenerationResult:
        rows = fetch_all_dicts(cursor.execute(
            """
            SELECT section.section_code, section.course_code,
                   structure.course_structure_id, structure.part_type,
                   structure.total_periods, structure.required_location_type,
                   structure.required_room_type, structure.max_sessions_per_week,
                   structure.allows_intensive, structure.max_candidate_plans,
                   structure.note
            FROM CourseSection AS section
            LEFT JOIN CourseTeachingStructure AS structure
              ON structure.course_code = section.course_code
             AND structure.is_active = 1
            WHERE section.term_code = ?
              AND section.status IN ('PLANNING', 'APPROVED')
            ORDER BY section.section_code, structure.part_type
            """,
            term_code,
        ))

        sections_without_structure = sorted({
            str(row["section_code"])
            for row in rows
            if row.get("course_structure_id") is None
        })
        if sections_without_structure:
            raise ValueError(
                "Chưa khai báo cấu trúc môn cho lớp học phần: "
                + ", ".join(sections_without_structure)
                + "."
            )

        generated_count = 0
        for row in rows:
            part_id = self._upsert_part(cursor, row)
            self._upsert_generation_rule(
                cursor,
                part_id=part_id,
                number_of_weeks=number_of_weeks,
                row=row,
            )
            self._replace_required_equipment(
                cursor,
                part_id=part_id,
                course_structure_id=int(row["course_structure_id"]),
            )
            generated_count += 1

        return TeachingPartGenerationResult(term_code, generated_count)

    def _upsert_part(self, cursor: Any, row: dict[str, Any]) -> int:
        existing = fetch_one_dict(cursor.execute(
            """
            SELECT teaching_part_id, part_code
            FROM TeachingPart
            WHERE section_code = ? AND part_type = ?
            """,
            row["section_code"],
            row["part_type"],
        ))
        if existing is None:
            part_code = self._make_part_code(
                str(row["section_code"]), str(row["part_type"])
            )
            inserted = fetch_one_dict(cursor.execute(
                """
                INSERT INTO TeachingPart(
                    section_code, part_code, part_type, course_structure_id,
                    total_periods, required_room_type,
                    required_location_type, note
                )
                OUTPUT INSERTED.teaching_part_id
                VALUES(?,?,?,?,?,?,?,?);
                """,
                row["section_code"], part_code, row["part_type"],
                row["course_structure_id"], row["total_periods"],
                row["required_room_type"], row["required_location_type"],
                row["note"],
            ))
            if inserted is None:
                raise RuntimeError("SQL Server không trả TeachingPart vừa tạo.")
            return int(inserted["teaching_part_id"])

        part_id = int(existing["teaching_part_id"])
        cursor.execute(
            """
            UPDATE TeachingPart
            SET course_structure_id=?, total_periods=?, required_room_type=?,
                required_location_type=?, note=?
            WHERE teaching_part_id=?;
            """,
            row["course_structure_id"], row["total_periods"],
            row["required_room_type"], row["required_location_type"],
            row["note"], part_id,
        )
        return part_id

    @staticmethod
    def _upsert_generation_rule(
        cursor: Any,
        *,
        part_id: int,
        number_of_weeks: int,
        row: dict[str, Any],
    ) -> None:
        # Course structures use the complete term as their allowed window.
        # Concentrated study is represented by generated plans that may finish
        # earlier, not by manually shortening this source window.
        cursor.execute(
            """
            UPDATE TeachingPlanGenerationRule
            SET start_week_number=1, end_week_number=?,
                max_sessions_per_week=?, allows_intensive=?,
                max_candidate_plans=?, is_active=1
            WHERE teaching_part_id=?;
            IF @@ROWCOUNT=0
                INSERT INTO TeachingPlanGenerationRule(
                    teaching_part_id,start_week_number,end_week_number,
                    max_sessions_per_week,allows_intensive,
                    max_candidate_plans,is_active
                ) VALUES(?,1,?,?,?,?,1);
            """,
            number_of_weeks, row["max_sessions_per_week"],
            row["allows_intensive"], row["max_candidate_plans"], part_id,
            part_id, number_of_weeks, row["max_sessions_per_week"],
            row["allows_intensive"], row["max_candidate_plans"],
        )

    @staticmethod
    def _replace_required_equipment(
        cursor: Any,
        *,
        part_id: int,
        course_structure_id: int,
    ) -> None:
        # Requirements are owned by the reusable course structure. Replacing
        # the generated rows prevents obsolete equipment from surviving after
        # a structure is edited and keeps repeated imports deterministic.
        cursor.execute(
            "DELETE FROM TeachingPartRequiredEquipment WHERE teaching_part_id=?",
            part_id,
        )
        cursor.execute(
            """
            INSERT INTO TeachingPartRequiredEquipment(
                teaching_part_id,equipment_code,minimum_quantity
            )
            SELECT ?,equipment_code,minimum_quantity
            FROM CourseTeachingStructureRequiredEquipment
            WHERE course_structure_id=?;
            """,
            part_id,
            course_structure_id,
        )

    @classmethod
    def _make_part_code(cls, section_code: str, part_type: str) -> str:
        suffix = cls._PART_SUFFIX[part_type]
        candidate = f"{section_code}_{suffix}"
        if len(candidate) <= 30:
            return candidate
        digest = sha256(candidate.encode("utf-8")).hexdigest()[:6].upper()
        prefix_length = 30 - len(suffix) - len(digest) - 2
        return f"{section_code[:prefix_length]}_{digest}_{suffix}"
