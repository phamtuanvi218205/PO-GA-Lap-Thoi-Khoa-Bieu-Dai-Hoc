"""Lưu TeachingPlan và ClassSession bằng Python thay cho Spring/JPA.

Service làm việc trên một transaction do tầng gọi quản lý. Quy tắc nghiệp vụ
được giữ nguyên: cùng generation key thì tái sử dụng dữ liệu đã kiểm chứng;
khi rule thay đổi, một generation mới được tạo và generation cũ chỉ bị
``RETIRED`` nếu không được scenario ``LOCKED`` tham chiếu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from .database import ConnectionProtocol, fetch_all_dicts, fetch_one_dict
from ..core.models import LocationType, TeachingPlanStatus
from .planning import (
    SessionExpander,
    TeachingPlanGenerationRequest,
    TeachingPlanGenerator,
    create_plan_generation_key,
)


@dataclass(frozen=True, slots=True)
class PersistedTeachingPlan:
    """Thông tin plan cần cho scenario orchestration và snapshot builder."""

    teaching_plan_id: int
    teaching_part_id: int
    plan_code: str
    plan_name: str
    status: TeachingPlanStatus
    allows_intensive: bool
    generation_no: int
    candidate_rank: int
    generation_key: str


class TeachingPlanPersistenceService:
    """Điều phối luồng từ dữ liệu rời rạc đến plan/session đã lưu."""

    def __init__(
        self,
        connection: ConnectionProtocol,
        *,
        generator: TeachingPlanGenerator | None = None,
        expander: SessionExpander | None = None,
    ) -> None:
        self._connection = connection
        self._generator = generator or TeachingPlanGenerator()
        self._expander = expander or SessionExpander()

    def ensure_current_plans(
        self, teaching_part_id: int
    ) -> tuple[PersistedTeachingPlan, ...]:
        """Trả generation hiện hành hoặc sinh và lưu generation mới."""

        cursor = self._connection.cursor()
        part = fetch_one_dict(cursor.execute(
            """
            SELECT p.teaching_part_id, p.part_code, p.part_type, p.total_periods,
                   p.required_location_type, s.term_code
            FROM TeachingPart AS p
            JOIN CourseSection AS s ON s.section_code = p.section_code
            WHERE p.teaching_part_id = ?
            """,
            teaching_part_id,
        ))
        if part is None:
            raise ValueError(f"Không tìm thấy TeachingPart {teaching_part_id}.")

        rule = fetch_one_dict(cursor.execute(
            """
            SELECT start_week_number, end_week_number, max_sessions_per_week,
                   allows_intensive, max_candidate_plans
            FROM TeachingPlanGenerationRule
            WHERE teaching_part_id = ? AND is_active = 1
            """,
            teaching_part_id,
        ))
        if rule is None:
            raise RuntimeError(
                f"TeachingPart {part['part_code']} chưa có rule sinh plan đang hoạt động."
            )

        duration_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT duration_periods
            FROM TeachingDurationRule
            WHERE part_type = ?
            ORDER BY duration_periods
            """,
            part["part_type"],
        ))
        allowed_durations = tuple(sorted({int(row["duration_periods"]) for row in duration_rows}))
        if not allowed_durations:
            raise RuntimeError(
                f"Loại phần {part['part_type']} chưa có TeachingDurationRule."
            )

        week_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT week_number FROM TermWeek
            WHERE term_code = ? ORDER BY week_number
            """,
            part["term_code"],
        ))
        available_weeks = {int(row["week_number"]) for row in week_rows}
        for week_number in range(
            int(rule["start_week_number"]), int(rule["end_week_number"]) + 1
        ):
            if week_number not in available_weeks:
                raise RuntimeError(
                    f"Học kỳ {part['term_code']} thiếu TermWeek {week_number}."
                )

        generation_key = create_plan_generation_key(
            term_code=str(part["term_code"]),
            part_code=str(part["part_code"]),
            part_type=str(part["part_type"]),
            total_periods=int(part["total_periods"]),
            required_location_type=str(part["required_location_type"]),
            start_week_number=int(rule["start_week_number"]),
            end_week_number=int(rule["end_week_number"]),
            max_sessions_per_week=int(rule["max_sessions_per_week"]),
            allows_intensive=bool(rule["allows_intensive"]),
            max_candidate_plans=int(rule["max_candidate_plans"]),
            allowed_durations=allowed_durations,
        )
        existing = self._load_generation(teaching_part_id, generation_key)
        if existing:
            self._validate_persisted_generation(existing, int(part["total_periods"]))
            cursor.execute(
                "UPDATE TeachingPlan SET status = 'VALID' "
                "WHERE teaching_part_id = ? AND generation_key = ?",
                teaching_part_id,
                generation_key,
            )
            self._retire_superseded_plans(teaching_part_id, generation_key)
            return tuple(
                PersistedTeachingPlan(
                    teaching_plan_id=plan.teaching_plan_id,
                    teaching_part_id=plan.teaching_part_id,
                    plan_code=plan.plan_code,
                    plan_name=plan.plan_name,
                    status=TeachingPlanStatus.VALID,
                    allows_intensive=plan.allows_intensive,
                    generation_no=plan.generation_no,
                    candidate_rank=plan.candidate_rank,
                    generation_key=plan.generation_key,
                )
                for plan in existing
            )

        request = TeachingPlanGenerationRequest(
            part_code=str(part["part_code"]),
            total_periods=int(part["total_periods"]),
            start_week_number=int(rule["start_week_number"]),
            end_week_number=int(rule["end_week_number"]),
            allowed_durations=allowed_durations,
            max_sessions_per_week=int(rule["max_sessions_per_week"]),
            allows_intensive=bool(rule["allows_intensive"]),
            max_candidate_plans=int(rule["max_candidate_plans"]),
        )
        generated_plans = self._generator.generate(request)
        if not generated_plans:
            raise RuntimeError(
                f"Không thể sinh TeachingPlan đủ {part['total_periods']} tiết "
                f"cho {part['part_code']}."
            )

        maximum_generation = fetch_one_dict(cursor.execute(
            """
            SELECT COALESCE(MAX(generation_no), 0) AS maximum_generation_no
            FROM TeachingPlan WHERE teaching_part_id = ?
            """,
            teaching_part_id,
        ))
        generation_no = int(maximum_generation["maximum_generation_no"]) + 1
        persisted: list[PersistedTeachingPlan] = []
        for generated_plan in generated_plans:
            plan_code = self._build_persistent_plan_code(
                str(part["part_code"]), generation_no, generated_plan.sequence_number
            )
            inserted = fetch_one_dict(cursor.execute(
                """
                INSERT INTO TeachingPlan(
                    teaching_part_id, plan_code, plan_name, status,
                    allows_intensive, generation_no, candidate_rank,
                    generation_key, generated_at, note
                )
                OUTPUT INSERTED.teaching_plan_id
                VALUES (?, ?, ?, 'VALID', ?, ?, ?, ?, ?, ?)
                """,
                teaching_part_id,
                plan_code,
                generated_plan.plan_name,
                generated_plan.intensive,
                generation_no,
                generated_plan.sequence_number,
                generation_key,
                datetime.now(),
                f"Kế hoạch được hệ thống sinh tự động từ generation key {generation_key}.",
            ))
            if inserted is None:
                raise RuntimeError("SQL Server không trả về teaching_plan_id vừa tạo.")
            plan_id = int(inserted["teaching_plan_id"])

            cursor.executemany(
                """
                INSERT INTO TeachingPlanItem(
                    teaching_plan_id, item_number, term_code, week_number,
                    session_order_in_week, duration_periods, stability_group_no
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        plan_id,
                        item.item_number,
                        part["term_code"],
                        item.week_number,
                        item.session_order_in_week,
                        item.duration_periods,
                        item.stability_group_no,
                    )
                    for item in generated_plan.items
                ],
            )
            sessions = self._expander.expand(
                generated_plan, LocationType(str(part["required_location_type"]))
            )
            cursor.executemany(
                """
                INSERT INTO ClassSession(
                    teaching_plan_id, session_number, stability_group_no,
                    term_code, week_number, duration_periods,
                    required_location_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        plan_id,
                        session.session_number,
                        session.stability_group_no,
                        part["term_code"],
                        session.week_number,
                        session.duration_periods,
                        session.required_location_type.value,
                    )
                    for session in sessions
                ],
            )
            persisted.append(PersistedTeachingPlan(
                teaching_plan_id=plan_id,
                teaching_part_id=teaching_part_id,
                plan_code=plan_code,
                plan_name=generated_plan.plan_name,
                status=TeachingPlanStatus.VALID,
                allows_intensive=generated_plan.intensive,
                generation_no=generation_no,
                candidate_rank=generated_plan.sequence_number,
                generation_key=generation_key,
            ))

        self._retire_superseded_plans(teaching_part_id, generation_key)
        return tuple(persisted)

    def _load_generation(
        self, teaching_part_id: int, generation_key: str
    ) -> tuple[PersistedTeachingPlan, ...]:
        rows = fetch_all_dicts(self._connection.cursor().execute(
            """
            SELECT teaching_plan_id, teaching_part_id, plan_code, plan_name,
                   status, allows_intensive, generation_no, candidate_rank,
                   generation_key
            FROM TeachingPlan
            WHERE teaching_part_id = ? AND generation_key = ?
            ORDER BY candidate_rank
            """,
            teaching_part_id,
            generation_key,
        ))
        return tuple(PersistedTeachingPlan(
            teaching_plan_id=int(row["teaching_plan_id"]),
            teaching_part_id=int(row["teaching_part_id"]),
            plan_code=str(row["plan_code"]),
            plan_name=str(row["plan_name"]),
            status=TeachingPlanStatus(str(row["status"])),
            allows_intensive=bool(row["allows_intensive"]),
            generation_no=int(row["generation_no"]),
            candidate_rank=int(row["candidate_rank"]),
            generation_key=str(row["generation_key"]),
        ) for row in rows)

    def _validate_persisted_generation(
        self,
        plans: tuple[PersistedTeachingPlan, ...],
        expected_total_periods: int,
    ) -> None:
        cursor = self._connection.cursor()
        for expected_rank, plan in enumerate(plans, start=1):
            if plan.candidate_rank != expected_rank:
                raise RuntimeError(
                    f"Generation hiện có của {plan.plan_code} có candidate rank không liên tục."
                )
            items = fetch_all_dicts(cursor.execute(
                """
                SELECT item_number, term_code, week_number, duration_periods,
                       stability_group_no
                FROM TeachingPlanItem WHERE teaching_plan_id = ?
                ORDER BY item_number
                """,
                plan.teaching_plan_id,
            ))
            sessions = fetch_all_dicts(cursor.execute(
                """
                SELECT session_number, term_code, week_number, duration_periods,
                       stability_group_no
                FROM ClassSession WHERE teaching_plan_id = ?
                ORDER BY session_number
                """,
                plan.teaching_plan_id,
            ))
            if not items or len(items) != len(sessions):
                raise RuntimeError(
                    f"Plan {plan.plan_code} thiếu TeachingPlanItem hoặc ClassSession."
                )
            for expected_number, (item, session) in enumerate(
                zip(items, sessions, strict=True), start=1
            ):
                if (
                    int(item["item_number"]) != expected_number
                    or int(session["session_number"]) != expected_number
                ):
                    raise RuntimeError(
                        f"Plan {plan.plan_code} có thứ tự item/session không liên tục."
                    )
                compared_fields = ("term_code", "week_number", "duration_periods", "stability_group_no")
                if any(item[field] != session[field] for field in compared_fields):
                    raise RuntimeError(
                        f"Plan {plan.plan_code} có TeachingPlanItem và ClassSession không đồng nhất."
                    )
            if (
                sum(int(item["duration_periods"]) for item in items) != expected_total_periods
                or sum(int(session["duration_periods"]) for session in sessions)
                != expected_total_periods
            ):
                raise RuntimeError(
                    f"Plan {plan.plan_code} không đủ tổng tiết của TeachingPart."
                )

    def _retire_superseded_plans(
        self, teaching_part_id: int, current_generation_key: str
    ) -> None:
        self._connection.cursor().execute(
            """
            UPDATE current_plan
            SET status = 'RETIRED'
            FROM TeachingPlan AS current_plan
            WHERE current_plan.teaching_part_id = ?
              AND current_plan.status = 'VALID'
              AND current_plan.generation_key <> ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM PlanningScenarioItem AS item
                  JOIN PlanningScenario AS scenario
                    ON scenario.scenario_id = item.scenario_id
                  WHERE item.teaching_plan_id = current_plan.teaching_plan_id
                    AND scenario.status = 'LOCKED'
              )
            """,
            teaching_part_id,
            current_generation_key,
        )

    @staticmethod
    def _build_persistent_plan_code(
        part_code: str, generation_no: int, candidate_rank: int
    ) -> str:
        suffix = f"_G{generation_no:03d}_P{candidate_rank:02d}"
        base = re.sub(r"[^A-Z0-9]+", "_", part_code.strip().upper()).strip("_")
        return base[: 40 - len(suffix)] + suffix
