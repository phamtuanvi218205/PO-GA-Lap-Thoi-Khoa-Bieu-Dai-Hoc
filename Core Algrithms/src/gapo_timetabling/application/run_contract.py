"""Hợp đồng JSON dùng để thực thi GA, PO hoặc GA–PO trên cùng pipeline lịch.

Module này là lớp điều phối ở biên hệ thống. Nó đọc một yêu cầu chạy có phiên
bản, chuẩn bị snapshot, tạo đúng một quần thể ban đầu và chuyển quần thể đó cho
optimizer được chọn. Các công thức GA/PO, decoder, repair, validator và fitness
không được cài lại tại đây.

Hai phiên bản hợp đồng hiện hành:

* ``optimization-run-request.v1``: cấu hình đầu vào của một lần chạy;
* ``optimization-run-result.v2``: kết quả máy đọc được để CLI hoặc service
  Python lưu ``OptimizationRun`` và ``TimetableEntry``.

Core nhận một yêu cầu bất biến, chạy đồng bộ và trả một kết quả hoàn chỉnh hoặc
một mã lỗi xác định. Persistence nằm ở ``optimization_service``; CLI vẫn được
giữ để chạy độc lập và phục vụ tích hợp ngoài tiến trình khi cần.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from ..core.constraints import validate_timetable
from ..core.ga import GAConfig, run_ga
from ..core.hybrid import HybridConfig, run_hybrid
from ..core.metrics import (
    ConvergencePoint,
    OptimizationMetrics,
    OptimizationProgress,
    OptimizationProgressCallback,
    OptimizationResult,
)
from .run_control import OptimizationRunInterrupted
from ..core.models import OptimizationAlgorithm, ProblemInstance
from ..core.po import PoConfig, run_po
from ..core.population import (
    CandidateEvaluationConfig,
    PopulationInitializationProgress,
    PopulationInitializationStatus,
    TimetableIndividual,
    initialize_population,
)
from ..core.snapshot import PreparedSnapshot, prepare_snapshot_for_optimization


REQUEST_SCHEMA_VERSION = "optimization-run-request.v1"
RESULT_SCHEMA_VERSION = "optimization-run-result.v2"


class RunErrorCode(str, Enum):
    """Các mã lỗi ổn định để tầng điều phối không phải phân tích thông báo."""

    INVALID_REQUEST = "INVALID_REQUEST"
    SNAPSHOT_ERROR = "SNAPSHOT_ERROR"
    NO_OPTION = "NO_OPTION"
    NO_FEASIBLE_SOLUTION_FOUND = "NO_FEASIBLE_SOLUTION_FOUND"
    OPTIMIZER_ERROR = "OPTIMIZER_ERROR"
    INVALID_RESULT = "INVALID_RESULT"
    IO_ERROR = "IO_ERROR"


class RunContractError(ValueError):
    """Lỗi có mã phát sinh khi request JSON vi phạm hợp đồng phiên bản hóa."""

    def __init__(self, code: RunErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SnapshotReference:
    """Vị trí snapshot và checksum mà bên gọi kỳ vọng.

    Đường dẫn tương đối được giải theo thư mục chứa request JSON, không theo
    working directory của tiến trình. Quy tắc này cho phép tạo một thư mục làm
    việc riêng cho từng run mà không phụ thuộc nơi Python được khởi động.
    """

    path: Path
    checksum: str | None = None


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Cấu hình đã được kiểm tra của một lần chạy optimizer."""

    request_id: str
    algorithm: OptimizationAlgorithm
    snapshot: SnapshotReference
    population_size: int
    max_fitness_evaluations: int
    random_seed: int
    max_initialization_attempts: int
    max_offspring_attempts: int
    evaluation_config: CandidateEvaluationConfig
    tournament_size: int = 3
    crossover_probability: float = 0.9
    crossover_distribution_index: float = 15.0
    mutation_probability: float | None = None
    mutation_distribution_index: float = 20.0
    ga_ratio: float = 0.5


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    """Trả một JSON object hoặc báo đúng trường gây lỗi."""

    if not isinstance(value, Mapping):
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            f"{field_name} phải là một JSON object.",
        )
    return value


def _require_non_empty_string(value: Any, field_name: str) -> str:
    """Đọc chuỗi bắt buộc và loại giá trị chỉ chứa khoảng trắng."""

    if not isinstance(value, str) or not value.strip():
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            f"{field_name} phải là chuỗi không rỗng.",
        )
    return value.strip()


def _read_integer(
    value: Any,
    field_name: str,
    *,
    minimum: int | None = None,
) -> int:
    """Đọc số nguyên JSON, không chấp nhận ``true``/``false`` như 1/0."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            f"{field_name} phải là số nguyên.",
        )
    if minimum is not None and value < minimum:
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            f"{field_name} phải lớn hơn hoặc bằng {minimum}.",
        )
    return value


def _read_float(
    value: Any,
    field_name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    allow_none: bool = False,
) -> float | None:
    """Đọc tham số số thực và kiểm tra miền đóng khi được chỉ định."""

    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            f"{field_name} phải là một số.",
        )
    parsed = float(value)
    if not isfinite(parsed):
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            f"{field_name} phải là số hữu hạn.",
        )
    if minimum is not None and parsed < minimum:
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            f"{field_name} phải lớn hơn hoặc bằng {minimum}.",
        )
    if maximum is not None and parsed > maximum:
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            f"{field_name} phải nhỏ hơn hoặc bằng {maximum}.",
        )
    return parsed


def parse_run_request(
    payload: Mapping[str, Any],
    *,
    base_directory: Path,
) -> RunRequest:
    """Chuyển JSON object thành :class:`RunRequest` đã kiểm tra đầy đủ."""

    if payload.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            "schema_version phải là optimization-run-request.v1.",
        )

    request_id = _require_non_empty_string(payload.get("request_id"), "request_id")
    algorithm_text = _require_non_empty_string(payload.get("algorithm"), "algorithm")
    try:
        algorithm = OptimizationAlgorithm(algorithm_text)
    except ValueError as error:
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            "algorithm chỉ nhận GA, PO hoặc GA_PO.",
        ) from error

    snapshot_payload = _require_mapping(payload.get("snapshot"), "snapshot")
    snapshot_path_text = _require_non_empty_string(
        snapshot_payload.get("path"),
        "snapshot.path",
    )
    snapshot_path = Path(snapshot_path_text)
    if not snapshot_path.is_absolute():
        snapshot_path = (base_directory / snapshot_path).resolve()

    checksum = snapshot_payload.get("checksum")
    if checksum is not None:
        checksum = _require_non_empty_string(checksum, "snapshot.checksum").lower()
        if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
            raise RunContractError(
                RunErrorCode.INVALID_REQUEST,
                "snapshot.checksum phải là SHA-256 gồm 64 ký tự hexa.",
            )

    population_size = _read_integer(
        payload.get("population_size"),
        "population_size",
        minimum=1,
    )
    max_fitness_evaluations = _read_integer(
        payload.get("max_fitness_evaluations"),
        "max_fitness_evaluations",
        minimum=population_size,
    )
    remaining_fitness_evaluations = max_fitness_evaluations - population_size
    if remaining_fitness_evaluations % population_size != 0:
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            "Phần FE sau khởi tạo phải chia hết cho population_size.",
        )

    random_seed = _read_integer(payload.get("random_seed"), "random_seed")
    max_initialization_attempts = _read_integer(
        payload.get("max_initialization_attempts"),
        "max_initialization_attempts",
        minimum=population_size,
    )
    max_offspring_attempts = _read_integer(
        payload.get("max_offspring_attempts"),
        "max_offspring_attempts",
        minimum=1,
    )

    evaluation_payload = _require_mapping(payload.get("evaluation"), "evaluation")
    enable_repair = evaluation_payload.get("enable_repair", True)
    if not isinstance(enable_repair, bool):
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            "evaluation.enable_repair phải là boolean.",
        )
    max_repair_attempts = _read_integer(
        evaluation_payload.get("max_repair_attempts", 1 if enable_repair else 0),
        "evaluation.max_repair_attempts",
        minimum=1 if enable_repair else 0,
    )
    repair_node_limit = evaluation_payload.get(
        "max_decode_nodes_per_repair_attempt"
    )
    if repair_node_limit is not None:
        repair_node_limit = _read_integer(
            repair_node_limit,
            "evaluation.max_decode_nodes_per_repair_attempt",
            minimum=1,
        )

    evaluation_config = CandidateEvaluationConfig(
        max_decode_nodes=_read_integer(
            evaluation_payload.get("max_decode_nodes"),
            "evaluation.max_decode_nodes",
            minimum=1,
        ),
        enable_repair=enable_repair,
        max_repair_attempts=max_repair_attempts,
        max_decode_nodes_per_repair_attempt=repair_node_limit,
    )

    ga_payload = _require_mapping(payload.get("ga", {}), "ga")
    hybrid_payload = _require_mapping(payload.get("hybrid", {}), "hybrid")
    tournament_size = _read_integer(
        ga_payload.get("tournament_size", 3),
        "ga.tournament_size",
        minimum=2,
    )
    crossover_probability = _read_float(
        ga_payload.get("crossover_probability", 0.9),
        "ga.crossover_probability",
        minimum=0.0,
        maximum=1.0,
    )
    crossover_distribution_index = _read_float(
        ga_payload.get("crossover_distribution_index", 15.0),
        "ga.crossover_distribution_index",
        minimum=0.0000001,
    )
    mutation_probability = _read_float(
        ga_payload.get("mutation_probability"),
        "ga.mutation_probability",
        minimum=0.0,
        maximum=1.0,
        allow_none=True,
    )
    mutation_distribution_index = _read_float(
        ga_payload.get("mutation_distribution_index", 20.0),
        "ga.mutation_distribution_index",
        minimum=0.0000001,
    )
    ga_ratio = _read_float(
        hybrid_payload.get("ga_ratio", 0.5),
        "hybrid.ga_ratio",
        minimum=0.0000001,
        maximum=0.9999999,
    )

    if algorithm == OptimizationAlgorithm.GA_PO:
        number_of_ga_agents = int(round(population_size * ga_ratio))
        if not 1 <= number_of_ga_agents < population_size:
            raise RunContractError(
                RunErrorCode.INVALID_REQUEST,
                "hybrid.ga_ratio phải chia quần thể thành hai nhánh không rỗng.",
            )

    return RunRequest(
        request_id=request_id,
        algorithm=algorithm,
        snapshot=SnapshotReference(path=snapshot_path, checksum=checksum),
        population_size=population_size,
        max_fitness_evaluations=max_fitness_evaluations,
        random_seed=random_seed,
        max_initialization_attempts=max_initialization_attempts,
        max_offspring_attempts=max_offspring_attempts,
        evaluation_config=evaluation_config,
        tournament_size=tournament_size,
        crossover_probability=float(crossover_probability),
        crossover_distribution_index=float(crossover_distribution_index),
        mutation_probability=mutation_probability,
        mutation_distribution_index=float(mutation_distribution_index),
        ga_ratio=float(ga_ratio),
    )


def load_run_request(path: Path) -> RunRequest:
    """Đọc request UTF-8 từ đĩa và giải đường dẫn snapshot tương đối."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunContractError(
            RunErrorCode.INVALID_REQUEST,
            f"Không thể đọc request JSON: {error}",
        ) from error
    return parse_run_request(
        _require_mapping(payload, "request"),
        base_directory=path.resolve().parent,
    )


def _run_optimizer(
    request: RunRequest,
    problem: ProblemInstance,
    option_domains,
    initialization,
    progress_callback: OptimizationProgressCallback | None = None,
) -> OptimizationResult:
    """Chọn optimizer theo request nhưng giữ chung input và quần thể khởi tạo."""

    common = {
        "max_fitness_evaluations": request.max_fitness_evaluations,
        "max_offspring_attempts": request.max_offspring_attempts,
        "seed": request.random_seed,
        "evaluation_config": request.evaluation_config,
    }
    if request.algorithm == OptimizationAlgorithm.GA:
        return run_ga(
            problem,
            option_domains,
            initialization,
            GAConfig(
                **common,
                tournament_size=request.tournament_size,
                crossover_probability=request.crossover_probability,
                crossover_distribution_index=request.crossover_distribution_index,
                mutation_probability=request.mutation_probability,
                mutation_distribution_index=request.mutation_distribution_index,
            ),
            progress_callback=progress_callback,
        )
    if request.algorithm == OptimizationAlgorithm.PO:
        return run_po(
            problem,
            option_domains,
            initialization,
            PoConfig(**common),
            progress_callback=progress_callback,
        )
    return run_hybrid(
        problem,
        option_domains,
        initialization,
        HybridConfig(
            **common,
            ga_ratio=request.ga_ratio,
            tournament_size=request.tournament_size,
            crossover_probability=request.crossover_probability,
            crossover_distribution_index=request.crossover_distribution_index,
            mutation_probability=request.mutation_probability,
            mutation_distribution_index=request.mutation_distribution_index,
        ),
        progress_callback=progress_callback,
    )


def _json_value(value: Any) -> Any:
    """Chuyển dataclass, Enum, tuple và date thành dữ liệu JSON thuần."""

    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def build_failure_result(
    request: RunRequest | None,
    code: RunErrorCode,
    message: str,
    *,
    details: Any = None,
    snapshot_checksum: str | None = None,
) -> dict[str, Any]:
    """Tạo một kết quả lỗi có cùng envelope cho mọi giai đoạn thất bại."""

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "request_id": request.request_id if request is not None else None,
        "status": "FAILED",
        "algorithm": request.algorithm.value if request is not None else None,
        "snapshot_checksum": snapshot_checksum,
        "error": {
            "code": code.value,
            "message": message,
            "details": _json_value(details),
        },
        "result": None,
    }


def build_completed_result_payload(
    *,
    request_id: str,
    algorithm_name: str,
    prepared: PreparedSnapshot,
    best_individual: TimetableIndividual,
    metrics: OptimizationMetrics,
    convergence_history: tuple[ConvergencePoint, ...],
) -> dict[str, Any]:
    """Chuẩn hóa một lịch hợp lệ thành envelope kết quả máy đọc được.

    Helper được dùng chung bởi ba optimizer và baseline thực nghiệm để không
    sao chép quy tắc ánh xạ ``SessionOption`` thành ``TimetableEntry``. Tên
    thuật toán là chuỗi vì baseline không phải một giá trị được persistence
    production ghi vào ``OptimizationRun``.
    """

    sessions = {
        session.session_index: session
        for session in prepared.problem.class_sessions
    }
    locations = {
        location.location_index: location
        for location in prepared.problem.locations
    }
    lecturers = {
        lecturer.lecturer_index: lecturer
        for lecturer in prepared.problem.lecturers
    }
    timetable_entries = []
    for option in best_individual.selected_options:
        session = sessions[option.session_index]
        location = locations[option.location_index]
        timetable_entries.append({
            "class_session_id": session.class_session_id,
            "lecturer_code": lecturers[
                prepared.problem.option_lecturer_index(option)
            ].lecturer_code,
            "term_code": prepared.problem.term.term_code,
            "teaching_date": option.teaching_date.isoformat(),
            "location_id": location.location_id,
            "location_type": location.location_type.value,
            "start_period": option.start_period,
            "end_period": option.end_period,
        })
    timetable_entries.sort(key=lambda item: item["class_session_id"])

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "request_id": request_id,
        "status": "COMPLETED",
        "algorithm": algorithm_name,
        "snapshot_checksum": prepared.snapshot_checksum,
        "error": None,
        "result": {
            "gene_option_mapping": prepared.gene_option_mapping,
            "gene_option_mapping_checksum": prepared.gene_option_mapping_checksum,
            "best_solution": {
                "vector": list(best_individual.vector),
                "selected_option_indices": list(
                    best_individual.selected_option_indices
                ),
            },
            "best_fitness": {
                "general_quality_score": (
                    best_individual.fitness.general_quality_score
                ),
                "lecturer_preference_score": (
                    best_individual.fitness.lecturer_preference_score
                ),
                "breakdown": _json_value(
                    asdict(best_individual.fitness.breakdown)
                ),
            },
            "metrics": _json_value(asdict(metrics)),
            "convergence_history": [
                _json_value(asdict(point))
                for point in convergence_history
            ],
            "timetable_entries": timetable_entries,
        },
    }


def execute_run_request(request: RunRequest) -> dict[str, Any]:
    """Thực thi một request đồng bộ và luôn trả envelope kết quả JSON."""

    try:
        prepared = prepare_snapshot_for_optimization(
            request.snapshot.path,
            expected_checksum=request.snapshot.checksum,
        )
    except (OSError, TypeError, ValueError) as error:
        return build_failure_result(request, RunErrorCode.SNAPSHOT_ERROR, str(error))

    return execute_prepared_run_request(request, prepared)


def execute_prepared_run_request(
    request: RunRequest,
    prepared: PreparedSnapshot,
    *,
    progress_callback: OptimizationProgressCallback | None = None,
) -> dict[str, Any]:
    """Chạy optimizer từ snapshot đã được Python build và preflight.

    Hàm này giúp ứng dụng thống nhất không phải ghi snapshot ra file rồi đọc
    lại. ``execute_run_request`` vẫn gọi cùng hàm nên CLI và database service
    không thể lệch logic tối ưu.
    """

    if not prepared.is_ready:
        return build_failure_result(
            request,
            RunErrorCode.NO_OPTION,
            "Có ClassSession không có SessionOption hợp lệ.",
            details=[asdict(issue) for issue in prepared.no_option_issues],
            snapshot_checksum=prepared.snapshot_checksum,
        )

    def report_initialization(
        progress: PopulationInitializationProgress,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(OptimizationProgress(
            algorithm=request.algorithm,
            iteration=0,
            max_iterations=0,
            max_fitness_evaluations=request.max_fitness_evaluations,
            metrics=OptimizationMetrics(
                completed_iterations=0,
                candidate_attempts=progress.candidate_attempts,
                fitness_evaluations=progress.fitness_evaluations,
                decode_failed_count=progress.decode_failed_count,
                validation_failed_count=progress.validation_failed_count,
                repaired_individual_count=progress.repaired_individual_count,
                failed_repair_count=progress.failed_repair_count,
                total_repair_attempts=progress.total_repair_attempts,
                discarded_offspring_count=0,
                total_decode_nodes=progress.total_decode_nodes,
                total_decode_backtracks=progress.total_decode_backtracks,
                runtime_seconds=0.0,
            ),
            best_general_quality_score=progress.best_general_quality_score,
            best_lecturer_preference_score=(
                progress.best_lecturer_preference_score
            ),
        ))

    initialization = initialize_population(
        prepared.problem,
        prepared.option_domains,
        population_size=request.population_size,
        max_initialization_attempts=request.max_initialization_attempts,
        seed=request.random_seed,
        evaluation_config=request.evaluation_config,
        progress_callback=report_initialization,
    )
    if initialization.status != PopulationInitializationStatus.SUCCESS:
        code = (
            RunErrorCode.NO_OPTION
            if initialization.status == PopulationInitializationStatus.NO_OPTION
            else RunErrorCode.NO_FEASIBLE_SOLUTION_FOUND
        )
        return build_failure_result(
            request,
            code,
            initialization.reason,
            details={
                "candidate_attempts": initialization.candidate_attempts,
                "fitness_evaluations": initialization.fitness_evaluations,
                "decode_failed_count": initialization.decode_failed_count,
                "validation_failed_count": initialization.validation_failed_count,
            },
            snapshot_checksum=prepared.snapshot_checksum,
        )

    try:
        optimization_result = _run_optimizer(
            request,
            prepared.problem,
            prepared.option_domains,
            initialization,
            progress_callback,
        )
    except OptimizationRunInterrupted:
        raise
    except (RuntimeError, ValueError) as error:
        return build_failure_result(
            request,
            RunErrorCode.OPTIMIZER_ERROR,
            str(error),
            snapshot_checksum=prepared.snapshot_checksum,
        )

    validation = validate_timetable(
        prepared.problem,
        optimization_result.best_individual.selected_options,
    )
    if not validation.is_valid:
        return build_failure_result(
            request,
            RunErrorCode.INVALID_RESULT,
            "Nghiệm tốt nhất còn vi phạm điều kiện bắt buộc.",
            details=[asdict(violation) for violation in validation.violations],
            snapshot_checksum=prepared.snapshot_checksum,
        )

    return build_completed_result_payload(
        request_id=request.request_id,
        algorithm_name=optimization_result.algorithm.value,
        prepared=prepared,
        best_individual=optimization_result.best_individual,
        metrics=optimization_result.metrics,
        convergence_history=optimization_result.convergence_history,
    )


def write_result_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Ghi kết quả UTF-8 vào file kết quả của một run độc lập."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
