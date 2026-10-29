"""Kiểm thử service đọc thời khóa biểu đã lưu từ database."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

import pytest

from gapo_timetabling.application.timetable_query import (
    OptimizationRunNotCompletedError,
    OptimizationRunNotFoundError,
    TimetableDataIntegrityError,
    TimetableQueryFilters,
    TimetableQueryService,
)


class FakeCursor:
    """Cursor nhỏ mô phỏng đúng hai truy vấn mà service cần thực hiện."""

    def __init__(
        self,
        run: Mapping[str, Any] | None,
        entries: Sequence[Mapping[str, Any]],
    ) -> None:
        self._run = run
        self._entries = list(entries)
        self._rows: list[tuple[Any, ...]] = []
        self.description: list[tuple[str]] | None = None
        self.executions: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, *parameters: Any) -> "FakeCursor":
        self.executions.append((sql, parameters))
        if "FROM OptimizationRun" in sql and "FROM TimetableEntry" not in sql:
            self._set_result([] if self._run is None else [self._run])
        elif "FROM TimetableEntry" in sql:
            # Mô phỏng các placeholder theo đúng thứ tự service xây dựng. Fake
            # không phân tích SQL tổng quát; nó chỉ kiểm tra hợp đồng truy vấn
            # cố định của TimetableQueryService.
            rows = list(self._entries)
            parameter_index = 1  # parameters[0] luôn là run_id.
            if "(entry.lecturer_code LIKE ? OR lecturer.full_name LIKE ?)" in sql:
                search = str(parameters[parameter_index]).strip("%").casefold()
                parameter_index += 2
                rows = [
                    row for row in rows
                    if search in str(row["lecturer_code"]).casefold()
                    or search in str(row["lecturer_name"]).casefold()
                ]
            for clause, field in (
                ("entry.lecturer_code = ?", "lecturer_code"),
                ("course_section.section_code = ?", "section_code"),
                ("entry.term_code = ?", "term_code"),
                ("class_session.week_number = ?", "week_number"),
            ):
                if clause not in sql:
                    continue
                expected = parameters[parameter_index]
                parameter_index += 1
                rows = [row for row in rows if row[field] == expected]
            self._set_result(rows)
        else:  # pragma: no cover - bảo vệ fake khi query production thay đổi.
            raise AssertionError(f"Truy vấn không được fake hỗ trợ: {sql}")
        return self

    def executemany(
        self, sql: str, parameters: Sequence[Sequence[Any]]
    ) -> "FakeCursor":  # pragma: no cover - service chỉ đọc.
        raise AssertionError("TimetableQueryService không được ghi dữ liệu.")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def _set_result(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            self.description = [("run_id",), ("status",)]
            self._rows = []
            return
        columns = list(rows[0])
        self.description = [(column,) for column in columns]
        self._rows = [tuple(row[column] for column in columns) for row in rows]


class FakeConnection:
    """Connection chỉ đọc; commit/rollback là lỗi nếu service gọi nhầm."""

    def __init__(
        self,
        run: Mapping[str, Any] | None,
        entries: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self.fake_cursor = FakeCursor(run, entries)

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def commit(self) -> None:  # pragma: no cover - service không được gọi.
        raise AssertionError("Truy vấn chỉ đọc không được commit.")

    def rollback(self) -> None:  # pragma: no cover - service không được gọi.
        raise AssertionError("Truy vấn chỉ đọc không được rollback.")

    def close(self) -> None:
        pass


def make_entry(
    *,
    class_session_id: int,
    week_number: int,
    teaching_date: date,
    section_code: str = "JAVA01",
    part_id: int = 101,
    part_code: str = "JAVA01_LT",
    part_type: str = "LECTURE",
    stability_group_no: int = 1,
    iso_weekday: int = 1,
    start_period: int = 1,
    end_period: int = 3,
    duration_periods: int = 3,
    lecturer_code: str = "GV001",
    location_id: int = 11,
    location_code: str = "A201",
) -> dict[str, Any]:
    """Tạo một occurrence đầy đủ theo aliases của truy vấn production."""

    return {
        "run_id": 7,
        "class_session_id": class_session_id,
        "term_code": "2026_HK1",
        "term_name": "Học kỳ 1 năm học 2026-2027",
        "week_number": week_number,
        "duration_periods": duration_periods,
        "stability_group_no": stability_group_no,
        "iso_weekday": iso_weekday,
        "teaching_date": teaching_date,
        "start_period": start_period,
        "end_period": end_period,
        "section_code": section_code,
        "section_name": f"Lớp {section_code}",
        "course_code": "JAVA",
        "course_name": "Lập trình Java",
        "teaching_part_id": part_id,
        "part_code": part_code,
        "part_type": part_type,
        "lecturer_code": lecturer_code,
        "lecturer_name": "Nguyễn Văn An",
        "location_id": location_id,
        "location_code": location_code,
        "location_name": f"Phòng {location_code}",
        "location_type": "PHYSICAL_ROOM",
    }


def test_reads_completed_run_groups_weeks_and_sorts_schedule() -> None:
    entries = [
        # Thực hành vào thứ Tư được đặt trước để chứng minh service tự sắp xếp.
        make_entry(
            class_session_id=3,
            week_number=1,
            teaching_date=date(2026, 8, 19),
            part_id=102,
            part_code="JAVA01_TH",
            part_type="PRACTICE",
            stability_group_no=2,
            iso_weekday=3,
            start_period=7,
            end_period=11,
            duration_periods=5,
            location_id=21,
            location_code="LAB01",
        ),
        make_entry(
            class_session_id=1,
            week_number=1,
            teaching_date=date(2026, 8, 17),
        ),
        make_entry(
            class_session_id=2,
            week_number=2,
            teaching_date=date(2026, 8, 24),
        ),
    ]
    connection = FakeConnection({"run_id": 7, "status": "COMPLETED"}, entries)

    rows = TimetableQueryService(connection).get_run_schedule(7)

    assert len(rows) == 2
    lecture, practice = rows
    assert lecture.section_code == "JAVA01"
    assert lecture.course_name == "Lập trình Java"
    assert lecture.part_type == "LECTURE"
    assert lecture.weekday_name == "Thứ Hai"
    assert lecture.active_week_numbers == (1, 2)
    assert lecture.start_period == 1
    assert lecture.end_period == 3
    assert practice.part_type == "PRACTICE"
    assert practice.weekday_name == "Thứ Tư"
    assert practice.location_code == "LAB01"
    assert practice.active_week_numbers == (1,)

    assert len(connection.fake_cursor.executions) == 2
    assert all(parameters == (7,) for _, parameters in connection.fake_cursor.executions)
    assert "INNER JOIN Course" in connection.fake_cursor.executions[1][0]
    assert "INNER JOIN Lecturer" in connection.fake_cursor.executions[1][0]


def test_rejects_missing_run_without_querying_entries() -> None:
    connection = FakeConnection(None)

    with pytest.raises(OptimizationRunNotFoundError, match="run_id=99"):
        TimetableQueryService(connection).get_run_schedule(99)

    assert len(connection.fake_cursor.executions) == 1


@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "FAILED", "CANCELLED"])
def test_rejects_run_that_is_not_completed(status: str) -> None:
    connection = FakeConnection({"run_id": 7, "status": status})

    with pytest.raises(OptimizationRunNotCompletedError, match=status):
        TimetableQueryService(connection).get_run_schedule(7)

    assert len(connection.fake_cursor.executions) == 1


def test_rejects_completed_run_without_timetable_entries() -> None:
    connection = FakeConnection({"run_id": 7, "status": "COMPLETED"})

    with pytest.raises(TimetableDataIntegrityError, match="không có TimetableEntry"):
        TimetableQueryService(connection).get_run_schedule(7)


def test_rejects_recurring_group_that_changes_room_between_weeks() -> None:
    first = make_entry(
        class_session_id=1,
        week_number=1,
        teaching_date=date(2026, 8, 17),
    )
    second = make_entry(
        class_session_id=2,
        week_number=2,
        teaching_date=date(2026, 8, 24),
        location_id=12,
        location_code="A202",
    )
    connection = FakeConnection(
        {"run_id": 7, "status": "COMPLETED"},
        [first, second],
    )

    with pytest.raises(TimetableDataIntegrityError, match="Recurring group thay đổi"):
        TimetableQueryService(connection).get_run_schedule(7)


def test_rejects_period_range_that_does_not_match_session_duration() -> None:
    invalid = make_entry(
        class_session_id=1,
        week_number=1,
        teaching_date=date(2026, 8, 17),
        end_period=4,
        duration_periods=3,
    )
    connection = FakeConnection(
        {"run_id": 7, "status": "COMPLETED"},
        [invalid],
    )

    with pytest.raises(TimetableDataIntegrityError, match="không khớp duration"):
        TimetableQueryService(connection).get_run_schedule(7)


@pytest.mark.parametrize("run_id", [0, -1, True, 1.5, "7"])
def test_rejects_invalid_run_id(run_id: object) -> None:
    connection = FakeConnection({"run_id": 7, "status": "COMPLETED"})

    with pytest.raises(ValueError, match="số nguyên dương"):
        TimetableQueryService(connection).get_run_schedule(run_id)  # type: ignore[arg-type]

    assert connection.fake_cursor.executions == []


def test_filters_by_lecturer_section_term_and_week_with_parameters() -> None:
    matching = make_entry(
        class_session_id=1,
        week_number=2,
        teaching_date=date(2026, 8, 24),
    )
    other_lecturer = make_entry(
        class_session_id=2,
        week_number=2,
        teaching_date=date(2026, 8, 24),
        section_code="JAVA02",
        part_id=201,
        part_code="JAVA02_LT",
        lecturer_code="GV002",
    )
    connection = FakeConnection(
        {"run_id": 7, "status": "COMPLETED"},
        [matching, other_lecturer],
    )
    filters = TimetableQueryFilters(
        lecturer_code="  GV001 ",
        section_code=" JAVA01 ",
        term_code=" 2026_HK1 ",
        week_number=2,
    )

    rows = TimetableQueryService(connection).get_run_schedule(7, filters)

    assert len(rows) == 1
    assert rows[0].lecturer_code == "GV001"
    assert rows[0].section_code == "JAVA01"
    assert rows[0].term_code == "2026_HK1"
    assert rows[0].active_week_numbers == (2,)
    query, parameters = connection.fake_cursor.executions[1]
    assert "entry.lecturer_code = ?" in query
    assert "course_section.section_code = ?" in query
    assert "entry.term_code = ?" in query
    assert "class_session.week_number = ?" in query
    assert parameters == (7, "GV001", "JAVA01", "2026_HK1", 2)
    assert "GV001" not in query


def test_filtered_query_returns_empty_tuple_when_nothing_matches() -> None:
    connection = FakeConnection(
        {"run_id": 7, "status": "COMPLETED"},
        [
            make_entry(
                class_session_id=1,
                week_number=1,
                teaching_date=date(2026, 8, 17),
            )
        ],
    )

    rows = TimetableQueryService(connection).get_run_schedule(
        7,
        TimetableQueryFilters(lecturer_code="GV999"),
    )

    assert rows == ()


def test_lecturer_query_matches_both_lecturer_name_and_code() -> None:
    entry = make_entry(
        class_session_id=1,
        week_number=1,
        teaching_date=date(2026, 8, 17),
    )
    connection = FakeConnection(
        {"run_id": 7, "status": "COMPLETED"},
        [entry],
    )

    by_name = TimetableQueryService(connection).get_run_schedule(
        7, TimetableQueryFilters(lecturer_query="Văn An")
    )

    assert len(by_name) == 1
    query, parameters = connection.fake_cursor.executions[-1]
    assert "lecturer.full_name LIKE ?" in query
    assert parameters == (7, "%Văn An%", "%Văn An%")


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"lecturer_code": "  "}, "lecturer_code"),
        ({"lecturer_query": "  "}, "lecturer_query"),
        ({"section_code": 123}, "section_code"),
        ({"term_code": ""}, "term_code"),
        ({"week_number": 0}, "week_number"),
        ({"week_number": True}, "week_number"),
    ],
)
def test_rejects_invalid_query_filters(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        TimetableQueryFilters(**kwargs)  # type: ignore[arg-type]


def test_rejects_unknown_filter_object() -> None:
    connection = FakeConnection({"run_id": 7, "status": "COMPLETED"})

    with pytest.raises(TypeError, match="TimetableQueryFilters"):
        TimetableQueryService(connection).get_run_schedule(7, object())  # type: ignore[arg-type]

    assert connection.fake_cursor.executions == []


def exception_records():
    return [
        make_entry(class_session_id=1, week_number=1, teaching_date=date(2026, 8, 17)),
        make_entry(class_session_id=2, week_number=2, teaching_date=date(2026, 8, 26),
                   iso_weekday=3, start_period=4, end_period=6, location_id=12, location_code="A202"),
        make_entry(class_session_id=3, week_number=3, teaching_date=date(2026, 8, 31)),
    ]


def test_revision_groups_exception_separately_without_duplicating_other_weeks():
    rows = TimetableQueryService._group_recurring_records(7, exception_records(), allow_occurrence_exceptions=True)
    assert len(rows) == 2
    original, exception = rows
    assert original.active_week_numbers == (1, 3)
    assert exception.active_week_numbers == (2,)
    assert exception.iso_weekday == 3 and exception.start_period == 4
    assert exception.location_code == "A202"
    assert sum(len(row.active_week_numbers) for row in rows) == 3


@pytest.mark.parametrize("change", [{"lecturer_code": "OTHER"}, {"course_code": "OTHER"}])
def test_revision_still_rejects_identity_change(change):
    records = exception_records()
    records[1].update(change)
    with pytest.raises(TimetableDataIntegrityError, match="không được thay đổi"):
        TimetableQueryService._group_recurring_records(7, records, allow_occurrence_exceptions=True)


def test_revision_still_rejects_two_occurrences_in_same_group_week():
    records = exception_records()
    records[1]["week_number"] = 1
    with pytest.raises(TimetableDataIntegrityError, match="trong cùng tuần"):
        TimetableQueryService._group_recurring_records(7, records, allow_occurrence_exceptions=True)


def test_original_optimizer_schedule_still_rejects_occurrence_exception():
    with pytest.raises(TimetableDataIntegrityError, match="Recurring group thay đổi"):
        TimetableQueryService._group_recurring_records(7, exception_records())


def test_exception_csv_and_excel_keep_week_numbers_and_slots_in_sync(tmp_path):
    import csv
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile
    from gapo_timetabling.application.timetable_export import TimetableExportService
    from gapo_timetabling.application.timetable_excel import TimetableExcelExportService
    rows = TimetableQueryService._group_recurring_records(7, exception_records(), allow_occurrence_exceptions=True)

    class RevisionQuery(TimetableQueryService):
        def __init__(self):
            pass

        def get_run_schedule(self, run_id, filters=None):
            assert run_id == 7 and filters.revision_id == 8
            return rows

    filters = TimetableQueryFilters(revision_id=8)
    query = RevisionQuery()
    csv_path, xlsx_path = tmp_path / "revision.csv", tmp_path / "revision.xlsx"
    TimetableExportService(query).export_run_csv(7, csv_path, filters)
    TimetableExcelExportService(query).export_run_xlsx(7, xlsx_path, filters)
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert [row["Tuần hoạt động"] for row in csv_rows] == ["1, 3", "2"]
    assert csv_rows[1]["Thứ"] == "Thứ Tư" and csv_rows[1]["Tiết bắt đầu"] == "4"
    with ZipFile(xlsx_path) as archive:
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values = {cell.attrib["r"]: "".join(cell.itertext()) for cell in root.findall(".//m:c", ns)}
    assert values["R5"] == "1, 3" and values["R6"] == "2"
    assert values["J6"] == "Thứ Tư" and values["K6"] == "4"
