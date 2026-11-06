"""Read-only explanations, common scoring mode, and full validation on save."""
from dataclasses import replace

import pytest

from gapo_timetabling.application.schedule_adjustment import (
    ScheduleAdjustmentService, ScheduleAdjustmentConflictError,
    ScheduleAdjustmentPreviewInput,
)
from gapo_timetabling.application.schedule_quality import explain_quality
from gapo_timetabling.core.fitness import calculate_fitness
from gapo_timetabling.core.models import (
    AvailabilityScopeType, AvailabilityType, AvailabilityWindow,
    ConstraintSetting, ConstraintType,
)
from tests.test_schedule_adjustment import (
    RevisionConnection, recurring_fixture, request, single_request,
)


@pytest.fixture
def service(monkeypatch):
    connection = RevisionConnection()
    result = ScheduleAdjustmentService(connection)
    monkeypatch.setattr(result, "_load", lambda *_: recurring_fixture())
    return result


def assert_read_only(service):
    assert service.connection.statements == []
    assert not service.connection.committed
    assert not service.connection.rolled_back


def test_quality_reconstructs_existing_fitness(service):
    problem, domains, selected = recurring_fixture()
    expected = calculate_fitness(problem, selected, domains)
    result = service.quality(7)
    assert result["general_quality_score"] == expected.general_quality_score
    assert result["lecturer_preference_score"] == expected.lecturer_preference_score
    assert sum(r["contribution"] for r in result["general_components"]) == pytest.approx(expected.general_quality_score)
    assert sum(r["contribution"] for r in result["lecturer_components"]) == pytest.approx(expected.lecturer_preference_score)
    assert result["preference_domain_mode"] == "RECURRING"
    assert result["session_count"] == 8
    assert_read_only(service)


def test_revision_quality_uses_occurrence_mode(service):
    assert service.quality(7, 8)["preference_domain_mode"] == "OCCURRENCE"
    assert_read_only(service)


@pytest.mark.parametrize("proposal, count", [(request(), 2), (single_request(), 1)])
def test_preview_changes_only_target_and_never_writes(service, proposal, count):
    result = service.preview(7, proposal)
    assert result["is_valid"] and result["can_save"]
    assert result["changed_session_count"] == count
    assert all(row["before"]["part_code"] == row["after"]["part_code"] == "P0" for row in result["changes"])
    assert all(row["before"]["lecturer_code"] == row["after"]["lecturer_code"] for row in result["changes"])
    assert result["before"]["preference_domain_mode"] == result["after"]["preference_domain_mode"] == "OCCURRENCE"
    for field in ("general_quality_score", "lecturer_preference_score"):
        assert result["delta"][field] == pytest.approx(result["after"][field] - result["before"][field])
    assert_read_only(service)


def test_conflict_explains_proposed_and_conflicting_sessions(service):
    result = service.preview(7, single_request(iso_weekday=2, start_period=4))
    assert not result["is_valid"] and not result["can_save"]
    conflict = next(v for v in result["violations"] if v["code"] == "ROOM_CONFLICT")
    assert len(conflict["sessions"]) == 2
    target = next(s for s in conflict["sessions"] if s["part_code"] == "P0")
    assert target["start_period"] == 4  # Not the old slot at period 1.
    assert_read_only(service)


def test_out_of_domain_proposal_is_not_a_server_error(service):
    result = service.preview(7, request(location_id=999))
    assert not result["can_save"] and not result["is_valid"]
    assert result["message"]
    assert_read_only(service)


def test_unchanged_schedule_cannot_create_revision(service):
    result = service.preview(7, request(iso_weekday=2))
    assert result["is_valid"] and not result["can_save"]
    assert result["changed_session_count"] == 0
    assert_read_only(service)


def test_preview_note_is_optional():
    payload = request().model_dump(exclude={"note"})
    assert ScheduleAdjustmentPreviewInput(**payload).note == "Xem trước"


def test_save_revalidates_not_trusting_an_earlier_preview(service):
    assert service.preview(7, single_request())["can_save"]
    with pytest.raises(ScheduleAdjustmentConflictError, match="ROOM_CONFLICT"):
        service.create(7, single_request(iso_weekday=2, start_period=4))
    assert not service.connection.committed
    assert service.connection.statements == []


def test_preview_uses_same_preference_domain_for_original_and_proposal(service, monkeypatch):
    from datetime import timedelta
    problem, _, selected = recurring_fixture()
    common = dict(resource_index=0, scope_type=AvailabilityScopeType.DATE,
                  iso_weekday=None, start_period=1, end_period=3)
    problem = replace(problem, lecturer_availabilities=(
        AvailabilityWindow(**common, calendar_date=selected[0].teaching_date + timedelta(days=1),
                           availability_type=AvailabilityType.PREFERRED, preference_weight=1),
        AvailabilityWindow(**common, calendar_date=selected[4].teaching_date + timedelta(days=1),
                           availability_type=AvailabilityType.UNAVAILABLE),
    ))
    from gapo_timetabling.core.encoder import build_option_domains
    domains = build_option_domains(problem)
    monkeypatch.setattr(service, "_load", lambda *_: (problem, domains, selected))
    result = service.preview(7, single_request())
    assert result["before"]["lecturer_preference_score"] == calculate_fitness(problem, selected, domains, preference_domain_mode="OCCURRENCE").lecturer_preference_score
    assert result["delta"]["lecturer_preference_score"] < 0
    assert_read_only(service)


def test_dynamic_quality_weighted_components_match_fitness():
    from tests.test_dynamic_lecturer_assignment import TestDynamicLecturerAssignment
    from gapo_timetabling.core.encoder import build_option_domains
    from gapo_timetabling.core.constraints import validate_timetable
    from itertools import product
    problem = TestDynamicLecturerAssignment().build_problem()
    domains = build_option_domains(problem)
    selected = next(items for items in product(*domains) if validate_timetable(problem, items).is_valid)
    result = explain_quality(problem, domains, selected, mode="RECURRING")
    assert sum(r["contribution"] for r in result["lecturer_components"]) == pytest.approx(result["lecturer_preference_score"])
    assert result["lecturer_components"][1]["value"] > 0


@pytest.mark.parametrize("time_enabled,suitability_enabled", [(False, True), (True, False), (False, False)])
def test_disabled_lecturer_weights_are_explained_without_division_by_zero(time_enabled, suitability_enabled):
    from tests.test_dynamic_lecturer_assignment import TestDynamicLecturerAssignment
    from gapo_timetabling.core.encoder import build_option_domains
    from gapo_timetabling.core.constraints import validate_timetable
    from itertools import product
    problem = TestDynamicLecturerAssignment().build_problem()
    problem = replace(problem, constraint_settings=(
        ConstraintSetting("SOFT_LECTURER_TIME_PREFERENCE", ConstraintType.SOFT, 3, 0.5, time_enabled),
        ConstraintSetting("SOFT_COURSE_SUITABILITY", ConstraintType.SOFT, 3, 0.5, suitability_enabled),
    ))
    domains = build_option_domains(problem)
    selected = next(items for items in product(*domains) if validate_timetable(problem, items).is_valid)
    result = explain_quality(problem, domains, selected, mode="RECURRING")
    assert sum(row["contribution"] for row in result["lecturer_components"]) == pytest.approx(result["lecturer_preference_score"])
    if not time_enabled:
        assert result["lecturer_components"][0]["value"] is None


def test_api_readonly_routes_without_starting_lifespan(monkeypatch):
    # Directly exercise the registered sync handlers: no live SQL or background
    # recovery monitor. ASGI route/HTTP checks are tested separately.
    from gapo_timetabling.application.api import create_app
    from tests.test_api import FakeRunManager
    connection = RevisionConnection()
    monkeypatch.setattr(ScheduleAdjustmentService, "_load", lambda *_: recurring_fixture())
    app = create_app(connection_factory=lambda: connection, run_manager=FakeRunManager())
    endpoints = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}
    quality = endpoints["/api/runs/{run_id}/schedule-quality"](run_id=7, revision_id=None, connection=connection)
    preview = endpoints["/api/runs/{run_id}/adjustment-preview"](run_id=7, request=ScheduleAdjustmentPreviewInput(**request().model_dump()), connection=connection)
    assert quality["session_count"] == 8 and preview["can_save"]
    assert not connection.committed and connection.statements == []


def test_preview_http_contract_and_quality(monkeypatch):
    from fastapi.testclient import TestClient
    from gapo_timetabling.application.api import create_app
    from tests.test_api import FakeRunManager
    connection = RevisionConnection()
    monkeypatch.setattr(ScheduleAdjustmentService, "_load", lambda *_: recurring_fixture())
    client = TestClient(create_app(connection_factory=lambda: connection, run_manager=FakeRunManager()))
    endpoint = "/api/runs/7/adjustment-preview"
    body = single_request().model_dump(exclude={"note"})
    result = client.post(endpoint, json=body)
    assert result.status_code == 200 and result.json()["can_save"]
    conflict = client.post(endpoint, json={**body, "iso_weekday": 2, "start_period": 4})
    assert conflict.status_code == 200 and not conflict.json()["can_save"]
    assert client.post(endpoint, json={**body, "scope": "BAD"}).status_code == 422
    assert client.get("/api/runs/7/schedule-quality").json()["preference_domain_mode"] == "RECURRING"
    assert client.get("/api/runs/7/schedule-quality?revision_id=8").json()["preference_domain_mode"] == "OCCURRENCE"
    assert client.get("/api/runs/7/schedule-quality?revision_id=0").status_code == 422
    assert connection.statements == [] and not connection.committed and not connection.rolled_back
