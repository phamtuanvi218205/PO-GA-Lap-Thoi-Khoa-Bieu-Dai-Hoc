"""Kiểm tra và chuẩn bị dữ liệu một học kỳ trước khi chạy optimizer.

Module này nối hai kênh nhập dữ liệu với pipeline đã có của dự án. Bước
``readiness`` chỉ đọc database để chỉ ra dữ liệu còn thiếu. Bước ``prepare``
sinh TeachingPlan/ClassSession, tạo PlanningScenario, dựng snapshot và chạy
encoder preflight trong một transaction. GA, PO và GA–PO chỉ được phép nhận
những scenario có preflight ``READY``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from .database import ConnectionProtocol, fetch_all_dicts, fetch_one_dict
from .planning import (
    AutomaticScenarioRequest,
    TeachingPlanGenerationRequest,
    TeachingPlanGenerator,
)
from .scenario_service import (
    PersistedPlanningScenario,
    PlanningScenarioOrchestrationService,
)
from .snapshot_builder import ProblemInstanceSnapshotBuilder
from ..core.models import PlanningScenarioStatus, ScenarioScopeType
from ..core.snapshot import PreparedSnapshot, prepare_snapshot_for_optimization


class ReadinessSeverity(str, Enum):
    """Mức độ ảnh hưởng của một phát hiện trong báo cáo readiness."""

    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True, slots=True)
class SemesterReadinessIssue:
    """Một lỗi hoặc cảnh báo gắn với đối tượng dữ liệu cụ thể."""

    code: str
    severity: ReadinessSeverity
    entity_type: str
    entity_code: str | None
    message: str


@dataclass(frozen=True, slots=True)
class SemesterReadinessReport:
    """Kết quả kiểm tra chỉ đọc trước khi hệ thống sinh dữ liệu dẫn xuất."""

    term_code: str
    ready: bool
    counts: Mapping[str, int]
    issues: tuple[SemesterReadinessIssue, ...]


@dataclass(frozen=True, slots=True)
class PreparedScenarioSummary:
    """Kết quả preflight của một scenario ứng viên."""

    scenario_id: int
    scenario_code: str
    scenario_status: str
    preparation_status: str
    runnable: bool
    snapshot_checksum: str | None
    gene_option_mapping_checksum: str | None
    dimension: int | None
    assignment_dimension: int | None
    schedule_dimension: int | None
    class_session_count: int | None
    atomic_option_count: int | None
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SemesterPreparationResult:
    """Kết quả chuẩn bị; khi READY chỉ có một scenario được chọn tự động."""

    term_code: str
    status: str
    reused_existing_scenarios: bool
    readiness: SemesterReadinessReport
    scenarios: tuple[PreparedScenarioSummary, ...]

    @property
    def ready_scenario_ids(self) -> tuple[int, ...]:
        return tuple(item.scenario_id for item in self.scenarios if item.runnable)


class SemesterPreparationNotFoundError(LookupError):
    """Mã học kỳ không tồn tại."""


class SemesterNotReadyError(RuntimeError):
    """Dữ liệu nguồn còn lỗi nên prepare chưa được phép thay đổi database."""

    def __init__(self, report: SemesterReadinessReport) -> None:
        super().__init__("Dữ liệu học kỳ chưa đủ điều kiện chuẩn bị bài toán.")
        self.report = report


class SemesterPreparationPersistenceError(RuntimeError):
    """Transaction chuẩn bị học kỳ thất bại ngoài lỗi readiness đã biết."""


class _ReadinessServiceProtocol(Protocol):
    def check(self, term_code: str) -> SemesterReadinessReport: ...


class _ScenarioServiceProtocol(Protocol):
    def create_and_lock_candidates(
        self, request: AutomaticScenarioRequest
    ) -> tuple[PersistedPlanningScenario, ...]: ...


class _SnapshotBuilderProtocol(Protocol):
    def build(self, scenario_id: int): ...


class SemesterReadinessService:
    """Đối chiếu dữ liệu nguồn mà không sinh plan, session hoặc scenario."""

    def __init__(
        self,
        connection: ConnectionProtocol,
        *,
        plan_generator: TeachingPlanGenerator | None = None,
    ) -> None:
        self._connection = connection
        self._plan_generator = plan_generator or TeachingPlanGenerator()

    def check(self, term_code: str) -> SemesterReadinessReport:
        """Trả báo cáo có cấu trúc; phương thức này tuyệt đối không ghi DB."""

        normalized_term_code = term_code.strip()
        if not normalized_term_code:
            raise ValueError("term_code không được để trống.")

        cursor = self._connection.cursor()
        term = fetch_one_dict(cursor.execute(
            """
            SELECT term_code, term_name, start_date, end_date, status
            FROM AcademicTerm WHERE term_code = ?
            """,
            normalized_term_code,
        ))
        if term is None:
            raise SemesterPreparationNotFoundError(
                f"Không tìm thấy học kỳ {normalized_term_code}."
            )

        count_row = fetch_one_dict(cursor.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM TermWeek WHERE term_code = ?) AS term_week_count,
              (SELECT COUNT(*) FROM TeachingDate WHERE term_code = ?) AS teaching_date_count,
              (SELECT COUNT(*) FROM CourseSection
                 WHERE term_code = ? AND status = 'APPROVED') AS approved_section_count,
              (SELECT COUNT(*) FROM CourseSection
                 WHERE term_code = ? AND status = 'PLANNING') AS planning_section_count,
              (SELECT COUNT(*) FROM TeachingPart AS part
                 JOIN CourseSection AS section ON section.section_code = part.section_code
                 WHERE section.term_code = ? AND section.status = 'APPROVED') AS teaching_part_count,
              (SELECT COUNT(*) FROM Lecturer WHERE is_active = 1) AS active_lecturer_count,
              (SELECT COUNT(*) FROM TeachingLocation WHERE is_active = 1) AS active_location_count,
              (SELECT COUNT(*) FROM TimePeriod) AS time_period_count,
              (SELECT COUNT(*) FROM AllowedPeriodBlock WHERE is_active = 1) AS allowed_block_count,
              (SELECT COUNT(*) FROM PlanningScenario
                 WHERE term_code = ? AND status = 'LOCKED') AS locked_scenario_count
            """,
            normalized_term_code,
            normalized_term_code,
            normalized_term_code,
            normalized_term_code,
            normalized_term_code,
            normalized_term_code,
        ))
        assert count_row is not None
        counts = {key: int(value) for key, value in count_row.items()}
        issues: list[SemesterReadinessIssue] = []

        self._check_common_counts(normalized_term_code, counts, issues)
        missing_structure_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT section.section_code,section.course_code
            FROM CourseSection AS section
            WHERE section.term_code=? AND section.status='APPROVED'
              AND NOT EXISTS(
                  SELECT 1 FROM CourseTeachingStructure AS structure
                  WHERE structure.course_code=section.course_code
                    AND structure.is_active=1
              )
            ORDER BY section.section_code
            """,
            normalized_term_code,
        ))
        for row in missing_structure_rows:
            issues.append(SemesterReadinessIssue(
                "COURSE_STRUCTURE_MISSING",
                ReadinessSeverity.ERROR,
                "Lớp học phần",
                str(row["section_code"]),
                "Môn học chưa có cấu trúc giảng dạy đang hoạt động để sinh TeachingPart.",
            ))
        week_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT week_number FROM TermWeek
            WHERE term_code = ? ORDER BY week_number
            """,
            normalized_term_code,
        ))
        week_numbers = tuple(int(row["week_number"]) for row in week_rows)
        if week_numbers and week_numbers != tuple(range(1, len(week_numbers) + 1)):
            issues.append(SemesterReadinessIssue(
                "TERM_WEEKS_NOT_CONTIGUOUS",
                ReadinessSeverity.ERROR,
                "Tuần học",
                normalized_term_code,
                "Số tuần học phải liên tục từ tuần 1, không được thiếu tuần ở giữa.",
            ))

        section_part_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT section.section_code, section.course_code,
                   section.expected_enrollment,
                   section.status AS section_status,
                   part.teaching_part_id, part.part_code, part.part_type,
                   part.total_periods, part.required_location_type,
                   part.required_room_type,
                   generation_rule.start_week_number,
                   generation_rule.end_week_number,
                   generation_rule.max_sessions_per_week,
                   generation_rule.allows_intensive,
                   generation_rule.max_candidate_plans
            FROM CourseSection AS section
            LEFT JOIN TeachingPart AS part ON part.section_code = section.section_code
            LEFT JOIN TeachingPlanGenerationRule AS generation_rule
              ON generation_rule.teaching_part_id = part.teaching_part_id
             AND generation_rule.is_active = 1
            WHERE section.term_code = ? AND section.status = 'APPROVED'
            ORDER BY section.section_code, part.part_code
            """,
            normalized_term_code,
        ))
        duration_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT part_type, duration_periods
            FROM TeachingDurationRule
            ORDER BY part_type, duration_periods
            """
        ))
        allowed_block_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT start_period, duration_periods
            FROM AllowedPeriodBlock
            WHERE is_active = 1
            ORDER BY start_period, duration_periods
            """
        ))
        capability_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT capability.lecturer_code, capability.course_code,
                   capability.can_teach_lecture, capability.can_teach_practice
            FROM LecturerCourseCapability AS capability
            JOIN Lecturer AS lecturer
              ON lecturer.lecturer_code = capability.lecturer_code
            WHERE lecturer.is_active = 1
            ORDER BY capability.course_code, capability.lecturer_code
            """
        ))
        room_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT location.location_id, location.location_code,
                   location.location_type, location.is_active,
                   room.room_type, room.capacity,
                   equipment.equipment_code, equipment.quantity
            FROM TeachingLocation AS location
            LEFT JOIN Room AS room ON room.location_id = location.location_id
            LEFT JOIN RoomEquipment AS equipment
              ON equipment.room_location_id = room.location_id
            ORDER BY location.location_id, equipment.equipment_code
            """
        ))
        part_equipment_rows = fetch_all_dicts(cursor.execute(
            """
            SELECT requirement.teaching_part_id, requirement.equipment_code,
                   requirement.minimum_quantity
            FROM TeachingPartRequiredEquipment AS requirement
            JOIN TeachingPart AS part
              ON part.teaching_part_id = requirement.teaching_part_id
            JOIN CourseSection AS section ON section.section_code = part.section_code
            WHERE section.term_code = ? AND section.status = 'APPROVED'
            ORDER BY requirement.teaching_part_id, requirement.equipment_code
            """,
            normalized_term_code,
        ))

        durations_by_type = self._durations_by_type(duration_rows)
        block_durations = {int(row["duration_periods"]) for row in allowed_block_rows}
        equipment_by_room = self._equipment_by_room(room_rows)
        required_equipment = self._required_equipment(part_equipment_rows)
        self._check_sections_and_capabilities(
            section_part_rows, capability_rows, issues
        )
        self._check_parts(
            section_part_rows,
            durations_by_type,
            block_durations,
            room_rows,
            equipment_by_room,
            required_equipment,
            counts["term_week_count"],
            issues,
        )

        issues.sort(key=lambda item: (
            item.severity.value,
            item.entity_type,
            item.entity_code or "",
            item.code,
        ))
        return SemesterReadinessReport(
            term_code=normalized_term_code,
            ready=not any(item.severity == ReadinessSeverity.ERROR for item in issues),
            counts=counts,
            issues=tuple(issues),
        )

    @staticmethod
    def _check_common_counts(
        term_code: str,
        counts: Mapping[str, int],
        issues: list[SemesterReadinessIssue],
    ) -> None:
        required_counts = (
            ("term_week_count", "TERM_WEEKS_MISSING", "Tuần học", "Học kỳ chưa có tuần học."),
            ("teaching_date_count", "TEACHING_DATES_MISSING", "Ngày học", "Học kỳ chưa có lịch ngày theo tuần."),
            ("approved_section_count", "APPROVED_SECTIONS_MISSING", "Lớp học phần", "Học kỳ chưa có lớp học phần APPROVED để xếp."),
            ("teaching_part_count", "TEACHING_PARTS_MISSING", "Phần giảng dạy", "Các lớp APPROVED chưa có phần giảng dạy."),
            ("active_lecturer_count", "ACTIVE_LECTURERS_MISSING", "Giảng viên", "Không có giảng viên đang hoạt động."),
            ("active_location_count", "ACTIVE_LOCATIONS_MISSING", "Địa điểm", "Không có phòng hoặc lớp trực tuyến đang hoạt động."),
            ("time_period_count", "TIME_PERIODS_MISSING", "Tiết học", "Chưa khai báo danh mục tiết học."),
            ("allowed_block_count", "ALLOWED_BLOCKS_MISSING", "Khung tiết", "Chưa khai báo khung tiết liên tiếp được phép."),
        )
        for field, code, entity_type, message in required_counts:
            if counts[field] == 0:
                issues.append(SemesterReadinessIssue(
                    code, ReadinessSeverity.ERROR, entity_type, term_code, message
                ))
        if counts["planning_section_count"]:
            issues.append(SemesterReadinessIssue(
                "PLANNING_SECTIONS_IGNORED",
                ReadinessSeverity.WARNING,
                "Lớp học phần",
                term_code,
                f"Có {counts['planning_section_count']} lớp PLANNING; FULL_TERM chỉ lấy lớp APPROVED.",
            ))

    def _check_sections_and_capabilities(
        self,
        rows: Sequence[Mapping[str, object]],
        capabilities: Sequence[Mapping[str, object]],
        issues: list[SemesterReadinessIssue],
    ) -> None:
        by_section: dict[str, list[Mapping[str, object]]] = {}
        for row in rows:
            by_section.setdefault(str(row["section_code"]), []).append(row)
        for section_code, parts in by_section.items():
            actual_parts = [item for item in parts if item["teaching_part_id"] is not None]
            if not actual_parts:
                issues.append(SemesterReadinessIssue(
                    "SECTION_WITHOUT_PART",
                    ReadinessSeverity.ERROR,
                    "Lớp học phần",
                    section_code,
                    "Lớp APPROVED chưa có phần lý thuyết hoặc thực hành.",
                ))
                continue
            course_code = str(parts[0]["course_code"])
            requires_lecture = any(str(item["part_type"]) == "LECTURE" for item in actual_parts)
            requires_practice = any(str(item["part_type"]) == "PRACTICE" for item in actual_parts)
            eligible = {
                str(item["lecturer_code"])
                for item in capabilities
                if str(item["course_code"]) == course_code
                and (not requires_lecture or bool(item["can_teach_lecture"]))
                and (not requires_practice or bool(item["can_teach_practice"]))
            }
            if not eligible:
                issues.append(SemesterReadinessIssue(
                    "SECTION_WITHOUT_ELIGIBLE_LECTURER",
                    ReadinessSeverity.ERROR,
                    "Lớp học phần",
                    section_code,
                    "Không có cùng một giảng viên đủ năng lực dạy mọi phần của lớp.",
                ))

    def _check_parts(
        self,
        rows: Sequence[Mapping[str, object]],
        durations_by_type: Mapping[str, tuple[int, ...]],
        block_durations: set[int],
        room_rows: Sequence[Mapping[str, object]],
        equipment_by_room: Mapping[int, Mapping[str, int]],
        required_equipment: Mapping[int, Mapping[str, int]],
        term_week_count: int,
        issues: list[SemesterReadinessIssue],
    ) -> None:
        seen_parts: set[int] = set()
        for part in rows:
            if part["teaching_part_id"] is None:
                continue
            part_id = int(part["teaching_part_id"])
            if part_id in seen_parts:
                continue
            seen_parts.add(part_id)
            part_code = str(part["part_code"])
            part_type = str(part["part_type"])
            if part["start_week_number"] is None:
                issues.append(SemesterReadinessIssue(
                    "PLAN_RULE_MISSING",
                    ReadinessSeverity.ERROR,
                    "Phần giảng dạy",
                    part_code,
                    "Chưa có rule sinh TeachingPlan đang hoạt động.",
                ))
                continue

            start_week = int(part["start_week_number"])
            end_week = int(part["end_week_number"])
            if start_week < 1 or end_week > term_week_count or end_week < start_week:
                issues.append(SemesterReadinessIssue(
                    "PLAN_RULE_WEEK_RANGE_INVALID",
                    ReadinessSeverity.ERROR,
                    "Phần giảng dạy",
                    part_code,
                    "Khoảng tuần của rule nằm ngoài lịch tuần của học kỳ.",
                ))
                continue

            durations = durations_by_type.get(part_type, ())
            if not durations:
                issues.append(SemesterReadinessIssue(
                    "DURATION_RULE_MISSING",
                    ReadinessSeverity.ERROR,
                    "Phần giảng dạy",
                    part_code,
                    f"Chưa có thời lượng buổi hợp lệ cho loại {part_type}.",
                ))
                continue

            request = TeachingPlanGenerationRequest(
                part_code=part_code,
                total_periods=int(part["total_periods"]),
                start_week_number=start_week,
                end_week_number=end_week,
                allowed_durations=durations,
                max_sessions_per_week=int(part["max_sessions_per_week"]),
                allows_intensive=bool(part["allows_intensive"]),
                max_candidate_plans=int(part["max_candidate_plans"]),
            )
            generated = self._plan_generator.generate(request)
            usable_plans = tuple(
                plan
                for plan in generated
                if all(item.duration_periods in block_durations for item in plan.items)
            )
            if not generated:
                issues.append(SemesterReadinessIssue(
                    "PLAN_CANNOT_BE_GENERATED",
                    ReadinessSeverity.ERROR,
                    "Phần giảng dạy",
                    part_code,
                    "Không thể chia đủ tổng số tiết theo rule đã nhập.",
                ))
            elif not usable_plans:
                issues.append(SemesterReadinessIssue(
                    "PERIOD_BLOCK_MISSING",
                    ReadinessSeverity.ERROR,
                    "Phần giảng dạy",
                    part_code,
                    "Các thời lượng do plan sinh ra chưa có khung tiết liên tiếp tương ứng.",
                ))

            if str(part["required_location_type"]) == "ONLINE":
                has_location = any(
                    str(row["location_type"]) == "ONLINE" and bool(row["is_active"])
                    for row in room_rows
                )
            else:
                expected_enrollment = part["expected_enrollment"]
                if expected_enrollment is None:
                    issues.append(SemesterReadinessIssue(
                        "EXPECTED_ENROLLMENT_MISSING",
                        ReadinessSeverity.ERROR,
                        "Lớp học phần",
                        str(part["section_code"]),
                        "Lớp học phần vật lý phải có sĩ số dự kiến để kiểm tra sức chứa phòng.",
                    ))
                    continue
                requirements = required_equipment.get(part_id, {})
                has_location = any(
                    str(row["location_type"]) == "PHYSICAL_ROOM"
                    and bool(row["is_active"])
                    and row["room_type"] == part["required_room_type"]
                    and row["capacity"] is not None
                    and int(row["capacity"]) >= int(expected_enrollment)
                    and self._room_has_equipment(
                        equipment_by_room.get(int(row["location_id"]), {}),
                        requirements,
                    )
                    for row in room_rows
                )
            if not has_location:
                issues.append(SemesterReadinessIssue(
                    "COMPATIBLE_LOCATION_MISSING",
                    ReadinessSeverity.ERROR,
                    "Phần giảng dạy",
                    part_code,
                    "Không có phòng đang hoạt động đúng loại, đủ sức chứa và đủ thiết bị bắt buộc.",
                ))

    @staticmethod
    def _durations_by_type(
        rows: Iterable[Mapping[str, object]],
    ) -> dict[str, tuple[int, ...]]:
        values: dict[str, set[int]] = {}
        for row in rows:
            values.setdefault(str(row["part_type"]), set()).add(int(row["duration_periods"]))
        return {key: tuple(sorted(items)) for key, items in values.items()}

    @staticmethod
    def _equipment_by_room(
        rows: Iterable[Mapping[str, object]],
    ) -> dict[int, dict[str, int]]:
        result: dict[int, dict[str, int]] = {}
        for row in rows:
            room_id = int(row["location_id"])
            result.setdefault(room_id, {})
            if row["equipment_code"] is not None:
                result[room_id][str(row["equipment_code"])] = int(row["quantity"])
        return result

    @staticmethod
    def _required_equipment(
        rows: Iterable[Mapping[str, object]],
    ) -> dict[int, dict[str, int]]:
        result: dict[int, dict[str, int]] = {}
        for row in rows:
            result.setdefault(int(row["teaching_part_id"]), {})[
                str(row["equipment_code"])
            ] = int(row["minimum_quantity"])
        return result

    @staticmethod
    def _room_has_equipment(
        available: Mapping[str, int], required: Mapping[str, int]
    ) -> bool:
        return all(available.get(code, 0) >= quantity for code, quantity in required.items())


class SemesterPreparationService:
    """Tạo hoặc tái sử dụng scenario rồi xác nhận miền gene có thể tối ưu."""

    def __init__(
        self,
        connection: ConnectionProtocol,
        *,
        readiness_service: _ReadinessServiceProtocol | None = None,
        scenario_service: _ScenarioServiceProtocol | None = None,
        snapshot_builder: _SnapshotBuilderProtocol | None = None,
        snapshot_preparer: Callable[..., PreparedSnapshot] = prepare_snapshot_for_optimization,
    ) -> None:
        self._connection = connection
        self._readiness_service = readiness_service or SemesterReadinessService(connection)
        self._scenario_service = scenario_service or PlanningScenarioOrchestrationService(connection)
        self._snapshot_builder = snapshot_builder or ProblemInstanceSnapshotBuilder(connection)
        self._snapshot_preparer = snapshot_preparer

    def prepare(
        self,
        term_code: str,
        *,
        max_scenario_candidates: int = 10,
    ) -> SemesterPreparationResult:
        """Chuẩn bị nguyên tử và không tự khởi chạy optimizer."""

        if not 1 <= max_scenario_candidates <= 100:
            raise ValueError("max_scenario_candidates phải nằm trong khoảng 1..100.")
        try:
            readiness = self._readiness_service.check(term_code)
            if not readiness.ready:
                raise SemesterNotReadyError(readiness)

            scenarios = self._load_locked_scenarios(term_code, max_scenario_candidates)
            reused = bool(scenarios)
            if not scenarios:
                scenarios = self._scenario_service.create_and_lock_candidates(
                    AutomaticScenarioRequest(
                        term_code=term_code,
                        scope_type=ScenarioScopeType.FULL_TERM,
                        max_scenario_candidates=max_scenario_candidates,
                    )
                )

            evaluated = [(scenario, self._preflight(scenario)) for scenario in scenarios]
            for index, (scenario, summary) in enumerate(evaluated):
                if (
                    summary.scenario_status == PlanningScenarioStatus.LOCKED.value
                    and not summary.runnable
                ):
                    self._archive_unrunnable_scenario(summary)
                    evaluated[index] = (
                        scenario,
                        replace(
                            summary,
                            scenario_status=PlanningScenarioStatus.ARCHIVED.value,
                        ),
                    )

            runnable = [item for item in evaluated if item[1].runnable]
            if runnable:
                selected_scenario, selected_summary = min(
                    runnable,
                    key=self._automatic_selection_key,
                )
                for scenario, summary in runnable:
                    if scenario.scenario_id != selected_scenario.scenario_id:
                        self._archive_unselected_scenario(
                            summary,
                            selected_scenario=selected_scenario,
                        )
                # Web và optimizer chỉ nhận đúng một scenario. Các ứng viên
                # còn lại được giữ ARCHIVED để truy nguyên, không bắt người
                # dùng chọn một phương án kỹ thuật mà chưa có điểm fitness.
                summaries = (selected_summary,)
            else:
                summaries = tuple(summary for _, summary in evaluated)
            self._connection.commit()
        except (ValueError, SemesterPreparationNotFoundError, SemesterNotReadyError):
            self._connection.rollback()
            raise
        except Exception as error:
            self._connection.rollback()
            raise SemesterPreparationPersistenceError(
                "Không thể chuẩn bị học kỳ; toàn bộ thay đổi của lần gọi đã được rollback."
            ) from error

        status = "READY" if any(item.runnable for item in summaries) else "NO_RUNNABLE_SCENARIO"
        return SemesterPreparationResult(
            term_code=term_code,
            status=status,
            reused_existing_scenarios=reused,
            readiness=readiness,
            scenarios=summaries,
        )

    def _load_locked_scenarios(
        self, term_code: str, limit: int
    ) -> tuple[PersistedPlanningScenario, ...]:
        rows = fetch_all_dicts(self._connection.cursor().execute(
            """
            SELECT TOP (?) scenario_id, scenario_code, term_code, scope_type,
                   status, candidate_rank, plan_rank_penalty, note
            FROM PlanningScenario
            WHERE term_code = ? AND scope_type = 'FULL_TERM' AND status = 'LOCKED'
            ORDER BY candidate_rank, scenario_id
            """,
            limit,
            term_code,
        ))
        return tuple(PersistedPlanningScenario(
            scenario_id=int(row["scenario_id"]),
            scenario_code=str(row["scenario_code"]),
            term_code=str(row["term_code"]),
            scope_type=ScenarioScopeType(str(row["scope_type"])),
            status=PlanningScenarioStatus(str(row["status"])),
            candidate_rank=int(row["candidate_rank"]),
            plan_rank_penalty=int(row["plan_rank_penalty"]),
            note="" if row["note"] is None else str(row["note"]),
        ) for row in rows)

    def _preflight(self, scenario: PersistedPlanningScenario) -> PreparedScenarioSummary:
        if scenario.status != PlanningScenarioStatus.LOCKED:
            return PreparedScenarioSummary(
                scenario.scenario_id,
                scenario.scenario_code,
                scenario.status.value,
                "STRUCTURE_INVALID",
                False,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                (scenario.note or "Scenario không được khóa do dữ liệu cấu trúc không hợp lệ.",),
            )

        built = self._snapshot_builder.build(scenario.scenario_id)
        prepared = self._snapshot_preparer(
            built.payload,
            expected_checksum=built.sha256_checksum,
        )
        problem = prepared.problem
        return PreparedScenarioSummary(
            scenario_id=scenario.scenario_id,
            scenario_code=scenario.scenario_code,
            scenario_status=scenario.status.value,
            preparation_status=prepared.status.value,
            runnable=prepared.is_ready,
            snapshot_checksum=prepared.snapshot_checksum,
            gene_option_mapping_checksum=prepared.gene_option_mapping_checksum,
            dimension=problem.dimension,
            assignment_dimension=problem.assignment_dimension,
            schedule_dimension=problem.schedule_dimension,
            class_session_count=len(problem.class_sessions),
            atomic_option_count=sum(len(domain) for domain in prepared.option_domains),
            issues=tuple(issue.reason for issue in prepared.no_option_issues),
        )

    def _archive_unrunnable_scenario(self, summary: PreparedScenarioSummary) -> None:
        message = "; ".join(summary.issues[:3]) or summary.preparation_status
        self._connection.cursor().execute(
            """
            UPDATE PlanningScenario
            SET status = 'ARCHIVED', note = ?
            WHERE scenario_id = ? AND status = 'LOCKED'
            """,
            f"Encoder preflight không READY: {message}"[:500],
            summary.scenario_id,
        )

    @staticmethod
    def _automatic_selection_key(
        item: tuple[PersistedPlanningScenario, PreparedScenarioSummary],
    ) -> tuple[int, int, int, int]:
        """Xếp hạng xác định, không dùng random hay fitness chưa chạy."""

        scenario, summary = item
        return (
            scenario.plan_rank_penalty,
            -(summary.atomic_option_count or 0),
            scenario.candidate_rank,
            scenario.scenario_id,
        )

    def _archive_unselected_scenario(
        self,
        summary: PreparedScenarioSummary,
        *,
        selected_scenario: PersistedPlanningScenario,
    ) -> None:
        """Ẩn ứng viên hợp lệ không được xếp hạng cao nhất khỏi luồng chạy."""

        self._connection.cursor().execute(
            """
            UPDATE PlanningScenario
            SET status = 'ARCHIVED', note = ?
            WHERE scenario_id = ? AND status = 'LOCKED'
            """,
            (
                "Không được chọn tự động; hệ thống dùng "
                f"{selected_scenario.scenario_code} có thứ hạng tốt hơn."
            )[:500],
            summary.scenario_id,
        )
