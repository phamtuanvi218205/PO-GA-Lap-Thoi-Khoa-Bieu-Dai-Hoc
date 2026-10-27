"""Kiểm thử hợp đồng HTTP cho tra cứu, xuất lịch và quản lý run."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from fastapi.testclient import TestClient

from gapo_timetabling.application.api import create_app
from gapo_timetabling.application.optimization_service import OptimizationRunConfig
from gapo_timetabling.application.run_manager import OptimizationJobSnapshot
from gapo_timetabling.application.semester_excel import SemesterExcelService
from gapo_timetabling.application.semester_preparation import (
    PreparedScenarioSummary,
    ReadinessSeverity,
    SemesterNotReadyError,
    SemesterPreparationResult,
    SemesterReadinessIssue,
    SemesterReadinessReport,
)
from gapo_timetabling.application.semester_reset import SemesterResetResult


class FakeCursor:
    """Mô phỏng các truy vấn chỉ đọc được API sử dụng."""

    def __init__(
        self,
        run: Mapping[str, Any] | None,
        entries: Sequence[Mapping[str, Any]],
    ) -> None:
        self._run = run
        self._entries = list(entries)
        self._rows: list[tuple[Any, ...]] = []
        self.description: list[tuple[str]] | None = None

    def execute(self, sql: str, *parameters: Any) -> "FakeCursor":
        if "FROM OptimizationRun" in sql and "FROM TimetableEntry" not in sql:
            self._set_result([] if self._run is None else [self._run])
        elif "FROM TimetableEntry" in sql:
            rows = list(self._entries)
            parameter_index = 1
            for clause, field in (
                ("entry.lecturer_code = ?", "lecturer_code"),
                ("course_section.section_code = ?", "section_code"),
                ("entry.term_code = ?", "term_code"),
                ("class_session.week_number = ?", "week_number"),
            ):
                if clause in sql:
                    expected = parameters[parameter_index]
                    parameter_index += 1
                    rows = [row for row in rows if row[field] == expected]
            self._set_result(rows)
        else:  # pragma: no cover - phát hiện khi API thay đổi SQL ngoài hợp đồng.
            raise AssertionError(f"Truy vấn không được fake hỗ trợ: {sql}")
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def _set_result(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            self.description = [("run_id",), ("status",)]
            self._rows = []
            return
        columns = list(rows[0])
        self.description = [(column,) for column in columns]
        self._rows = [tuple(row[column] for column in columns) for row in rows]


class FakeConnection:
    """Connection chỉ đọc và ghi nhận việc đóng tài nguyên."""

    def __init__(
        self,
        run: Mapping[str, Any] | None,
        entries: Sequence[Mapping[str, Any]],
    ) -> None:
        self.fake_cursor = FakeCursor(run, entries)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def commit(self) -> None:  # pragma: no cover - API tra cứu không ghi.
        raise AssertionError("API tra cứu không được commit.")

    def rollback(self) -> None:  # pragma: no cover - API tra cứu không ghi.
        raise AssertionError("API tra cứu không được rollback.")

    def close(self) -> None:
        self.closed = True


class FakeRunManager:
    """Manager xác định để kiểm tra hợp đồng HTTP mà không tạo thread thật."""

    def __init__(self) -> None:
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        self.snapshot = OptimizationJobSnapshot(
            job_id="job-001",
            scenario_id=3,
            status="QUEUED",
            run_id=None,
            fitness_evaluations=0,
            max_fitness_evaluations=1_000,
            progress_ratio=0.0,
            completed_iterations=0,
            max_iterations=0,
            best_general_quality_score=None,
            best_lecturer_preference_score=None,
            created_at=now,
            updated_at=now,
        )
        self.received_config: OptimizationRunConfig | None = None

    def start_run(
        self,
        scenario_id: int,
        config: OptimizationRunConfig,
    ) -> OptimizationJobSnapshot:
        self.received_config = config
        self.snapshot = replace(
            self.snapshot,
            scenario_id=scenario_id,
            max_fitness_evaluations=config.max_fitness_evaluations,
        )
        return self.snapshot

    def get_job(self, job_id: str) -> OptimizationJobSnapshot:
        if job_id != self.snapshot.job_id:
            from gapo_timetabling.application.run_manager import (
                OptimizationJobNotFoundError,
            )

            raise OptimizationJobNotFoundError(job_id)
        return self.snapshot

    def cancel_job(self, job_id: str) -> OptimizationJobSnapshot:
        snapshot = self.get_job(job_id)
        self.snapshot = replace(snapshot, status="CANCEL_REQUESTED")
        return self.snapshot


def make_run() -> dict[str, Any]:
    return {
        "run_id": 7,
        "scenario_id": 3,
        "algorithm_name": "GA_PO",
        "status": "COMPLETED",
        "population_size": 60,
        "max_fitness_evaluations": 1_000,
        "current_fitness_evaluations": 1_000,
        "completed_iterations": 12,
        "progress_updated_at": datetime(2026, 10, 21, 9, 0),
        "cancel_requested": False,
        "timeout_seconds": None,
        "started_at": datetime(2026, 10, 21, 8, 55),
        "finished_at": datetime(2026, 10, 21, 9, 0),
        "error_message": None,
        "general_quality_score": 0.2,
        "lecturer_preference_score": 0.3,
    }


def make_entry() -> dict[str, Any]:
    return {
        "run_id": 7,
        "class_session_id": 101,
        "term_code": "2026_HK1",
        "term_name": "Học kỳ 1 năm học 2026-2027",
        "week_number": 1,
        "duration_periods": 3,
        "stability_group_no": 1,
        "iso_weekday": 2,
        "teaching_date": date(2026, 8, 18),
        "start_period": 1,
        "end_period": 3,
        "section_code": "JAVA01",
        "section_name": "Lớp JAVA01",
        "course_code": "JAVA",
        "course_name": "Lập trình Java",
        "teaching_part_id": 201,
        "part_code": "JAVA01_LT",
        "part_type": "LECTURE",
        "lecturer_code": "GV001",
        "lecturer_name": "Nguyễn Văn An",
        "location_id": 11,
        "location_code": "A201",
        "location_name": "Phòng A201",
        "location_type": "PHYSICAL_ROOM",
    }


def make_client() -> tuple[TestClient, FakeRunManager, list[FakeConnection]]:
    connections: list[FakeConnection] = []

    def connection_factory() -> FakeConnection:
        connection = FakeConnection(make_run(), [make_entry()])
        connections.append(connection)
        return connection

    manager = FakeRunManager()
    app = create_app(connection_factory=connection_factory, run_manager=manager)  # type: ignore[arg-type]
    return TestClient(app), manager, connections


def test_health_and_persisted_run_status() -> None:
    client, _, connections = make_client()

    assert client.get("/health").json() == {"status": "ok"}
    response = client.get("/api/runs/7")

    assert response.status_code == 200
    assert response.json()["current_fitness_evaluations"] == 1_000
    assert connections[-1].closed is True


def test_web_interface_and_local_assets_are_served_by_fastapi() -> None:
    """Giao diện phải được đóng gói cùng API, không phụ thuộc web server khác."""

    client, _, _ = make_client()

    page = client.get("/")
    stylesheet = client.get("/ui-assets/styles.css")
    script = client.get("/ui-assets/app.js")

    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert page.headers["cache-control"] == "no-store"
    assert "Thời khóa biểu" in page.text
    assert stylesheet.status_code == 200
    assert ".timetable" in stylesheet.text
    assert script.status_code == 200
    assert "renderSchedule" in script.text


def test_schedule_query_supports_filters_and_returns_vietnamese_weekday() -> None:
    client, _, _ = make_client()

    response = client.get(
        "/api/runs/7/schedule",
        params={"lecturer_code": "GV001", "week_number": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["row_count"] == 1
    assert payload["items"][0]["weekday_name"] == "Thứ Ba"
    assert payload["items"][0]["active_week_numbers"] == [1]


def test_schedule_query_accepts_lecturer_name_or_code_search_text() -> None:
    client, _, _ = make_client()

    response = client.get(
        "/api/runs/7/schedule",
        params={"lecturer_query": "Nguyễn Văn An"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["lecturer_code"] == "GV001"


def test_download_csv_and_xlsx_use_the_same_persisted_schedule() -> None:
    client, _, _ = make_client()

    csv_response = client.get("/api/runs/7/schedule.csv")
    xlsx_response = client.get("/api/runs/7/schedule.xlsx")

    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert "JAVA01" in csv_response.content.decode("utf-8-sig")
    assert xlsx_response.status_code == 200
    assert "spreadsheetml.sheet" in xlsx_response.headers["content-type"]
    assert xlsx_response.content.startswith(b"PK")


def test_start_get_and_cancel_optimization_job() -> None:
    client, manager, _ = make_client()

    response = client.post(
        "/api/scenarios/3/optimization-jobs",
        json={
            "algorithm": "PO",
            "population_size": 30,
            "max_fitness_evaluations": 2_010,
            "random_seed": 17,
            "timeout_seconds": 120,
        },
    )

    assert response.status_code == 202
    assert response.json()["job_id"] == "job-001"
    assert manager.received_config is not None
    assert manager.received_config.algorithm.value == "PO"
    assert manager.received_config.timeout_seconds == 120
    assert client.get("/api/optimization-jobs/job-001").status_code == 200
    cancelled = client.post("/api/optimization-jobs/job-001/cancel")
    assert cancelled.json()["status"] == "CANCEL_REQUESTED"


def test_schedule_endpoints_reject_blank_string_filters_as_http_422() -> None:
    client, _, _ = make_client()

    for suffix in ("schedule", "schedule.csv", "schedule.xlsx"):
        response = client.get(
            f"/api/runs/7/{suffix}",
            params={"lecturer_code": "   "},
        )
        assert response.status_code == 422
        assert "lecturer_code" in response.json()["detail"]


def test_start_job_rejects_inconsistent_fitness_evaluation_budget() -> None:
    client, _, _ = make_client()

    smaller_than_population = client.post(
        "/api/scenarios/3/optimization-jobs",
        json={"population_size": 60, "max_fitness_evaluations": 2},
    )
    incomplete_iteration = client.post(
        "/api/scenarios/3/optimization-jobs",
        json={"population_size": 30, "max_fitness_evaluations": 2_000},
    )

    assert smaller_than_population.status_code == 422
    assert incomplete_iteration.status_code == 422


def test_api_maps_missing_job_and_invalid_identifiers() -> None:
    client, _, _ = make_client()

    assert client.get("/api/optimization-jobs/missing").status_code == 404
    assert client.get("/api/runs/0/schedule").status_code == 422
    assert client.post(
        "/api/scenarios/0/optimization-jobs",
        json={},
    ).status_code == 422


def test_input_template_preview_and_manual_validation_share_one_contract() -> None:
    client, _, _ = make_client()

    template = client.get("/api/input-data/excel-template")
    assert template.status_code == 200
    assert template.content.startswith(b"PK")

    preview = client.post(
        "/api/input-data/excel/preview",
        files={
            "file": (
                "semester.xlsx",
                SemesterExcelService().create_template(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert preview.status_code == 200
    assert preview.json()["source"] == "EXCEL"
    assert preview.json()["term_code"] == "2026_HK1"

    manual = client.post(
        "/api/input-data/validate",
        json={
            "term": {
                "term_code": "2026_HK1",
                "term_name": "Học kỳ 1",
                "start_date": "2026-08-17",
                "number_of_weeks": 15,
            }
        },
    )
    assert manual.status_code == 200
    assert manual.json()["source"] == "MANUAL"


def test_excel_preview_returns_structured_validation_issues() -> None:
    client, _, _ = make_client()

    response = client.post(
        "/api/input-data/excel/preview",
        files={"file": ("semester.xlsx", b"not-an-xlsx", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["sheet"] == "Workbook"


class FakeReadinessService:
    def __init__(self, report: SemesterReadinessReport) -> None:
        self.report = report

    def check(self, term_code: str) -> SemesterReadinessReport:
        assert term_code == self.report.term_code
        return self.report


class FakePreparationService:
    def __init__(
        self,
        result: SemesterPreparationResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.received_max_candidates: int | None = None

    def prepare(
        self, term_code: str, *, max_scenario_candidates: int
    ) -> SemesterPreparationResult:
        self.received_max_candidates = max_scenario_candidates
        if self.error is not None:
            raise self.error
        assert self.result is not None
        assert term_code == self.result.term_code
        return self.result


def test_readiness_and_prepare_endpoints_return_structured_pipeline_status() -> None:
    _, manager, _ = make_client()

    connections: list[FakeConnection] = []

    def fake_connection_factory() -> FakeConnection:
        connection = FakeConnection(make_run(), [make_entry()])
        connections.append(connection)
        return connection

    report = SemesterReadinessReport(
        term_code="2026_HK1",
        ready=True,
        counts={"approved_section_count": 3, "teaching_part_count": 6},
        issues=(),
    )
    scenario = PreparedScenarioSummary(
        scenario_id=41,
        scenario_code="AUTO_2026_V01",
        scenario_status="LOCKED",
        preparation_status="READY",
        runnable=True,
        snapshot_checksum="a" * 64,
        gene_option_mapping_checksum="b" * 64,
        dimension=12,
        assignment_dimension=3,
        schedule_dimension=9,
        class_session_count=90,
        atomic_option_count=720,
        issues=(),
    )
    result = SemesterPreparationResult(
        term_code="2026_HK1",
        status="READY",
        reused_existing_scenarios=False,
        readiness=report,
        scenarios=(scenario,),
    )
    preparation = FakePreparationService(result=result)
    app = create_app(
        connection_factory=fake_connection_factory,  # type: ignore[arg-type]
        run_manager=manager,
        readiness_service_factory=lambda connection: FakeReadinessService(report),  # type: ignore[arg-type]
        preparation_service_factory=lambda connection: preparation,  # type: ignore[arg-type]
    )
    client = TestClient(app)

    readiness_response = client.get("/api/input-data/terms/2026_HK1/readiness")
    prepare_response = client.post(
        "/api/input-data/terms/2026_HK1/prepare",
        json={"max_scenario_candidates": 7},
    )

    assert readiness_response.status_code == 200
    assert readiness_response.json()["ready"] is True
    assert prepare_response.status_code == 200
    assert prepare_response.json()["ready_scenario_ids"] == [41]
    assert prepare_response.json()["scenarios"][0]["atomic_option_count"] == 720
    assert preparation.received_max_candidates == 7
    assert all(connection.closed for connection in connections)


def test_prepare_endpoint_returns_readiness_report_with_http_409() -> None:
    _, manager, _ = make_client()

    def fake_connection_factory() -> FakeConnection:
        return FakeConnection(make_run(), [make_entry()])

    report = SemesterReadinessReport(
        term_code="2026_HK1",
        ready=False,
        counts={"approved_section_count": 0},
        issues=(SemesterReadinessIssue(
            "APPROVED_SECTIONS_MISSING",
            ReadinessSeverity.ERROR,
            "Lớp học phần",
            "2026_HK1",
            "Học kỳ chưa có lớp APPROVED để xếp.",
        ),),
    )
    preparation = FakePreparationService(error=SemesterNotReadyError(report))
    app = create_app(
        connection_factory=fake_connection_factory,  # type: ignore[arg-type]
        run_manager=manager,
        readiness_service_factory=lambda connection: FakeReadinessService(report),  # type: ignore[arg-type]
        preparation_service_factory=lambda connection: preparation,  # type: ignore[arg-type]
    )
    client = TestClient(app)

    response = client.post("/api/input-data/terms/2026_HK1/prepare", json={})

    assert response.status_code == 409
    assert response.json()["detail"]["readiness"]["ready"] is False
    assert response.json()["detail"]["readiness"]["issues"][0]["severity"] == "ERROR"


def test_reset_semester_endpoint_returns_deleted_derived_counts() -> None:
    _, manager, _ = make_client()
    connections: list[FakeConnection] = []

    def fake_connection_factory() -> FakeConnection:
        connection = FakeConnection(make_run(), [make_entry()])
        connections.append(connection)
        return connection

    class FakeResetService:
        def reset(self, term_code: str) -> SemesterResetResult:
            assert term_code == "2027_HK1"
            return SemesterResetResult(
                term_code=term_code,
                deleted_counts={"optimization_runs": 3, "scenarios": 10},
            )

    app = create_app(
        connection_factory=fake_connection_factory,  # type: ignore[arg-type]
        run_manager=manager,
        reset_service_factory=lambda connection: FakeResetService(),  # type: ignore[arg-type]
    )
    client = TestClient(app)

    response = client.delete("/api/input-data/terms/2027_HK1/scheduling-data")

    assert response.status_code == 200
    assert response.json() == {
        "term_code": "2027_HK1",
        "status": "RESET",
        "deleted_counts": {"optimization_runs": 3, "scenarios": 10},
    }
    assert connections[-1].closed is True
