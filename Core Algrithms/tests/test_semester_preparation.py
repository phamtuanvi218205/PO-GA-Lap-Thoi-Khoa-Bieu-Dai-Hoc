"""Kiểm thử readiness và transaction chuẩn bị học kỳ."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import pytest

from gapo_timetabling.application.planning import AutomaticScenarioRequest
from gapo_timetabling.application.scenario_service import PersistedPlanningScenario
from gapo_timetabling.application.semester_preparation import (
    ReadinessSeverity,
    SemesterNotReadyError,
    SemesterPreparationService,
    SemesterReadinessIssue,
    SemesterReadinessReport,
    SemesterReadinessService,
)
from gapo_timetabling.core.models import PlanningScenarioStatus, ScenarioScopeType
from gapo_timetabling.core.snapshot import SnapshotPreparationStatus


class ScriptedCursor:
    """Cursor trả fixture theo dấu hiệu ổn định trong từng câu SQL."""

    def __init__(
        self,
        *,
        include_practice_capability: bool = True,
        expected_enrollment: int | None = 50,
        room_capacity: int | None = 60,
    ) -> None:
        self.include_practice_capability = include_practice_capability
        self.expected_enrollment = expected_enrollment
        self.room_capacity = room_capacity
        self.description: list[tuple[str]] | None = None
        self._rows: list[tuple[Any, ...]] = []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, *parameters: Any) -> "ScriptedCursor":
        self.executed.append((sql, parameters))
        if "FROM AcademicTerm WHERE term_code" in sql:
            rows = [{
                "term_code": "2026_HK1",
                "term_name": "Học kỳ 1",
                "start_date": "2026-08-17",
                "end_date": "2026-08-30",
                "status": "PLANNING",
            }]
        elif "AS term_week_count" in sql:
            rows = [{
                "term_week_count": 2,
                "teaching_date_count": 14,
                "approved_section_count": 1,
                "planning_section_count": 0,
                "teaching_part_count": 2,
                "active_lecturer_count": 1,
                "active_location_count": 2,
                "time_period_count": 12,
                "allowed_block_count": 2,
                "locked_scenario_count": 0,
            }]
        elif "CourseTeachingStructure AS structure" in sql:
            rows = []
        elif "SELECT week_number FROM TermWeek" in sql:
            rows = [{"week_number": 1}, {"week_number": 2}]
        elif "LEFT JOIN TeachingPlanGenerationRule" in sql:
            common = {
                "section_code": "JAVA01",
                "course_code": "JAVA",
                "section_status": "APPROVED",
                "expected_enrollment": self.expected_enrollment,
                "total_periods": 6,
                "required_location_type": "PHYSICAL_ROOM",
                "start_week_number": 1,
                "end_week_number": 2,
                "max_sessions_per_week": 1,
                "allows_intensive": False,
                "max_candidate_plans": 10,
            }
            rows = [
                {
                    **common,
                    "teaching_part_id": 11,
                    "part_code": "JAVA01_LT",
                    "part_type": "LECTURE",
                    "required_room_type": "THEORY",
                },
                {
                    **common,
                    "teaching_part_id": 12,
                    "part_code": "JAVA01_TH",
                    "part_type": "PRACTICE",
                    "required_room_type": "LAB",
                },
            ]
        elif "FROM TeachingDurationRule" in sql:
            rows = [
                {"part_type": "LECTURE", "duration_periods": 3},
                {"part_type": "PRACTICE", "duration_periods": 3},
            ]
        elif "FROM AllowedPeriodBlock" in sql and "COUNT" not in sql:
            rows = [
                {"start_period": 1, "duration_periods": 3},
                {"start_period": 7, "duration_periods": 3},
            ]
        elif "FROM LecturerCourseCapability AS capability" in sql:
            rows = [{
                "lecturer_code": "GV01",
                "course_code": "JAVA",
                "can_teach_lecture": True,
                "can_teach_practice": self.include_practice_capability,
            }]
        elif "FROM TeachingLocation AS location" in sql:
            rows = [
                {
                    "location_id": 1,
                    "location_code": "A101",
                    "location_type": "PHYSICAL_ROOM",
                    "is_active": True,
                    "room_type": "THEORY",
                    "capacity": self.room_capacity,
                    "equipment_code": None,
                    "quantity": None,
                },
                {
                    "location_id": 2,
                    "location_code": "LAB01",
                    "location_type": "PHYSICAL_ROOM",
                    "is_active": True,
                    "room_type": "LAB",
                    "capacity": self.room_capacity,
                    "equipment_code": None,
                    "quantity": None,
                },
            ]
        elif "FROM TeachingPartRequiredEquipment AS requirement" in sql:
            rows = []
        elif "FROM PlanningScenario" in sql and "TOP (?)" in sql:
            rows = []
        elif "UPDATE PlanningScenario" in sql:
            rows = []
        else:  # pragma: no cover - buộc test phát hiện truy vấn mới chưa mô phỏng.
            raise AssertionError(f"SQL chưa được fixture hỗ trợ: {sql}")
        self._set(rows)
        return self

    def executemany(self, sql: str, parameters: Sequence[Sequence[Any]]) -> "ScriptedCursor":
        raise AssertionError("Fixture này không dùng executemany.")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def _set(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            self.description = [("empty",)]
            self._rows = []
            return
        columns = list(rows[0])
        self.description = [(column,) for column in columns]
        self._rows = [tuple(row[column] for column in columns) for row in rows]


class ScriptedConnection:
    def __init__(self, cursor: ScriptedCursor | None = None) -> None:
        self.scripted_cursor = cursor or ScriptedCursor()
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self) -> ScriptedCursor:
        return self.scripted_cursor

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        pass


def ready_report() -> SemesterReadinessReport:
    return SemesterReadinessReport(
        term_code="2026_HK1",
        ready=True,
        counts={"approved_section_count": 1},
        issues=(),
    )


def test_readiness_accepts_complete_source_data_without_writing() -> None:
    connection = ScriptedConnection()

    report = SemesterReadinessService(connection).check("2026_HK1")

    assert report.ready is True
    assert report.issues == ()
    assert report.counts["teaching_part_count"] == 2
    assert connection.commit_count == 0
    assert connection.rollback_count == 0
    assert not any("INSERT" in sql or "UPDATE" in sql for sql, _ in connection.scripted_cursor.executed)


def test_readiness_requires_one_lecturer_for_all_parts_of_a_section() -> None:
    connection = ScriptedConnection(ScriptedCursor(include_practice_capability=False))

    report = SemesterReadinessService(connection).check("2026_HK1")

    assert report.ready is False
    assert "SECTION_WITHOUT_ELIGIBLE_LECTURER" in {item.code for item in report.issues}


def test_readiness_rejects_physical_section_without_expected_enrollment() -> None:
    connection = ScriptedConnection(ScriptedCursor(expected_enrollment=None))

    report = SemesterReadinessService(connection).check("2026_HK1")

    assert report.ready is False
    assert "EXPECTED_ENROLLMENT_MISSING" in {item.code for item in report.issues}


def test_readiness_rejects_rooms_below_expected_enrollment() -> None:
    connection = ScriptedConnection(ScriptedCursor(room_capacity=40))

    report = SemesterReadinessService(connection).check("2026_HK1")

    assert report.ready is False
    assert "COMPATIBLE_LOCATION_MISSING" in {item.code for item in report.issues}


class FakeReadinessService:
    def __init__(self, report: SemesterReadinessReport) -> None:
        self.report = report

    def check(self, term_code: str) -> SemesterReadinessReport:
        assert term_code == self.report.term_code
        return self.report


class FakeScenarioService:
    def __init__(self) -> None:
        self.requests: list[AutomaticScenarioRequest] = []

    def create_and_lock_candidates(
        self, request: AutomaticScenarioRequest
    ) -> tuple[PersistedPlanningScenario, ...]:
        self.requests.append(request)
        return (PersistedPlanningScenario(
            scenario_id=31,
            scenario_code="AUTO_2026_V01",
            term_code=request.term_code,
            scope_type=ScenarioScopeType.FULL_TERM,
            status=PlanningScenarioStatus.LOCKED,
            candidate_rank=1,
            plan_rank_penalty=0,
            note="Đã khóa.",
        ),)


@dataclass(frozen=True)
class FakeBuiltSnapshot:
    payload: dict[str, str]
    sha256_checksum: str


class FakeSnapshotBuilder:
    def build(self, scenario_id: int) -> FakeBuiltSnapshot:
        assert scenario_id == 31
        return FakeBuiltSnapshot({"schema_version": "fake"}, "a" * 64)


def make_prepared_snapshot(*, ready: bool) -> SimpleNamespace:
    problem = SimpleNamespace(
        dimension=5,
        assignment_dimension=1,
        schedule_dimension=4,
        class_sessions=(1, 2, 3, 4),
    )
    return SimpleNamespace(
        status=(SnapshotPreparationStatus.READY if ready else SnapshotPreparationStatus.NO_OPTION),
        is_ready=ready,
        problem=problem,
        snapshot_checksum="a" * 64,
        gene_option_mapping_checksum=("b" * 64 if ready else None),
        option_domains=((1, 2), (3,), (4,), (5, 6)),
        no_option_issues=(() if ready else (SimpleNamespace(reason="Không có option."),)),
    )


def test_prepare_creates_scenarios_preflights_and_commits_once() -> None:
    connection = ScriptedConnection()
    scenario_service = FakeScenarioService()
    service = SemesterPreparationService(
        connection,
        readiness_service=FakeReadinessService(ready_report()),
        scenario_service=scenario_service,
        snapshot_builder=FakeSnapshotBuilder(),
        snapshot_preparer=lambda *args, **kwargs: make_prepared_snapshot(ready=True),
    )

    result = service.prepare("2026_HK1", max_scenario_candidates=3)

    assert result.status == "READY"
    assert result.ready_scenario_ids == (31,)
    assert result.scenarios[0].dimension == 5
    assert result.scenarios[0].atomic_option_count == 6
    assert scenario_service.requests[0].max_scenario_candidates == 3
    assert connection.commit_count == 1
    assert connection.rollback_count == 0


def test_prepare_automatically_keeps_only_best_runnable_scenario() -> None:
    class MultipleScenarioService:
        def create_and_lock_candidates(
            self, request: AutomaticScenarioRequest
        ) -> tuple[PersistedPlanningScenario, ...]:
            return (
                PersistedPlanningScenario(
                    31, "AUTO_V01", request.term_code, ScenarioScopeType.FULL_TERM,
                    PlanningScenarioStatus.LOCKED, 1, 1, "",
                ),
                PersistedPlanningScenario(
                    32, "AUTO_V02", request.term_code, ScenarioScopeType.FULL_TERM,
                    PlanningScenarioStatus.LOCKED, 2, 0, "",
                ),
                PersistedPlanningScenario(
                    33, "AUTO_V03", request.term_code, ScenarioScopeType.FULL_TERM,
                    PlanningScenarioStatus.LOCKED, 3, 0, "",
                ),
            )

    class MultipleSnapshotBuilder:
        def build(self, scenario_id: int) -> FakeBuiltSnapshot:
            return FakeBuiltSnapshot({"scenario_id": str(scenario_id)}, "a" * 64)

    def prepare_by_scenario(payload: Mapping[str, str], **_: Any) -> SimpleNamespace:
        # Scenario 31 có nhiều option nhất nhưng penalty xấu hơn nên không thắng.
        # Giữa 32 và 33 cùng penalty, 33 thắng vì miền option rộng hơn.
        option_counts = {31: 12, 32: 5, 33: 8}
        count = option_counts[int(payload["scenario_id"])]
        prepared = make_prepared_snapshot(ready=True)
        return SimpleNamespace(
            **{
                **prepared.__dict__,
                "option_domains": (tuple(range(count)),),
            }
        )

    connection = ScriptedConnection()
    service = SemesterPreparationService(
        connection,
        readiness_service=FakeReadinessService(ready_report()),
        scenario_service=MultipleScenarioService(),
        snapshot_builder=MultipleSnapshotBuilder(),
        snapshot_preparer=prepare_by_scenario,
    )

    result = service.prepare("2026_HK1", max_scenario_candidates=3)

    assert result.status == "READY"
    assert result.ready_scenario_ids == (33,)
    assert len(result.scenarios) == 1
    updates = [
        parameters
        for sql, parameters in connection.scripted_cursor.executed
        if "UPDATE PlanningScenario" in sql
    ]
    assert {parameters[-1] for parameters in updates} == {31, 32}
    assert connection.commit_count == 1


def test_prepare_rolls_back_before_generation_when_readiness_has_error() -> None:
    not_ready = SemesterReadinessReport(
        term_code="2026_HK1",
        ready=False,
        counts={},
        issues=(SemesterReadinessIssue(
            "TEST_ERROR",
            ReadinessSeverity.ERROR,
            "Kiểm thử",
            None,
            "Thiếu dữ liệu.",
        ),),
    )
    connection = ScriptedConnection()
    scenario_service = FakeScenarioService()
    service = SemesterPreparationService(
        connection,
        readiness_service=FakeReadinessService(not_ready),
        scenario_service=scenario_service,
    )

    with pytest.raises(SemesterNotReadyError):
        service.prepare("2026_HK1")

    assert scenario_service.requests == []
    assert connection.commit_count == 0
    assert connection.rollback_count == 1


def test_prepare_archives_locked_scenario_when_encoder_finds_no_option() -> None:
    connection = ScriptedConnection()
    service = SemesterPreparationService(
        connection,
        readiness_service=FakeReadinessService(ready_report()),
        scenario_service=FakeScenarioService(),
        snapshot_builder=FakeSnapshotBuilder(),
        snapshot_preparer=lambda *args, **kwargs: make_prepared_snapshot(ready=False),
    )

    result = service.prepare("2026_HK1")

    assert result.status == "NO_RUNNABLE_SCENARIO"
    assert result.scenarios[0].scenario_status == "ARCHIVED"
    assert result.ready_scenario_ids == ()
    updates = [sql for sql, _ in connection.scripted_cursor.executed if "UPDATE PlanningScenario" in sql]
    assert len(updates) == 1
    assert connection.commit_count == 1
