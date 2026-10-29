"""Điều chỉnh mẫu lặp phải cập nhật mọi tuần và không sửa kết quả thuật toán."""

from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import ValidationError

from gapo_timetabling.application.schedule_adjustment import (
    ScheduleAdjustmentInput,
    ScheduleAdjustmentService,
    ScheduleAdjustmentConflictError,
    apply_pattern_change,
)
from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.encoder import build_option_domains
from gapo_timetabling.core.fitness import calculate_fitness
from gapo_timetabling.core.models import AvailabilityScopeType, AvailabilityType, AvailabilityWindow
from tests.test_constraints import ConstraintFixture


def recurring_fixture():
    fixture = ConstraintFixture()
    fixture.setUp()
    original = fixture.problem
    delta = timedelta(days=7)
    problem = replace(
        original,
        term=replace(original.term, end_date=original.term.end_date + delta),
        weeks=original.weeks
        + (
            replace(
                original.weeks[0],
                week_number=2,
                start_date=original.weeks[0].start_date + delta,
                end_date=original.weeks[0].end_date + delta,
            ),
        ),
        teaching_dates=original.teaching_dates
        + tuple(
            replace(day, calendar_date=day.calendar_date + delta, week_number=2)
            for day in original.teaching_dates
        ),
        teaching_parts=tuple(
            replace(part, total_periods=6) for part in original.teaching_parts
        ),
        class_sessions=original.class_sessions
        + tuple(
            replace(
                session,
                session_index=session.session_index + 4,
                class_session_id=session.class_session_id + 4,
                session_number=2,
                week_number=2,
            )
            for session in original.class_sessions
        ),
    )
    selected = fixture.valid_options + tuple(
        replace(
            option,
            session_index=option.session_index + 4,
            teaching_date=option.teaching_date + delta,
        )
        for option in fixture.valid_options
    )
    return problem, build_option_domains(problem), selected


def request(**changes):
    values = dict(
        part_code="P0",
        stability_group_no=1,
        iso_weekday=3,
        start_period=1,
        location_id=10,
        note="Đổi lịch theo yêu cầu",
    )
    values.update(changes)
    return ScheduleAdjustmentInput(**values)


def test_changes_all_active_weeks_and_preserves_other_groups():
    problem, domains, selected = recurring_fixture()
    updated = apply_pattern_change(problem, domains, selected, request())
    assert validate_timetable(problem, updated).is_valid
    assert len(updated) == len(selected)
    assert (
        updated[0].teaching_date.isoweekday()
        == updated[4].teaching_date.isoweekday()
        == 3
    )
    assert updated[0].lecturer_index == updated[4].lecturer_index
    assert all(updated[index] == selected[index] for index in (1, 2, 3, 5, 6, 7))
    assert selected[0].teaching_date.isoweekday() == 2


def test_rejects_room_conflict_instead_of_asking_decoder_to_rearrange():
    problem, domains, selected = recurring_fixture()
    with pytest.raises(ScheduleAdjustmentConflictError, match="ROOM_CONFLICT"):
        apply_pattern_change(
            problem, domains, selected, request(iso_weekday=2, start_period=4)
        )


@pytest.mark.parametrize(
    "changes", [dict(location_id=999), dict(part_code="UNKNOWN"), dict(start_period=2)]
)
def test_rejects_unknown_group_or_option(changes):
    problem, domains, selected = recurring_fixture()
    with pytest.raises(ScheduleAdjustmentConflictError):
        apply_pattern_change(problem, domains, selected, request(**changes))


def test_rejects_whitespace_note():
    with pytest.raises(ValidationError):
        request(note="   ")


class RevisionConnection:
    def __init__(self, fail_insert=False):
        self.statements = []
        self.parameters = []
        self.committed = False
        self.rolled_back = False
        self.fail_insert = fail_insert

    def cursor(self):
        return self

    def execute(self, sql, *parameters):
        self.statements.append(sql)
        self.parameters.append(parameters)
        self.description = [("revision_id",)]
        return self

    def fetchone(self):
        return (8,)

    def executemany(self, sql, parameters):
        self.statements.append(sql)
        self.parameters.append(parameters)
        if self.fail_insert:
            raise RuntimeError("insert failed")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_persists_full_revision_without_updating_original_run(monkeypatch):
    connection = RevisionConnection()
    service = ScheduleAdjustmentService(connection)
    monkeypatch.setattr(service, "_load", lambda *_: recurring_fixture())
    result = service.create(7, request())
    assert result["revision_id"] == 8 and result["entry_count"] == 8
    assert connection.committed
    assert len(connection.parameters[-1]) == 8
    assert all(
        "UPDATE OptimizationRun" not in sql and "INSERT INTO TimetableEntry(" not in sql
        for sql in connection.statements
    )


def test_revision_rolls_back_on_entry_write_failure(monkeypatch):
    connection = RevisionConnection(fail_insert=True)
    service = ScheduleAdjustmentService(connection)
    monkeypatch.setattr(service, "_load", lambda *_: recurring_fixture())
    with pytest.raises(RuntimeError):
        service.create(7, request())
    assert connection.rolled_back and not connection.committed


def single_request(**changes):
    return request(**{"scope": "SINGLE_SESSION", "week_number": 1, **changes})


def test_single_session_changes_only_chosen_week():
    problem, domains, selected = recurring_fixture()
    updated = apply_pattern_change(problem, domains, selected, single_request())
    assert validate_timetable(problem, updated).is_valid
    assert updated[0].teaching_date.isoweekday() == 3
    assert updated[4] == selected[4]
    assert all(updated[index] == selected[index] for index in range(1, 8))
    assert updated[0].end_period - updated[0].start_period == 2
    assert problem.option_lecturer_index(updated[0]) == problem.option_lecturer_index(selected[0])


def test_single_session_can_use_slot_blocked_in_another_week():
    problem, _, selected = recurring_fixture()
    busy = AvailabilityWindow(
        resource_index=0, scope_type=AvailabilityScopeType.DATE,
        calendar_date=selected[4].teaching_date + timedelta(days=1),
        iso_weekday=None, start_period=1, end_period=3,
        availability_type=AvailabilityType.UNAVAILABLE,
    )
    problem = replace(problem, lecturer_availabilities=(busy,))
    domains = build_option_domains(problem)
    updated = apply_pattern_change(problem, domains, selected, single_request())
    assert updated[4] == selected[4]
    with pytest.raises(ScheduleAdjustmentConflictError, match="mọi tuần"):
        apply_pattern_change(problem, domains, selected, request())
    with pytest.raises(ScheduleAdjustmentConflictError, match="buổi đã chọn"):
        apply_pattern_change(problem, domains, selected, single_request(week_number=2))


def test_single_session_rejects_conflict_with_other_group():
    problem, domains, selected = recurring_fixture()
    with pytest.raises(ScheduleAdjustmentConflictError, match="ROOM_CONFLICT"):
        apply_pattern_change(problem, domains, selected, single_request(iso_weekday=2, start_period=4))


@pytest.mark.parametrize("changes", [
    {"scope": "SINGLE_SESSION"}, {"scope": "UNKNOWN"},
    {"week_number": 1}, {"scope": "SINGLE_SESSION", "week_number": 0},
])
def test_scope_contract_rejects_ambiguous_target(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_single_session_rejects_week_outside_plan():
    problem, domains, selected = recurring_fixture()
    with pytest.raises(ScheduleAdjustmentConflictError, match="tuần đã chọn"):
        apply_pattern_change(problem, domains, selected, single_request(week_number=3))


def test_all_weeks_can_replace_existing_exception_and_other_edits_preserve_it():
    problem, domains, selected = recurring_fixture()
    first = apply_pattern_change(problem, domains, selected, single_request())
    other = apply_pattern_change(problem, domains, first, request(part_code="P3", location_id=12))
    assert other[0] == first[0] and other[4] == selected[4]
    all_weeks = apply_pattern_change(problem, domains, first, request())
    assert all_weeks[0].teaching_date.isoweekday() == all_weeks[4].teaching_date.isoweekday() == 3


def test_options_single_week_uses_atomic_domain_and_dates(monkeypatch):
    service = ScheduleAdjustmentService(RevisionConnection())
    monkeypatch.setattr(service, "_load", lambda *_: recurring_fixture())
    payload = service.options(7, "P0", 1, scope="SINGLE_SESSION", week_number=2)
    assert payload["scope"] == "SINGLE_SESSION"
    assert payload["active_week_numbers"] == [1, 2]
    assert payload["items"]
    assert all(item["teaching_date"] >= "2026-08-24" for item in payload["items"])
    assert all(item["teaching_date"] <= "2026-08-30" for item in payload["items"])
    with pytest.raises(ScheduleAdjustmentConflictError):
        service.options(7, "P0", 1, scope="SINGLE_SESSION")


def test_single_revision_metadata_and_full_copy_are_saved(monkeypatch):
    import json
    connection = RevisionConnection()
    service = ScheduleAdjustmentService(connection)
    monkeypatch.setattr(service, "_load", lambda *_: recurring_fixture())
    result = service.create(7, single_request(parent_revision_id=6))
    assert result["scope"] == "SINGLE_SESSION" and result["week_number"] == 1
    assert result["entry_count"] == 8
    metadata = json.loads(connection.parameters[0][-1])
    assert metadata["adjustment_scope"] == "SINGLE_SESSION"
    assert metadata["preference_domain_mode"] == "OCCURRENCE"
    assert connection.parameters[0][1] == 6


def test_exception_fitness_uses_atomic_preference_domain_and_optimizer_default_unchanged():
    problem, _, selected = recurring_fixture()
    # Thứ Tư chỉ khả dụng tuần 1 và là giờ mong muốn của đúng tuần này.
    common = dict(resource_index=0, scope_type=AvailabilityScopeType.DATE,
                  iso_weekday=None, start_period=1, end_period=3)
    problem = replace(problem, lecturer_availabilities=(
        AvailabilityWindow(**common, calendar_date=selected[0].teaching_date + timedelta(days=1),
                           availability_type=AvailabilityType.PREFERRED, preference_weight=1.0),
        AvailabilityWindow(**common, calendar_date=selected[4].teaching_date + timedelta(days=1),
                           availability_type=AvailabilityType.UNAVAILABLE),
    ))
    domains = build_option_domains(problem)
    updated = apply_pattern_change(problem, domains, selected, single_request())
    before = calculate_fitness(problem, selected, domains, preference_domain_mode="OCCURRENCE")
    after = calculate_fitness(problem, updated, domains, preference_domain_mode="OCCURRENCE")
    assert 0 <= after.lecturer_preference_score < before.lecturer_preference_score <= 1
    assert calculate_fitness(problem, selected, domains) == calculate_fitness(
        problem, selected, domains, preference_domain_mode="RECURRING"
    )


def test_api_scope_validation_and_single_session_create(monkeypatch):
    from fastapi.testclient import TestClient
    from gapo_timetabling.application.api import create_app
    from tests.test_api import FakeRunManager
    connection = RevisionConnection()
    monkeypatch.setattr(ScheduleAdjustmentService, "_load", lambda *_: recurring_fixture())
    client = TestClient(create_app(connection_factory=lambda: connection, run_manager=FakeRunManager()))
    endpoint = "/api/runs/7/adjustment-options"
    params = dict(part_code="P0", stability_group_no=1, scope="SINGLE_SESSION", week_number=1)
    assert client.get(endpoint, params=params).status_code == 200
    assert client.get(endpoint, params={**params, "scope": "BAD"}).status_code == 422
    assert client.get(endpoint, params={**params, "week_number": 3}).status_code == 409
    payload = single_request().model_dump()
    assert client.post("/api/runs/7/schedule-revisions", json={**payload, "week_number": None}).status_code == 422
    response = client.post("/api/runs/7/schedule-revisions", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["scope"] == "SINGLE_SESSION"
    html = client.get("/").text
    assert 'id="adjustment-scope"' in html
    assert "Chỉ buổi này" in html and "Toàn bộ các tuần hoạt động" in html
