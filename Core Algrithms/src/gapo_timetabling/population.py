"""Quản lý cá thể và khởi tạo quần thể cho bài toán thời khóa biểu.

Module này là lớp dùng chung giữa GA, PO V2 và pipeline lai. Nó không chứa
toán tử di truyền hoặc công thức cập nhật của PO. Trách nhiệm duy nhất là đưa
một vector random-key đi qua đúng chuỗi xử lý đã chốt:

``Decoder -> Repair tùy chọn -> Validator độc lập -> Fitness``.

Chỉ vector tạo được lịch hợp lệ mới trở thành ``TimetableIndividual``. Một
vector ``DECODE_FAILED`` bị loại khỏi lần thử hiện tại, còn ``NO_OPTION`` là
lỗi miền đầu vào và phải dừng trước khi khởi tạo quần thể. Cách phân biệt này
tuân theo D051, D054, D056 và D058 trong context của project.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from random import Random
from typing import Iterable

from .constraints import ValidationResult, validate_timetable
from .decoder import DecodeResult, DecodeStatus, decode_vector
from .fitness import calculate_fitness
from .models import FitnessResult, ProblemInstance, SessionOption
from .repair import RepairResult, RepairStatus, repair_vector


class CandidateEvaluationStatus(str, Enum):
    """Kết quả đánh giá một vector ứng viên."""

    SUCCESS = "SUCCESS"
    NO_OPTION = "NO_OPTION"
    DECODE_FAILED = "DECODE_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class PopulationInitializationStatus(str, Enum):
    """Kết quả của toàn bộ quá trình tạo quần thể ban đầu."""

    SUCCESS = "SUCCESS"
    NO_OPTION = "NO_OPTION"
    NO_FEASIBLE_SOLUTION_FOUND = "NO_FEASIBLE_SOLUTION_FOUND"


@dataclass(frozen=True, slots=True)
class CandidateEvaluationConfig:
    """Giới hạn xác định cho một lần đánh giá vector.

    ``max_decode_nodes`` giới hạn lần decode đầu. Nếu repair được bật,
    ``max_decode_nodes_per_repair_attempt`` giới hạn từng lần repair gọi lại
    decoder; để ``None`` thì dùng cùng giới hạn với lần decode đầu.

    Các giá trị này là cấu hình kỹ thuật của lần chạy, không phải ràng buộc
    nghiệp vụ và không được ghi cứng vào decoder hoặc repair.
    """

    max_decode_nodes: int
    enable_repair: bool = True
    max_repair_attempts: int = 1
    max_decode_nodes_per_repair_attempt: int | None = None

    def __post_init__(self) -> None:
        """Từ chối cấu hình không thể tạo ra một lần tìm kiếm hợp lệ."""

        if self.max_decode_nodes < 1:
            raise ValueError("max_decode_nodes phải lớn hơn hoặc bằng 1.")
        if self.enable_repair and self.max_repair_attempts < 1:
            raise ValueError(
                "Khi bật repair, max_repair_attempts phải lớn hơn hoặc bằng 1."
            )
        if not self.enable_repair and self.max_repair_attempts < 0:
            raise ValueError("max_repair_attempts không được âm.")
        if (
            self.max_decode_nodes_per_repair_attempt is not None
            and self.max_decode_nodes_per_repair_attempt < 1
        ):
            raise ValueError(
                "max_decode_nodes_per_repair_attempt phải lớn hơn hoặc bằng 1."
            )

    @property
    def repair_decode_node_limit(self) -> int:
        """Trả giới hạn node dùng cho mỗi lần decoder được repair gọi lại."""

        if self.max_decode_nodes_per_repair_attempt is None:
            return self.max_decode_nodes
        return self.max_decode_nodes_per_repair_attempt


@dataclass(frozen=True, slots=True)
class TimetableIndividual:
    """Một cá thể hợp lệ mà GA, PO và GA–PO có thể sử dụng.

    ``vector`` là vector đã được decoder/repair đồng bộ với option thực sự
    được chọn. Nhờ vậy thuật toán ở thế hệ sau không tiếp tục giữ một gene
    biểu diễn khác với lịch nằm trong chính cá thể đó.
    """

    vector: tuple[float, ...]
    selected_options: tuple[SessionOption, ...]
    selected_option_indices: tuple[int, ...]
    fitness: FitnessResult
    decode_nodes_explored: int
    decode_backtracks: int
    repair_attempts: int
    was_repaired: bool

    @property
    def fitness_key(self) -> tuple[float, float, float]:
        """Khóa so sánh theo đúng thứ tự lexicographic đã chốt ở Gate F."""

        return self.fitness.fitness_key


@dataclass(frozen=True, slots=True)
class CandidateEvaluationResult:
    """Kết quả chi tiết của một vector, kể cả khi vector bị loại.

    ``fitness_evaluations`` bằng 1 chỉ khi ``calculate_fitness`` đã thực sự
    được gọi. Các lần decode hoặc repair thất bại không phải FE, nhưng số node
    và backtrack vẫn được giữ riêng để đo chi phí tính toán.
    """

    status: CandidateEvaluationStatus
    input_vector: tuple[float, ...]
    individual: TimetableIndividual | None
    initial_decode_result: DecodeResult
    final_decode_result: DecodeResult
    repair_result: RepairResult | None
    validation_result: ValidationResult | None
    fitness_evaluations: int
    reason: str

    @property
    def is_success(self) -> bool:
        """Cho biết vector đã trở thành một cá thể lịch hợp lệ hay chưa."""

        return self.status == CandidateEvaluationStatus.SUCCESS

    @property
    def total_decode_nodes(self) -> int:
        """Tổng node của lần decode đầu và mọi lần decoder do repair gọi."""

        repair_nodes = 0
        if self.repair_result is not None:
            repair_nodes = self.repair_result.total_nodes_explored
        return self.initial_decode_result.nodes_explored + repair_nodes

    @property
    def total_decode_backtracks(self) -> int:
        """Tổng backtrack của lần decode đầu và mọi lần thử repair."""

        repair_backtracks = 0
        if self.repair_result is not None:
            repair_backtracks = self.repair_result.total_backtracks
        return self.initial_decode_result.backtracks + repair_backtracks


@dataclass(frozen=True, slots=True)
class PopulationInitializationResult:
    """Quần thể ban đầu cùng các chỉ số chẩn đoán của quá trình tạo.

    Khi ``status`` là ``SUCCESS``, số cá thể luôn đúng bằng kích thước yêu cầu.
    Khi hết giới hạn thử mà chưa đủ, kết quả dùng tên
    ``NO_FEASIBLE_SOLUTION_FOUND`` theo D054/D056; tên này không khẳng định
    bài toán toán học vô nghiệm.
    """

    status: PopulationInitializationStatus
    individuals: tuple[TimetableIndividual, ...]
    requested_population_size: int
    candidate_attempts: int
    fitness_evaluations: int
    decode_failed_count: int
    validation_failed_count: int
    repaired_individual_count: int
    failed_repair_count: int
    total_repair_attempts: int
    total_decode_nodes: int
    total_decode_backtracks: int
    terminal_evaluation: CandidateEvaluationResult | None
    reason: str

    @property
    def is_success(self) -> bool:
        """Cho biết đã tạo đủ số cá thể hợp lệ được yêu cầu hay chưa."""

        return self.status == PopulationInitializationStatus.SUCCESS


def _validate_option_domains(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
) -> None:
    """Kiểm tra cấu trúc miền mà không thay decoder kiểm tra tính khả thi."""

    if len(option_domains) != problem.dimension:
        raise ValueError("Số miền option phải bằng số ClassSession.")

    for session_index, domain in enumerate(option_domains):
        if any(option.session_index != session_index for option in domain):
            raise ValueError("Option phải nằm trong miền của đúng session_index.")


def evaluate_candidate(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    vector: tuple[float, ...],
    config: CandidateEvaluationConfig,
) -> CandidateEvaluationResult:
    """Đưa một vector qua Decoder, Repair, Validator và Fitness.

    Hàm này là cổng đánh giá duy nhất mà quần thể và các optimizer lịch nên
    dùng. Nhờ đó GA, PO V2 và GA–PO không thể vô tình áp dụng ba quy trình
    đánh giá khác nhau cho cùng một vector.
    """

    _validate_option_domains(problem, option_domains)

    initial_decode = decode_vector(
        problem,
        option_domains,
        vector,
        max_decode_nodes=config.max_decode_nodes,
    )
    final_decode = initial_decode
    repair_result: RepairResult | None = None

    if initial_decode.status == DecodeStatus.NO_OPTION:
        return CandidateEvaluationResult(
            status=CandidateEvaluationStatus.NO_OPTION,
            input_vector=vector,
            individual=None,
            initial_decode_result=initial_decode,
            final_decode_result=initial_decode,
            repair_result=None,
            validation_result=None,
            fitness_evaluations=0,
            reason=initial_decode.reason,
        )

    if initial_decode.status == DecodeStatus.DECODE_FAILED and config.enable_repair:
        repair_result = repair_vector(
            problem,
            option_domains,
            vector,
            initial_decode,
            max_repair_attempts=config.max_repair_attempts,
            max_decode_nodes_per_attempt=config.repair_decode_node_limit,
        )
        final_decode = repair_result.decode_result

    if not final_decode.is_success:
        if repair_result is None:
            reason = final_decode.reason
        else:
            reason = f"{repair_result.reason} Decoder cuối: {final_decode.reason}"
        return CandidateEvaluationResult(
            status=CandidateEvaluationStatus.DECODE_FAILED,
            input_vector=vector,
            individual=None,
            initial_decode_result=initial_decode,
            final_decode_result=final_decode,
            repair_result=repair_result,
            validation_result=None,
            fitness_evaluations=0,
            reason=reason,
        )

    # Đây là lần kiểm tra độc lập bắt buộc theo D058. Decoder hiện cũng có
    # validator cuối, nhưng population không được dựa vào giả định đó để bỏ
    # lớp bảo vệ trước Fitness.
    validation = validate_timetable(problem, final_decode.selected_options)
    if not validation.is_valid:
        return CandidateEvaluationResult(
            status=CandidateEvaluationStatus.VALIDATION_FAILED,
            input_vector=vector,
            individual=None,
            initial_decode_result=initial_decode,
            final_decode_result=final_decode,
            repair_result=repair_result,
            validation_result=validation,
            fitness_evaluations=0,
            reason=(
                "Validator độc lập từ chối lịch sau Decoder/Repair; "
                "Fitness không được gọi."
            ),
        )

    fitness = calculate_fitness(
        problem,
        final_decode.selected_options,
        option_domains,
    )
    repair_attempts = 0
    was_repaired = False
    if repair_result is not None:
        repair_attempts = repair_result.attempts
        was_repaired = repair_result.status == RepairStatus.REPAIRED

    individual = TimetableIndividual(
        vector=final_decode.repaired_vector,
        selected_options=final_decode.selected_options,
        selected_option_indices=final_decode.selected_option_indices,
        fitness=fitness,
        decode_nodes_explored=(
            initial_decode.nodes_explored
            + (repair_result.total_nodes_explored if repair_result else 0)
        ),
        decode_backtracks=(
            initial_decode.backtracks
            + (repair_result.total_backtracks if repair_result else 0)
        ),
        repair_attempts=repair_attempts,
        was_repaired=was_repaired,
    )

    return CandidateEvaluationResult(
        status=CandidateEvaluationStatus.SUCCESS,
        input_vector=vector,
        individual=individual,
        initial_decode_result=initial_decode,
        final_decode_result=final_decode,
        repair_result=repair_result,
        validation_result=validation,
        fitness_evaluations=1,
        reason="Vector đã qua Decoder/Repair, Validator và Fitness.",
    )


def initialize_population(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    population_size: int,
    max_initialization_attempts: int,
    seed: int,
    evaluation_config: CandidateEvaluationConfig,
) -> PopulationInitializationResult:
    """Sinh ngẫu nhiên đến khi có đủ N cá thể hợp lệ hoặc hết giới hạn.

    Cùng ``ProblemInstance``, miền option, cấu hình và seed sẽ tạo cùng chuỗi
    vector và cùng kết quả. Quần thể trả về giữ nguyên thứ tự cá thể được chấp
    nhận; ba thuật toán có thể nhận bản sao của cùng tuple này để bảo đảm so
    sánh công bằng.
    """

    if population_size < 1:
        raise ValueError("population_size phải lớn hơn hoặc bằng 1.")
    if max_initialization_attempts < population_size:
        raise ValueError(
            "max_initialization_attempts phải ít nhất bằng population_size."
        )
    _validate_option_domains(problem, option_domains)

    # D051 yêu cầu miền rỗng dừng trước khi khởi tạo. Chỉ khi phát hiện miền
    # rỗng mới gọi decoder với vector trung tính để nhận đúng nguyên nhân đã
    # được decoder chuẩn hóa; lần này không tính là một candidate attempt.
    if any(not domain for domain in option_domains):
        neutral_vector = tuple(0.5 for _ in range(problem.dimension))
        terminal = evaluate_candidate(
            problem,
            option_domains,
            neutral_vector,
            evaluation_config,
        )
        return PopulationInitializationResult(
            status=PopulationInitializationStatus.NO_OPTION,
            individuals=(),
            requested_population_size=population_size,
            candidate_attempts=0,
            fitness_evaluations=0,
            decode_failed_count=0,
            validation_failed_count=0,
            repaired_individual_count=0,
            failed_repair_count=0,
            total_repair_attempts=0,
            total_decode_nodes=0,
            total_decode_backtracks=0,
            terminal_evaluation=terminal,
            reason=terminal.reason,
        )

    rng = Random(seed)
    individuals: list[TimetableIndividual] = []
    candidate_attempts = 0
    fitness_evaluations = 0
    decode_failed_count = 0
    validation_failed_count = 0
    repaired_individual_count = 0
    failed_repair_count = 0
    total_repair_attempts = 0
    total_decode_nodes = 0
    total_decode_backtracks = 0
    last_evaluation: CandidateEvaluationResult | None = None

    while (
        len(individuals) < population_size
        and candidate_attempts < max_initialization_attempts
    ):
        vector = tuple(rng.random() for _ in range(problem.dimension))
        candidate_attempts += 1
        evaluation = evaluate_candidate(
            problem,
            option_domains,
            vector,
            evaluation_config,
        )
        last_evaluation = evaluation
        fitness_evaluations += evaluation.fitness_evaluations
        total_decode_nodes += evaluation.total_decode_nodes
        total_decode_backtracks += evaluation.total_decode_backtracks

        if evaluation.repair_result is not None:
            # Một lần gọi repair có thể thử nhiều thay đổi gene. Tổng số lần
            # thử phải được giữ riêng để đo đúng chi phí repair của khởi tạo.
            total_repair_attempts += evaluation.repair_result.attempts

            if evaluation.repair_result.status == RepairStatus.REPAIRED:
                repaired_individual_count += 1
            elif evaluation.repair_result.status == RepairStatus.FAILED:
                failed_repair_count += 1

        if evaluation.status == CandidateEvaluationStatus.NO_OPTION:
            # Trường hợp này về nguyên tắc đã bị preflight chặn. Nhánh bảo vệ
            # vẫn giữ để không tiếp tục run nếu miền bị thay đổi sai giữa chừng.
            return PopulationInitializationResult(
                status=PopulationInitializationStatus.NO_OPTION,
                individuals=tuple(individuals),
                requested_population_size=population_size,
                candidate_attempts=candidate_attempts,
                fitness_evaluations=fitness_evaluations,
                decode_failed_count=decode_failed_count,
                validation_failed_count=validation_failed_count,
                repaired_individual_count=repaired_individual_count,
                failed_repair_count=failed_repair_count,
                total_repair_attempts=total_repair_attempts,
                total_decode_nodes=total_decode_nodes,
                total_decode_backtracks=total_decode_backtracks,
                terminal_evaluation=evaluation,
                reason=evaluation.reason,
            )

        if evaluation.status == CandidateEvaluationStatus.DECODE_FAILED:
            decode_failed_count += 1
            continue
        if evaluation.status == CandidateEvaluationStatus.VALIDATION_FAILED:
            validation_failed_count += 1
            continue

        # SUCCESS luôn phải mang đúng một cá thể. Nếu hợp đồng nội bộ bị phá,
        # dừng rõ ràng thay vì âm thầm thêm None vào quần thể.
        if evaluation.individual is None:
            raise RuntimeError("Evaluation SUCCESS nhưng không có individual.")
        individuals.append(evaluation.individual)

    if len(individuals) == population_size:
        return PopulationInitializationResult(
            status=PopulationInitializationStatus.SUCCESS,
            individuals=tuple(individuals),
            requested_population_size=population_size,
            candidate_attempts=candidate_attempts,
            fitness_evaluations=fitness_evaluations,
            decode_failed_count=decode_failed_count,
            validation_failed_count=validation_failed_count,
            repaired_individual_count=repaired_individual_count,
            failed_repair_count=failed_repair_count,
            total_repair_attempts=total_repair_attempts,
            total_decode_nodes=total_decode_nodes,
            total_decode_backtracks=total_decode_backtracks,
            terminal_evaluation=None,
            reason="Đã tạo đủ quần thể ban đầu gồm các lịch hợp lệ.",
        )

    return PopulationInitializationResult(
        status=PopulationInitializationStatus.NO_FEASIBLE_SOLUTION_FOUND,
        individuals=tuple(individuals),
        requested_population_size=population_size,
        candidate_attempts=candidate_attempts,
        fitness_evaluations=fitness_evaluations,
        decode_failed_count=decode_failed_count,
        validation_failed_count=validation_failed_count,
        repaired_individual_count=repaired_individual_count,
        failed_repair_count=failed_repair_count,
        total_repair_attempts=total_repair_attempts,
        total_decode_nodes=total_decode_nodes,
        total_decode_backtracks=total_decode_backtracks,
        terminal_evaluation=last_evaluation,
        reason=(
            "Đã hết max_initialization_attempts nhưng chưa tạo đủ N cá thể "
            "hợp lệ; kết quả này không chứng minh bài toán vô nghiệm."
        ),
    )


def sort_individuals(
    individuals: Iterable[TimetableIndividual],
) -> tuple[TimetableIndividual, ...]:
    """Sắp xếp cá thể từ tốt đến kém theo Gate F và tie-break xác định.

    Vector chỉ được dùng khi ba score bằng nhau hoàn toàn. Nó không thay đổi
    thứ tự ưu tiên nghiệp vụ, mà chỉ giúp cùng dữ liệu luôn có cùng thứ tự để
    kiểm thử và tái lập kết quả.
    """

    return tuple(
        sorted(
            individuals,
            key=lambda individual: (
                individual.fitness_key,
                individual.vector,
            ),
        )
    )


def best_individual(
    individuals: Iterable[TimetableIndividual],
) -> TimetableIndividual:
    """Trả cá thể tốt nhất; từ chối tập rỗng để tránh che lỗi pipeline."""

    ordered = sort_individuals(individuals)
    if not ordered:
        raise ValueError("Không thể chọn cá thể tốt nhất từ quần thể rỗng.")
    return ordered[0]
