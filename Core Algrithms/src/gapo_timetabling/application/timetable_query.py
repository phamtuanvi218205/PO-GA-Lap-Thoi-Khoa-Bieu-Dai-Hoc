"""Đọc thời khóa biểu đã lưu từ SQL Server cho tầng ứng dụng.

Module này không chạy optimizer và không ghi dữ liệu. Kết quả chi tiết trong
``TimetableEntry`` được nối với dữ liệu nghiệp vụ rồi gom theo recurring group
để một mẫu thứ–tiết–địa điểm xuất hiện đúng một lần cùng danh sách tuần hoạt
động. CSV, Excel, API và giao diện sẽ sử dụng hợp đồng đọc này ở các bước sau.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from .database import ConnectionProtocol, fetch_all_dicts, fetch_one_dict


WEEKDAY_NAMES = (
    "",
    "Thứ Hai",
    "Thứ Ba",
    "Thứ Tư",
    "Thứ Năm",
    "Thứ Sáu",
    "Thứ Bảy",
    "Chủ nhật",
)


class TimetableQueryError(RuntimeError):
    """Lỗi cơ sở của thao tác đọc thời khóa biểu đã lưu."""


class OptimizationRunNotFoundError(TimetableQueryError):
    """Không tồn tại OptimizationRun có định danh được yêu cầu."""


class OptimizationRunNotCompletedError(TimetableQueryError):
    """OptimizationRun chưa có kết quả hoàn chỉnh để tra cứu."""


class TimetableDataIntegrityError(TimetableQueryError):
    """Dữ liệu lịch đã lưu không nhất quán với hợp đồng recurring schedule."""


@dataclass(frozen=True, slots=True)
class TimetableScheduleRow:
    """Một mẫu lịch lặp cùng các tuần mà mẫu đó được áp dụng.

    Lý thuyết và thực hành là hai dòng riêng vì chúng có ``part_code`` và
    ``part_type`` khác nhau. Khi một plan có hai buổi cố định mỗi tuần,
    ``stability_group_no`` phân biệt hai mẫu lịch đó.
    """

    run_id: int
    term_code: str
    term_name: str
    section_code: str
    section_name: str | None
    course_code: str
    course_name: str
    part_code: str
    part_type: str
    stability_group_no: int
    lecturer_code: str
    lecturer_name: str
    location_id: int
    location_code: str
    location_name: str
    location_type: str
    iso_weekday: int
    start_period: int
    end_period: int
    active_week_numbers: tuple[int, ...]

    @property
    def weekday_name(self) -> str:
        """Tên thứ tiếng Việt tương ứng chuẩn ISO 1=Thứ Hai, 7=Chủ nhật."""

        return WEEKDAY_NAMES[self.iso_weekday]


@dataclass(frozen=True, slots=True)
class TimetableQueryFilters:
    """Các điều kiện tùy chọn khi tra cứu lịch của một run.

    Mọi giá trị chuỗi được loại khoảng trắng hai đầu nhưng không tự đổi hoa,
    thường hoặc suy đoán mã. SQL Server quyết định quy tắc so sánh theo collation
    của database. ``week_number`` lọc occurrence trước khi gom recurring group,
    nên tập tuần trong kết quả chỉ chứa tuần được yêu cầu.
    """

    lecturer_code: str | None = None
    lecturer_query: str | None = None
    section_code: str | None = None
    term_code: str | None = None
    week_number: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "lecturer_code", "lecturer_query", "section_code", "term_code"
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} phải là chuỗi không rỗng hoặc None.")
            object.__setattr__(self, field_name, value.strip())

        if self.week_number is not None:
            if (
                isinstance(self.week_number, bool)
                or not isinstance(self.week_number, int)
                or self.week_number < 1
            ):
                raise ValueError("week_number phải là số nguyên dương hoặc None.")

    @property
    def is_empty(self) -> bool:
        """Cho biết truy vấn có đang yêu cầu toàn bộ lịch của run hay không."""

        return (
            self.lecturer_code is None
            and self.lecturer_query is None
            and self.section_code is None
            and self.term_code is None
            and self.week_number is None
        )


@dataclass(slots=True)
class _RecurringScheduleAccumulator:
    """Trạng thái nội bộ khi gom các occurrence tuần của cùng một pattern."""

    signature: tuple[Any, ...]
    values: Mapping[str, Any]
    week_numbers: set[int]


class TimetableQueryService:
    """Tra cứu lịch đã lưu của một lần tối ưu hoàn thành."""

    def __init__(self, connection: ConnectionProtocol) -> None:
        self._connection = connection

    def get_run_schedule(
        self,
        run_id: int,
        filters: TimetableQueryFilters | None = None,
    ) -> tuple[TimetableScheduleRow, ...]:
        """Trả lịch lặp của ``run_id`` theo thứ, tiết và mã lớp.

        Phương thức cố ý tách truy vấn trạng thái run khỏi truy vấn lịch. Nhờ
        vậy run chưa hoàn thành không thể vô tình lộ một tập ``TimetableEntry``
        đang được ghi dở. Đây là thao tác chỉ đọc nên không commit hoặc rollback
        transaction do caller quản lý.
        """

        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
            raise ValueError("run_id phải là số nguyên dương.")

        actual_filters = filters or TimetableQueryFilters()
        if not isinstance(actual_filters, TimetableQueryFilters):
            raise TypeError("filters phải là TimetableQueryFilters hoặc None.")

        cursor = self._connection.cursor()
        run = fetch_one_dict(cursor.execute(
            """
            SELECT run_id, status
            FROM OptimizationRun
            WHERE run_id = ?
            """,
            run_id,
        ))
        if run is None:
            raise OptimizationRunNotFoundError(
                f"Không tồn tại OptimizationRun run_id={run_id}."
            )

        status = str(run["status"])
        if status != "COMPLETED":
            raise OptimizationRunNotCompletedError(
                f"OptimizationRun run_id={run_id} có trạng thái {status}; "
                "chỉ run COMPLETED mới được tra cứu lịch."
            )

        where_clauses = [
            "entry.run_id = ?",
            "optimization_run.status = 'COMPLETED'",
        ]
        parameters: list[Any] = [run_id]
        if actual_filters.lecturer_code is not None:
            where_clauses.append("entry.lecturer_code = ?")
            parameters.append(actual_filters.lecturer_code)
        if actual_filters.lecturer_query is not None:
            where_clauses.append(
                "(entry.lecturer_code LIKE ? OR lecturer.full_name LIKE ?)"
            )
            search_pattern = f"%{actual_filters.lecturer_query}%"
            parameters.extend((search_pattern, search_pattern))
        if actual_filters.section_code is not None:
            where_clauses.append("course_section.section_code = ?")
            parameters.append(actual_filters.section_code)
        if actual_filters.term_code is not None:
            where_clauses.append("entry.term_code = ?")
            parameters.append(actual_filters.term_code)
        if actual_filters.week_number is not None:
            where_clauses.append("class_session.week_number = ?")
            parameters.append(actual_filters.week_number)

        # Chỉ các tên cột/điều kiện cố định ở trên được ghép vào SQL. Giá trị
        # người dùng luôn đi qua placeholder ``?`` để không tạo SQL injection.
        query = """
            SELECT
                entry.run_id,
                entry.class_session_id,
                entry.term_code,
                academic_term.term_name,
                class_session.week_number,
                class_session.duration_periods,
                class_session.stability_group_no,
                teaching_date.iso_weekday,
                entry.teaching_date,
                entry.start_period,
                entry.end_period,
                course_section.section_code,
                course_section.section_name,
                course.course_code,
                course.course_name,
                teaching_part.teaching_part_id,
                teaching_part.part_code,
                teaching_part.part_type,
                lecturer.lecturer_code,
                lecturer.full_name AS lecturer_name,
                location.location_id,
                location.location_code,
                location.location_name,
                location.location_type
            FROM TimetableEntry AS entry
            INNER JOIN OptimizationRun AS optimization_run
                ON optimization_run.run_id = entry.run_id
            INNER JOIN ClassSession AS class_session
                ON class_session.class_session_id = entry.class_session_id
               AND class_session.term_code = entry.term_code
            INNER JOIN TeachingPlan AS teaching_plan
                ON teaching_plan.teaching_plan_id = class_session.teaching_plan_id
            INNER JOIN TeachingPart AS teaching_part
                ON teaching_part.teaching_part_id = teaching_plan.teaching_part_id
            INNER JOIN CourseSection AS course_section
                ON course_section.section_code = teaching_part.section_code
            INNER JOIN Course AS course
                ON course.course_code = course_section.course_code
            INNER JOIN Lecturer AS lecturer
                ON lecturer.lecturer_code = entry.lecturer_code
            INNER JOIN TeachingLocation AS location
                ON location.location_id = entry.location_id
               AND location.location_type = entry.location_type
            INNER JOIN AcademicTerm AS academic_term
                ON academic_term.term_code = entry.term_code
            INNER JOIN TeachingDate AS teaching_date
                ON teaching_date.term_code = entry.term_code
               AND teaching_date.calendar_date = entry.teaching_date
            WHERE {where_clause}
            ORDER BY
                teaching_date.iso_weekday,
                entry.start_period,
                course_section.section_code,
                teaching_part.part_type,
                class_session.stability_group_no,
                class_session.week_number
            """.format(where_clause="\n              AND ".join(where_clauses))
        records = fetch_all_dicts(cursor.execute(query, *parameters))
        if not records:
            if not actual_filters.is_empty:
                return ()
            raise TimetableDataIntegrityError(
                f"OptimizationRun run_id={run_id} đã COMPLETED nhưng không có "
                "TimetableEntry."
            )

        return self._group_recurring_records(run_id, records)

    @staticmethod
    def _group_recurring_records(
        run_id: int,
        records: list[dict[str, Any]],
    ) -> tuple[TimetableScheduleRow, ...]:
        """Gom occurrence tuần và kiểm tra pattern không thay đổi giữa kỳ."""

        grouped: dict[tuple[int, int], _RecurringScheduleAccumulator] = {}
        for record in records:
            teaching_part_id = _required_int(record, "teaching_part_id")
            stability_group_no = _required_int(record, "stability_group_no")
            week_number = _required_int(record, "week_number")
            iso_weekday = _required_int(record, "iso_weekday")
            start_period = _required_int(record, "start_period")
            end_period = _required_int(record, "end_period")
            duration_periods = _required_int(record, "duration_periods")

            if not 1 <= iso_weekday <= 7:
                raise TimetableDataIntegrityError(
                    f"iso_weekday={iso_weekday} nằm ngoài khoảng 1..7."
                )
            if end_period - start_period + 1 != duration_periods:
                raise TimetableDataIntegrityError(
                    "Khoảng tiết đã lưu không khớp duration của ClassSession "
                    f"{record.get('class_session_id')}."
                )

            teaching_date = record.get("teaching_date")
            if isinstance(teaching_date, date) and teaching_date.isoweekday() != iso_weekday:
                raise TimetableDataIntegrityError(
                    "Ngày dạy và iso_weekday không nhất quán tại ClassSession "
                    f"{record.get('class_session_id')}."
                )

            # Mọi trường trong signature phải bất biến giữa các occurrence của
            # cùng part/group. Nếu khác, dữ liệu đã lưu không còn biểu diễn một
            # recurring pattern cố định và không được âm thầm tách thành hai dòng.
            signature = (
                _required_str(record, "term_code"),
                _required_str(record, "term_name"),
                _required_str(record, "section_code"),
                _optional_str(record, "section_name"),
                _required_str(record, "course_code"),
                _required_str(record, "course_name"),
                _required_str(record, "part_code"),
                _required_str(record, "part_type"),
                _required_str(record, "lecturer_code"),
                _required_str(record, "lecturer_name"),
                _required_int(record, "location_id"),
                _required_str(record, "location_code"),
                _required_str(record, "location_name"),
                _required_str(record, "location_type"),
                iso_weekday,
                start_period,
                end_period,
            )
            key = (teaching_part_id, stability_group_no)
            accumulator = grouped.get(key)
            if accumulator is None:
                grouped[key] = _RecurringScheduleAccumulator(
                    signature=signature,
                    values=record,
                    week_numbers={week_number},
                )
                continue
            if accumulator.signature != signature:
                raise TimetableDataIntegrityError(
                    "Recurring group thay đổi giảng viên, thứ, tiết hoặc địa điểm: "
                    f"teaching_part_id={teaching_part_id}, "
                    f"stability_group_no={stability_group_no}."
                )
            if week_number in accumulator.week_numbers:
                raise TimetableDataIntegrityError(
                    "Recurring group có nhiều TimetableEntry trong cùng tuần: "
                    f"teaching_part_id={teaching_part_id}, "
                    f"stability_group_no={stability_group_no}, week={week_number}."
                )
            accumulator.week_numbers.add(week_number)

        result = [
            _build_schedule_row(run_id, accumulator)
            for accumulator in grouped.values()
        ]
        result.sort(key=lambda item: (
            item.iso_weekday,
            item.start_period,
            item.section_code,
            item.part_type,
            item.stability_group_no,
        ))
        return tuple(result)


def _required_int(record: Mapping[str, Any], field: str) -> int:
    """Đọc số nguyên bắt buộc và báo lỗi dữ liệu thay vì ép kiểu mơ hồ."""

    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TimetableDataIntegrityError(f"{field} phải là số nguyên.")
    return value


def _required_str(record: Mapping[str, Any], field: str) -> str:
    """Đọc chuỗi bắt buộc đã loại khoảng trắng ở hai đầu."""

    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise TimetableDataIntegrityError(f"{field} phải là chuỗi không rỗng.")
    return value.strip()


def _optional_str(record: Mapping[str, Any], field: str) -> str | None:
    """Đọc chuỗi tùy chọn nhưng từ chối kiểu dữ liệu không xác định."""

    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TimetableDataIntegrityError(f"{field} phải là chuỗi hoặc NULL.")
    stripped = value.strip()
    return stripped or None


def _build_schedule_row(
    run_id: int,
    accumulator: _RecurringScheduleAccumulator,
) -> TimetableScheduleRow:
    """Chuyển accumulator đã kiểm tra thành hợp đồng bất biến công khai."""

    record = accumulator.values
    return TimetableScheduleRow(
        run_id=run_id,
        term_code=_required_str(record, "term_code"),
        term_name=_required_str(record, "term_name"),
        section_code=_required_str(record, "section_code"),
        section_name=_optional_str(record, "section_name"),
        course_code=_required_str(record, "course_code"),
        course_name=_required_str(record, "course_name"),
        part_code=_required_str(record, "part_code"),
        part_type=_required_str(record, "part_type"),
        stability_group_no=_required_int(record, "stability_group_no"),
        lecturer_code=_required_str(record, "lecturer_code"),
        lecturer_name=_required_str(record, "lecturer_name"),
        location_id=_required_int(record, "location_id"),
        location_code=_required_str(record, "location_code"),
        location_name=_required_str(record, "location_name"),
        location_type=_required_str(record, "location_type"),
        iso_weekday=_required_int(record, "iso_weekday"),
        start_period=_required_int(record, "start_period"),
        end_period=_required_int(record, "end_period"),
        active_week_numbers=tuple(sorted(accumulator.week_numbers)),
    )
