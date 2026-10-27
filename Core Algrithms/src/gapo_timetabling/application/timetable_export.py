"""Xuất thời khóa biểu đã lưu thành tệp CSV dùng cho trao đổi dữ liệu.

Module chỉ chuyển hợp đồng đọc :class:`TimetableScheduleRow` thành dữ liệu
bảng. Nó không chạy optimizer, không sửa ``OptimizationRun`` và không tự truy
vấn các bảng nghiệp vụ ngoài :class:`TimetableQueryService`.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Final

from .timetable_query import (
    TimetableQueryFilters,
    TimetableQueryService,
    TimetableScheduleRow,
)


CSV_COLUMNS: Final[tuple[tuple[str, str], ...]] = (
    ("term_code", "Mã học kỳ"),
    ("term_name", "Tên học kỳ"),
    ("section_code", "Mã lớp học phần"),
    ("section_name", "Tên lớp học phần"),
    ("course_code", "Mã môn học"),
    ("course_name", "Tên môn học"),
    ("part_code", "Mã phần giảng dạy"),
    ("part_type", "Hình thức"),
    ("stability_group_no", "Nhóm buổi cố định"),
    ("weekday_name", "Thứ"),
    ("start_period", "Tiết bắt đầu"),
    ("end_period", "Tiết kết thúc"),
    ("location_code", "Mã địa điểm"),
    ("location_name", "Tên địa điểm"),
    ("location_type", "Loại địa điểm"),
    ("lecturer_code", "Mã giảng viên"),
    ("lecturer_name", "Tên giảng viên"),
    ("active_week_numbers", "Tuần hoạt động"),
)

PART_TYPE_LABELS: Final[dict[str, str]] = {
    "LECTURE": "Lý thuyết",
    "PRACTICE": "Thực hành",
}

LOCATION_TYPE_LABELS: Final[dict[str, str]] = {
    "PHYSICAL_ROOM": "Phòng học",
    "ONLINE": "Trực tuyến",
}


@dataclass(frozen=True, slots=True)
class TimetableCsvExportResult:
    """Thông tin tệp CSV đã tạo thành công."""

    output_path: Path
    row_count: int


class TimetableExportService:
    """Xuất kết quả của một run hoàn thành mà không chạy lại thuật toán."""

    def __init__(self, query_service: TimetableQueryService) -> None:
        if not isinstance(query_service, TimetableQueryService):
            raise TypeError("query_service phải là TimetableQueryService.")
        self._query_service = query_service

    def export_run_csv(
        self,
        run_id: int,
        output_path: str | os.PathLike[str],
        filters: TimetableQueryFilters | None = None,
    ) -> TimetableCsvExportResult:
        """Đọc lịch của ``run_id`` và ghi một dòng cho mỗi mẫu lịch lặp.

        Tệp dùng UTF-8 BOM để Microsoft Excel nhận đúng tiếng Việt. Việc ghi
        được thực hiện vào tệp tạm trong cùng thư mục rồi thay thế nguyên tử,
        nhờ đó lỗi giữa chừng không để lại một báo cáo CSV chỉ có một phần.
        """

        destination = _validate_csv_path(output_path)
        rows = self._query_service.get_run_schedule(run_id, filters)
        destination.parent.mkdir(parents=True, exist_ok=True)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            with temporary_path.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[label for _, label in CSV_COLUMNS],
                    extrasaction="raise",
                )
                writer.writeheader()
                writer.writerows(_to_csv_record(row) for row in rows)
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)

        return TimetableCsvExportResult(
            output_path=destination.resolve(),
            row_count=len(rows),
        )


def _validate_csv_path(output_path: str | os.PathLike[str]) -> Path:
    """Chuẩn hóa đường dẫn và từ chối đích không phải tệp CSV."""

    if not isinstance(output_path, (str, os.PathLike)):
        raise TypeError("output_path phải là chuỗi hoặc đối tượng đường dẫn.")
    path = Path(output_path)
    if path.suffix.lower() != ".csv":
        raise ValueError("output_path phải có phần mở rộng .csv.")
    if not path.name or path.name in {".", ".."}:
        raise ValueError("output_path không xác định một tệp hợp lệ.")
    return path


def _to_csv_record(row: TimetableScheduleRow) -> dict[str, object]:
    """Chuyển một dòng miền thành nhãn tiếng Việt ổn định cho báo cáo."""

    raw_values: dict[str, object] = {
        "term_code": row.term_code,
        "term_name": row.term_name,
        "section_code": row.section_code,
        "section_name": row.section_name or "",
        "course_code": row.course_code,
        "course_name": row.course_name,
        "part_code": row.part_code,
        "part_type": PART_TYPE_LABELS.get(row.part_type, row.part_type),
        "stability_group_no": row.stability_group_no,
        "weekday_name": row.weekday_name,
        "start_period": row.start_period,
        "end_period": row.end_period,
        "location_code": row.location_code,
        "location_name": row.location_name,
        "location_type": LOCATION_TYPE_LABELS.get(
            row.location_type,
            row.location_type,
        ),
        "lecturer_code": row.lecturer_code,
        "lecturer_name": row.lecturer_name,
        "active_week_numbers": ", ".join(map(str, row.active_week_numbers)),
    }
    return {
        label: _safe_spreadsheet_value(raw_values[field_name])
        for field_name, label in CSV_COLUMNS
    }


def _safe_spreadsheet_value(value: object) -> object:
    """Ngăn chuỗi dữ liệu bị Excel diễn giải thành công thức khi mở CSV."""

    if not isinstance(value, str):
        return value
    first_character = value.lstrip()[:1]
    if first_character in {"=", "+", "-", "@"}:
        return "'" + value
    return value
