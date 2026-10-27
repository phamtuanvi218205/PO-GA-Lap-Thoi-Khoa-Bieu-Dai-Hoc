"""Sinh option theo tuần và giao chúng thành mẫu lịch lặp cho cả học kỳ.

Encoder chỉ kiểm tra những điều kiện bắt buộc có thể xác định cho *một* buổi
độc lập: giảng viên đủ năng lực, tuần/ngày, khung tiết, loại địa điểm, sức
chứa, thiết bị và trạng thái ``UNAVAILABLE``. Xung đột giữa nhiều buổi sẽ do
decoder/validator xử lý; các tiêu chí mềm như mong muốn giảng viên sẽ do
fitness đánh giá.

Ngày nghỉ lễ không còn làm thay đổi miền tối ưu. ``TeachingDate`` vẫn được
dùng để quy đổi thứ sang ngày thật của từng tuần và kiểm tra availability theo
ngày, nhưng ``DateStatus`` không loại option. Sau khi sinh option nguyên tử,
encoder lấy giao theo ``(thứ, tiết bắt đầu, địa điểm)`` giữa mọi tuần của cùng
một nhóm lặp. Một giao điểm như vậy là một mẫu cố định cho toàn thời gian hoạt
động của plan.
"""

from dataclasses import dataclass
from datetime import date

from .models import (
    AllowedPeriodBlock,
    AvailabilityScopeType,
    AvailabilityType,
    AvailabilityWindow,
    ClassSession,
    LocationType,
    OnlineLocation,
    ProblemInstance,
    Room,
    SessionOption,
    TeachingPart,
    TimePeriod,
)


@dataclass(frozen=True, slots=True)
class RecurringPattern:
    """Một mẫu thứ–tiết–địa điểm dùng được ở mọi tuần của một chuỗi buổi.

    ``session_options`` chứa đúng một option nguyên tử cho mỗi lần xuất hiện
    theo tuần, theo cùng thứ, tiết bắt đầu, địa điểm và giảng viên. Thời lượng
    và tiết kết thúc có thể khác giữa các giai đoạn nếu TeachingPlan quy định.
    """

    group_index: int
    lecturer_index: int
    iso_weekday: int
    start_period: int
    location_index: int
    session_options: tuple[SessionOption, ...]
    raw_option_indices: tuple[int, ...]


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


def room_can_host_part(
    room: Room,
    teaching_part: TeachingPart,
    expected_enrollment: int | None,
) -> bool:
    """Kiểm tra toàn bộ điều kiện cứng của phòng cho ``TeachingPart``.

    Với buổi vật lý, sĩ số dự kiến và sức chứa phòng phải có dữ liệu, đồng
    thời phòng phải đủ chỗ. Dữ liệu thiếu không được ngầm hiểu là 0 hoặc vô
    hạn; readiness sẽ báo lỗi còn encoder loại phòng khỏi miền option.
    """

    if not room.active:
        return False
    if teaching_part.required_location_type != LocationType.PHYSICAL_ROOM:
        return False
    if room.room_type != teaching_part.required_room_type:
        return False
    if expected_enrollment is None or room.capacity is None:
        return False
    if room.capacity < expected_enrollment:
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
    section = next(
        candidate
        for candidate in problem.course_sections
        if candidate.section_code == teaching_part.section_code
    )

    teaching_dates = sorted(
        (
            item
            for item in problem.teaching_dates
            if item.week_number == class_session.week_number
        ),
        key=lambda item: item.calendar_date,
    )
    valid_blocks = _get_valid_blocks(problem, class_session)

    if class_session.required_location_type == LocationType.PHYSICAL_ROOM:
        locations = tuple(
            room
            for room in problem.rooms
            if room_can_host_part(
                room,
                teaching_part,
                section.expected_enrollment,
            )
        )
    else:
        locations = tuple(
            location
            for location in problem.online_locations
            if isinstance(location, OnlineLocation) and location.active
        )

    locations = tuple(sorted(locations, key=lambda item: item.location_index))
    options: list[SessionOption] = []

    # Miền option chứa mọi giảng viên đủ khả năng dạy *toàn bộ* lớp học phần.
    # Gene phân công ở đầu vector sẽ chọn một người; decoder sau đó chỉ giữ
    # các option mang đúng lecturer_index đó. Encoder không tự chọn người tốt.
    eligible_lecturers = problem.eligible_lecturer_indices(teaching_part.section_code)
    for lecturer_index in eligible_lecturers:
        for current_date in teaching_dates:
            for block in valid_blocks:
                lecturer_is_unavailable = is_resource_unavailable(
                    availability_windows=problem.lecturer_availabilities,
                    resource_index=lecturer_index,
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
                            lecturer_index=(
                                lecturer_index
                                if problem.lecturer_course_capabilities
                                else -1
                            ),
                        )
                    )

    return tuple(options)


def build_option_domains(
    problem: ProblemInstance,
) -> tuple[tuple[SessionOption, ...], ...]:
    """Sinh một miền option cho mỗi session theo thứ tự ``session_index``.

    Số miền bằng ``session_dimension``. Nhóm gene phân công giảng viên không
    cần ``SessionOption`` riêng vì miền của chúng được lấy trực tiếp từ
    ``eligible_lecturer_indices``.
    """

    return tuple(
        build_options_for_session(problem, class_session)
        for class_session in problem.class_sessions
    )


def build_recurring_patterns_for_group(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    group_index: int,
    lecturer_index: int,
) -> tuple[RecurringPattern, ...]:
    """Lấy các mẫu cố định khả thi cho một nhóm lặp và một giảng viên.

    Một mẫu chỉ tồn tại khi mọi session theo tuần của nhóm đều có option cùng
    thứ ISO, tiết bắt đầu và địa điểm. Vì mỗi option tuần đã qua bộ lọc
    ``UNAVAILABLE``, phép giao này cũng loại mẫu đụng bất kỳ ngày bận cụ thể
    nào của giảng viên hoặc phòng mà không cần cho phép lịch nhảy giữa tuần.
    """

    if len(option_domains) != problem.session_dimension:
        raise ValueError("Số miền option phải bằng số ClassSession.")
    if not 0 <= group_index < problem.schedule_dimension:
        raise ValueError("group_index nằm ngoài miền nhóm lịch lặp.")

    session_indices = problem.schedule_groups[group_index]
    indexed_options_by_session: list[
        dict[tuple[int, int, int], tuple[int, SessionOption]]
    ] = []

    for session_index in session_indices:
        keyed: dict[tuple[int, int, int], tuple[int, SessionOption]] = {}
        for raw_index, option in enumerate(option_domains[session_index]):
            if problem.option_lecturer_index(option) != lecturer_index:
                continue
            key = (
                option.teaching_date.isoweekday(),
                option.start_period,
                option.location_index,
            )
            # Trong một TermWeek hợp lệ chỉ có một ngày cho mỗi thứ. Giữ
            # option đầu tiên giúp hành vi vẫn xác định nếu dữ liệu nguồn bị
            # lặp nhưng chưa bị tầng import chặn.
            keyed.setdefault(key, (raw_index, option))
        indexed_options_by_session.append(keyed)

    if not indexed_options_by_session:
        return ()

    common_keys = set(indexed_options_by_session[0])
    for keyed in indexed_options_by_session[1:]:
        common_keys.intersection_update(keyed)

    patterns: list[RecurringPattern] = []
    for iso_weekday, start_period, location_index in sorted(common_keys):
        values = tuple(
            keyed[(iso_weekday, start_period, location_index)]
            for keyed in indexed_options_by_session
        )
        patterns.append(
            RecurringPattern(
                group_index=group_index,
                lecturer_index=lecturer_index,
                iso_weekday=iso_weekday,
                start_period=start_period,
                location_index=location_index,
                session_options=tuple(value[1] for value in values),
                raw_option_indices=tuple(value[0] for value in values),
            )
        )
    return tuple(patterns)


def build_all_recurring_pattern_domains(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
) -> tuple[tuple[RecurringPattern, ...], ...]:
    """Sinh miền mẫu lặp của mọi gene lịch, gồm tất cả người đủ năng lực."""

    plans_by_id = {
        plan.teaching_plan_id: plan for plan in problem.teaching_plans
    }
    parts_by_index = {
        part.teaching_part_index: part for part in problem.teaching_parts
    }
    domains: list[tuple[RecurringPattern, ...]] = []
    for group_index, session_indices in enumerate(problem.schedule_groups):
        first_session = problem.class_sessions[session_indices[0]]
        part = parts_by_index[
            plans_by_id[first_session.teaching_plan_id].teaching_part_index
        ]
        group_patterns: list[RecurringPattern] = []
        for lecturer_index in problem.eligible_lecturer_indices(part.section_code):
            group_patterns.extend(
                build_recurring_patterns_for_group(
                    problem,
                    option_domains,
                    group_index,
                    lecturer_index,
                )
            )
        domains.append(tuple(group_patterns))
    return tuple(domains)
