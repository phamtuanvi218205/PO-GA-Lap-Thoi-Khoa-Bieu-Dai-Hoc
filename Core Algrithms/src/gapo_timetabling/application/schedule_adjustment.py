"""Điều chỉnh một buổi hoặc mẫu lịch lặp, lưu bản sao toàn thời khóa biểu.

Không chạy lại optimizer, không sửa gene hay TimetableEntry của run gốc. Mọi
phương án được kiểm tra trên đúng snapshot đã lưu, qua Validator độc lập rồi
tính lại fitness trước khi tạo bản điều chỉnh. Giảng viên, plan, tuần và tổng
số tiết giữ nguyên.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .database import ConnectionProtocol, fetch_all_dicts, fetch_one_dict
from .timetable_query import (
    OptimizationRunNotFoundError,
    OptimizationRunNotCompletedError,
    TimetableDataIntegrityError,
)
from ..core.constraints import validate_timetable
from ..core.encoder import build_option_domains, build_recurring_patterns_for_group
from ..core.fitness import calculate_fitness
from ..core.models import ProblemInstance, SessionOption
from ..core.snapshot import load_problem_instance_snapshot


class ScheduleAdjustmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_code: str = Field(min_length=1, max_length=50)
    stability_group_no: int = Field(ge=1)
    iso_weekday: int = Field(ge=1, le=7)
    start_period: int = Field(ge=1, le=16)
    location_id: int = Field(ge=1)
    scope: Literal["ALL_WEEKS", "SINGLE_SESSION"] = "ALL_WEEKS"
    week_number: int | None = Field(default=None, ge=1)
    parent_revision_id: int | None = Field(default=None, ge=1)
    note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_scope(self) -> "ScheduleAdjustmentInput":
        if self.scope == "SINGLE_SESSION" and self.week_number is None:
            raise ValueError("Chỉ buổi này cần xác định tuần đang chọn.")
        if self.scope == "ALL_WEEKS" and self.week_number is not None:
            raise ValueError("Đổi toàn bộ tuần không nhận week_number.")
        return self

    @field_validator("note")
    @classmethod
    def require_note(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Lý do điều chỉnh không được chỉ chứa khoảng trắng.")
        return value.strip()


class ScheduleAdjustmentConflictError(ValueError):
    """Phương án điều chỉnh không thuộc miền hoặc vi phạm điều kiện cứng."""


class ScheduleRevisionNotFoundError(LookupError):
    """Bản điều chỉnh không tồn tại hoặc không thuộc run đang xét."""


def find_schedule_group(problem: ProblemInstance, part_code: str, group_no: int) -> int:
    """Xác định gene lịch từ mã phần giảng dạy và số buổi lặp trong tuần."""
    parts = {part.teaching_part_index: part for part in problem.teaching_parts}
    plans = {plan.teaching_plan_id: plan for plan in problem.teaching_plans}
    for index, (plan_id, number) in enumerate(problem.schedule_group_keys):
        if (
            number == group_no
            and parts[plans[plan_id].teaching_part_index].part_code == part_code
        ):
            return index
    raise ScheduleAdjustmentConflictError(
        "Không tìm thấy mẫu lịch lặp được chọn trong snapshot của run."
    )


def apply_pattern_change(
    problem: ProblemInstance,
    domains: tuple[tuple[SessionOption, ...], ...],
    selected: tuple[SessionOption, ...],
    request: ScheduleAdjustmentInput,
) -> tuple[SessionOption, ...]:
    """Thay đúng phạm vi đã chọn; không dùng decoder tự dời các buổi khác."""
    group = find_schedule_group(problem, request.part_code, request.stability_group_no)
    selected_by_session = {option.session_index: option for option in selected}
    lecturer = problem.option_lecturer_index(
        selected_by_session[problem.schedule_groups[group][0]]
    )
    locations = {
        location.location_id: location.location_index for location in problem.locations
    }
    target_location = locations.get(request.location_id)
    if request.scope == "SINGLE_SESSION":
        session_index = find_group_session(problem, group, request.week_number)
        replacement = next(
            (option for option in domains[session_index] if (
                problem.option_lecturer_index(option) == lecturer
                and option.teaching_date.isoweekday() == request.iso_weekday
                and option.start_period == request.start_period
                and option.location_index == target_location
            )), None,
        )
        if replacement is None:
            raise ScheduleAdjustmentConflictError(
                "Khung giờ/phòng không hợp lệ cho buổi đã chọn: kiểm tra lịch bận, sức chứa, thiết bị và khung tiết."
            )
        replacements = (replacement,)
    else:
        patterns = build_recurring_patterns_for_group(problem, domains, group, lecturer)
        pattern = next(
            (item for item in patterns if (
                item.iso_weekday == request.iso_weekday
                and item.start_period == request.start_period
                and item.location_index == target_location
            )), None,
        )
        if pattern is None:
            raise ScheduleAdjustmentConflictError(
                "Khung giờ/phòng không dùng được ở mọi tuần hoạt động: kiểm tra lịch bận, sức chứa, thiết bị và khung tiết."
            )
        replacements = pattern.session_options
    selected_by_session.update(
        {option.session_index: option for option in replacements}
    )
    updated = tuple(
        selected_by_session[index] for index in range(problem.session_dimension)
    )
    validation = validate_timetable(problem, updated)
    if not validation.is_valid:
        details = "; ".join(
            f"{item.code.value}: {item.message}" for item in validation.violations[:8]
        )
        raise ScheduleAdjustmentConflictError(
            "Không thể lưu vì vi phạm ràng buộc cứng: " + details
        )
    return updated


def find_group_session(problem: ProblemInstance, group: int, week_number: int | None) -> int:
    """Một nhóm chỉ có một occurrence mỗi tuần; từ chối tuần ngoài plan."""
    matches = [
        index for index in problem.schedule_groups[group]
        if problem.class_sessions[index].week_number == week_number
    ]
    if len(matches) != 1:
        raise ScheduleAdjustmentConflictError("Không có đúng một buổi của nhóm trong tuần đã chọn.")
    return matches[0]


class ScheduleAdjustmentService:
    def __init__(self, connection: ConnectionProtocol) -> None:
        self.connection = connection

    def list_revisions(self, run_id: int) -> tuple[dict, ...]:
        self._get_run(run_id)
        rows = fetch_all_dicts(
            self.connection.cursor().execute(
                """SELECT revision_id,run_id,parent_revision_id,created_at,note,
                  general_quality_score,lecturer_preference_score,fitness_breakdown_json
                  FROM TimetableRevision WHERE run_id=? ORDER BY revision_id""",
                run_id,
            )
        )
        for row in rows:
            metadata = json.loads(row.pop("fitness_breakdown_json") or "{}")
            row["preference_domain_mode"] = metadata.get("preference_domain_mode", "RECURRING")
            row["adjustment_scope"] = metadata.get("adjustment_scope", "ALL_WEEKS")
            row["adjustment_week_number"] = metadata.get("adjustment_week_number")
        return tuple(rows)

    def options(
        self, run_id: int, part_code: str, group_no: int, revision_id: int | None = None,
        *, scope: Literal["ALL_WEEKS", "SINGLE_SESSION"] = "ALL_WEEKS",
        week_number: int | None = None,
    ) -> dict:
        problem, domains, selected = self._load(run_id, revision_id)
        group = find_schedule_group(problem, part_code, group_no)
        current = selected[problem.schedule_groups[group][0]]
        lecturer = problem.option_lecturer_index(current)
        if scope not in ("ALL_WEEKS", "SINGLE_SESSION"):
            raise ScheduleAdjustmentConflictError("Phạm vi điều chỉnh không hợp lệ.")
        if scope == "ALL_WEEKS" and week_number is not None:
            raise ScheduleAdjustmentConflictError("Đổi toàn bộ tuần không nhận week_number.")
        if scope == "SINGLE_SESSION":
            session_index = find_group_session(problem, group, week_number)
            candidates = [option for option in domains[session_index]
                          if problem.option_lecturer_index(option) == lecturer]
        else:
            patterns = build_recurring_patterns_for_group(problem, domains, group, lecturer)
            candidates = [pattern.session_options[0] for pattern in patterns]
        locations = {
            location.location_index: location for location in problem.locations
        }
        return {
            "scope": scope,
            "week_number": week_number,
            "active_week_numbers": sorted(
                {
                    problem.class_sessions[index].week_number
                    for index in problem.schedule_groups[group]
                }
            ),
            "items": [
                {
                    "iso_weekday": item.teaching_date.isoweekday(),
                    "start_period": item.start_period,
                    "end_period": item.end_period,
                    "teaching_date": item.teaching_date.isoformat() if scope == "SINGLE_SESSION" else None,
                    "location_id": locations[item.location_index].location_id,
                    "location_code": locations[item.location_index].location_code,
                }
                for item in candidates
            ],
        }

    def create(self, run_id: int, request: ScheduleAdjustmentInput) -> dict:
        try:
            problem, domains, selected = self._load(run_id, request.parent_revision_id)
            updated = apply_pattern_change(problem, domains, selected, request)
            if updated == selected:
                raise ScheduleAdjustmentConflictError(
                    "Phương án mới giống lịch đang xem; không tạo bản sao không thay đổi."
                )
            # Bản điều chỉnh cho phép ngoại lệ tuần. Chuẩn hóa mong muốn theo
            # miền từng buổi, không theo giao toàn kỳ. Mặc định của optimizer
            # vẫn là RECURRING; điểm revision không dùng xếp hạng benchmark.
            fitness = calculate_fitness(
                problem, updated, domains, preference_domain_mode="OCCURRENCE"
            )
            cursor = self.connection.cursor()
            row = fetch_one_dict(
                cursor.execute(
                    """INSERT INTO TimetableRevision(run_id,parent_revision_id,note,
                     general_quality_score,lecturer_preference_score,fitness_breakdown_json)
                   OUTPUT INSERTED.revision_id VALUES(?,?,?,?,?,?)""",
                    run_id,
                    request.parent_revision_id,
                    request.note.strip(),
                    fitness.general_quality_score,
                    fitness.lecturer_preference_score,
                    json.dumps({
                        **asdict(fitness.breakdown),
                        "preference_domain_mode": "OCCURRENCE",
                        "adjustment_scope": request.scope,
                        "adjustment_week_number": request.week_number,
                    }, ensure_ascii=False),
                )
            )
            revision_id = int(row["revision_id"])
            cursor.executemany(
                """INSERT INTO TimetableRevisionEntry(revision_id,run_id,class_session_id,
                       lecturer_code,term_code,teaching_date,location_id,location_type,start_period,end_period)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                [
                    self._entry_values(problem, option, revision_id, run_id)
                    for option in updated
                ],
            )
            self.connection.commit()
            return {
                "revision_id": revision_id,
                "run_id": run_id,
                "entry_count": len(updated),
                "hard_violation_count": 0,
                "scope": request.scope,
                "week_number": request.week_number,
                "general_quality_score": fitness.general_quality_score,
                "lecturer_preference_score": fitness.lecturer_preference_score,
            }
        except Exception:
            self.connection.rollback()
            raise

    def _get_run(self, run_id: int) -> dict:
        if run_id < 1:
            raise ValueError("run_id phải là số nguyên dương.")
        run = fetch_one_dict(
            self.connection.cursor().execute(
                "SELECT run_id,status,snapshot_json,snapshot_checksum FROM OptimizationRun WHERE run_id=?",
                run_id,
            )
        )
        if run is None:
            raise OptimizationRunNotFoundError("Không tồn tại run.")
        if run["status"] != "COMPLETED":
            raise OptimizationRunNotCompletedError("Chỉ điều chỉnh được run COMPLETED.")
        return run

    def _load(self, run_id: int, revision_id: int | None):
        run = self._get_run(run_id)
        try:
            problem, _ = load_problem_instance_snapshot(
                run["snapshot_json"], expected_checksum=run["snapshot_checksum"]
            )
        except ValueError as error:
            raise ScheduleAdjustmentConflictError(
                "Snapshot lịch nguồn không hợp lệ hoặc không khớp checksum; không được điều chỉnh."
            ) from error
        domains = build_option_domains(problem)
        cursor = self.connection.cursor()
        if revision_id is not None:
            if (
                fetch_one_dict(
                    cursor.execute(
                        "SELECT revision_id FROM TimetableRevision WHERE revision_id=? AND run_id=?",
                        revision_id,
                        run_id,
                    )
                )
                is None
            ):
                raise ScheduleRevisionNotFoundError(
                    "Bản điều chỉnh không thuộc run này."
                )
        table = "TimetableEntry" if revision_id is None else "TimetableRevisionEntry"
        sql = f"SELECT class_session_id,lecturer_code,teaching_date,location_id,start_period,end_period FROM {table} WHERE run_id=?"
        parameters = [run_id]
        if revision_id is not None:
            sql += " AND revision_id=?"
            parameters.append(revision_id)
        entries = fetch_all_dicts(cursor.execute(sql, *parameters))
        options_by_key = {}
        for domain in domains:
            for option in domain:
                key = (
                    problem.class_sessions[option.session_index].class_session_id,
                    problem.lecturers[
                        problem.option_lecturer_index(option)
                    ].lecturer_code,
                    option.teaching_date,
                    problem.locations[option.location_index].location_id,
                    option.start_period,
                    option.end_period,
                )
                options_by_key[key] = option
        selected = []
        for entry in entries:
            day = entry["teaching_date"]
            if isinstance(day, str):
                day = date.fromisoformat(day)
            key = (
                entry["class_session_id"],
                entry["lecturer_code"],
                day,
                entry["location_id"],
                entry["start_period"],
                entry["end_period"],
            )
            if key not in options_by_key:
                raise ScheduleAdjustmentConflictError(
                    "Lịch nguồn không còn hợp lệ theo Validator hiện tại (có thể là kết quả cũ trước hard capacity). Hãy chạy lại bài toán; không sửa lịch sử."
                )
            selected.append(options_by_key[key])
        validation = validate_timetable(problem, tuple(selected))
        if not validation.is_valid:
            raise TimetableDataIntegrityError(
                "Lịch nguồn thiếu buổi hoặc vi phạm ràng buộc cứng; không được điều chỉnh."
            )
        return (
            problem,
            domains,
            tuple(sorted(selected, key=lambda item: item.session_index)),
        )

    @staticmethod
    def _entry_values(problem, option, revision_id, run_id):
        location = problem.locations[option.location_index]
        return (
            revision_id,
            run_id,
            problem.class_sessions[option.session_index].class_session_id,
            problem.lecturers[problem.option_lecturer_index(option)].lecturer_code,
            problem.term.term_code,
            option.teaching_date,
            location.location_id,
            location.location_type.value,
            option.start_period,
            option.end_period,
        )
