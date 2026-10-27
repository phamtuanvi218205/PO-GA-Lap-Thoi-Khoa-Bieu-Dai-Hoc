"""Kiểm thử workbook Excel xuất từ lịch đã lưu."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from gapo_timetabling.application.timetable_excel import (
    TimetableExcelExportService,
)
from gapo_timetabling.application.timetable_query import (
    TimetableQueryFilters,
    TimetableQueryService,
    TimetableScheduleRow,
)


class StubTimetableQueryService(TimetableQueryService):
    def __init__(self, rows: tuple[TimetableScheduleRow, ...]) -> None:
        self.rows = rows
        self.calls: list[tuple[int, TimetableQueryFilters | None]] = []

    def get_run_schedule(
        self,
        run_id: int,
        filters: TimetableQueryFilters | None = None,
    ) -> tuple[TimetableScheduleRow, ...]:
        self.calls.append((run_id, filters))
        return self.rows


def make_row() -> TimetableScheduleRow:
    return TimetableScheduleRow(
        run_id=7,
        term_code="2026_HK1",
        term_name="Học kỳ 1 năm học 2026-2027",
        section_code="JAVA01",
        section_name="Lớp Java 01",
        course_code="JAVA",
        course_name="Lập trình Java",
        part_code="JAVA01_LT",
        part_type="LECTURE",
        stability_group_no=1,
        lecturer_code="GV001",
        lecturer_name="Nguyễn Văn An",
        location_id=11,
        location_code="A201",
        location_name="Phòng A201",
        location_type="PHYSICAL_ROOM",
        iso_weekday=1,
        start_period=1,
        end_period=3,
        active_week_numbers=(1, 2, 4),
    )


def test_exports_valid_ooxml_package_with_two_sheets(tmp_path: Path) -> None:
    query = StubTimetableQueryService((make_row(),))
    filters = TimetableQueryFilters(lecturer_code="GV001")
    output = tmp_path / "nested" / "timetable.xlsx"

    result = TimetableExcelExportService(query).export_run_xlsx(
        7,
        output,
        filters,
    )

    assert result.output_path == output.resolve()
    assert result.row_count == 1
    assert query.calls == [(7, filters)]
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/worksheets/sheet2.xml" in names
        workbook = archive.read("xl/workbook.xml").decode("utf-8")
        assert "Thời khóa biểu" in workbook
        assert "Thông tin xuất" in workbook
        schedule = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert "Lập trình Java" in schedule
        assert "Nguyễn Văn An" in schedule
        assert "1, 2, 4" in schedule
        assert 'autoFilter ref="A4:R5"' in schedule
        ET.fromstring(archive.read("xl/styles.xml"))


def test_empty_filtered_result_creates_header_only_workbook(tmp_path: Path) -> None:
    query = StubTimetableQueryService(())
    output = tmp_path / "empty.xlsx"

    result = TimetableExcelExportService(query).export_run_xlsx(7, output)

    assert result.row_count == 0
    with ZipFile(output) as archive:
        schedule = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert "Không có dòng phù hợp bộ lọc" in schedule
        assert 'autoFilter ref="A4:R4"' in schedule


@pytest.mark.parametrize("name", ["schedule.csv", "schedule", "schedule.xls"])
def test_rejects_non_xlsx_output_path(tmp_path: Path, name: str) -> None:
    query = StubTimetableQueryService((make_row(),))

    with pytest.raises(ValueError, match=r"\.xlsx"):
        TimetableExcelExportService(query).export_run_xlsx(7, tmp_path / name)

    assert query.calls == []


def test_rejects_unknown_query_service() -> None:
    with pytest.raises(TypeError, match="TimetableQueryService"):
        TimetableExcelExportService(object())  # type: ignore[arg-type]
