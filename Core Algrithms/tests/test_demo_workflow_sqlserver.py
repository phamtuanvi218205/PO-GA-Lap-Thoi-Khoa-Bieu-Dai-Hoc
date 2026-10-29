"""Kiểm tra bốn chức năng trên SQL Server cục bộ khi được bật tường minh.

Chạy GAPO_SQL_SMOKE=1 rồi pytest file này sau khi migration. Các thao tác thử
được bọc trong một transaction và rollback; không sửa dữ liệu demo đã lưu.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gapo_timetabling.application.api import create_app
from gapo_timetabling.application.constraint_settings import ConstraintSettingsService
from gapo_timetabling.application.database import connect_sql_server, fetch_all_dicts
from gapo_timetabling.application.schedule_adjustment import (
    ScheduleAdjustmentService,
    ScheduleAdjustmentInput,
    ScheduleAdjustmentConflictError,
)
from gapo_timetabling.application.timetable_query import (
    TimetableQueryService,
    TimetableQueryFilters,
)
from gapo_timetabling.application.timetable_export import TimetableExportService
from gapo_timetabling.application.timetable_excel import TimetableExcelExportService
from gapo_timetabling.application.semester_reset import SemesterResetService
from tests.test_api import FakeRunManager

pytestmark = pytest.mark.skipif(
    os.getenv("GAPO_SQL_SMOKE") != "1",
    reason="SQL Server smoke phải được bật tường minh",
)


class RollbackConnection:
    """Service vẫn thực hiện transaction API; test giữ commit trong transaction ngoài."""

    def __init__(self, raw):
        self.raw = raw

    def cursor(self):
        return self.raw.cursor()

    def commit(self):
        pass

    def rollback(self):
        self.raw.rollback()

    def close(self):
        pass


@pytest.fixture
def db():
    raw = connect_sql_server()
    try:
        yield RollbackConnection(raw)
    finally:
        raw.rollback()
        raw.close()


def current_run(db):
    row = db.cursor().execute("""SELECT TOP 1 run_id FROM OptimizationRun
        WHERE status='COMPLETED' AND algorithm_version='demo-hard-capacity-20261028'
        ORDER BY run_id DESC""").fetchone()
    assert row is not None, "Cần có demo hard capacity mới trước khi chạy SQL smoke."
    return int(row[0])


def test_settings_update_and_manual_form_input_share_real_database_transaction(db):
    client = TestClient(
        create_app(connection_factory=lambda: db, run_manager=FakeRunManager())
    )
    schema = client.get("/api/input-data/form-schema")
    assert schema.status_code == 200
    assert "lecturer_capabilities" in schema.json()["properties"]
    original = client.get("/api/constraint-settings").json()
    settings = [
        {key: item[key] for key in ("constraint_code", "weight", "threshold_value")}
        for item in original["settings"]
    ]
    next(
        item
        for item in settings
        if item["constraint_code"] == "SOFT_LECTURER_CONSECUTIVE"
    )["threshold_value"] = 7
    update = client.put(
        "/api/constraint-settings",
        json={"expected_checksum": original["checksum"], "settings": settings},
    )
    assert update.status_code == 200
    assert (
        next(
            item
            for item in update.json()["settings"]
            if item["constraint_code"] == "SOFT_LECTURER_CONSECUTIVE"
        )["threshold_value"]
        == 7
    )
    bundle = {
        "term": {
            "term_code": "SMOKE_20261028",
            "term_name": "Dữ liệu thử rollback",
            "start_date": "2028-01-03",
            "number_of_weeks": 2,
        },
        "courses": [
            {"course_code": "SMOKE_COURSE", "course_name": "Môn nhập bằng biểu mẫu"}
        ],
    }
    assert client.post("/api/input-data/validate", json=bundle).status_code == 200
    response = client.post("/api/input-data/apply", json=bundle)
    assert response.status_code == 201, response.text
    saved = client.get("/api/input-data/terms/SMOKE_20261028")
    assert saved.status_code == 200
    assert saved.json()["term"]["number_of_weeks"] == 2
    assert any(
        item["course_code"] == "SMOKE_COURSE" for item in saved.json()["courses"]
    )


def test_real_revision_is_exportable_and_keeps_original_entries_unchanged(db, tmp_path):
    run_id = current_run(db)
    original = fetch_all_dicts(
        db.cursor().execute(
            "SELECT * FROM TimetableEntry WHERE run_id=? ORDER BY class_session_id",
            run_id,
        )
    )
    service = ScheduleAdjustmentService(db)
    rows = TimetableQueryService(db).get_run_schedule(run_id)
    created = None
    target = None
    for row in rows:
        for option in service.options(run_id, row.part_code, row.stability_group_no)[
            "items"
        ]:
            if (
                option["iso_weekday"],
                option["start_period"],
                option["location_id"],
            ) == (row.iso_weekday, row.start_period, row.location_id):
                continue
            request = ScheduleAdjustmentInput(
                part_code=row.part_code,
                stability_group_no=row.stability_group_no,
                iso_weekday=option["iso_weekday"],
                start_period=option["start_period"],
                location_id=option["location_id"],
                note="SQL smoke rollback",
            )
            # Chỉ thử trong bộ nhớ để không rollback transaction ngoài khi có xung đột.
            from gapo_timetabling.application.schedule_adjustment import (
                apply_pattern_change,
            )

            problem, domains, selected = service._load(run_id, None)
            try:
                apply_pattern_change(problem, domains, selected, request)
            except ScheduleAdjustmentConflictError:
                continue
            created = service.create(run_id, request)
            target = row
            break
        if created:
            break
    assert created and target
    filters = TimetableQueryFilters(revision_id=created["revision_id"])
    updated = TimetableQueryService(db).get_run_schedule(run_id, filters)
    assert len(updated) == len(rows)
    changed = next(
        row
        for row in updated
        if row.part_code == target.part_code
        and row.stability_group_no == target.stability_group_no
    )
    assert changed.active_week_numbers == target.active_week_numbers
    assert changed.lecturer_code == target.lecturer_code
    assert (changed.iso_weekday, changed.start_period, changed.location_id) != (
        target.iso_weekday,
        target.start_period,
        target.location_id,
    )
    after = fetch_all_dicts(
        db.cursor().execute(
            "SELECT * FROM TimetableEntry WHERE run_id=? ORDER BY class_session_id",
            run_id,
        )
    )
    assert after == original
    query = TimetableQueryService(db)
    TimetableExportService(query).export_run_csv(
        run_id, tmp_path / "revision.csv", filters
    )
    TimetableExcelExportService(query).export_run_xlsx(
        run_id, tmp_path / "revision.xlsx", filters
    )
    assert (tmp_path / "revision.csv").stat().st_size > 0
    assert (tmp_path / "revision.xlsx").read_bytes().startswith(b"PK")
    client = TestClient(
        create_app(connection_factory=lambda: db, run_manager=FakeRunManager())
    )
    assert (
        client.get(
            f"/api/runs/{run_id}/schedule",
            params={"revision_id": created["revision_id"]},
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/runs/{run_id}/schedule.xlsx",
            params={"revision_id": created["revision_id"]},
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/runs/{run_id}/schedule", params={"revision_id": 99999999}
        ).status_code
        == 422
    )


def test_old_capacity_soft_run_cannot_be_adjusted_under_current_validator(db):
    old = (
        db.cursor()
        .execute(
            "SELECT TOP 1 run_id FROM OptimizationRun WHERE snapshot_checksum='a91cd60ea6bf93a0648787d91fca3b28fb4005f75ae98bc065ed6bee418f073c'"
        )
        .fetchone()
    )
    if old is None:
        pytest.skip("Không có run lịch sử trong database này")
    row = TimetableQueryService(db).get_run_schedule(int(old[0]))[0]
    with pytest.raises(ScheduleAdjustmentConflictError, match="kết quả cũ"):
        ScheduleAdjustmentService(db).options(
            int(old[0]), row.part_code, row.stability_group_no
        )


def test_reset_with_revisions_preserves_input_sources_and_is_rolled_back(db):
    """Chạy DELETE thật trong transaction thử, cuối test rollback toàn bộ."""
    sources = ("CourseSection", "TeachingPart", "Course", "Lecturer", "Room")
    before = {
        table: db.cursor().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in sources
    }
    result = SemesterResetService(db).reset("2027_HK1")
    assert result.deleted_counts["schedule_revisions"] >= 1
    assert result.deleted_counts["revision_entries"] >= 132
    assert (
        db.cursor().execute("SELECT COUNT(*) FROM TimetableRevision").fetchone()[0] == 0
    )
    after = {
        table: db.cursor().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in sources
    }
    assert before == after
