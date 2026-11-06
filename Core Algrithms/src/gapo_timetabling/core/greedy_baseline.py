"""Baseline tham lam xác định cho thực nghiệm thời khóa biểu.

Baseline này không tạo quần thể và không lặp tối ưu. Nó phân công lần lượt
những lớp khó trước, ưu tiên giảng viên đang có tải thấp và có độ phù hợp môn
cao, sau đó giao một vector ưu tiên xác định cho decoder. Decoder vẫn chịu
trách nhiệm kiến tạo mẫu lịch hợp lệ theo priority để mọi phương pháp
dùng chung decoder hard-only. Baseline không lặp tiến hóa và decoder không
chấm điểm mềm để chọn vị trí; fitness chỉ đánh giá lịch hoàn chỉnh.

Mục đích của baseline là tạo một mốc ``first feasible`` dễ giải thích. Nó
không phải đối thủ có cùng ngân sách FE với GA, PO hoặc GA–PO và không được
đưa vào kiểm định nhiều seed như ba optimizer ngẫu nhiên.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from time import perf_counter

from .encoder import build_recurring_patterns_for_group
from .metrics import (
    ConvergencePoint,
    OptimizationMetrics,
    accumulate_candidate_evaluation,
)
from .models import ProblemInstance, SessionOption
from .population import (
    CandidateEvaluationConfig,
    CandidateEvaluationResult,
    CandidateEvaluationStatus,
    TimetableIndividual,
    evaluate_candidate,
)


GREEDY_BASELINE_NAME = "GREEDY_FIRST_FEASIBLE"


class GreedyBaselineStatus(str, Enum):
    """Trạng thái kết thúc của một lần dựng lịch baseline."""

    COMPLETED = "COMPLETED"
    NO_FEASIBLE_ASSIGNMENT = "NO_FEASIBLE_ASSIGNMENT"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"


@dataclass(frozen=True, slots=True)
class GreedyBaselineResult:
    """Kết quả baseline cùng số liệu tương thích với báo cáo optimizer."""

    status: GreedyBaselineStatus
    vector: tuple[float, ...]
    individual: TimetableIndividual | None
    evaluation: CandidateEvaluationResult | None
    metrics: OptimizationMetrics
    convergence_history: tuple[ConvergencePoint, ...]
    reason: str

    @property
    def is_success(self) -> bool:
        return self.status == GreedyBaselineStatus.COMPLETED


def _empty_metrics() -> OptimizationMetrics:
    return OptimizationMetrics(
        completed_iterations=0,
        candidate_attempts=0,
        fitness_evaluations=0,
        decode_failed_count=0,
        validation_failed_count=0,
        repaired_individual_count=0,
        failed_repair_count=0,
        total_repair_attempts=0,
        discarded_offspring_count=0,
        total_decode_nodes=0,
        total_decode_backtracks=0,
        runtime_seconds=0.0,
    )


def _section_periods(problem: ProblemInstance) -> dict[str, int]:
    """Tổng khối lượng của mỗi lớp dùng để kiểm giới hạn tải giảng viên."""

    totals = {code: 0 for code in problem.assignment_keys}
    for part in problem.teaching_parts:
        key = problem.assignment_key_for_part(part)
        if key in totals:
            totals[key] += part.total_periods
    return totals


def _group_sections(problem: ProblemInstance) -> tuple[str, ...]:
    """Ánh xạ mỗi gene lịch lặp về lớp học phần nguồn."""

    plans = {
        plan.teaching_plan_id: plan for plan in problem.teaching_plans
    }
    sections: list[str] = []
    for session_indices in problem.schedule_groups:
        first_session = problem.class_sessions[session_indices[0]]
        plan = plans[first_session.teaching_plan_id]
        sections.append(
            problem.assignment_key_for_part(problem.teaching_parts[plan.teaching_part_index])
        )
    return tuple(sections)


def _capability_scores(
    problem: ProblemInstance,
) -> dict[tuple[int, str], float]:
    """Đưa điểm phù hợp về khóa giảng viên–môn để tie-break xác định."""

    return {
        (item.lecturer_index, item.course_code): item.suitability_score
        for item in problem.lecturer_course_capabilities
    }


def build_greedy_vector(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
) -> tuple[float, ...]:
    """Tạo một vector ưu tiên xác định mà không gọi fitness.

    Lớp có ít giảng viên hợp lệ hơn và nhiều tiết hơn được phân trước. Với
    từng lớp, baseline chỉ xét người có ít nhất một recurring pattern cho mọi
    nhóm lịch của lớp và không vượt tải tối đa. Khóa chọn là tải hiện tại thấp
    nhất, điểm phù hợp môn cao nhất rồi ``lecturer_index`` nhỏ nhất.

    Các gene lịch bằng 0: tie-break theo ClassSession ID xác định thứ tự xếp.
    Decoder chọn vị trí theo thứ–tiết–phòng và chỉ quay lui để bảo đảm hard.
    """

    if len(option_domains) != problem.session_dimension:
        raise ValueError("Số miền option phải bằng số ClassSession.")

    # Snapshot v1 không có gene phân công; khóa lịch bằng nhau dùng ID để
    # quyết định thứ tự, giữ nguyên người đã gán trong snapshot.
    if not problem.assignment_keys:
        return tuple(0.0 for _ in range(problem.dimension))

    periods = _section_periods(problem)
    group_sections = _group_sections(problem)
    lecturers = {
        item.lecturer_index: item for item in problem.lecturers
    }
    sections = {
        key: next(item for item in problem.course_sections if item.section_code == problem.parts_for_assignment(key)[0].section_code)
        for key in problem.assignment_keys
    }
    suitability = _capability_scores(problem)
    loads = {index: 0 for index in lecturers}
    selected: dict[str, int] = {}

    ordered_sections = sorted(
        problem.assignment_keys,
        key=lambda code: (
            len(problem.eligible_assignment_lecturers(code)),
            -periods[code],
            code,
        ),
    )

    # Cache điều kiện độc lập với tải để không dựng lại recurring pattern ở
    # mọi nhánh backtracking. Baseline vẫn chỉ dùng dữ liệu hard constraint;
    # suitability chỉ là tie-break xác định, không phải fitness tối ưu.
    feasible_lecturers: dict[str, tuple[int, ...]] = {}
    for section_code in ordered_sections:
        relevant_groups = tuple(
            index
            for index, code in enumerate(group_sections)
            if code == section_code
        )
        feasible_lecturers[section_code] = tuple(
            lecturer_index
            for lecturer_index in problem.eligible_assignment_lecturers(section_code)
            if all(
                build_recurring_patterns_for_group(
                    problem,
                    option_domains,
                    group_index,
                    lecturer_index,
                )
                for group_index in relevant_groups
            )
        )
        if not feasible_lecturers[section_code]:
            raise ValueError(
                f"Lớp {section_code} không có giảng viên nào vừa đủ năng "
                "lực vừa có mẫu lịch khả dụng."
            )

    def assign_section(position: int) -> bool:
        """Tìm phân công tải hợp lệ đầu tiên theo thứ tự tham lam xác định."""

        if position == len(ordered_sections):
            return True

        section_code = ordered_sections[position]
        section_periods = periods[section_code]
        course_code = sections[section_code].course_code
        candidate_indices = sorted(
            feasible_lecturers[section_code],
            key=lambda lecturer_index: (
                loads[lecturer_index],
                -suitability.get((lecturer_index, course_code), 1.0),
                lecturer_index,
            ),
        )
        for lecturer_index in candidate_indices:
            lecturer = lecturers[lecturer_index]
            projected_load = loads[lecturer_index] + section_periods
            if (
                lecturer.max_teaching_periods is not None
                and projected_load > lecturer.max_teaching_periods
            ):
                continue

            selected[section_code] = lecturer_index
            loads[lecturer_index] = projected_load
            if assign_section(position + 1):
                return True
            loads[lecturer_index] -= section_periods
            del selected[section_code]
        return False

    if not assign_section(0):
        raise ValueError(
            "Không tồn tại phân công giảng viên thỏa đồng thời năng lực, "
            "mẫu lịch khả dụng và tải giảng dạy tối đa."
        )

    assignment_genes: list[float] = []
    for section_code in problem.assignment_keys:
        eligible = problem.eligible_assignment_lecturers(section_code)
        selected_position = eligible.index(selected[section_code])
        assignment_genes.append(
            (selected_position + 0.5) / len(eligible)
        )

    return tuple(assignment_genes) + tuple(
        0.0 for _ in range(problem.dimension - problem.assignment_dimension)
    )


def run_greedy_first_feasible(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    evaluation_config: CandidateEvaluationConfig,
) -> GreedyBaselineResult:
    """Dựng và đánh giá đúng một lịch tham lam xác định."""

    started_at = perf_counter()
    metrics = _empty_metrics()
    try:
        vector = build_greedy_vector(problem, option_domains)
    except ValueError as error:
        return GreedyBaselineResult(
            status=GreedyBaselineStatus.NO_FEASIBLE_ASSIGNMENT,
            vector=(),
            individual=None,
            evaluation=None,
            metrics=replace(
                metrics,
                runtime_seconds=perf_counter() - started_at,
            ),
            convergence_history=(),
            reason=str(error),
        )

    evaluation = evaluate_candidate(
        problem,
        option_domains,
        vector,
        evaluation_config,
    )
    metrics = accumulate_candidate_evaluation(metrics, evaluation)
    metrics = replace(
        metrics,
        runtime_seconds=perf_counter() - started_at,
    )
    if (
        evaluation.status != CandidateEvaluationStatus.SUCCESS
        or evaluation.individual is None
    ):
        return GreedyBaselineResult(
            status=GreedyBaselineStatus.CANDIDATE_REJECTED,
            vector=vector,
            individual=None,
            evaluation=evaluation,
            metrics=metrics,
            convergence_history=(),
            reason=evaluation.reason,
        )

    individual = evaluation.individual
    history = (ConvergencePoint(
        iteration=0,
        fitness_evaluations=metrics.fitness_evaluations,
        general_quality_score=individual.fitness.general_quality_score,
        lecturer_preference_score=(
            individual.fitness.lecturer_preference_score
        ),
    ),)
    return GreedyBaselineResult(
        status=GreedyBaselineStatus.COMPLETED,
        vector=vector,
        individual=individual,
        evaluation=evaluation,
        metrics=metrics,
        convergence_history=history,
        reason="Đã dựng lịch tham lam hợp lệ đầu tiên mà không lặp tối ưu.",
    )
