"""Giải mã vector random-key thành phân công và lịch cố định theo học kỳ.

Nhóm gene đầu chọn đúng một giảng viên cho mỗi ``CourseSection``. Mỗi gene
lịch còn lại tương ứng một chuỗi buổi lặp, không phải một tuần riêng lẻ. Gene
đó ưu tiên một mẫu ``(thứ, tiết bắt đầu, địa điểm)`` dùng được ở tất cả tuần
hoạt động của chuỗi. Decoder chỉ thử mẫu khác khi cần tránh vi phạm cứng; nó
không đánh đổi điều kiện sức chứa hoặc tự tối ưu các tiêu chí mềm thay GA/PO.
"""

from dataclasses import dataclass
from enum import Enum
from math import floor, isfinite

from .constraints import HardViolationCode, ValidationResult, validate_timetable
from .encoder import (
    RecurringPattern,
    build_options_for_session,
    build_recurring_patterns_for_group,
    get_periods_for_block,
    room_can_host_part,
)
from .models import ClassSession, LocationType, ProblemInstance, SessionOption


class DecodeStatus(str, Enum):
    """Trạng thái kết thúc có cấu trúc của một lần giải mã vector."""

    SUCCESS = "SUCCESS"
    NO_OPTION = "NO_OPTION"
    DECODE_FAILED = "DECODE_FAILED"


@dataclass(frozen=True, slots=True)
class DecodeResult:
    """Kết quả giải mã cùng số liệu chẩn đoán tìm kiếm có quay lui."""

    status: DecodeStatus
    selected_options: tuple[SessionOption, ...]
    selected_option_indices: tuple[int, ...]
    repaired_vector: tuple[float, ...]
    nodes_explored: int
    backtracks: int
    failed_session_index: int | None
    reason: str
    selected_lecturer_indices: tuple[int, ...] = ()

    @property
    def is_success(self) -> bool:
        return self.status == DecodeStatus.SUCCESS


def preferred_option_index(gene: float, option_count: int) -> int:
    """Ánh xạ random-key ``x`` sang ``min(floor(x*m), m-1)``."""

    return min(floor(gene * option_count), option_count - 1)


def _ordered_option_indices(preferred_index: int, option_count: int) -> tuple[int, ...]:
    """Thử lựa chọn do gene ưu tiên trước, rồi đi vòng qua phần còn lại."""

    return tuple(
        (preferred_index + offset) % option_count
        for offset in range(option_count)
    )


def _has_hard_violation(result: ValidationResult) -> bool:
    """Bỏ qua lỗi thiếu buổi vì lịch từng bước cố ý chưa hoàn chỉnh."""

    return any(
        violation.code != HardViolationCode.MISSING_ASSIGNMENT
        for violation in result.violations
    )


def explain_empty_domain(problem: ProblemInstance, session: ClassSession) -> str:
    """Chỉ ra tầng lọc làm rỗng miền option nguyên tử của một tuần."""

    suitable_dates = tuple(
        item for item in problem.teaching_dates
        if item.week_number == session.week_number
    )
    if not suitable_dates:
        return "Tuần của buổi không có TeachingDate để suy ra thứ trong tuần."

    suitable_blocks = tuple(
        block
        for block in problem.allowed_period_blocks
        if block.duration_periods == session.duration_periods
        and get_periods_for_block(problem.time_periods, block) is not None
    )
    if not suitable_blocks:
        return "Không có khung tiết hợp lệ cho duration của buổi."

    plan = next(
        item for item in problem.teaching_plans
        if item.teaching_plan_id == session.teaching_plan_id
    )
    part = problem.teaching_parts[plan.teaching_part_index]
    if session.required_location_type == LocationType.PHYSICAL_ROOM:
        section = next(
            item
            for item in problem.course_sections
            if item.section_code == part.section_code
        )
        has_location = any(
            room_can_host_part(room, part, section.expected_enrollment)
            for room in problem.rooms
        )
    else:
        has_location = any(location.active for location in problem.online_locations)
    if not has_location:
        return (
            "Không có địa điểm đang hoạt động đúng loại, đủ sức chứa và "
            "đủ thiết bị bắt buộc."
        )
    if not build_options_for_session(problem, session):
        return "Mọi tổ hợp còn lại bị UNAVAILABLE của giảng viên hoặc phòng chặn."
    return "Miền truyền vào rỗng dù encoder vẫn sinh được option; cần kiểm tra dữ liệu."


def explain_empty_recurring_group(problem: ProblemInstance, group_index: int) -> str:
    """Giải thích khi từng tuần có option nhưng không tồn tại mẫu chung."""

    group_key = problem.schedule_group_keys[group_index]
    return (
        f"Nhóm plan={group_key[0]}, stability_group={group_key[1]} không có "
        "cùng một thứ–tiết–địa điểm khả dụng ở mọi tuần hoạt động."
    )


def _validate_decode_inputs(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    vector: tuple[float, ...],
    max_decode_nodes: int,
) -> None:
    """Kiểm tra hình dạng dữ liệu trước khi giải mã."""

    if max_decode_nodes < 1:
        raise ValueError("max_decode_nodes phải lớn hơn hoặc bằng 1.")
    if len(option_domains) != problem.session_dimension:
        raise ValueError("Số miền option phải bằng số ClassSession.")
    if len(vector) != problem.dimension:
        raise ValueError("Số gene phải bằng gene phân công cộng gene nhóm lịch lặp.")
    for session_index, domain in enumerate(option_domains):
        if any(option.session_index != session_index for option in domain):
            raise ValueError("Option phải nằm trong miền của đúng session_index.")
    for gene in vector:
        if not isfinite(gene) or not 0.0 <= gene <= 1.0:
            raise ValueError("Gene sau boundary phải là số hữu hạn trong [0,1].")


def _select_lecturers(
    problem: ProblemInstance,
    vector: tuple[float, ...],
) -> tuple[dict[str, int], tuple[int, ...], DecodeResult | None]:
    """Đọc gene phân công; snapshot v1 tiếp tục dùng người đã gán cứng."""

    selected: list[int] = []
    lecturer_by_section: dict[str, int] = {}
    for assignment_index, section_code in enumerate(problem.assignment_section_codes):
        eligible = problem.eligible_lecturer_indices(section_code)
        if not eligible:
            return {}, (), DecodeResult(
                DecodeStatus.NO_OPTION, (), (), (), 0, 0, None,
                f"CourseSection {section_code} không có giảng viên đủ năng lực.",
            )
        lecturer_index = eligible[
            preferred_option_index(vector[assignment_index], len(eligible))
        ]
        lecturer_by_section[section_code] = lecturer_index
        selected.append(lecturer_index)

    if not problem.lecturer_course_capabilities:
        for part in problem.teaching_parts:
            if part.lecturer_index is None:
                raise ValueError("Snapshot v1 thiếu lecturer_index.")
            lecturer_by_section[part.section_code] = part.lecturer_index
    return lecturer_by_section, tuple(selected), None


def _load_failure(
    problem: ProblemInstance,
    lecturer_by_section: dict[str, int],
    selected_lecturers: tuple[int, ...],
) -> DecodeResult | None:
    """Loại sớm phân công chắc chắn vượt tải giảng dạy tối đa."""

    lecturers = {item.lecturer_index: item for item in problem.lecturers}
    loads: dict[int, int] = {}
    for part in problem.teaching_parts:
        lecturer_index = lecturer_by_section[part.section_code]
        loads[lecturer_index] = loads.get(lecturer_index, 0) + part.total_periods
    for lecturer_index, assigned_periods in loads.items():
        maximum = lecturers[lecturer_index].max_teaching_periods
        if maximum is not None and assigned_periods > maximum:
            return DecodeResult(
                DecodeStatus.DECODE_FAILED, (), (), (), 0, 0, None,
                f"Giảng viên {lecturer_index} được phân {assigned_periods} tiết, "
                f"vượt giới hạn {maximum} tiết trong snapshot.",
                selected_lecturers,
            )
    return None


def _part_for_group(problem: ProblemInstance, group_index: int):
    """Lấy TeachingPart nguồn của một nhóm lịch lặp."""

    first_session_index = problem.schedule_groups[group_index][0]
    session = problem.class_sessions[first_session_index]
    plan = next(
        item for item in problem.teaching_plans
        if item.teaching_plan_id == session.teaching_plan_id
    )
    return problem.teaching_parts[plan.teaching_part_index]


def decode_vector(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    vector: tuple[float, ...],
    max_decode_nodes: int,
) -> DecodeResult:
    """Ghép các mẫu lịch lặp thành lịch hợp lệ bằng MRV và backtracking."""

    _validate_decode_inputs(problem, option_domains, vector, max_decode_nodes)
    for session_index, domain in enumerate(option_domains):
        if not domain:
            session = problem.class_sessions[session_index]
            return DecodeResult(
                DecodeStatus.NO_OPTION, (), (), (), 0, 0, session_index,
                f"ClassSession {session.class_session_id} không có option: "
                f"{explain_empty_domain(problem, session)}",
            )

    lecturer_by_section, selected_lecturers, failure = _select_lecturers(
        problem, vector
    )
    if failure is not None:
        return failure
    failure = _load_failure(problem, lecturer_by_section, selected_lecturers)
    if failure is not None:
        return failure

    active_domains: list[tuple[RecurringPattern, ...]] = []
    for group_index in range(problem.schedule_dimension):
        part = _part_for_group(problem, group_index)
        chosen_lecturer = lecturer_by_section[part.section_code]
        patterns = build_recurring_patterns_for_group(
            problem, option_domains, group_index, chosen_lecturer
        )
        if not patterns:
            first_session = problem.schedule_groups[group_index][0]
            return DecodeResult(
                DecodeStatus.DECODE_FAILED, (), (), (), 0, 0, first_session,
                f"Giảng viên {chosen_lecturer} của {part.section_code}: "
                f"{explain_empty_recurring_group(problem, group_index)}",
                selected_lecturers,
            )
        active_domains.append(patterns)

    preferred_indices = tuple(
        preferred_option_index(
            vector[problem.schedule_gene_offset + group_index], len(domain)
        )
        for group_index, domain in enumerate(active_domains)
    )
    option_orders = tuple(
        _ordered_option_indices(preferred_indices[index], len(domain))
        for index, domain in enumerate(active_domains)
    )
    unary_valid_indices: list[tuple[int, ...]] = []
    for domain, ordered_indices in zip(active_domains, option_orders):
        valid = []
        for pattern_index in ordered_indices:
            result = validate_timetable(problem, domain[pattern_index].session_options)
            if not _has_hard_violation(result):
                valid.append(pattern_index)
        unary_valid_indices.append(tuple(valid))

    assigned_indices: dict[int, int] = {}
    compatibility_cache: dict[tuple[int, int, int, int], bool] = {}
    nodes_explored = 0
    backtracks = 0
    failed_group_index: int | None = None
    failure_reason = "Không ghép được các mẫu lịch lặp thành lịch hợp lệ."
    budget_exhausted = False

    def patterns_are_compatible(
        first_group: int,
        first_index: int,
        second_group: int,
        second_index: int,
    ) -> bool:
        """Kiểm tra xung đột giữa toàn bộ tuần của hai mẫu và ghi nhớ."""

        if first_group > second_group:
            first_group, second_group = second_group, first_group
            first_index, second_index = second_index, first_index
        key = (first_group, first_index, second_group, second_index)
        if key not in compatibility_cache:
            first_pattern = active_domains[first_group][first_index]
            second_pattern = active_domains[second_group][second_index]
            # Hai mẫu ở hai thứ khác nhau không bao giờ chia sẻ cùng ngày,
            # nên không thể trùng giảng viên/phòng hoặc phát sinh di chuyển
            # trong ngày. Nhánh nhanh này loại phần lớn lời gọi validator.
            if first_pattern.iso_weekday != second_pattern.iso_weekday:
                compatibility_cache[key] = True
            else:
                first_by_date = {
                    option.teaching_date: option
                    for option in first_pattern.session_options
                }
                second_by_date = {
                    option.teaching_date: option
                    for option in second_pattern.session_options
                }
                compatibility_cache[key] = all(
                    not _has_hard_violation(
                        validate_timetable(
                            problem,
                            (first_by_date[current_date], second_by_date[current_date]),
                        )
                    )
                    for current_date in first_by_date.keys() & second_by_date.keys()
                )
        return compatibility_cache[key]

    def compatible_indices(group_index: int) -> tuple[int, ...]:
        return tuple(
            pattern_index
            for pattern_index in unary_valid_indices[group_index]
            if all(
                patterns_are_compatible(
                    group_index, pattern_index, other_group, other_pattern
                )
                for other_group, other_pattern in assigned_indices.items()
            )
        )

    def search() -> bool:
        """Gán đệ quy theo miền còn lại nhỏ nhất trong giới hạn node."""

        nonlocal nodes_explored, backtracks, failed_group_index
        nonlocal failure_reason, budget_exhausted
        if len(assigned_indices) == problem.schedule_dimension:
            flattened = tuple(
                option
                for group_index in range(problem.schedule_dimension)
                for option in active_domains[group_index][
                    assigned_indices[group_index]
                ].session_options
            )
            final_validation = validate_timetable(problem, flattened)
            if final_validation.is_valid:
                return True
            failure_reason = final_validation.violations[0].message
            return False

        candidates = []
        for group_index in range(problem.schedule_dimension):
            if group_index not in assigned_indices:
                possible = compatible_indices(group_index)
                candidates.append((len(possible), group_index, possible))
        _, group_index, possible_indices = min(candidates)
        if not possible_indices:
            failed_group_index = group_index
            plan_id, stability_group = problem.schedule_group_keys[group_index]
            failure_reason = (
                f"Nhóm plan={plan_id}, stability_group={stability_group} "
                "không còn mẫu cố định tương thích với lịch đang xây dựng."
            )
            return False

        for pattern_index in possible_indices:
            if nodes_explored >= max_decode_nodes:
                budget_exhausted = True
                failed_group_index = group_index
                failure_reason = "Đã đạt giới hạn max_decode_nodes."
                return False
            nodes_explored += 1
            assigned_indices[group_index] = pattern_index
            if search():
                return True
            del assigned_indices[group_index]
            backtracks += 1
            if budget_exhausted:
                return False
        return False

    if not search():
        failed_session = None
        if failed_group_index is not None:
            failed_session = problem.schedule_groups[failed_group_index][0]
        return DecodeResult(
            DecodeStatus.DECODE_FAILED, (), (), (), nodes_explored, backtracks,
            failed_session, failure_reason, selected_lecturers,
        )

    selected_by_session: dict[int, SessionOption] = {}
    raw_index_by_session: dict[int, int] = {}
    for group_index in range(problem.schedule_dimension):
        pattern = active_domains[group_index][assigned_indices[group_index]]
        for option, raw_index in zip(pattern.session_options, pattern.raw_option_indices):
            selected_by_session[option.session_index] = option
            raw_index_by_session[option.session_index] = raw_index

    selected_options = tuple(
        selected_by_session[index] for index in range(problem.session_dimension)
    )
    selected_raw_indices = tuple(
        raw_index_by_session[index] for index in range(problem.session_dimension)
    )
    repaired_vector = tuple(vector[:problem.schedule_gene_offset]) + tuple(
        vector[problem.schedule_gene_offset + group_index]
        if assigned_indices[group_index] == preferred_indices[group_index]
        else (assigned_indices[group_index] + 0.5) / len(active_domains[group_index])
        for group_index in range(problem.schedule_dimension)
    )
    return DecodeResult(
        DecodeStatus.SUCCESS,
        selected_options,
        selected_raw_indices,
        repaired_vector,
        nodes_explored,
        backtracks,
        None,
        "Phân công và mẫu lịch cố định đã qua validator hard constraints.",
        selected_lecturers,
    )
