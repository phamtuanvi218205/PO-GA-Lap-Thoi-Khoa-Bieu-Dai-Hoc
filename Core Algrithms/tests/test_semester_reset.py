"""Kiểm thử thao tác đặt lại dữ liệu dẫn xuất để chạy demo nhiều lần."""

from __future__ import annotations

from typing import Any

import pytest

from gapo_timetabling.application.semester_reset import (
    SemesterResetConflictError,
    SemesterResetPersistenceError,
    SemesterResetService,
)


class ResetCursor:
    def __init__(
        self,
        *,
        term_exists: bool = True,
        active_run: dict[str, Any] | None = None,
        fail_delete_number: int | None = None,
    ) -> None:
        self.term_exists = term_exists
        self.active_run = active_run
        self.fail_delete_number = fail_delete_number
        self.delete_count = 0
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.description: list[tuple[str]] | None = None
        self._row: tuple[Any, ...] | None = None

    def execute(self, sql: str, *parameters: Any) -> "ResetCursor":
        normalized = " ".join(sql.split())
        self.executed.append((normalized, parameters))
        if normalized.startswith("SELECT term_code FROM AcademicTerm"):
            self.description = [("term_code",)]
            self._row = (parameters[0],) if self.term_exists else None
        elif "SELECT TOP 1 run.run_id" in normalized:
            self.description = [("run_id",), ("status",)]
            self._row = (
                (self.active_run["run_id"], self.active_run["status"])
                if self.active_run is not None
                else None
            )
        elif normalized.startswith("SELECT COUNT_BIG"):
            self.description = [("row_count",)]
            self._row = (2,)
        elif normalized.startswith("DELETE"):
            self.delete_count += 1
            if self.delete_count == self.fail_delete_number:
                raise RuntimeError("database failure")
            self.description = None
            self._row = None
        else:  # pragma: no cover - giúp test báo rõ query mới chưa được mô phỏng.
            raise AssertionError(normalized)
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [] if self._row is None else [self._row]


class ResetConnection:
    def __init__(self, cursor: ResetCursor) -> None:
        self.fake_cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> ResetCursor:
        return self.fake_cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        pass


def test_reset_removes_only_seven_derived_groups_in_one_transaction() -> None:
    cursor = ResetCursor()
    connection = ResetConnection(cursor)

    result = SemesterResetService(connection).reset(" 2027_HK1 ")

    assert result.term_code == "2027_HK1"
    assert result.deleted_counts == {
        "timetable_entries": 2,
        "optimization_runs": 2,
        "scenario_items": 2,
        "scenarios": 2,
        "class_sessions": 2,
        "plan_items": 2,
        "teaching_plans": 2,
    }
    assert cursor.delete_count == 7
    assert connection.committed is True
    assert connection.rolled_back is False
    delete_sql = " ".join(sql for sql, _ in cursor.executed if sql.startswith("DELETE"))
    assert "TeachingPartGenerationRule" not in delete_sql
    assert "DELETE FROM CourseSection" not in delete_sql
    assert "DELETE section" not in delete_sql
    assert "DELETE FROM TeachingPart" not in delete_sql
    assert "DELETE part" not in delete_sql


def test_reset_rejects_term_with_active_run_without_deleting_anything() -> None:
    cursor = ResetCursor(active_run={"run_id": 81, "status": "RUNNING"})
    connection = ResetConnection(cursor)

    with pytest.raises(SemesterResetConflictError, match="run 81"):
        SemesterResetService(connection).reset("2027_HK1")

    assert cursor.delete_count == 0
    assert connection.committed is False
    assert connection.rolled_back is False


def test_reset_rolls_back_when_one_delete_fails() -> None:
    cursor = ResetCursor(fail_delete_number=4)
    connection = ResetConnection(cursor)

    with pytest.raises(SemesterResetPersistenceError):
        SemesterResetService(connection).reset("2027_HK1")

    assert connection.committed is False
    assert connection.rolled_back is True
