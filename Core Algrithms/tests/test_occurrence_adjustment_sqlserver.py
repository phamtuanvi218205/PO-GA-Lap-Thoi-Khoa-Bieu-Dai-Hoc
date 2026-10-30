"""SQL integration tự dựng đề bài nhỏ, rollback toàn bộ sau kiểm tra.

Chỉ chạy khi GAPO_SQL_SMOKE=1. Không phụ thuộc demo/run hiện có và không
chạy benchmark. Hai lớp, hai tuần đủ kiểm chứng ngoại lệ, revision kế tiếp,
JSON/CSV/XLSX và tính bất biến của kết quả gốc.
"""

import csv
import io
import os
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from gapo_timetabling.application.api import create_app
from gapo_timetabling.application.database import connect_sql_server, fetch_all_dicts
from gapo_timetabling.application.input_data import SemesterInputBundle, SemesterInputService
from gapo_timetabling.application.optimization_service import OptimizationRunConfig, OptimizationRunService
from gapo_timetabling.application.schedule_adjustment import (
    ScheduleAdjustmentService, ScheduleAdjustmentInput, apply_pattern_change,
)
from gapo_timetabling.application.semester_preparation import SemesterPreparationService
from gapo_timetabling.application.timetable_query import TimetableQueryService
from gapo_timetabling.core.models import OptimizationAlgorithm
from tests.test_api import FakeRunManager
from tests.test_demo_workflow_sqlserver import RollbackConnection


pytestmark = pytest.mark.skipif(
    os.getenv("GAPO_SQL_SMOKE") != "1", reason="Bật GAPO_SQL_SMOKE=1 để kiểm tra SQL Server"
)


def test_occurrence_revision_roundtrip_real_database():
    raw = connect_sql_server()
    db = RollbackConnection(raw)
    try:
        bundle = SemesterInputBundle.model_validate({
            "term": {"term_code": "EXCEPT_20261028", "term_name": "Kiểm tra ngoại lệ rollback",
                     "start_date": "2028-01-03", "number_of_weeks": 2},
            "campuses": [{"campus_code": "EXC_CS", "campus_name": "Cơ sở thử"}],
            "courses": [{"course_code": "EXC_C", "course_name": "Môn thử ngoại lệ"}],
            "lecturers": [{"lecturer_code": "EXC_GV", "full_name": "Giảng viên thử", "home_campus_code": "EXC_CS"}],
            "lecturer_capabilities": [{"lecturer_code": "EXC_GV", "course_code": "EXC_C", "can_teach_lecture": True}],
            "rooms": [{"room_code": "EXC_R", "room_name": "Phòng thử", "campus_code": "EXC_CS",
                       "room_type": "LECTURE_ROOM", "capacity": 60}],
            "course_sections": [{"section_code": f"EXC_0{i}", "course_code": "EXC_C",
                                 "expected_enrollment": 50, "status": "APPROVED"} for i in (1, 2)],
            "course_teaching_structures": [{"course_code": "EXC_C", "part_type": "LECTURE",
                "total_periods": 6, "required_room_type": "LECTURE_ROOM", "max_sessions_per_week": 1}],
        })
        SemesterInputService(db).apply(bundle)
        prepared = SemesterPreparationService(db).prepare(bundle.term.term_code, max_scenario_candidates=1)
        assert prepared.status == "READY"
        run = OptimizationRunService(db).run_scenario(prepared.ready_scenario_ids[0], OptimizationRunConfig(
            algorithm=OptimizationAlgorithm.GA_PO, population_size=2, max_fitness_evaluations=4,
            random_seed=42, algorithm_version="occurrence-sql-smoke",
            max_initialization_attempts=20, max_offspring_attempts=2,
        ))
        assert run.status == "COMPLETED", run.result
        run_id = run.run_id
        original = fetch_all_dicts(db.cursor().execute(
            "SELECT * FROM TimetableEntry WHERE run_id=? ORDER BY class_session_id", run_id
        ))
        original_run = fetch_all_dicts(db.cursor().execute("SELECT * FROM OptimizationRun WHERE run_id=?", run_id))
        row = TimetableQueryService(db).get_run_schedule(run_id)[0]
        assert row.active_week_numbers == (1, 2)
        service = ScheduleAdjustmentService(db)
        problem, domains, selected = service._load(run_id, None)
        options = service.options(run_id, row.part_code, row.stability_group_no, scope="SINGLE_SESSION", week_number=1)
        option = next(item for item in options["items"] if item["iso_weekday"] != row.iso_weekday)
        request = ScheduleAdjustmentInput(
            part_code=row.part_code, stability_group_no=row.stability_group_no,
            scope="SINGLE_SESSION", week_number=1, iso_weekday=option["iso_weekday"],
            start_period=option["start_period"], location_id=option["location_id"], note="Chỉ tuần 1",
        )
        updated = apply_pattern_change(problem, domains, selected, request)
        assert sum(a != b for a, b in zip(selected, updated)) == 1
        client = TestClient(create_app(connection_factory=lambda: db, run_manager=FakeRunManager()))
        response = client.post(f"/api/runs/{run_id}/schedule-revisions", json=request.model_dump())
        assert response.status_code == 201, response.text
        revision = response.json()["revision_id"]
        schedule_url = f"/api/runs/{run_id}/schedule"
        all_rows = client.get(schedule_url, params={"revision_id": revision}).json()["items"]
        assert len(all_rows) == 3
        assert sum(len(item["active_week_numbers"]) for item in all_rows) == 4
        for week in (1, 2):
            rows = client.get(schedule_url, params={"revision_id": revision, "week_number": week}).json()["items"]
            assert len(rows) == 2
            target = next(item for item in rows if item["part_code"] == row.part_code)
            assert target["iso_weekday"] == (option["iso_weekday"] if week == 1 else row.iso_weekday)
        csv_response = client.get(schedule_url + ".csv", params={"revision_id": revision})
        assert csv_response.status_code == 200
        records = list(csv.DictReader(io.StringIO(csv_response.content.decode("utf-8-sig"))))
        assert len(records) == 3
        assert sum(len(record["Tuần hoạt động"].split(",")) for record in records) == 4
        xlsx_response = client.get(schedule_url + ".xlsx", params={"revision_id": revision})
        assert xlsx_response.status_code == 200
        with ZipFile(io.BytesIO(xlsx_response.content)) as archive:
            root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        excel_rows = root.findall("m:sheetData/m:row", ns)[3:]
        assert len(excel_rows) == 3
        metadata = client.get(f"/api/runs/{run_id}/schedule-revisions").json()["items"][0]
        assert metadata["preference_domain_mode"] == "OCCURRENCE"
        assert metadata["adjustment_scope"] == "SINGLE_SESSION"

        # Đổi toàn nhóm từ revision có ngoại lệ: áp dụng lại cùng mẫu cho hai tuần.
        all_request = request.model_copy(update={"scope": "ALL_WEEKS", "week_number": None,
                                                "parent_revision_id": revision, "note": "Đổi toàn nhóm"})
        second = client.post(f"/api/runs/{run_id}/schedule-revisions", json=all_request.model_dump())
        assert second.status_code == 201, second.text
        rows = client.get(schedule_url, params={"revision_id": second.json()["revision_id"]}).json()["items"]
        assert len(rows) == 2
        target = next(item for item in rows if item["part_code"] == row.part_code)
        assert target["active_week_numbers"] == [1, 2] and target["iso_weekday"] == option["iso_weekday"]
        assert fetch_all_dicts(db.cursor().execute(
            "SELECT * FROM TimetableEntry WHERE run_id=? ORDER BY class_session_id", run_id
        )) == original
        assert fetch_all_dicts(db.cursor().execute(
            "SELECT * FROM OptimizationRun WHERE run_id=?", run_id
        )) == original_run
    finally:
        raw.rollback()
        raw.close()
