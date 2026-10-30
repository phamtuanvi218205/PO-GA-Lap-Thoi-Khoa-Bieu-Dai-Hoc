"""HTTP API tra cứu, xuất lịch và quản lý optimization run nền."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Iterator, Literal

from fastapi import (
    Depends,
    File,
    FastAPI,
    HTTPException,
    Path as ApiPath,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .database import ConnectionProtocol, connect_sql_server, fetch_one_dict
from .optimization_service import OptimizationRunConfig
from .input_data import (
    SemesterInputBundle,
    SemesterInputNotFoundError,
    SemesterInputPersistenceError,
    SemesterInputQueryService,
    SemesterInputService,
)
from .run_manager import (
    OptimizationJobNotFoundError,
    OptimizationJobSnapshot,
    OptimizationRunManager,
)
from .timetable_excel import TimetableExcelExportService
from .timetable_export import TimetableExportService
from .timetable_query import (
    OptimizationRunNotCompletedError,
    OptimizationRunNotFoundError,
    TimetableDataIntegrityError,
    TimetableQueryFilters,
    TimetableQueryService,
)
from .semester_excel import SemesterExcelService, SemesterExcelValidationError
from .semester_preparation import (
    SemesterNotReadyError,
    SemesterPreparationNotFoundError,
    SemesterPreparationPersistenceError,
    SemesterPreparationService,
    SemesterReadinessReport,
    SemesterReadinessService,
)
from .semester_reset import (
    SemesterResetConflictError,
    SemesterResetNotFoundError,
    SemesterResetPersistenceError,
    SemesterResetService,
)
from ..core.models import OptimizationAlgorithm
from .constraint_settings import (
    ConstraintSettingsService,
    ConstraintSettingsUpdate,
    ConstraintSettingsConflictError,
)
from .schedule_adjustment import (
    ScheduleAdjustmentService,
    ScheduleAdjustmentInput,
    ScheduleAdjustmentConflictError,
    ScheduleRevisionNotFoundError,
)

WEB_DIRECTORY = Path(__file__).with_name("web")


class OptimizationRunStartRequest(BaseModel):
    """Cấu hình công khai dùng để đưa một run vào hàng đợi."""

    algorithm: Literal["GA", "PO", "GA_PO"] = "GA_PO"
    population_size: int = Field(default=60, ge=2)
    max_fitness_evaluations: int = Field(default=30_060, ge=2)
    random_seed: int = 42
    algorithm_version: str = Field(
        default="python-unified-v1", min_length=1, max_length=50
    )
    max_initialization_attempts: int = Field(default=6_000, ge=1)
    max_offspring_attempts: int = Field(default=5, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_fitness_evaluation_budget(self) -> "OptimizationRunStartRequest":
        """Từ chối ngân sách không thể chia thành quần thể đầu và các vòng đầy đủ."""

        if self.max_fitness_evaluations < self.population_size:
            raise ValueError(
                "max_fitness_evaluations phải lớn hơn hoặc bằng population_size."
            )
        remaining = self.max_fitness_evaluations - self.population_size
        if remaining % self.population_size != 0:
            raise ValueError("Phần FE sau khởi tạo phải chia hết cho population_size.")
        if self.max_initialization_attempts < self.population_size:
            raise ValueError(
                "max_initialization_attempts phải lớn hơn hoặc bằng population_size."
            )
        return self


class SemesterPrepareRequest(BaseModel):
    """Giới hạn số tổ hợp plan được kiểm tra trong một lần chuẩn bị."""

    max_scenario_candidates: int = Field(default=10, ge=1, le=100)


def create_app(
    *,
    connection_factory: Callable[[], ConnectionProtocol] = connect_sql_server,
    run_manager: OptimizationRunManager | None = None,
    input_service_factory: Callable[
        [ConnectionProtocol], SemesterInputService
    ] = SemesterInputService,
    readiness_service_factory: Callable[
        [ConnectionProtocol], SemesterReadinessService
    ] = SemesterReadinessService,
    preparation_service_factory: Callable[
        [ConnectionProtocol], SemesterPreparationService
    ] = SemesterPreparationService,
    reset_service_factory: Callable[
        [ConnectionProtocol], SemesterResetService
    ] = SemesterResetService,
    excel_service: SemesterExcelService | None = None,
) -> FastAPI:
    """Tạo FastAPI app có thể thay dependency trong integration test."""

    manager = run_manager or OptimizationRunManager(connection_factory)
    workbook_service = excel_service or SemesterExcelService()
    owns_manager = run_manager is None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            start_monitor = getattr(manager, "start_recovery_monitor", None)
            if callable(start_monitor):
                start_monitor()
            yield
        finally:
            if owns_manager:
                manager.shutdown(wait=False)

    app = FastAPI(
        title="GA-PO Timetabling API",
        version="0.1.0",
        description="Tra cứu, xuất lịch và quản lý các lần chạy tối ưu.",
        lifespan=lifespan,
    )
    app.state.run_manager = manager
    app.mount(
        "/ui-assets",
        StaticFiles(directory=WEB_DIRECTORY),
        name="ui-assets",
    )

    @app.get("/", include_in_schema=False)
    def web_interface() -> FileResponse:
        """Phục vụ giao diện web tối thiểu trên cùng origin với HTTP API."""

        # Không cache index trong môi trường demo để browser luôn nhận đúng
        # phiên bản giao diện sau khi uvicorn reload.
        return FileResponse(
            WEB_DIRECTORY / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    def query_service_dependency() -> Iterator[TimetableQueryService]:
        connection = connection_factory()
        try:
            yield TimetableQueryService(connection)
        finally:
            connection.close()

    def connection_dependency() -> Iterator[ConnectionProtocol]:
        connection = connection_factory()
        try:
            yield connection
        finally:
            connection.close()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/input-data/excel-template")
    def download_input_template() -> Response:
        """Tải workbook mẫu; file này chỉ chứa dữ liệu nguồn trước khi xếp."""

        return Response(
            content=workbook_service.create_template(),
            media_type=(
                "application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": (
                    'attachment; filename="gapo-semester-input-template.xlsx"'
                )
            },
        )

    @app.get("/api/input-data/form-schema")
    def input_form_schema() -> dict:
        """Biểu mẫu web sử dụng cùng schema với JSON/Excel, không tạo bộ rule khác."""
        return SemesterInputBundle.model_json_schema()

    @app.get("/api/constraint-settings")
    def get_constraint_settings(
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict:
        try:
            return ConstraintSettingsService(connection).get()
        except ConstraintSettingsConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.put("/api/constraint-settings")
    def update_constraint_settings(
        request: ConstraintSettingsUpdate,
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict:
        try:
            return ConstraintSettingsService(connection).update(request)
        except ConstraintSettingsConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/input-data/terms")
    def list_input_terms(
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict[str, object]:
        items = SemesterInputQueryService(connection).list_terms()
        return {"row_count": len(items), "items": items}

    @app.get("/api/input-data/terms/{term_code}")
    def get_semester_input_bundle(
        term_code: str = ApiPath(min_length=1, max_length=20),
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> SemesterInputBundle:
        try:
            return SemesterInputQueryService(connection).load(term_code)
        except SemesterInputNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/input-data/validate")
    def validate_manual_input(
        bundle: SemesterInputBundle,
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict[str, object]:
        """Kiểm tra gói nhập tay và mã tham chiếu nhưng không sửa database."""

        try:
            input_service_factory(connection).validate(bundle)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _input_bundle_payload(bundle, source="MANUAL")

    @app.post("/api/input-data/apply", status_code=status.HTTP_201_CREATED)
    def apply_manual_input(
        bundle: SemesterInputBundle,
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict[str, object]:
        """Lưu gói nhập tay bằng cùng service được importer Excel sử dụng."""

        try:
            result = input_service_factory(connection).apply(bundle)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SemesterInputPersistenceError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "source": "MANUAL",
            "term_code": result.term_code,
            "entity_counts": result.entity_counts,
        }

    @app.post("/api/input-data/excel/preview")
    async def preview_excel_input(
        file: UploadFile = File(...),
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict[str, object]:
        """Đọc và kiểm tra workbook nhưng không ghi bất kỳ dòng nào."""

        bundle = await _parse_excel_upload(file, workbook_service)
        try:
            input_service_factory(connection).validate(bundle)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _input_bundle_payload(bundle, source="EXCEL")

    @app.post(
        "/api/input-data/excel/apply",
        status_code=status.HTTP_201_CREATED,
    )
    async def apply_excel_input(
        file: UploadFile = File(...),
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict[str, object]:
        """Kiểm tra toàn bộ workbook rồi mới lưu nguyên tử vào SQL Server."""

        bundle = await _parse_excel_upload(file, workbook_service)
        try:
            result = input_service_factory(connection).apply(bundle)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SemesterInputPersistenceError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "source": "EXCEL",
            "term_code": result.term_code,
            "entity_counts": result.entity_counts,
        }

    @app.get("/api/input-data/terms/{term_code}/readiness")
    def get_semester_readiness(
        term_code: str = ApiPath(min_length=1, max_length=20),
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict[str, object]:
        """Kiểm tra dữ liệu học kỳ mà không sinh dữ liệu dẫn xuất."""

        try:
            report = readiness_service_factory(connection).check(term_code)
        except SemesterPreparationNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _readiness_payload(report)

    @app.post("/api/input-data/terms/{term_code}/prepare")
    def prepare_semester(
        request: SemesterPrepareRequest,
        term_code: str = ApiPath(min_length=1, max_length=20),
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict[str, object]:
        """Sinh plan/scenario và chạy encoder preflight, nhưng chưa chạy optimizer."""

        try:
            result = preparation_service_factory(connection).prepare(
                term_code,
                max_scenario_candidates=request.max_scenario_candidates,
            )
        except SemesterPreparationNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except SemesterNotReadyError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(error),
                    "readiness": _readiness_payload(error.report),
                },
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SemesterPreparationPersistenceError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "term_code": result.term_code,
            "status": result.status,
            "reused_existing_scenarios": result.reused_existing_scenarios,
            "ready_scenario_ids": list(result.ready_scenario_ids),
            "readiness": _readiness_payload(result.readiness),
            "scenarios": [asdict(item) for item in result.scenarios],
        }

    @app.delete("/api/input-data/terms/{term_code}/scheduling-data")
    def reset_semester_scheduling_data(
        term_code: str = ApiPath(min_length=1, max_length=20),
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict[str, object]:
        """Xóa kết quả chuẩn bị/chạy nhưng giữ nguyên dữ liệu nguồn học kỳ."""

        try:
            result = reset_service_factory(connection).reset(term_code)
        except SemesterResetNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except SemesterResetConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SemesterResetPersistenceError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "term_code": result.term_code,
            "status": "RESET",
            "deleted_counts": result.deleted_counts,
        }

    @app.get("/api/runs/{run_id}")
    def get_persisted_run(
        run_id: int = ApiPath(ge=1),
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict[str, object]:
        row = fetch_one_dict(
            connection.cursor().execute(
                """
            SELECT run_id, scenario_id, algorithm_name, status,
                   population_size, max_fitness_evaluations,
                   current_fitness_evaluations, completed_iterations,
                   progress_updated_at, cancel_requested, timeout_seconds,
                   started_at, finished_at, error_message,
                   general_quality_score, lecturer_preference_score
            FROM OptimizationRun
            WHERE run_id = ?
            """,
                run_id,
            )
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Không tồn tại run.")
        return row

    @app.get("/api/runs/{run_id}/schedule")
    def get_schedule(
        run_id: int = ApiPath(ge=1),
        lecturer_code: str | None = None,
        lecturer_query: str | None = None,
        section_code: str | None = None,
        term_code: str | None = None,
        week_number: int | None = Query(default=None, ge=1),
        revision_id: int | None = Query(default=None, ge=1),
        service: TimetableQueryService = Depends(query_service_dependency),
    ) -> dict[str, object]:
        filters = _build_filters(
            lecturer_code,
            lecturer_query,
            section_code,
            term_code,
            week_number,
            revision_id,
        )
        rows = _query_rows(service, run_id, filters)
        return {
            "run_id": run_id,
            "row_count": len(rows),
            "items": [
                {**asdict(row), "weekday_name": row.weekday_name} for row in rows
            ],
        }

    @app.get("/api/runs/{run_id}/schedule.csv")
    def download_schedule_csv(
        run_id: int = ApiPath(ge=1),
        lecturer_code: str | None = None,
        lecturer_query: str | None = None,
        section_code: str | None = None,
        term_code: str | None = None,
        week_number: int | None = Query(default=None, ge=1),
        revision_id: int | None = Query(default=None, ge=1),
        service: TimetableQueryService = Depends(query_service_dependency),
    ) -> Response:
        filters = _build_filters(
            lecturer_code,
            lecturer_query,
            section_code,
            term_code,
            week_number,
            revision_id,
        )
        with TemporaryDirectory(prefix="gapo-csv-") as directory:
            path = Path(directory) / f"timetable-run-{run_id}.csv"
            try:
                TimetableExportService(service).export_run_csv(run_id, path, filters)
            except _QUERY_ERRORS as error:
                raise _query_http_exception(error) from error
            content = path.read_bytes()
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="timetable-run-{run_id}{f"-revision-{revision_id}" if revision_id else ""}.csv"'
                )
            },
        )

    @app.get("/api/runs/{run_id}/schedule.xlsx")
    def download_schedule_xlsx(
        run_id: int = ApiPath(ge=1),
        lecturer_code: str | None = None,
        lecturer_query: str | None = None,
        section_code: str | None = None,
        term_code: str | None = None,
        week_number: int | None = Query(default=None, ge=1),
        revision_id: int | None = Query(default=None, ge=1),
        service: TimetableQueryService = Depends(query_service_dependency),
    ) -> Response:
        filters = _build_filters(
            lecturer_code,
            lecturer_query,
            section_code,
            term_code,
            week_number,
            revision_id,
        )
        with TemporaryDirectory(prefix="gapo-xlsx-") as directory:
            path = Path(directory) / f"timetable-run-{run_id}.xlsx"
            try:
                TimetableExcelExportService(service).export_run_xlsx(
                    run_id,
                    path,
                    filters,
                )
            except _QUERY_ERRORS as error:
                raise _query_http_exception(error) from error
            content = path.read_bytes()
        return Response(
            content=content,
            media_type=(
                "application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="timetable-run-{run_id}{f"-revision-{revision_id}" if revision_id else ""}.xlsx"'
                )
            },
        )

    @app.get("/api/runs/{run_id}/schedule-revisions")
    def list_schedule_revisions(
        run_id: int = ApiPath(ge=1),
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict:
        try:
            return {
                "items": ScheduleAdjustmentService(connection).list_revisions(run_id)
            }
        except _QUERY_ERRORS as error:
            raise _query_http_exception(error) from error

    @app.get("/api/runs/{run_id}/adjustment-options")
    def schedule_adjustment_options(
        run_id: int = ApiPath(ge=1),
        part_code: str = Query(min_length=1, max_length=50),
        stability_group_no: int = Query(ge=1),
        revision_id: int | None = Query(default=None, ge=1),
        scope: Literal["ALL_WEEKS", "SINGLE_SESSION"] = "ALL_WEEKS",
        week_number: int | None = Query(default=None, ge=1),
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict:
        try:
            return ScheduleAdjustmentService(connection).options(
                run_id, part_code, stability_group_no, revision_id,
                scope=scope, week_number=week_number,
            )
        except ScheduleRevisionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (ScheduleAdjustmentConflictError, *_QUERY_ERRORS) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/runs/{run_id}/schedule-revisions", status_code=201)
    def create_schedule_revision(
        request: ScheduleAdjustmentInput,
        run_id: int = ApiPath(ge=1),
        connection: ConnectionProtocol = Depends(connection_dependency),
    ) -> dict:
        try:
            return ScheduleAdjustmentService(connection).create(run_id, request)
        except ScheduleRevisionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (ScheduleAdjustmentConflictError, *_QUERY_ERRORS) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/api/scenarios/{scenario_id}/optimization-jobs",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def start_optimization_job(
        request: OptimizationRunStartRequest,
        scenario_id: int = ApiPath(ge=1),
    ) -> dict[str, object]:
        config = OptimizationRunConfig(
            algorithm=OptimizationAlgorithm(request.algorithm),
            population_size=request.population_size,
            max_fitness_evaluations=request.max_fitness_evaluations,
            random_seed=request.random_seed,
            algorithm_version=request.algorithm_version,
            max_initialization_attempts=request.max_initialization_attempts,
            max_offspring_attempts=request.max_offspring_attempts,
            timeout_seconds=request.timeout_seconds,
        )
        return _job_payload(manager.start_run(scenario_id, config))

    @app.get("/api/optimization-jobs/{job_id}")
    def get_optimization_job(job_id: str) -> dict[str, object]:
        try:
            return _job_payload(manager.get_job(job_id))
        except OptimizationJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="Không tồn tại job.") from error

    @app.post("/api/optimization-jobs/{job_id}/cancel")
    def cancel_optimization_job(job_id: str) -> dict[str, object]:
        try:
            return _job_payload(manager.cancel_job(job_id))
        except OptimizationJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="Không tồn tại job.") from error

    return app


_QUERY_ERRORS = (
    OptimizationRunNotFoundError,
    OptimizationRunNotCompletedError,
    TimetableDataIntegrityError,
)


def _build_filters(
    lecturer_code: str | None,
    lecturer_query: str | None,
    section_code: str | None,
    term_code: str | None,
    week_number: int | None,
    revision_id: int | None = None,
) -> TimetableQueryFilters:
    """Chuyển lỗi dữ liệu lọc thành phản hồi HTTP 422 nhất quán."""

    try:
        return TimetableQueryFilters(
            lecturer_code=lecturer_code,
            lecturer_query=lecturer_query,
            section_code=section_code,
            term_code=term_code,
            week_number=week_number,
            revision_id=revision_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _query_rows(
    service: TimetableQueryService,
    run_id: int,
    filters: TimetableQueryFilters,
):
    try:
        return service.get_run_schedule(run_id, filters)
    except _QUERY_ERRORS as error:
        raise _query_http_exception(error) from error


def _query_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, OptimizationRunNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, OptimizationRunNotCompletedError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


def _job_payload(snapshot: OptimizationJobSnapshot) -> dict[str, object]:
    return asdict(snapshot)


def _input_bundle_payload(
    bundle: SemesterInputBundle,
    *,
    source: str,
) -> dict[str, object]:
    """Tóm tắt dữ liệu đã qua cùng hợp đồng Pydantic của hai kênh nhập."""

    list_fields = (
        "campuses",
        "courses",
        "lecturers",
        "lecturer_capabilities",
        "rooms",
        "online_locations",
        "equipment",
        "room_equipment",
        "course_sections",
        "course_teaching_structures",
        "course_structure_equipment",
        "lecturer_availability",
        "room_availability",
    )
    return {
        "valid": True,
        "source": source,
        "term_code": bundle.term.term_code,
        "entity_counts": {field: len(getattr(bundle, field)) for field in list_fields},
    }


def _readiness_payload(report: SemesterReadinessReport) -> dict[str, object]:
    """Chuyển dataclass readiness thành JSON ổn định cho website."""

    return {
        "term_code": report.term_code,
        "ready": report.ready,
        "counts": dict(report.counts),
        "issues": [
            {
                **asdict(issue),
                "severity": issue.severity.value,
            }
            for issue in report.issues
        ],
    }


async def _parse_excel_upload(
    file: UploadFile,
    service: SemesterExcelService,
) -> SemesterInputBundle:
    """Giới hạn kích thước và chuẩn hóa lỗi workbook thành HTTP 422."""

    if file.filename and not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=422, detail="Chỉ chấp nhận tệp .xlsx.")
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail="Tệp Excel vượt quá giới hạn 10 MB."
        )
    try:
        return service.parse(content)
    except SemesterExcelValidationError as error:
        raise HTTPException(
            status_code=422,
            detail=[asdict(issue) for issue in error.issues],
        ) from error


app = create_app()
