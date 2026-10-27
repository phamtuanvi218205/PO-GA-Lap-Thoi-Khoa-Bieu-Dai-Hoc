"""Đặt lại dữ liệu dẫn xuất của một học kỳ để có thể chạy demo lại.

Service này cố ý giữ nguyên toàn bộ dữ liệu nguồn do người dùng nhập. Chỉ các
plan, session, scenario, run và thời khóa biểu đã sinh ra mới bị xóa.
"""

from __future__ import annotations

from dataclasses import dataclass

from .database import ConnectionProtocol, CursorProtocol, fetch_one_dict


class SemesterResetNotFoundError(LookupError):
    """Học kỳ cần đặt lại không tồn tại."""


class SemesterResetConflictError(RuntimeError):
    """Học kỳ đang có run hoạt động nên chưa thể đặt lại an toàn."""


class SemesterResetPersistenceError(RuntimeError):
    """Database từ chối thao tác đặt lại dữ liệu dẫn xuất."""


@dataclass(frozen=True, slots=True)
class SemesterResetResult:
    """Số dòng đã xóa theo từng nhóm dữ liệu dẫn xuất."""

    term_code: str
    deleted_counts: dict[str, int]


class SemesterResetService:
    """Xóa nguyên tử dữ liệu phát sinh sau bước nhập của một học kỳ."""

    _COUNT_QUERIES = {
        "timetable_entries": """
            SELECT COUNT_BIG(*) AS row_count
            FROM TimetableEntry entry
            JOIN OptimizationRun run ON run.run_id = entry.run_id
            JOIN PlanningScenario scenario ON scenario.scenario_id = run.scenario_id
            WHERE scenario.term_code = ?
        """,
        "optimization_runs": """
            SELECT COUNT_BIG(*) AS row_count
            FROM OptimizationRun run
            JOIN PlanningScenario scenario ON scenario.scenario_id = run.scenario_id
            WHERE scenario.term_code = ?
        """,
        "scenario_items": """
            SELECT COUNT_BIG(*) AS row_count
            FROM PlanningScenarioItem item
            JOIN PlanningScenario scenario ON scenario.scenario_id = item.scenario_id
            WHERE scenario.term_code = ?
        """,
        "scenarios": """
            SELECT COUNT_BIG(*) AS row_count
            FROM PlanningScenario
            WHERE term_code = ?
        """,
        "class_sessions": """
            SELECT COUNT_BIG(*) AS row_count
            FROM ClassSession cls
            JOIN TeachingPlan tp ON tp.teaching_plan_id = cls.teaching_plan_id
            JOIN TeachingPart part ON part.teaching_part_id = tp.teaching_part_id
            JOIN CourseSection course_section
              ON course_section.section_code = part.section_code
            WHERE course_section.term_code = ?
        """,
        "plan_items": """
            SELECT COUNT_BIG(*) AS row_count
            FROM TeachingPlanItem item
            JOIN TeachingPlan tp ON tp.teaching_plan_id = item.teaching_plan_id
            JOIN TeachingPart part ON part.teaching_part_id = tp.teaching_part_id
            JOIN CourseSection course_section
              ON course_section.section_code = part.section_code
            WHERE course_section.term_code = ?
        """,
        "teaching_plans": """
            SELECT COUNT_BIG(*) AS row_count
            FROM TeachingPlan tp
            JOIN TeachingPart part ON part.teaching_part_id = tp.teaching_part_id
            JOIN CourseSection course_section
              ON course_section.section_code = part.section_code
            WHERE course_section.term_code = ?
        """,
    }

    _DELETE_QUERIES = (
        """
        DELETE entry
        FROM TimetableEntry entry
        JOIN OptimizationRun run ON run.run_id = entry.run_id
        JOIN PlanningScenario scenario ON scenario.scenario_id = run.scenario_id
        WHERE scenario.term_code = ?
        """,
        """
        DELETE run
        FROM OptimizationRun run
        JOIN PlanningScenario scenario ON scenario.scenario_id = run.scenario_id
        WHERE scenario.term_code = ?
        """,
        """
        DELETE item
        FROM PlanningScenarioItem item
        JOIN PlanningScenario scenario ON scenario.scenario_id = item.scenario_id
        WHERE scenario.term_code = ?
        """,
        "DELETE FROM PlanningScenario WHERE term_code = ?",
        """
        DELETE cls
        FROM ClassSession cls
        JOIN TeachingPlan tp ON tp.teaching_plan_id = cls.teaching_plan_id
        JOIN TeachingPart part ON part.teaching_part_id = tp.teaching_part_id
        JOIN CourseSection course_section
          ON course_section.section_code = part.section_code
        WHERE course_section.term_code = ?
        """,
        """
        DELETE item
        FROM TeachingPlanItem item
        JOIN TeachingPlan tp ON tp.teaching_plan_id = item.teaching_plan_id
        JOIN TeachingPart part ON part.teaching_part_id = tp.teaching_part_id
        JOIN CourseSection course_section
          ON course_section.section_code = part.section_code
        WHERE course_section.term_code = ?
        """,
        """
        DELETE tp
        FROM TeachingPlan tp
        JOIN TeachingPart part ON part.teaching_part_id = tp.teaching_part_id
        JOIN CourseSection course_section
          ON course_section.section_code = part.section_code
        WHERE course_section.term_code = ?
        """,
    )

    def __init__(self, connection: ConnectionProtocol) -> None:
        self._connection = connection

    def reset(self, term_code: str) -> SemesterResetResult:
        """Đặt học kỳ về trạng thái ngay sau khi nhập dữ liệu nguồn."""

        normalized_term = term_code.strip()
        if not normalized_term:
            raise ValueError("Mã học kỳ không được để trống.")

        cursor = self._connection.cursor()
        term = fetch_one_dict(cursor.execute(
            "SELECT term_code FROM AcademicTerm WHERE term_code = ?",
            normalized_term,
        ))
        if term is None:
            raise SemesterResetNotFoundError(
                f"Không tồn tại học kỳ {normalized_term}."
            )

        active_run = fetch_one_dict(cursor.execute(
            """
            SELECT TOP 1 run.run_id, run.status
            FROM OptimizationRun run
            JOIN PlanningScenario scenario ON scenario.scenario_id = run.scenario_id
            WHERE scenario.term_code = ?
              AND run.status IN ('PENDING', 'RUNNING')
            ORDER BY run.run_id
            """,
            normalized_term,
        ))
        if active_run is not None:
            raise SemesterResetConflictError(
                "Học kỳ đang có run "
                f"{active_run['run_id']} ở trạng thái {active_run['status']}. "
                "Hãy hủy hoặc chờ run kết thúc trước khi đặt lại."
            )

        try:
            deleted_counts = {
                name: self._count(cursor, sql, normalized_term)
                for name, sql in self._COUNT_QUERIES.items()
            }
            for sql in self._DELETE_QUERIES:
                cursor.execute(sql, normalized_term)
            self._connection.commit()
        except Exception as error:
            self._connection.rollback()
            raise SemesterResetPersistenceError(
                f"Không thể đặt lại dữ liệu dẫn xuất của học kỳ {normalized_term}."
            ) from error

        return SemesterResetResult(
            term_code=normalized_term,
            deleted_counts=deleted_counts,
        )

    @staticmethod
    def _count(cursor: CursorProtocol, sql: str, term_code: str) -> int:
        row = fetch_one_dict(cursor.execute(sql, term_code))
        return int(row["row_count"]) if row is not None else 0
