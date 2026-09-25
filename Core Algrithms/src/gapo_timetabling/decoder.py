"""Giải mã vector random-key thành thời khóa biểu hợp lệ.

Mỗi gene chỉ ưu tiên một ``SessionOption`` của đúng ``ClassSession``. Decoder
có thể thử option khác khi cần tránh xung đột, nhưng không thay đổi plan,
giảng viên, tuần hay thời lượng. Validator độc lập kiểm tra lại lịch cuối.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import floor, isfinite

from .constraints import HardViolationCode, ValidationResult, validate_timetable
from .encoder import (
    build_options_for_session,
    get_periods_for_block,
    room_can_host_part,
)
from .models import (
    ClassSession,
    DateStatus,
    LocationType,
    ProblemInstance,
    SessionOption,
)


class DecodeStatus(str, Enum):
    """Trạng thái kết thúc có cấu trúc của một lần giải mã vector."""

    SUCCESS = "SUCCESS"
    NO_OPTION = "NO_OPTION"
    DECODE_FAILED = "DECODE_FAILED"


@dataclass(frozen=True, slots=True)
class DecodeResult:
    """Kết quả một lần giải mã cùng số liệu chẩn đoán."""

    status: DecodeStatus
    selected_options: tuple[SessionOption, ...]
    selected_option_indices: tuple[int, ...]
    repaired_vector: tuple[float, ...]
    nodes_explored: int
    backtracks: int
    failed_session_index: int | None
    reason: str

    @property
    def is_success(self) -> bool:
        """Cho biết decoder đã tạo được một lịch hợp lệ hoàn chỉnh hay chưa."""

        return self.status == DecodeStatus.SUCCESS


def _preferred_option_index(gene: float, option_count: int) -> int:
    """Đổi gene trong [0,1] thành chỉ số option, kể cả biên x=1."""

    return min(floor(gene * option_count), option_count - 1)


def _ordered_option_indices(preferred_index: int, option_count: int) -> tuple[int, ...]:
    """Thử option ưu tiên trước, rồi đi vòng qua các chỉ số còn lại."""

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


def _explain_empty_domain(problem: ProblemInstance, session: ClassSession) -> str:
    """Chỉ ra tầng lọc làm rỗng miền để hỗ trợ chẩn đoán dữ liệu đầu vào."""

    suitable_dates = tuple(
        item
        for item in problem.teaching_dates
        if item.week_number == session.week_number
        and item.status != DateStatus.HOLIDAY
    )
    if not suitable_dates:
        return "Tuần của buổi không có TeachingDate được phép giảng dạy."

    suitable_blocks = tuple(
        block
        for block in problem.allowed_period_blocks
        if block.duration_periods == session.duration_periods
        and get_periods_for_block(problem.time_periods, block) is not None
    )
    if not suitable_blocks:
        return "Không có khung tiết hợp lệ cho duration của buổi."

    plan = next(
        item
        for item in problem.teaching_plans
        if item.teaching_plan_id == session.teaching_plan_id
    )
    part = problem.teaching_parts[plan.teaching_part_index]

    if session.required_location_type == LocationType.PHYSICAL_ROOM:
        has_location = any(room_can_host_part(room, part) for room in problem.rooms)
    else:
        has_location = any(location.active for location in problem.online_locations)
    if not has_location:
        return "Không có địa điểm đang hoạt động đúng loại và thiết bị bắt buộc."

    if not build_options_for_session(problem, session):
        return "Mọi tổ hợp còn lại bị UNAVAILABLE của giảng viên hoặc phòng chặn."

    return "Miền truyền vào rỗng dù encoder vẫn sinh được option; cần kiểm tra dữ liệu miền."


def decode_vector(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    vector: tuple[float, ...],
    max_decode_nodes: int,
) -> DecodeResult:
    """Tìm lịch hợp lệ theo option ưu tiên của vector và quay lui có giới hạn.

    Một node là một lần thử gán một option cho một session. ``NO_OPTION`` chỉ
    dành cho miền rỗng ngay từ đầu; miền không rỗng nhưng không ghép được sẽ
    trả ``DECODE_FAILED``. Thứ tự thử và lựa chọn MRV đều xác định, nên cùng
    snapshot, vector và giới hạn sẽ cho cùng kết quả.
    """

    if max_decode_nodes < 1:
        raise ValueError("max_decode_nodes phải lớn hơn hoặc bằng 1.")
    if len(option_domains) != problem.dimension:
        raise ValueError("Số miền option phải bằng số ClassSession.")
    if len(vector) != problem.dimension:
        raise ValueError("Số gene phải bằng số ClassSession.")

    for session_index, domain in enumerate(option_domains):
        if any(option.session_index != session_index for option in domain):
            raise ValueError("Option phải nằm trong miền của đúng session_index.")

    for gene in vector:
        if not isfinite(gene) or not 0.0 <= gene <= 1.0:
            raise ValueError("Gene sau boundary phải là số hữu hạn trong [0,1].")

    for session_index, domain in enumerate(option_domains):
        if not domain:
            session = problem.class_sessions[session_index]
            return DecodeResult(
                status=DecodeStatus.NO_OPTION,
                selected_options=(),
                selected_option_indices=(),
                repaired_vector=(),
                nodes_explored=0,
                backtracks=0,
                failed_session_index=session_index,
                reason=(
                    f"ClassSession {session.class_session_id} không có option: "
                    f"{_explain_empty_domain(problem, session)}"
                ),
            )

    preferred_indices = tuple(
        _preferred_option_index(vector[index], len(domain))
        for index, domain in enumerate(option_domains)
    )
    option_orders = tuple(
        _ordered_option_indices(preferred_indices[index], len(domain))
        for index, domain in enumerate(option_domains)
    )

    # Kiểm tra từng option riêng bằng validator; miền encoder chuẩn sẽ luôn
    # vượt qua bước này, nhưng nó bảo vệ decoder khi dữ liệu miền bị sửa sai.
    unary_valid_indices: list[tuple[int, ...]] = []
    for domain, ordered_indices in zip(option_domains, option_orders):
        valid_indices: list[int] = []
        for option_index in ordered_indices:
            option = domain[option_index]
            result = validate_timetable(problem, (option,))
            if not _has_hard_violation(result):
                valid_indices.append(option_index)
        unary_valid_indices.append(tuple(valid_indices))

    assigned_indices: dict[int, int] = {}
    assigned_by_date: dict[date, dict[int, int]] = {}
    compatibility_cache: dict[tuple[int, int, int, int], bool] = {}
    nodes_explored = 0
    backtracks = 0
    failed_session_index: int | None = None
    failure_reason = "Không ghép được toàn bộ option thành lịch hợp lệ."
    budget_exhausted = False

    def options_are_compatible(
        first_session: int,
        first_index: int,
        second_session: int,
        second_index: int,
    ) -> bool:
        """Dùng validator độc lập cho cặp option và ghi nhớ kết quả."""

        if first_session > second_session:
            first_session, second_session = second_session, first_session
            first_index, second_index = second_index, first_index

        cache_key = (first_session, first_index, second_session, second_index)
        cached = compatibility_cache.get(cache_key)
        if cached is not None:
            return cached

        first_option = option_domains[first_session][first_index]
        second_option = option_domains[second_session][second_index]
        # Validator hiện chỉ kiểm tra xung đột giữa các buổi cùng ngày.
        # Không dựng lại toàn bộ lịch cho cặp ở hai ngày khác nhau.
        if first_option.teaching_date != second_option.teaching_date:
            compatibility_cache[cache_key] = True
            return True

        result = validate_timetable(problem, (first_option, second_option))
        compatible = not _has_hard_violation(result)
        compatibility_cache[cache_key] = compatible
        return compatible

    def compatible_indices_for_session(session_index: int) -> tuple[int, ...]:
        """Lọc các option không xung đột với phần lịch đã gán."""

        remaining: list[int] = []
        for option_index in unary_valid_indices[session_index]:
            option = option_domains[session_index][option_index]
            same_date_assignments = assigned_by_date.get(option.teaching_date, {})
            if all(
                options_are_compatible(
                    session_index,
                    option_index,
                    assigned_session,
                    assigned_option_index,
                )
                for assigned_session, assigned_option_index in same_date_assignments.items()
            ):
                remaining.append(option_index)
        return tuple(remaining)

    def search() -> bool:
        """Gán đệ quy bằng MRV và quay lui trong giới hạn số node cho phép."""

        nonlocal nodes_explored, backtracks
        nonlocal failed_session_index, failure_reason, budget_exhausted

        if len(assigned_indices) == problem.dimension:
            chosen = tuple(
                option_domains[index][assigned_indices[index]]
                for index in range(problem.dimension)
            )
            final_validation = validate_timetable(problem, chosen)
            if final_validation.is_valid:
                return True

            # Validator cuối là lớp bảo vệ độc lập. Nếu có một ràng buộc
            # không thể phát hiện bằng cặp, tiếp tục quay lui thay vì trả lịch sai.
            failed_session_index = chosen[-1].session_index
            failure_reason = final_validation.violations[0].message
            return False

        # MRV: session còn ít option tương thích nhất được xếp trước.
        # Khi bằng nhau, session_index nhỏ hơn được chọn để tái lập kết quả.
        candidates = []
        for session_index in range(problem.dimension):
            if session_index in assigned_indices:
                continue
            possible_indices = compatible_indices_for_session(session_index)
            candidates.append((len(possible_indices), session_index, possible_indices))

        _, session_index, possible_indices = min(candidates)
        if not possible_indices:
            failed_session_index = session_index
            failure_reason = (
                f"ClassSession {problem.class_sessions[session_index].class_session_id} "
                "không còn option tương thích với lịch đang xây dựng."
            )
            return False

        for option_index in possible_indices:
            if nodes_explored >= max_decode_nodes:
                budget_exhausted = True
                failed_session_index = session_index
                failure_reason = "Đã đạt giới hạn max_decode_nodes."
                return False

            nodes_explored += 1
            assigned_indices[session_index] = option_index
            selected_date = option_domains[session_index][option_index].teaching_date
            date_assignments = assigned_by_date.setdefault(selected_date, {})
            date_assignments[session_index] = option_index
            if search():
                return True

            del assigned_indices[session_index]
            del date_assignments[session_index]
            if not date_assignments:
                del assigned_by_date[selected_date]
            backtracks += 1
            if budget_exhausted:
                return False

        return False

    if not search():
        return DecodeResult(
            status=DecodeStatus.DECODE_FAILED,
            selected_options=(),
            selected_option_indices=(),
            repaired_vector=(),
            nodes_explored=nodes_explored,
            backtracks=backtracks,
            failed_session_index=failed_session_index,
            reason=failure_reason,
        )

    selected_indices = tuple(
        assigned_indices[index]
        for index in range(problem.dimension)
    )
    selected_options = tuple(
        option_domains[index][selected_indices[index]]
        for index in range(problem.dimension)
    )
    repaired_vector = tuple(
        vector[index]
        if selected_indices[index] == preferred_indices[index]
        else (selected_indices[index] + 0.5) / len(option_domains[index])
        for index in range(problem.dimension)
    )

    return DecodeResult(
        status=DecodeStatus.SUCCESS,
        selected_options=selected_options,
        selected_option_indices=selected_indices,
        repaired_vector=repaired_vector,
        nodes_explored=nodes_explored,
        backtracks=backtracks,
        failed_session_index=None,
        reason="Lịch đã qua validator hard constraints.",
    )
