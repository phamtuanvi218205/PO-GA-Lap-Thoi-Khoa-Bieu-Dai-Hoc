"""Tính fitness mềm cho một thời khóa biểu đã vượt qua Validator.

Module này triển khai ba tầng mục tiêu có thứ tự ưu tiên độc lập:

1. ``Q_time``: giữ ổn định thứ và tiết bắt đầu giữa các tuần.
2. ``Q_general``: sức chứa, khoảng trống giảng viên, số tiết dạy liên tục,
   thời gian hạn chế dùng phòng và mức ổn định phòng.
3. ``Q_lecturer``: mức đáp ứng mong muốn thời gian của giảng viên.

Ba điểm được so sánh theo thứ tự từ trái sang phải bằng khóa
``(Q_time, Q_general, Q_lecturer)``. Chúng không được cộng thành một số duy
nhất, vì một cải thiện ở tầng thấp không được bù cho lịch kém ổn định hơn ở
tầng cao. Mọi công thức trong module đều dùng quy ước: điểm nhỏ hơn tốt hơn.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from .constraints import validate_timetable
from .models import (
    AvailabilityScopeType,
    AvailabilityType,
    AvailabilityWindow,
    ClassSession,
    ConstraintType,
    FitnessBreakdown,
    FitnessResult,
    LecturerPreferenceBreakdown,
    ProblemInstance,
    SessionOption,
    TeachingPart,
    TimeStabilityException,
)


# Các trọng số mặc định được chuẩn hóa để tổng đúng bằng 1.0000. Đây là cấu
# hình kỹ thuật ban đầu; ConstraintSetting của snapshot có thể ghi đè từng
# trọng số để phục vụ sensitivity test có kiểm soát.
DEFAULT_GENERAL_WEIGHTS = {
    "SOFT_CAPACITY": 0.4091,
    "SOFT_LECTURER_GAP": 0.2273,
    "SOFT_LECTURER_CONSECUTIVE": 0.0909,
    "SOFT_ROOM_DISCOURAGED": 0.1818,
    "SOFT_ROOM_STABILITY": 0.0909,
}

# Nếu snapshot cũ chưa chứa tham số, fitness dùng ngưỡng mặc định tương thích.
# Snapshot mới ghi rõ ngưỡng để kết quả có thể được tái lập.
DEFAULT_MAX_CONSECUTIVE_PERIODS = 6


@dataclass(frozen=True, slots=True)
class TimeStabilityResult:
    """Kết quả trung gian của tiêu chí ổn định thứ và tiết bắt đầu."""

    score: float
    weekday_change_count: int
    start_period_change_count: int
    valid_exception_count: int
    comparable_session_count: int
    exceptions: tuple[TimeStabilityException, ...]


@dataclass(frozen=True, slots=True)
class RoomStabilityResult:
    """Kết quả trung gian của tiêu chí đổi phòng giữa các tuần."""

    score: float
    room_change_count: int
    comparable_physical_session_count: int


@dataclass(frozen=True, slots=True)
class GeneralQualityResult:
    """Năm thành phần đã chuẩn hóa và điểm ``Q_general`` sau khi ghép."""

    score: float
    capacity_component: float
    gap_component: float
    lecturer_consecutive_component: float
    room_discouraged_component: float
    room_stability: RoomStabilityResult


@dataclass(frozen=True, slots=True)
class LecturerPreferenceResult:
    """Điểm ``Q_lecturer`` và phần giải thích theo từng giảng viên."""

    score: float
    breakdown: tuple[LecturerPreferenceBreakdown, ...]


def _get_time_pattern(option: SessionOption) -> tuple[int, int]:
    """Trích cặp ``(thứ ISO, tiết bắt đầu)`` từ một option."""

    return option.teaching_date.isoweekday(), option.start_period


def _count_overlapping_periods(
    first_start: int,
    first_end: int,
    second_start: int,
    second_end: int,
) -> int:
    """Đếm số tiết chung của hai khoảng tiết đóng.

    Ví dụ, buổi học tiết 1--3 và cửa sổ hạn chế tiết 3--5 chồng lên nhau
    đúng một tiết là tiết 3.
    """

    overlap_start = max(first_start, second_start)
    overlap_end = min(first_end, second_end)
    return max(0, overlap_end - overlap_start + 1)


def _window_applies_to_date(
    window: AvailabilityWindow,
    teaching_date: date,
) -> bool:
    """Kiểm tra cửa sổ áp dụng cho ngày cụ thể hay cho thứ lặp hằng tuần."""

    if window.scope_type == AvailabilityScopeType.DATE:
        return window.calendar_date == teaching_date

    return window.iso_weekday == teaching_date.isoweekday()


def _choose_standard_pattern(
    selected_options: tuple[SessionOption, ...],
) -> tuple[int, int]:
    """Chọn mẫu thứ và tiết bắt đầu đại diện cho một nhóm ổn định.

    Mẫu xuất hiện nhiều nhất được chọn. Nếu nhiều mẫu có cùng tần suất, hàm
    chọn mẫu gây ít thay đổi thành phần nhất cho toàn nhóm. Nếu vẫn hòa, thứ
    nhỏ hơn rồi tiết bắt đầu nhỏ hơn được chọn để kết quả có thể tái lập.
    """

    if not selected_options:
        raise ValueError("Không thể chọn mẫu chuẩn từ danh sách option rỗng.")

    patterns = tuple(_get_time_pattern(option) for option in selected_options)
    pattern_counts = Counter(patterns)
    highest_count = max(pattern_counts.values())
    most_common_patterns = tuple(
        pattern
        for pattern, count in pattern_counts.items()
        if count == highest_count
    )

    def count_total_changes(candidate_pattern: tuple[int, int]) -> int:
        """Đếm tổng số thành phần thứ/tiết khác một mẫu ứng viên."""

        candidate_weekday, candidate_start_period = candidate_pattern
        total_changes = 0

        for weekday, start_period in patterns:
            if weekday != candidate_weekday:
                total_changes += 1
            if start_period != candidate_start_period:
                total_changes += 1

        return total_changes

    return min(
        most_common_patterns,
        key=lambda pattern: (
            count_total_changes(pattern),
            pattern[0],
            pattern[1],
        ),
    )


def _choose_standard_room(selected_options: tuple[SessionOption, ...]) -> int:
    """Chọn phòng xuất hiện nhiều nhất; hòa thì lấy ``location_index`` nhỏ."""

    if not selected_options:
        raise ValueError("Không thể chọn phòng chuẩn từ danh sách option rỗng.")

    room_counts = Counter(option.location_index for option in selected_options)
    highest_count = max(room_counts.values())
    candidate_rooms = (
        location_index
        for location_index, count in room_counts.items()
        if count == highest_count
    )
    return min(candidate_rooms)


def _domain_contains_pattern(
    option_domain: tuple[SessionOption, ...],
    standard_pattern: tuple[int, int],
) -> bool:
    """Cho biết miền của một session còn option đúng mẫu chuẩn hay không."""

    return any(
        _get_time_pattern(option) == standard_pattern
        for option in option_domain
    )


def _validate_fitness_inputs(
    problem: ProblemInstance,
    selected_options: tuple[SessionOption, ...],
    option_domains: tuple[tuple[SessionOption, ...], ...],
) -> dict[int, SessionOption]:
    """Kiểm tra dữ liệu trước khi tính bất kỳ tiêu chí mềm nào.

    Fitness chỉ nhận một lịch hoàn chỉnh, hợp lệ và được tạo từ đúng miền
    option của snapshot. Hàm trả về ánh xạ theo ``session_index`` để các công
    thức phía sau không phụ thuộc vào thứ tự của ``selected_options``.
    """

    if len(option_domains) != problem.dimension:
        raise ValueError("Số miền option phải bằng số ClassSession.")

    for session_index, domain in enumerate(option_domains):
        for option in domain:
            if option.session_index != session_index:
                raise ValueError(
                    "Mỗi option phải nằm trong miền của đúng session_index."
                )

    validation_result = validate_timetable(problem, selected_options)
    if not validation_result.is_valid:
        violation_codes = ", ".join(
            violation.code.value
            for violation in validation_result.violations
        )
        raise ValueError(
            "Chỉ được tính fitness cho lịch đã hợp lệ. "
            f"Các lỗi hiện tại: {violation_codes}"
        )

    selected_by_session = {
        option.session_index: option
        for option in selected_options
    }

    for session in problem.class_sessions:
        selected_option = selected_by_session[session.session_index]
        session_domain = option_domains[session.session_index]
        if selected_option not in session_domain:
            raise ValueError(
                "Option được chọn phải thuộc miền option của ClassSession."
            )

    return selected_by_session


def _group_sessions_by_stability(
    problem: ProblemInstance,
) -> dict[tuple[int, int], list[ClassSession]]:
    """Gom session theo ``TeachingPlan`` và ``stability_group_no``."""

    groups: dict[tuple[int, int], list[ClassSession]] = {}

    for session in problem.class_sessions:
        group_key = (
            session.teaching_plan_id,
            session.stability_group_no,
        )
        groups.setdefault(group_key, []).append(session)

    return groups


def _calculate_time_stability_from_validated_input(
    problem: ProblemInstance,
    selected_by_session: dict[int, SessionOption],
    option_domains: tuple[tuple[SessionOption, ...], ...],
) -> TimeStabilityResult:
    """Tính ``Q_time`` khi đầu vào đã được kiểm tra một lần ở bên ngoài."""

    weekday_change_count = 0
    start_period_change_count = 0
    comparable_session_count = 0
    exceptions: list[TimeStabilityException] = []

    for sessions in _group_sessions_by_stability(problem).values():
        # Một session đứng một mình không có tuần khác để so độ ổn định.
        if len(sessions) < 2:
            continue

        selected_in_group = tuple(
            selected_by_session[session.session_index]
            for session in sessions
        )
        standard_weekday, standard_start_period = _choose_standard_pattern(
            selected_in_group
        )
        standard_pattern = (standard_weekday, standard_start_period)

        for session in sessions:
            selected_option = selected_by_session[session.session_index]
            selected_pattern = _get_time_pattern(selected_option)

            # Buổi đang theo mẫu chuẩn luôn là một buổi có thể so sánh.
            if selected_pattern == standard_pattern:
                comparable_session_count += 1
                continue

            session_domain = option_domains[session.session_index]
            if not _domain_contains_pattern(session_domain, standard_pattern):
                exceptions.append(
                    TimeStabilityException(
                        session_index=session.session_index,
                        standard_iso_weekday=standard_weekday,
                        standard_start_period=standard_start_period,
                        reason=(
                            "Miền option của session không còn lựa chọn dùng "
                            "đúng thứ và tiết bắt đầu chuẩn sau các bộ lọc cứng."
                        ),
                    )
                )
                continue

            # Nếu miền vẫn còn mẫu chuẩn mà lịch không chọn nó, thay đổi này
            # không phải ngoại lệ khách quan và phải đi vào Q_time.
            comparable_session_count += 1
            if selected_pattern[0] != standard_weekday:
                weekday_change_count += 1
            if selected_pattern[1] != standard_start_period:
                start_period_change_count += 1

    if comparable_session_count == 0:
        score = 0.0
    else:
        score = (
            weekday_change_count + start_period_change_count
        ) / (2 * comparable_session_count)

    return TimeStabilityResult(
        score=score,
        weekday_change_count=weekday_change_count,
        start_period_change_count=start_period_change_count,
        valid_exception_count=len(exceptions),
        comparable_session_count=comparable_session_count,
        exceptions=tuple(exceptions),
    )


def calculate_time_stability(
    problem: ProblemInstance,
    selected_options: tuple[SessionOption, ...],
    option_domains: tuple[tuple[SessionOption, ...], ...],
) -> TimeStabilityResult:
    """Kiểm tra đầu vào rồi tính tầng ưu tiên cao nhất ``Q_time``."""

    selected_by_session = _validate_fitness_inputs(
        problem,
        selected_options,
        option_domains,
    )
    return _calculate_time_stability_from_validated_input(
        problem,
        selected_by_session,
        option_domains,
    )


def _calculate_room_stability_from_validated_input(
    problem: ProblemInstance,
    selected_by_session: dict[int, SessionOption],
) -> RoomStabilityResult:
    """Tính ``Q_room``; chỉ các buổi dùng phòng vật lý được đưa vào."""

    rooms_by_index = {
        room.location_index: room
        for room in problem.rooms
    }
    room_change_count = 0
    comparable_physical_session_count = 0

    for sessions in _group_sessions_by_stability(problem).values():
        physical_options = tuple(
            selected_by_session[session.session_index]
            for session in sessions
            if selected_by_session[session.session_index].location_index
            in rooms_by_index
        )

        # Tương tự Q_time, một phòng chỉ xuất hiện trong một buổi thì chưa có
        # quan hệ lặp giữa các tuần để gọi là ổn định hay thay đổi.
        if len(physical_options) < 2:
            continue

        standard_room_index = _choose_standard_room(physical_options)
        comparable_physical_session_count += len(physical_options)
        room_change_count += sum(
            option.location_index != standard_room_index
            for option in physical_options
        )

    if comparable_physical_session_count == 0:
        score = 0.0
    else:
        score = room_change_count / comparable_physical_session_count

    return RoomStabilityResult(
        score=score,
        room_change_count=room_change_count,
        comparable_physical_session_count=comparable_physical_session_count,
    )


def _build_session_context(
    problem: ProblemInstance,
) -> dict[int, tuple[ClassSession, TeachingPart]]:
    """Nối nhanh session với part thông qua plan đã được scenario chọn."""

    plans_by_id = {
        plan.teaching_plan_id: plan
        for plan in problem.teaching_plans
    }
    parts_by_index = {
        part.teaching_part_index: part
        for part in problem.teaching_parts
    }

    return {
        session.session_index: (
            session,
            parts_by_index[
                plans_by_id[session.teaching_plan_id].teaching_part_index
            ],
        )
        for session in problem.class_sessions
    }


def _calculate_capacity_component(
    problem: ProblemInstance,
    selected_by_session: dict[int, SessionOption],
    session_context: dict[int, tuple[ClassSession, TeachingPart]],
) -> float:
    """Tính ``Q_capacity`` có trọng số theo số tiết của từng buổi.

    Buổi online, lớp chưa có chỉ tiêu hoặc phòng chưa có capacity được bỏ khỏi
    cả tử và mẫu. Phòng nhỏ vẫn là lựa chọn hợp lệ; nó chỉ nhận điểm mềm xấu.
    """

    rooms_by_index = {
        room.location_index: room
        for room in problem.rooms
    }
    sections_by_code = {
        section.section_code: section
        for section in problem.course_sections
    }
    weighted_shortage_sum = 0.0
    evaluated_duration_sum = 0

    for session_index, selected_option in selected_by_session.items():
        room = rooms_by_index.get(selected_option.location_index)
        if room is None:
            continue

        session, part = session_context[session_index]
        expected_enrollment = sections_by_code[
            part.section_code
        ].expected_enrollment

        if expected_enrollment is None or room.capacity is None:
            continue

        shortage_ratio = max(
            0,
            expected_enrollment - room.capacity,
        ) / expected_enrollment
        weighted_shortage_sum += session.duration_periods * shortage_ratio
        evaluated_duration_sum += session.duration_periods

    if evaluated_duration_sum == 0:
        return 0.0

    return weighted_shortage_sum / evaluated_duration_sum


def _calculate_gap_component(
    selected_by_session: dict[int, SessionOption],
    session_context: dict[int, tuple[ClassSession, TeachingPart]],
) -> float:
    """Tính tỷ lệ khoảng trống đã chuẩn hóa của giảng viên.

    Chỉ các tiết trống nằm giữa hai buổi trong cùng ngày mới được tính. Mẫu số
    gồm cả tiết trống và tiết giảng dạy của những ngày có ít nhất hai buổi::

        Q_gap = total_gap_periods / (total_gap_periods + total_teaching_periods)

    Công thức này giữ ``Q_gap`` trong ``[0, 1]`` ngay cả khi khoảng nghỉ dài
    hơn tổng thời lượng giảng dạy. Ngày chỉ có một buổi không tạo khoảng trống
    giữa buổi nên không được đưa vào mẫu số.
    """

    options_by_lecturer_and_date: dict[
        tuple[int, date],
        list[SessionOption],
    ] = {}

    for session_index, selected_option in selected_by_session.items():
        _, part = session_context[session_index]
        group_key = (part.lecturer_index, selected_option.teaching_date)
        options_by_lecturer_and_date.setdefault(group_key, []).append(
            selected_option
        )

    total_gap_periods = 0
    total_teaching_periods = 0

    for options in options_by_lecturer_and_date.values():
        if len(options) < 2:
            continue

        ordered_options = sorted(options, key=lambda option: option.start_period)
        total_teaching_periods += sum(
            option.end_period - option.start_period + 1
            for option in ordered_options
        )

        for previous_option, next_option in zip(
            ordered_options,
            ordered_options[1:],
        ):
            total_gap_periods += max(
                0,
                next_option.start_period - previous_option.end_period - 1,
            )

    evaluated_periods = total_gap_periods + total_teaching_periods
    if evaluated_periods == 0:
        return 0.0

    return total_gap_periods / evaluated_periods


def _calculate_lecturer_consecutive_component(
    selected_by_session: dict[int, SessionOption],
    session_context: dict[int, tuple[ClassSession, TeachingPart]],
    max_consecutive_periods: int,
) -> float:
    """Tính tỷ lệ tiết vượt ngưỡng dạy liên tục của giảng viên.

    Các buổi của cùng giảng viên trong cùng ngày được sắp theo tiết bắt đầu.
    Hai buổi nối tiếp nhau, ví dụ tiết 1--3 và 4--6, thuộc cùng một chuỗi dạy
    liên tục. Chỉ phần vượt quá ``max_consecutive_periods`` mới bị phạt.

    Công thức chuẩn hóa::

        Q_consecutive = tổng tiết vượt ngưỡng / tổng tiết giảng dạy

    Ví dụ một chuỗi tiết 1--9 với ngưỡng 6 có ba tiết vượt ngưỡng, nên thành
    phần này bằng ``3 / 9`` nếu đó là toàn bộ lịch đang xét.
    """

    options_by_lecturer_and_date: dict[
        tuple[int, date],
        list[SessionOption],
    ] = {}

    for session_index, selected_option in selected_by_session.items():
        _, part = session_context[session_index]
        group_key = (part.lecturer_index, selected_option.teaching_date)
        options_by_lecturer_and_date.setdefault(group_key, []).append(
            selected_option
        )

    total_excess_periods = 0
    total_teaching_periods = 0

    for options in options_by_lecturer_and_date.values():
        ordered_options = sorted(options, key=lambda option: option.start_period)
        total_teaching_periods += sum(
            option.end_period - option.start_period + 1
            for option in ordered_options
        )

        current_streak_length = 0
        previous_end_period: int | None = None

        for option in ordered_options:
            option_length = option.end_period - option.start_period + 1

            if (
                previous_end_period is not None
                and option.start_period == previous_end_period + 1
            ):
                current_streak_length += option_length
            else:
                total_excess_periods += max(
                    0,
                    current_streak_length - max_consecutive_periods,
                )
                current_streak_length = option_length

            previous_end_period = option.end_period

        total_excess_periods += max(
            0,
            current_streak_length - max_consecutive_periods,
        )

    if total_teaching_periods == 0:
        return 0.0

    return total_excess_periods / total_teaching_periods


def _calculate_room_discouraged_component(
    problem: ProblemInstance,
    selected_by_session: dict[int, SessionOption],
) -> float:
    """Tính tỷ lệ tiết phòng vật lý chồng lên cửa sổ ``DISCOURAGED``."""

    room_indices = {
        room.location_index
        for room in problem.rooms
    }
    discouraged_period_count = 0
    evaluated_physical_period_count = 0

    for selected_option in selected_by_session.values():
        if selected_option.location_index not in room_indices:
            continue

        option_periods = set(
            range(selected_option.start_period, selected_option.end_period + 1)
        )
        discouraged_periods: set[int] = set()

        for window in problem.room_availabilities:
            if window.resource_index != selected_option.location_index:
                continue
            if window.availability_type != AvailabilityType.DISCOURAGED:
                continue
            if not _window_applies_to_date(window, selected_option.teaching_date):
                continue

            discouraged_periods.update(
                option_periods.intersection(
                    range(window.start_period, window.end_period + 1)
                )
            )

        discouraged_period_count += len(discouraged_periods)
        evaluated_physical_period_count += len(option_periods)

    if evaluated_physical_period_count == 0:
        return 0.0

    return discouraged_period_count / evaluated_physical_period_count


def _get_soft_weight(
    problem: ProblemInstance,
    constraint_code: str,
) -> float:
    """Lấy trọng số từ cấu hình hoặc dùng giá trị mặc định chuẩn hóa."""

    default_weight = DEFAULT_GENERAL_WEIGHTS[constraint_code]

    for setting in problem.constraint_settings:
        if setting.constraint_code != constraint_code:
            continue
        if setting.constraint_type != ConstraintType.SOFT:
            raise ValueError(
                f"{constraint_code} phải là một ConstraintSetting loại SOFT."
            )
        if not setting.enabled:
            return 0.0
        # Model đã bảo đảm SOFT luôn có weight hữu hạn và dương.
        return float(setting.weight)

    return default_weight


def _get_max_consecutive_periods(problem: ProblemInstance) -> int:
    """Đọc ngưỡng tiết liên tục từ snapshot hoặc dùng mặc định là 6.

    Ngưỡng biểu diễn số tiết nên bắt buộc là số nguyên dương. Việc kiểm tra tại
    đây giúp phát hiện snapshot cấu hình sai trước khi optimizer chạy lâu.
    """

    for setting in problem.constraint_settings:
        if setting.constraint_code != "SOFT_LECTURER_CONSECUTIVE":
            continue
        if setting.constraint_type != ConstraintType.SOFT:
            raise ValueError(
                "SOFT_LECTURER_CONSECUTIVE phải là ConstraintSetting loại SOFT."
            )
        if setting.threshold_value is None:
            return DEFAULT_MAX_CONSECUTIVE_PERIODS
        if not float(setting.threshold_value).is_integer():
            raise ValueError("Ngưỡng tiết liên tục phải là một số nguyên dương.")
        return int(setting.threshold_value)

    return DEFAULT_MAX_CONSECUTIVE_PERIODS


def _calculate_general_quality_from_validated_input(
    problem: ProblemInstance,
    selected_by_session: dict[int, SessionOption],
) -> GeneralQualityResult:
    """Tính và tổng hợp các thành phần của ``Q_general``."""

    session_context = _build_session_context(problem)
    room_stability = _calculate_room_stability_from_validated_input(
        problem,
        selected_by_session,
    )
    capacity_component = _calculate_capacity_component(
        problem,
        selected_by_session,
        session_context,
    )
    gap_component = _calculate_gap_component(
        selected_by_session,
        session_context,
    )
    lecturer_consecutive_component = _calculate_lecturer_consecutive_component(
        selected_by_session,
        session_context,
        _get_max_consecutive_periods(problem),
    )
    room_discouraged_component = _calculate_room_discouraged_component(
        problem,
        selected_by_session,
    )

    score = (
        _get_soft_weight(problem, "SOFT_CAPACITY") * capacity_component
        + _get_soft_weight(problem, "SOFT_LECTURER_GAP") * gap_component
        + _get_soft_weight(problem, "SOFT_LECTURER_CONSECUTIVE")
        * lecturer_consecutive_component
        + _get_soft_weight(problem, "SOFT_ROOM_DISCOURAGED")
        * room_discouraged_component
        + _get_soft_weight(problem, "SOFT_ROOM_STABILITY")
        * room_stability.score
    )

    return GeneralQualityResult(
        score=score,
        capacity_component=capacity_component,
        gap_component=gap_component,
        lecturer_consecutive_component=lecturer_consecutive_component,
        room_discouraged_component=room_discouraged_component,
        room_stability=room_stability,
    )


def _preference_values_for_option(
    option: SessionOption,
    lecturer_index: int,
    windows: tuple[AvailabilityWindow, ...],
) -> tuple[float, float]:
    """Trả điểm đạt ``PREFERRED`` và mức chồng ``DISCOURAGED`` của option."""

    preferred_value = 0.0
    discouraged_value = 0.0

    for window in windows:
        if window.resource_index != lecturer_index:
            continue
        if window.availability_type == AvailabilityType.UNAVAILABLE:
            continue
        if not _window_applies_to_date(window, option.teaching_date):
            continue

        overlap_count = _count_overlapping_periods(
            option.start_period,
            option.end_period,
            window.start_period,
            window.end_period,
        )
        if overlap_count == 0:
            continue

        # ProblemInstance đã kiểm tra mọi cửa sổ mềm của giảng viên có weight.
        weighted_overlap = overlap_count * float(window.preference_weight)
        if window.availability_type == AvailabilityType.PREFERRED:
            preferred_value += weighted_overlap
        elif window.availability_type == AvailabilityType.DISCOURAGED:
            discouraged_value += weighted_overlap

    return preferred_value, discouraged_value


def _calculate_lecturer_preference_from_validated_input(
    problem: ProblemInstance,
    selected_by_session: dict[int, SessionOption],
    option_domains: tuple[tuple[SessionOption, ...], ...],
) -> LecturerPreferenceResult:
    """Tính ``Q_lecturer`` so với preference tốt nhất có thể đạt trong miền.

    Với mỗi session:

    * ``missed_preferred`` là phần PREFERRED tốt nhất trong miền nhưng option
      đã chọn bỏ lỡ.
    * ``avoidable_discouraged`` là phần DISCOURAGED cao hơn mức thấp nhất có
      thể đạt trong miền. Nếu mọi option đều bị hạn chế như nhau thì không phạt.

    Tổng phạt được chia cho tổng cơ hội cải thiện thực sự, nhờ đó điểm nằm
    trong ``[0, 1]`` và không phạt một mong muốn bất khả thi.
    """

    session_context = _build_session_context(problem)
    penalties_by_lecturer: dict[int, dict[str, float | int]] = {}
    total_penalty = 0.0
    total_opportunity = 0.0

    for session_index, selected_option in selected_by_session.items():
        _, part = session_context[session_index]
        lecturer_index = part.lecturer_index
        domain = option_domains[session_index]
        domain_values = tuple(
            _preference_values_for_option(
                option,
                lecturer_index,
                problem.lecturer_availabilities,
            )
            for option in domain
        )
        selected_values = _preference_values_for_option(
            selected_option,
            lecturer_index,
            problem.lecturer_availabilities,
        )

        best_preferred = max(value[0] for value in domain_values)
        minimum_discouraged = min(value[1] for value in domain_values)
        maximum_discouraged = max(value[1] for value in domain_values)

        missed_preferred = max(0.0, best_preferred - selected_values[0])
        avoidable_discouraged = max(
            0.0,
            selected_values[1] - minimum_discouraged,
        )
        opportunity = (
            best_preferred
            + maximum_discouraged
            - minimum_discouraged
        )

        # Không có preferred đạt được và cũng không có discouraged tránh được
        # nghĩa là session này không mang thông tin cho Q_lecturer.
        if opportunity == 0.0:
            continue

        lecturer_values = penalties_by_lecturer.setdefault(
            lecturer_index,
            {
                "evaluated_session_count": 0,
                "missed_preferred_penalty": 0.0,
                "discouraged_overlap_penalty": 0.0,
            },
        )
        lecturer_values["evaluated_session_count"] += 1
        lecturer_values["missed_preferred_penalty"] += missed_preferred
        lecturer_values[
            "discouraged_overlap_penalty"
        ] += avoidable_discouraged

        total_penalty += missed_preferred + avoidable_discouraged
        total_opportunity += opportunity

    if total_opportunity == 0.0:
        score = 0.0
    else:
        score = total_penalty / total_opportunity

    breakdown = tuple(
        LecturerPreferenceBreakdown(
            lecturer_index=lecturer_index,
            evaluated_session_count=int(values["evaluated_session_count"]),
            missed_preferred_penalty=float(
                values["missed_preferred_penalty"]
            ),
            discouraged_overlap_penalty=float(
                values["discouraged_overlap_penalty"]
            ),
        )
        for lecturer_index, values in sorted(penalties_by_lecturer.items())
    )

    return LecturerPreferenceResult(score=score, breakdown=breakdown)


def calculate_fitness(
    problem: ProblemInstance,
    selected_options: tuple[SessionOption, ...],
    option_domains: tuple[tuple[SessionOption, ...], ...],
) -> FitnessResult:
    """Tính đầy đủ ba tầng fitness cho một lịch hợp lệ.

    Đây là hàm công khai mà GA, PO và pipeline lai sẽ gọi sau khi decoder và
    validator tạo được một lịch hoàn chỉnh. Thuộc tính ``fitness_key`` của kết
    quả phải được dùng để so sánh hai lịch theo thứ tự mục tiêu nghiêm ngặt.
    """

    selected_by_session = _validate_fitness_inputs(
        problem,
        selected_options,
        option_domains,
    )
    time_stability = _calculate_time_stability_from_validated_input(
        problem,
        selected_by_session,
        option_domains,
    )
    general_quality = _calculate_general_quality_from_validated_input(
        problem,
        selected_by_session,
    )
    lecturer_preference = _calculate_lecturer_preference_from_validated_input(
        problem,
        selected_by_session,
        option_domains,
    )

    breakdown = FitnessBreakdown(
        weekday_change_count=time_stability.weekday_change_count,
        start_period_change_count=time_stability.start_period_change_count,
        room_change_count=general_quality.room_stability.room_change_count,
        valid_time_exception_count=time_stability.valid_exception_count,
        comparable_time_session_count=(
            time_stability.comparable_session_count
        ),
        comparable_physical_session_count=(
            general_quality.room_stability.comparable_physical_session_count
        ),
        capacity_component=general_quality.capacity_component,
        gap_component=general_quality.gap_component,
        lecturer_consecutive_component=(
            general_quality.lecturer_consecutive_component
        ),
        room_discouraged_component=(
            general_quality.room_discouraged_component
        ),
        room_stability_component=general_quality.room_stability.score,
        lecturer_breakdown=lecturer_preference.breakdown,
        time_exceptions=time_stability.exceptions,
    )

    return FitnessResult(
        time_stability_score=time_stability.score,
        general_quality_score=general_quality.score,
        lecturer_preference_score=lecturer_preference.score,
        breakdown=breakdown,
    )
