"""Kiểm tra độc lập các ràng buộc cứng của một thời khóa biểu.

Validator không sửa lịch và không tính fitness. Nó nhận một ``ProblemInstance``
cùng các ``SessionOption`` đã được decoder chọn, sau đó trả về toàn bộ vi phạm
cứng tìm thấy. Nhờ vậy một lỗi trong decoder không thể âm thầm đi qua bước
fitness hoặc được lưu thành lịch chính thức.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .models import (
    AvailabilityScopeType,
    AvailabilityType,
    AvailabilityWindow,
    ClassSession,
    DateStatus,
    LocationType,
    OnlineLocation,
    ProblemInstance,
    Room,
    SessionOption,
    TeachingPart,
)


class HardViolationCode(str, Enum):
    """Mã lỗi ổn định để decoder, test và API không phải đọc chuỗi message."""

    UNKNOWN_SESSION = "UNKNOWN_SESSION"
    MISSING_ASSIGNMENT = "MISSING_ASSIGNMENT"
    DUPLICATE_ASSIGNMENT = "DUPLICATE_ASSIGNMENT"
    DATE_NOT_ALLOWED = "DATE_NOT_ALLOWED"
    PERIOD_NOT_ALLOWED = "PERIOD_NOT_ALLOWED"
    LOCATION_NOT_ALLOWED = "LOCATION_NOT_ALLOWED"
    LECTURER_UNAVAILABLE = "LECTURER_UNAVAILABLE"
    ROOM_UNAVAILABLE = "ROOM_UNAVAILABLE"
    LECTURER_CONFLICT = "LECTURER_CONFLICT"
    ROOM_CONFLICT = "ROOM_CONFLICT"
    MISSING_TRAVEL_TIME = "MISSING_TRAVEL_TIME"
    INSUFFICIENT_TRAVEL_TIME = "INSUFFICIENT_TRAVEL_TIME"


@dataclass(frozen=True, slots=True)
class HardConstraintViolation:
    """Một lỗi cứng cùng các session liên quan đến lỗi đó."""

    code: HardViolationCode
    session_indices: tuple[int, ...]
    message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Kết quả validator; lịch hợp lệ khi không có bất kỳ vi phạm nào."""

    violations: tuple[HardConstraintViolation, ...]

    @property
    def is_valid(self) -> bool:
        """Lịch hợp lệ khi danh sách vi phạm cứng rỗng."""

        return not self.violations


def _period_ranges_overlap(
    first_start: int,
    first_end: int,
    second_start: int,
    second_end: int,
) -> bool:
    """Hai khoảng tiết đóng giao nhau khi chúng có ít nhất một tiết chung."""

    return first_start <= second_end and second_start <= first_end


def _window_blocks_option(
    window: AvailabilityWindow,
    option: SessionOption,
) -> bool:
    """Kiểm tra một cửa sổ ``UNAVAILABLE`` có chặn option hay không."""

    if window.availability_type != AvailabilityType.UNAVAILABLE:
        return False

    if window.scope_type == AvailabilityScopeType.DATE:
        applies_to_date = window.calendar_date == option.teaching_date
    else:
        applies_to_date = window.iso_weekday == option.teaching_date.isoweekday()

    return applies_to_date and _period_ranges_overlap(
        window.start_period,
        window.end_period,
        option.start_period,
        option.end_period,
    )


def _resource_is_unavailable(
    windows: tuple[AvailabilityWindow, ...],
    resource_index: int,
    option: SessionOption,
) -> bool:
    """Trả về True nếu resource bị cấm tại ngày và khoảng tiết của option."""

    return any(
        window.resource_index == resource_index
        and _window_blocks_option(window, option)
        for window in windows
    )


def _room_has_required_equipment(room: Room, part: TeachingPart) -> bool:
    """Kiểm tra loại phòng và số lượng thiết bị bắt buộc, không xét capacity."""

    if room.room_type != part.required_room_type:
        return False

    available_equipment = dict(room.equipment_quantities)
    return all(
        available_equipment.get(equipment_code, 0) >= required_quantity
        for equipment_code, required_quantity in part.required_equipment
    )


def _option_uses_allowed_periods(
    problem: ProblemInstance,
    session: ClassSession,
    option: SessionOption,
) -> bool:
    """Kiểm tra duration, block cho phép, các tiết tồn tại và cùng một ca."""

    if not 1 <= option.start_period <= option.end_period <= 16:
        return False

    actual_duration = option.end_period - option.start_period + 1
    if actual_duration != session.duration_periods:
        return False

    block_is_allowed = any(
        block.start_period == option.start_period
        and block.duration_periods == session.duration_periods
        for block in problem.allowed_period_blocks
    )
    if not block_is_allowed:
        return False

    periods_by_number = {
        period.period_number: period
        for period in problem.time_periods
    }
    selected_periods = []
    for period_number in range(option.start_period, option.end_period + 1):
        period = periods_by_number.get(period_number)
        if period is None:
            return False
        selected_periods.append(period)

    session_type = selected_periods[0].session_type
    return all(period.session_type == session_type for period in selected_periods)


def _build_session_context(
    problem: ProblemInstance,
) -> dict[int, tuple[ClassSession, TeachingPart]]:
    """Ánh xạ session_index sang session và TeachingPart tương ứng."""

    plans_by_id = {
        plan.teaching_plan_id: plan
        for plan in problem.teaching_plans
    }
    parts_by_index = {
        part.teaching_part_index: part
        for part in problem.teaching_parts
    }

    context: dict[int, tuple[ClassSession, TeachingPart]] = {}
    for session in problem.class_sessions:
        plan = plans_by_id[session.teaching_plan_id]
        part = parts_by_index[plan.teaching_part_index]
        context[session.session_index] = (session, part)

    return context


def _validate_one_option(
    problem: ProblemInstance,
    session: ClassSession,
    part: TeachingPart,
    option: SessionOption,
) -> list[HardConstraintViolation]:
    """Kiểm tra các điều kiện cứng chỉ liên quan đến một session riêng lẻ."""

    violations: list[HardConstraintViolation] = []
    teaching_dates_by_date = {
        item.calendar_date: item
        for item in problem.teaching_dates
    }
    teaching_date = teaching_dates_by_date.get(option.teaching_date)

    if (
        teaching_date is None
        or teaching_date.week_number != session.week_number
        or teaching_date.status == DateStatus.HOLIDAY
    ):
        violations.append(
            HardConstraintViolation(
                code=HardViolationCode.DATE_NOT_ALLOWED,
                session_indices=(session.session_index,),
                message="Ngày được chọn không được phép cho tuần của ClassSession.",
            )
        )

    if not _option_uses_allowed_periods(problem, session, option):
        violations.append(
            HardConstraintViolation(
                code=HardViolationCode.PERIOD_NOT_ALLOWED,
                session_indices=(session.session_index,),
                message="Khoảng tiết không khớp duration hoặc khung tiết được phép.",
            )
        )

    locations_by_index = {
        location.location_index: location
        for location in problem.locations
    }
    location = locations_by_index.get(option.location_index)

    location_is_allowed = location is not None and location.active
    if location_is_allowed and part.required_location_type == LocationType.PHYSICAL_ROOM:
        location_is_allowed = (
            isinstance(location, Room)
            and _room_has_required_equipment(location, part)
        )
    elif location_is_allowed and part.required_location_type == LocationType.ONLINE:
        location_is_allowed = isinstance(location, OnlineLocation)

    if not location_is_allowed:
        violations.append(
            HardConstraintViolation(
                code=HardViolationCode.LOCATION_NOT_ALLOWED,
                session_indices=(session.session_index,),
                message="Địa điểm không đúng loại, không hoạt động hoặc thiếu thiết bị.",
            )
        )

    if _resource_is_unavailable(
        problem.lecturer_availabilities,
        part.lecturer_index,
        option,
    ):
        violations.append(
            HardConstraintViolation(
                code=HardViolationCode.LECTURER_UNAVAILABLE,
                session_indices=(session.session_index,),
                message="Giảng viên bị đánh dấu UNAVAILABLE tại thời gian được chọn.",
            )
        )

    if isinstance(location, Room) and _resource_is_unavailable(
        problem.room_availabilities,
        location.location_index,
        option,
    ):
        violations.append(
            HardConstraintViolation(
                code=HardViolationCode.ROOM_UNAVAILABLE,
                session_indices=(session.session_index,),
                message="Phòng bị đánh dấu UNAVAILABLE tại thời gian được chọn.",
            )
        )

    return violations


def _travel_violation_for_pair(
    problem: ProblemInstance,
    first_option: SessionOption,
    second_option: SessionOption,
    first_room: Room,
    second_room: Room,
) -> HardConstraintViolation | None:
    """Kiểm tra thời gian di chuyển cho hai buổi cùng giảng viên trong một ngày."""

    if first_room.campus_code == second_room.campus_code:
        return None

    if first_option.start_period < second_option.start_period:
        earlier_option = first_option
        later_option = second_option
        from_campus = first_room.campus_code
        to_campus = second_room.campus_code
    else:
        earlier_option = second_option
        later_option = first_option
        from_campus = second_room.campus_code
        to_campus = first_room.campus_code

    travel_times = {
        (item.from_campus_code, item.to_campus_code): item.travel_minutes
        for item in problem.campus_travel_times
    }
    required_minutes = travel_times.get((from_campus, to_campus))
    session_indices = tuple(sorted((first_option.session_index, second_option.session_index)))

    if required_minutes is None:
        return HardConstraintViolation(
            code=HardViolationCode.MISSING_TRAVEL_TIME,
            session_indices=session_indices,
            message=f"Thiếu cấu hình thời gian di chuyển {from_campus} → {to_campus}.",
        )

    periods_by_number = {
        period.period_number: period
        for period in problem.time_periods
    }
    earlier_end_time = periods_by_number[earlier_option.end_period].end_time
    later_start_time = periods_by_number[later_option.start_period].start_time
    earlier_end = datetime.combine(earlier_option.teaching_date, earlier_end_time)
    later_start = datetime.combine(later_option.teaching_date, later_start_time)
    available_minutes = int((later_start - earlier_end).total_seconds() // 60)

    if available_minutes < required_minutes:
        return HardConstraintViolation(
            code=HardViolationCode.INSUFFICIENT_TRAVEL_TIME,
            session_indices=session_indices,
            message=(
                f"Chỉ có {available_minutes} phút để đi {from_campus} → "
                f"{to_campus}, cần ít nhất {required_minutes} phút."
            ),
        )

    return None


def _validate_pairs(
    problem: ProblemInstance,
    valid_options: tuple[SessionOption, ...],
    session_context: dict[int, tuple[ClassSession, TeachingPart]],
) -> list[HardConstraintViolation]:
    """Kiểm tra xung đột giữa từng cặp option đã hợp lệ riêng lẻ."""

    violations: list[HardConstraintViolation] = []
    locations_by_index = {
        location.location_index: location
        for location in problem.locations
    }

    for first_position in range(len(valid_options)):
        first_option = valid_options[first_position]
        _, first_part = session_context[first_option.session_index]
        first_location = locations_by_index[first_option.location_index]

        for second_position in range(first_position + 1, len(valid_options)):
            second_option = valid_options[second_position]
            _, second_part = session_context[second_option.session_index]
            second_location = locations_by_index[second_option.location_index]

            if first_option.teaching_date != second_option.teaching_date:
                continue

            periods_overlap = _period_ranges_overlap(
                first_option.start_period,
                first_option.end_period,
                second_option.start_period,
                second_option.end_period,
            )
            session_indices = tuple(sorted((
                first_option.session_index,
                second_option.session_index,
            )))

            same_lecturer = first_part.lecturer_index == second_part.lecturer_index
            if same_lecturer and periods_overlap:
                violations.append(
                    HardConstraintViolation(
                        code=HardViolationCode.LECTURER_CONFLICT,
                        session_indices=session_indices,
                        message="Hai buổi của cùng giảng viên bị trùng thời gian.",
                    )
                )

            same_physical_room = (
                isinstance(first_location, Room)
                and isinstance(second_location, Room)
                and first_location.location_index == second_location.location_index
            )
            if same_physical_room and periods_overlap:
                violations.append(
                    HardConstraintViolation(
                        code=HardViolationCode.ROOM_CONFLICT,
                        session_indices=session_indices,
                        message="Hai buổi dùng cùng phòng vật lý bị trùng thời gian.",
                    )
                )

            if (
                same_lecturer
                and not periods_overlap
                and isinstance(first_location, Room)
                and isinstance(second_location, Room)
            ):
                travel_violation = _travel_violation_for_pair(
                    problem,
                    first_option,
                    second_option,
                    first_location,
                    second_location,
                )
                if travel_violation is not None:
                    violations.append(travel_violation)

    return violations


def validate_timetable(
    problem: ProblemInstance,
    selected_options: tuple[SessionOption, ...],
) -> ValidationResult:
    """Kiểm tra một lịch hoàn chỉnh và trả về tất cả vi phạm cứng.

    Hàm không ném exception chỉ vì lịch ứng viên sai. Lỗi được trả về dưới dạng
    ``HardConstraintViolation`` để decoder biết cá thể nào cần loại hoặc repair.
    ``ProblemInstance`` bản thân nó đã được kiểm tra khi khởi tạo.
    """

    violations: list[HardConstraintViolation] = []
    session_context = _build_session_context(problem)
    options_by_session: dict[int, list[SessionOption]] = {}

    for option in selected_options:
        if option.session_index not in session_context:
            violations.append(
                HardConstraintViolation(
                    code=HardViolationCode.UNKNOWN_SESSION,
                    session_indices=(option.session_index,),
                    message="Option tham chiếu session_index không tồn tại.",
                )
            )
            continue
        options_by_session.setdefault(option.session_index, []).append(option)

    structurally_valid_options: list[SessionOption] = []
    for session in problem.class_sessions:
        options = options_by_session.get(session.session_index, [])
        if not options:
            violations.append(
                HardConstraintViolation(
                    code=HardViolationCode.MISSING_ASSIGNMENT,
                    session_indices=(session.session_index,),
                    message="ClassSession chưa được chọn SessionOption.",
                )
            )
            continue
        if len(options) > 1:
            violations.append(
                HardConstraintViolation(
                    code=HardViolationCode.DUPLICATE_ASSIGNMENT,
                    session_indices=(session.session_index,),
                    message="ClassSession được gán nhiều hơn một SessionOption.",
                )
            )
            continue

        option = options[0]
        _, part = session_context[session.session_index]
        option_violations = _validate_one_option(problem, session, part, option)
        violations.extend(option_violations)

        if not option_violations:
            structurally_valid_options.append(option)

    violations.extend(
        _validate_pairs(
            problem,
            tuple(structurally_valid_options),
            session_context,
        )
    )

    return ValidationResult(tuple(violations))
