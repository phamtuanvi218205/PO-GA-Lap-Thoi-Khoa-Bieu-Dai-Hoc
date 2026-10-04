"""Sinh miền ``SessionOption`` cho từng ``ClassSession``.

Encoder chỉ kiểm tra những điều kiện bắt buộc có thể xác định cho *một* buổi
độc lập: tuần/ngày, khung tiết, loại địa điểm, thiết bị và trạng thái
``UNAVAILABLE``. Xung đột giữa nhiều buổi sẽ do decoder/validator xử lý; các
tiêu chí mềm như sức chứa và mong muốn giảng viên sẽ do fitness đánh giá.
"""

from datetime import date

from .models import (
    AllowedPeriodBlock,
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
    TimePeriod,
)


def period_ranges_overlap(
    first_start_period: int,
    first_end_period: int,
    second_start_period: int,
    second_end_period: int,
) -> bool:
    """Trả về ``True`` khi hai khoảng tiết đóng có ít nhất một tiết chung."""

    if first_start_period > first_end_period:
        raise ValueError("Khoảng tiết thứ nhất không hợp lệ.")
    if second_start_period > second_end_period:
        raise ValueError("Khoảng tiết thứ hai không hợp lệ.")

    return (
        first_start_period <= second_end_period
        and second_start_period <= first_end_period
    )


def is_resource_unavailable(
    availability_windows: tuple[AvailabilityWindow, ...],
    resource_index: int,
    teaching_date: date,
    start_period: int,
    end_period: int,
) -> bool:
    """Kiểm tra resource có bị cấm tại ngày và khoảng tiết đang xét không.

    ``DATE`` chỉ áp dụng cho đúng ngày cụ thể. ``WEEKDAY`` áp dụng lặp lại theo
    thứ ISO của ngày (thứ Hai = 1, Chủ nhật = 7). Chỉ ``UNAVAILABLE`` là điều
    kiện cứng; ``PREFERRED`` và ``DISCOURAGED`` không bị encoder loại.
    """

    if start_period > end_period:
        raise ValueError("Khoảng tiết cần kiểm tra không hợp lệ.")

    iso_weekday = teaching_date.isoweekday()

    for window in availability_windows:
        if window.resource_index != resource_index:
            continue
        if window.availability_type != AvailabilityType.UNAVAILABLE:
            continue

        if window.scope_type == AvailabilityScopeType.DATE:
            window_applies_to_date = window.calendar_date == teaching_date
        else:
            window_applies_to_date = window.iso_weekday == iso_weekday

        if not window_applies_to_date:
            continue

        if period_ranges_overlap(
            first_start_period=start_period,
            first_end_period=end_period,
            second_start_period=window.start_period,
            second_end_period=window.end_period,
        ):
            return True

    return False


def get_periods_for_block(
    time_periods: tuple[TimePeriod, ...],
    block: AllowedPeriodBlock,
) -> tuple[TimePeriod, ...] | None:
    """Lấy đủ các tiết liên tục của một khung đã được nhà trường cho phép.

    Hàm còn kiểm tra các tiết thuộc cùng một ca. Nhờ vậy một cấu hình sai như
    khung bắt đầu ở cuối ca sáng rồi kéo sang ca chiều sẽ không sinh option.
    """

    periods_by_number = {
        period.period_number: period
        for period in time_periods
    }
    selected_periods: list[TimePeriod] = []

    for period_number in range(block.start_period, block.end_period + 1):
        period = periods_by_number.get(period_number)
        if period is None:
            return None
        selected_periods.append(period)

    first_session_type = selected_periods[0].session_type
    if any(
        period.session_type != first_session_type
        for period in selected_periods
    ):
        return None

    return tuple(selected_periods)


def room_can_host_part(room: Room, teaching_part: TeachingPart) -> bool:
    """Kiểm tra phòng có đúng loại và đủ thiết bị cho ``TeachingPart``.

    Sức chứa không xuất hiện trong hàm này vì được mô hình hóa là tiêu chí
    mềm. Phòng nhỏ hơn chỉ tiêu dự kiến vẫn là một option hợp lệ và chỉ nhận
    điểm phạt ở bước đánh giá fitness.
    """

    if not room.active:
        return False
    if teaching_part.required_location_type != LocationType.PHYSICAL_ROOM:
        return False
    if room.room_type != teaching_part.required_room_type:
        return False

    room_equipment = dict(room.equipment_quantities)
    for equipment_code, minimum_quantity in teaching_part.required_equipment:
        if room_equipment.get(equipment_code, 0) < minimum_quantity:
            return False

    return True


def _find_teaching_part(
    problem: ProblemInstance,
    class_session: ClassSession,
) -> TeachingPart:
    """Tìm ``TeachingPart`` của session thông qua ``TeachingPlan``."""

    plan = next(
        (
            candidate
            for candidate in problem.teaching_plans
            if candidate.teaching_plan_id == class_session.teaching_plan_id
        ),
        None,
    )
    if plan is None:
        raise ValueError("ClassSession tham chiếu TeachingPlan không tồn tại.")

    part = next(
        (
            candidate
            for candidate in problem.teaching_parts
            if candidate.teaching_part_index == plan.teaching_part_index
        ),
        None,
    )
    if part is None:
        raise ValueError("TeachingPlan tham chiếu TeachingPart không tồn tại.")

    return part


def _get_valid_blocks(
    problem: ProblemInstance,
    class_session: ClassSession,
) -> tuple[AllowedPeriodBlock, ...]:
    """Lấy các khung đúng duration và có đủ tiết trong cùng một ca."""

    valid_blocks: list[AllowedPeriodBlock] = []

    for block in sorted(
        problem.allowed_period_blocks,
        key=lambda item: item.start_period,
    ):
        if block.duration_periods != class_session.duration_periods:
            continue
        if get_periods_for_block(problem.time_periods, block) is None:
            continue
        valid_blocks.append(block)

    return tuple(valid_blocks)


def build_options_for_session(
    problem: ProblemInstance,
    class_session: ClassSession,
) -> tuple[SessionOption, ...]:
    """Sinh toàn bộ option hợp lệ riêng cho một ``ClassSession``.

    Hàm chưa kiểm tra trùng giảng viên, trùng phòng, khoảng di chuyển giữa cơ
    sở hoặc quan hệ với các session khác. Các điều kiện đó chỉ có nghĩa sau
    khi nhiều gene đã được ghép thành một lịch hoàn chỉnh.
    """

    teaching_part = _find_teaching_part(problem, class_session)

    teaching_dates = sorted(
        (
            item
            for item in problem.teaching_dates
            if item.week_number == class_session.week_number
            and item.status != DateStatus.HOLIDAY
        ),
        key=lambda item: item.calendar_date,
    )
    valid_blocks = _get_valid_blocks(problem, class_session)

    if class_session.required_location_type == LocationType.PHYSICAL_ROOM:
        locations = tuple(
            room
            for room in problem.rooms
            if room_can_host_part(room, teaching_part)
        )
    else:
        locations = tuple(
            location
            for location in problem.online_locations
            if isinstance(location, OnlineLocation) and location.active
        )

    locations = tuple(sorted(locations, key=lambda item: item.location_index))
    options: list[SessionOption] = []

    for current_date in teaching_dates:
        for block in valid_blocks:
            lecturer_is_unavailable = is_resource_unavailable(
                availability_windows=problem.lecturer_availabilities,
                resource_index=teaching_part.lecturer_index,
                teaching_date=current_date.calendar_date,
                start_period=block.start_period,
                end_period=block.end_period,
            )
            if lecturer_is_unavailable:
                continue

            for location in locations:
                if isinstance(location, Room):
                    room_is_unavailable = is_resource_unavailable(
                        availability_windows=problem.room_availabilities,
                        resource_index=location.location_index,
                        teaching_date=current_date.calendar_date,
                        start_period=block.start_period,
                        end_period=block.end_period,
                    )
                    if room_is_unavailable:
                        continue

                options.append(
                    SessionOption(
                        session_index=class_session.session_index,
                        location_index=location.location_index,
                        teaching_date=current_date.calendar_date,
                        start_period=block.start_period,
                        end_period=block.end_period,
                    )
                )

    return tuple(options)


def build_option_domains(
    problem: ProblemInstance,
) -> tuple[tuple[SessionOption, ...], ...]:
    """Sinh miền option theo đúng thứ tự gene của ``ProblemInstance``."""

    return tuple(
        build_options_for_session(problem, class_session)
        for class_session in problem.class_sessions
    )
