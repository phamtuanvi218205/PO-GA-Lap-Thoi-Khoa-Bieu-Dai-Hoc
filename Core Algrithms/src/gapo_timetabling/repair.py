"""Repair mỏng cho vector random-key sau một lần decode thất bại.

Decoder vẫn là thành phần chính chịu trách nhiệm ghép các ``SessionOption``
thành lịch hợp lệ bằng MRV và quay lui có giới hạn. Module này không lặp lại
logic xếp lịch, không tự kiểm tra xung đột và không thay đổi cấu trúc bài toán.

Repair chỉ làm đúng ba việc:

1. Chọn một gene để thử lại.
2. Đưa gene đó vào giữa khoảng của một option khác trong cùng miền cố định.
3. Gọi lại decoder và nhận kết quả đã được decoder/validator kiểm tra.

Cách làm này tuân theo D057 và D078: repair không được đổi giảng viên, plan,
tuần, thời lượng, số buổi, tổng số tiết hoặc loại phần giảng dạy.
"""

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from .decoder import (
    DecodeResult,
    DecodeStatus,
    decode_vector,
    preferred_option_index,
)
from .models import ProblemInstance, SessionOption


class RepairStatus(str, Enum):
    """Trạng thái kết thúc của lớp repair mỏng."""

    NOT_NEEDED = "NOT_NEEDED"
    REPAIRED = "REPAIRED"
    NOT_REPAIRABLE = "NOT_REPAIRABLE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RepairResult:
    """Kết quả repair cùng số liệu phục vụ theo dõi và đánh giá sau này.

    ``decode_result`` luôn là kết quả decoder có ý nghĩa nhất:

    - kết quả ban đầu nếu không cần hoặc không thể repair;
    - kết quả thành công khi repair được;
    - kết quả của lần thử cuối nếu đã dùng hết số lần repair.

    ``attempts`` chỉ đếm số lần repair gọi lại decoder, không tính lần decode
    ban đầu do bên gọi đã thực hiện trước đó.
    """

    status: RepairStatus
    decode_result: DecodeResult
    attempts: int
    total_nodes_explored: int
    total_backtracks: int
    changed_session_index: int | None
    requested_option_index: int | None
    reason: str

    @property
    def is_success(self) -> bool:
        """Cho biết kết quả cuối có chứa một thời khóa biểu hợp lệ hay không."""

        return self.decode_result.is_success

    @property
    def was_repaired(self) -> bool:
        """Phân biệt lịch do repair tìm được với lịch vốn đã hợp lệ."""

        return self.status == RepairStatus.REPAIRED


def gene_for_option_index(option_index: int, option_count: int) -> float:
    """Trả gene ở chính giữa khoảng ánh xạ tới một option.

    Với ``m`` option, option ``j`` nhận khoảng ``[j/m, (j+1)/m)``. Giá trị
    giữa khoảng ``(j + 0.5) / m`` tránh nằm đúng biên và khi giải mã lại sẽ
    luôn ưu tiên đúng option ``j``.
    """

    if option_count < 1:
        raise ValueError("option_count phải lớn hơn hoặc bằng 1.")
    if not 0 <= option_index < option_count:
        raise ValueError("option_index phải nằm trong miền option.")

    return (option_index + 0.5) / option_count


def _validate_repair_input(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    vector: tuple[float, ...],
    max_repair_attempts: int,
    max_decode_nodes_per_attempt: int,
) -> None:
    """Kiểm tra biên API; đây không phải logic kiểm tra lịch của validator."""

    if max_repair_attempts < 1:
        raise ValueError("max_repair_attempts phải lớn hơn hoặc bằng 1.")
    if max_decode_nodes_per_attempt < 1:
        raise ValueError("max_decode_nodes_per_attempt phải lớn hơn hoặc bằng 1.")
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


def _session_retry_order(
    dimension: int,
    failed_session_index: int | None,
) -> tuple[int, ...]:
    """Ưu tiên gene được decoder báo thất bại, rồi mới thử các gene còn lại."""

    if failed_session_index is None or not 0 <= failed_session_index < dimension:
        return tuple(range(dimension))

    return (failed_session_index,) + tuple(
        index
        for index in range(dimension)
        if index != failed_session_index
    )


def _candidate_vectors(
    option_domains: tuple[tuple[SessionOption, ...], ...],
    vector: tuple[float, ...],
    failed_session_index: int | None,
):
    """Sinh lần lượt các vector chỉ khác vector gốc đúng một gene.

    Repair thử option kế tiếp theo vòng tròn trong cùng miền. Hàm không tạo
    option mới và không thay đổi miền; vì vậy mọi ứng viên vẫn giữ nguyên
    tuần, thời lượng và dữ liệu nghiệp vụ đã được khóa trong ProblemInstance.
    """

    retry_order = _session_retry_order(len(vector), failed_session_index)
    for session_index in retry_order:
        option_count = len(option_domains[session_index])
        if option_count < 2:
            # Miền có một option không có lựa chọn thay thế để repair.
            continue

        current_index = preferred_option_index(
            vector[session_index],
            option_count,
        )
        for offset in range(1, option_count):
            requested_index = (current_index + offset) % option_count
            candidate = list(vector)
            candidate[session_index] = gene_for_option_index(
                requested_index,
                option_count,
            )
            yield session_index, requested_index, tuple(candidate)


def repair_vector(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    vector: tuple[float, ...],
    initial_decode_result: DecodeResult,
    max_repair_attempts: int,
    max_decode_nodes_per_attempt: int,
) -> RepairResult:
    """Thử cứu một vector thất bại bằng các thay đổi một gene có giới hạn.

    Hàm chỉ được gọi sau lần decode đầu tiên. Nếu lịch đã hợp lệ thì trả ngay
    ``NOT_NEEDED``. Nếu có miền rỗng (``NO_OPTION``), repair không thể tự tạo
    option nên trả ``NOT_REPAIRABLE``. Với ``DECODE_FAILED``, hàm thử các
    vector lân cận theo thứ tự xác định và dừng ngay khi decoder tìm được lịch.

    Repair không bảo đảm cứu được mọi vector. Đặc biệt, nếu miền option thực
    sự không thể ghép thành lịch, mọi lần thử sẽ vẫn thất bại. Giá trị thực tế
    của lớp này cần được đo sau khi có population và optimizer hoàn chỉnh.
    """

    _validate_repair_input(
        problem,
        option_domains,
        vector,
        max_repair_attempts,
        max_decode_nodes_per_attempt,
    )

    if initial_decode_result.status == DecodeStatus.SUCCESS:
        return RepairResult(
            status=RepairStatus.NOT_NEEDED,
            decode_result=initial_decode_result,
            attempts=0,
            total_nodes_explored=0,
            total_backtracks=0,
            changed_session_index=None,
            requested_option_index=None,
            reason="Vector ban đầu đã giải mã thành lịch hợp lệ.",
        )

    if initial_decode_result.status == DecodeStatus.NO_OPTION:
        return RepairResult(
            status=RepairStatus.NOT_REPAIRABLE,
            decode_result=initial_decode_result,
            attempts=0,
            total_nodes_explored=0,
            total_backtracks=0,
            changed_session_index=None,
            requested_option_index=None,
            reason=(
                "Có ClassSession không có option; repair không được phép "
                "tự tạo option hoặc thay đổi dữ liệu đầu vào."
            ),
        )

    attempts = 0
    total_nodes_explored = 0
    total_backtracks = 0
    last_result = initial_decode_result
    last_session_index: int | None = None
    last_requested_index: int | None = None

    candidates = _candidate_vectors(
        option_domains,
        vector,
        initial_decode_result.failed_session_index,
    )
    for session_index, requested_index, candidate_vector in candidates:
        if attempts >= max_repair_attempts:
            break

        attempts += 1
        last_session_index = session_index
        last_requested_index = requested_index
        last_result = decode_vector(
            problem,
            option_domains,
            candidate_vector,
            max_decode_nodes=max_decode_nodes_per_attempt,
        )
        total_nodes_explored += last_result.nodes_explored
        total_backtracks += last_result.backtracks

        if last_result.is_success:
            return RepairResult(
                status=RepairStatus.REPAIRED,
                decode_result=last_result,
                attempts=attempts,
                total_nodes_explored=total_nodes_explored,
                total_backtracks=total_backtracks,
                changed_session_index=session_index,
                requested_option_index=requested_index,
                reason="Đổi một gene đã giúp decoder tìm được lịch hợp lệ.",
            )

    if attempts == 0:
        reason = (
            "Không có gene nào sở hữu option thay thế trong miền cố định; "
            "repair không thể thực hiện thay đổi hợp lệ."
        )
    else:
        reason = (
            "Đã dùng hết số lần repair cho phép nhưng decoder vẫn chưa "
            "tìm được lịch hợp lệ."
        )

    return RepairResult(
        status=RepairStatus.FAILED,
        decode_result=last_result,
        attempts=attempts,
        total_nodes_explored=total_nodes_explored,
        total_backtracks=total_backtracks,
        changed_session_index=last_session_index,
        requested_option_index=last_requested_index,
        reason=reason,
    )
