"""Kiểm thử xuất thời khóa biểu đã lưu thành CSV."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from gapo_timetabling.application.timetable_export import TimetableExportService
from gapo_timetabling.application.timetable_query import (
    TimetableQueryFilters,
    TimetableQueryService,
    TimetableScheduleRow,
)


class StubTimetableQueryService(TimetableQueryService):
    """Stub giữ hợp đồng public nhưng không cần kết nối database."""

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


def make_row(
    *,
    part_type: str = "LECTURE",
    lecturer_name: str = "Nguyễn Văn An",
) -> TimetableScheduleRow:
    """Tạo một recurring row đại diện cho ba tuần hoạt động."""

    return TimetableScheduleRow(
        run_id=7,
        term_code="2026_HK1",
        term_name="Học kỳ 1 năm học 2026-2027",
        section_code="JAVA01",
        section_name="Lớp Java 01",
        course_code="JAVA",
        course_name="Lập trình Java",
        part_code="JAVA01_LT",
        part_type=part_type,
        stability_group_no=1,
        lecturer_code="GV001",
        lecturer_name=lecturer_name,
        location_id=11,
        location_code="A201",
        location_name="Phòng A201",
        location_type="PHYSICAL_ROOM",
        iso_weekday=1,
        start_period=1,
        end_period=3,
        active_week_numbers=(1, 2, 4),
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def test_exports_utf8_bom_csv_with_vietnamese_labels(tmp_path: Path) -> None:
    query = StubTimetableQueryService((make_row(),))
    output = tmp_path / "nested" / "thoi-khoa-bieu.csv"

    result = TimetableExportService(query).export_run_csv(7, output)

    assert result.output_path == output.resolve()
    assert result.row_count == 1
    assert output.read_bytes().startswith(b"\xef\xbb\xbf")
    rows = read_csv(output)
    assert rows[0]["Mã lớp học phần"] == "JAVA01"
    assert rows[0]["Hình thức"] == "Lý thuyết"
    assert rows[0]["Thứ"] == "Thứ Hai"
    assert rows[0]["Tiết bắt đầu"] == "1"
    assert rows[0]["Tiết kết thúc"] == "3"
    assert rows[0]["Loại địa điểm"] == "Phòng học"
    assert rows[0]["Tuần hoạt động"] == "1, 2, 4"


def test_forwards_filters_to_query_service(tmp_path: Path) -> None:
    query = StubTimetableQueryService((make_row(part_type="PRACTICE"),))
    filters = TimetableQueryFilters(lecturer_code="GV001", week_number=2)

    TimetableExportService(query).export_run_csv(
        7,
        tmp_path / "filtered.csv",
        filters,
    )

    assert query.calls == [(7, filters)]
    assert read_csv(tmp_path / "filtered.csv")[0]["Hình thức"] == "Thực hành"


def test_empty_filtered_result_still_writes_header(tmp_path: Path) -> None:
    query = StubTimetableQueryService(())
    output = tmp_path / "empty.csv"

    result = TimetableExportService(query).export_run_csv(7, output)

    assert result.row_count == 0
    with output.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        header = next(reader)
        assert "Mã học kỳ" in header
        assert list(reader) == []


def test_prefixes_formula_like_text_for_spreadsheet_safety(tmp_path: Path) -> None:
    query = StubTimetableQueryService((make_row(lecturer_name="=1+1"),))
    output = tmp_path / "safe.csv"

    TimetableExportService(query).export_run_csv(7, output)

    assert read_csv(output)[0]["Tên giảng viên"] == "'=1+1"


@pytest.mark.parametrize("path", ["schedule.txt", "schedule", "schedule.xlsx"])
def test_rejects_non_csv_output_path(tmp_path: Path, path: str) -> None:
    query = StubTimetableQueryService((make_row(),))

    with pytest.raises(ValueError, match=r"\.csv"):
        TimetableExportService(query).export_run_csv(7, tmp_path / path)

    assert query.calls == []


def test_rejects_unknown_query_service() -> None:
    with pytest.raises(TypeError, match="TimetableQueryService"):
        TimetableExportService(object())  # type: ignore[arg-type]
