"""Tạo và khóa PlanningScenario hoàn toàn trong runtime Python."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from uuid import uuid4

from .database import ConnectionProtocol, fetch_all_dicts, fetch_one_dict
from ..core.models import (
    PlanningScenarioStatus,
    ScenarioScopeType,
    TeachingPlanStatus,
)
from .planning import (
    AutomaticScenarioRequest,
    PlanningScenarioCandidatePlanner,
    ScenarioPlanCandidate,
)
from .planning_persistence import TeachingPlanPersistenceService


@dataclass(frozen=True, slots=True)
class PersistedPlanningScenario:
    """Thông tin scenario sau khi điều phối và kiểm tra cấu trúc."""

    scenario_id: int
    scenario_code: str
    term_code: str
    scope_type: ScenarioScopeType
    status: PlanningScenarioStatus
    candidate_rank: int
    plan_rank_penalty: int
    note: str


class PlanningScenarioOrchestrationService:
    """Sinh hữu hạn scenario, kiểm tra dữ liệu và khóa scenario hợp lệ."""

    SYSTEM_ACTOR = "SYSTEM"

    def __init__(
        self,
        connection: ConnectionProtocol,
        *,
        plan_service: TeachingPlanPersistenceService | None = None,
        candidate_planner: PlanningScenarioCandidatePlanner | None = None,
    ) -> None:
        self._connection = connection
        self._plan_service = plan_service or TeachingPlanPersistenceService(connection)
        self._candidate_planner = candidate_planner or PlanningScenarioCandidatePlanner()

    def create_and_lock_candidates(
        self, request: AutomaticScenarioRequest
    ) -> tuple[PersistedPlanningScenario, ...]:
        """Tạo scenario DRAFT, xác nhận READY rồi khóa tự động khi hợp lệ."""

        cursor = self._connection.cursor()
        term = fetch_one_dict(cursor.execute(
            "SELECT term_code FROM AcademicTerm WHERE term_code = ?",
            request.term_code,
        ))
        if term is None:
            raise ValueError(f"Không tìm thấy học kỳ {request.term_code}.")

        parts = self._load_parts(request)
        if not parts:
            raise RuntimeError("Phạm vi scenario không có TeachingPart nào.")

        candidates_by_part: dict[int, tuple[ScenarioPlanCandidate, ...]] = {}
        for part in parts:
            part_id = int(part["teaching_part_id"])
            current_plans = self._plan_service.ensure_current_plans(part_id)
            candidates = tuple(
                ScenarioPlanCandidate(
                    teaching_part_id=part_id,
                    teaching_plan_id=plan.teaching_plan_id,
                    candidate_rank=plan.candidate_rank,
                    intensive=plan.allows_intensive,
                )
                for plan in current_plans
                if plan.status == TeachingPlanStatus.VALID
            )
            if not candidates:
                raise RuntimeError(
                    f"TeachingPart {part['part_code']} không có plan VALID hiện hành."
                )
            candidates_by_part[part_id] = candidates

        selections = self._candidate_planner.generate(
            candidates_by_part, request.max_scenario_candidates
        )
        batch_code = self._build_batch_code(request.term_code)
        created_at = datetime.now()
        results: list[PersistedPlanningScenario] = []

        for selection in selections:
            scenario_code = f"{batch_code}_V{selection.candidate_rank:02d}"
            inserted = fetch_one_dict(cursor.execute(
                """
                INSERT INTO PlanningScenario(
                    scenario_code, scenario_name, term_code, scope_type,
                    status, scenario_batch_code, candidate_rank,
                    plan_rank_penalty, created_by, created_at, note
                )
                OUTPUT INSERTED.scenario_id
                VALUES (?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?)
                """,
                scenario_code,
                f"Tự động {request.term_code} - phương án {selection.candidate_rank:02d}",
                request.term_code,
                request.scope_type.value,
                batch_code,
                selection.candidate_rank,
                selection.plan_rank_penalty,
                self.SYSTEM_ACTOR,
                created_at,
                "Scenario được hệ thống tạo tự động từ các plan VALID.",
            ))
            if inserted is None:
                raise RuntimeError("SQL Server không trả về scenario_id vừa tạo.")
            scenario_id = int(inserted["scenario_id"])
            cursor.executemany(
                """
                INSERT INTO PlanningScenarioItem(
                    scenario_id, teaching_part_id, teaching_plan_id
                ) VALUES (?, ?, ?)
                """,
                [
                    (
                        scenario_id,
                        candidate.teaching_part_id,
                        candidate.teaching_plan_id,
                    )
                    for candidate in selection.plans
                ],
            )

            try:
                self._validate_structure(
                    scenario_id,
                    request.term_code,
                    expected_part_count=len(parts),
                )
                cursor.execute(
                    "UPDATE PlanningScenario SET status = 'READY' WHERE scenario_id = ?",
                    scenario_id,
                )
                locked_at = datetime.now()
                note = (
                    "Đã tự kiểm tra đủ plan/session và khóa dữ liệu. "
                    "Miền SessionOption được kiểm tra ở bước tạo snapshot/encoder."
                )
                cursor.execute(
                    """
                    UPDATE PlanningScenario
                    SET status = 'LOCKED', locked_by = ?, locked_at = ?, note = ?
                    WHERE scenario_id = ?
                    """,
                    self.SYSTEM_ACTOR,
                    locked_at,
                    note,
                    scenario_id,
                )
                status = PlanningScenarioStatus.LOCKED
            except RuntimeError as exception:
                note = f"Không thể khóa tự động: {exception}"
                cursor.execute(
                    """
                    UPDATE PlanningScenario
                    SET status = 'DRAFT', locked_by = NULL, locked_at = NULL,
                        note = ?
                    WHERE scenario_id = ?
                    """,
                    note,
                    scenario_id,
                )
                status = PlanningScenarioStatus.DRAFT

            results.append(PersistedPlanningScenario(
                scenario_id=scenario_id,
                scenario_code=scenario_code,
                term_code=request.term_code,
                scope_type=request.scope_type,
                status=status,
                candidate_rank=selection.candidate_rank,
                plan_rank_penalty=selection.plan_rank_penalty,
                note=note,
            ))

        return tuple(results)

    def _load_parts(self, request: AutomaticScenarioRequest) -> list[dict[str, object]]:
        cursor = self._connection.cursor()
        if request.scope_type == ScenarioScopeType.FULL_TERM:
            return fetch_all_dicts(cursor.execute(
                """
                SELECT p.teaching_part_id, p.part_code, s.term_code, s.status
                FROM TeachingPart AS p
                JOIN CourseSection AS s ON s.section_code = p.section_code
                WHERE s.term_code = ? AND s.status = 'APPROVED'
                ORDER BY p.part_code
                """,
                request.term_code,
            ))

        part_ids = tuple(sorted(request.teaching_part_ids))
        placeholders = ",".join("?" for _ in part_ids)
        rows = fetch_all_dicts(cursor.execute(
            f"""
            SELECT p.teaching_part_id, p.part_code, s.term_code, s.status
            FROM TeachingPart AS p
            JOIN CourseSection AS s ON s.section_code = p.section_code
            WHERE p.teaching_part_id IN ({placeholders})
            ORDER BY p.part_code
            """,
            *part_ids,
        ))
        if len(rows) != len(part_ids):
            raise ValueError("Có TeachingPart trong SUBSET không tồn tại.")
        for part in rows:
            if str(part["term_code"]) != request.term_code:
                raise ValueError(
                    f"TeachingPart {part['part_code']} không thuộc học kỳ yêu cầu."
                )
            if str(part["status"]) == "CANCELLED":
                raise ValueError(
                    "Không thể xếp TeachingPart của lớp học phần đã hủy: "
                    f"{part['part_code']}."
                )
        return rows

    def _validate_structure(
        self, scenario_id: int, term_code: str, expected_part_count: int
    ) -> None:
        rows = fetch_all_dicts(self._connection.cursor().execute(
            """
            SELECT item.teaching_part_id, item.teaching_plan_id,
                   part.total_periods, selected_plan.plan_code,
                   selected_plan.status,
                   selected_plan.teaching_part_id AS plan_part_id,
                   session.session_number, session.term_code AS session_term_code,
                   session.duration_periods
            FROM PlanningScenarioItem AS item
            JOIN TeachingPart AS part
              ON part.teaching_part_id = item.teaching_part_id
            JOIN TeachingPlan AS selected_plan
              ON selected_plan.teaching_plan_id = item.teaching_plan_id
            LEFT JOIN ClassSession AS session
              ON session.teaching_plan_id = selected_plan.teaching_plan_id
            WHERE item.scenario_id = ?
            ORDER BY item.teaching_part_id, session.session_number
            """,
            scenario_id,
        ))
        if not rows:
            raise RuntimeError("Scenario chưa chọn plan nào.")

        grouped: dict[int, list[dict[str, object]]] = {}
        for row in rows:
            grouped.setdefault(int(row["teaching_part_id"]), []).append(row)
        if len(grouped) != expected_part_count:
            raise RuntimeError(
                "Scenario không bao phủ đúng toàn bộ TeachingPart trong phạm vi yêu cầu."
            )

        for part_id, part_rows in grouped.items():
            first = part_rows[0]
            if str(first["status"]) != TeachingPlanStatus.VALID.value:
                raise RuntimeError("Scenario chỉ được chọn TeachingPlan VALID.")
            if int(first["plan_part_id"]) != part_id:
                raise RuntimeError("TeachingPlan không thuộc TeachingPart tương ứng.")
            if first["session_number"] is None:
                raise RuntimeError(f"Plan {first['plan_code']} chưa có ClassSession.")

            total_periods = 0
            for expected_number, row in enumerate(part_rows, start=1):
                if int(row["session_number"]) != expected_number:
                    raise RuntimeError("Session number của plan không liên tục.")
                if str(row["session_term_code"]) != term_code:
                    raise RuntimeError("ClassSession không thuộc học kỳ của scenario.")
                total_periods += int(row["duration_periods"])
            if total_periods != int(first["total_periods"]):
                raise RuntimeError(
                    f"Plan {first['plan_code']} không đủ tổng tiết của TeachingPart."
                )

    @staticmethod
    def _build_batch_code(term_code: str) -> str:
        normalized = re.sub(r"[^A-Z0-9]+", "_", term_code.upper()).strip("_")[:8]
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        random_suffix = uuid4().hex[:6].upper()
        return f"AUTO_{normalized}_{timestamp}_{random_suffix}"
