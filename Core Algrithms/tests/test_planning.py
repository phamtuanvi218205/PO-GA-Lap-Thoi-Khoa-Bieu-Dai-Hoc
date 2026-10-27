"""Kiểm thử tương đương cho nghiệp vụ planning được chuyển từ Java."""

from __future__ import annotations

from collections import Counter

import pytest

from gapo_timetabling.core.models import LocationType, ScenarioScopeType, TeachingPlanStatus
from gapo_timetabling.application.planning import (
    AutomaticScenarioRequest,
    ExpandedClassSession,
    GeneratedTeachingPlan,
    GeneratedTeachingPlanItem,
    PlanningScenarioCandidatePlanner,
    ScenarioPlanCandidate,
    SessionExpander,
    TeachingPlanGenerationRequest,
    TeachingPlanGenerator,
)


def test_generator_creates_valid_lecture_plans_from_discrete_rule() -> None:
    request = TeachingPlanGenerationRequest(
        "JAVA01_LT", 45, 1, 15, (3, 6), 2, True, 100
    )
    plans = TeachingPlanGenerator().generate(request)

    assert plans
    for plan in plans:
        assert plan.status == TeachingPlanStatus.VALID
        assert plan.total_periods == 45
        assert all(1 <= item.week_number <= 15 for item in plan.items)
        assert all(item.duration_periods in (3, 6) for item in plan.items)
        assert max(Counter(item.week_number for item in plan.items).values()) <= 2

    assert any(
        len(plan.items) == 15
        and all(item.duration_periods == 3 for item in plan.items)
        and not plan.intensive
        for plan in plans
    )
    assert any(
        sum(item.duration_periods == 3 for item in plan.items) == 5
        and sum(item.duration_periods == 6 for item in plan.items) == 5
        for plan in plans
    )


def test_generator_creates_valid_practice_compositions() -> None:
    request = TeachingPlanGenerationRequest(
        "JAVA01_TH", 30, 1, 15, (5, 6), 1, True, 100
    )
    plans = TeachingPlanGenerator().generate(request)

    assert any(len(plan.items) == 6 and all(item.duration_periods == 5 for item in plan.items) for plan in plans)
    assert any(len(plan.items) == 5 and all(item.duration_periods == 6 for item in plan.items) for plan in plans)
    assert all(plan.total_periods == 30 for plan in plans)

    # Mọi tuần nằm giữa tuần bắt đầu và kết thúc đều phải có buổi học.
    for plan in plans:
        active_weeks = sorted({item.week_number for item in plan.items})
        assert active_weeks == list(range(active_weeks[0], active_weeks[-1] + 1))

    # Cùng cấu trúc 6 buổi x 5 tiết có thể trượt đến mọi cửa sổ hợp lệ,
    # trong đó có ví dụ tuần 7-12 đã được chốt ở tầng nghiệp vụ.
    assert any(
        [item.week_number for item in plan.items] == [7, 8, 9, 10, 11, 12]
        and all(item.duration_periods == 5 for item in plan.items)
        for plan in plans
    )
    assert all(plan.items[-1].week_number <= 15 for plan in plans)


def test_generator_respects_intensive_flag_determinism_and_limit() -> None:
    request = TeachingPlanGenerationRequest(
        "JAVA01_TH", 30, 1, 15, (6, 5, 5), 1, False, 3
    )
    generator = TeachingPlanGenerator()
    first = generator.generate(request)
    second = generator.generate(request)

    assert first == second
    assert len(first) == 3
    assert [plan.sequence_number for plan in first] == [1, 2, 3]
    assert all(not plan.intensive for plan in first)
    assert [[item.week_number for item in plan.items] for plan in first] == [
        [1, 2, 3, 4, 5, 6],
        [2, 3, 4, 5, 6, 7],
        [3, 4, 5, 6, 7, 8],
    ]
    assert len({plan.items for plan in first}) == len(first)


def test_generator_returns_empty_when_total_cannot_be_composed() -> None:
    request = TeachingPlanGenerationRequest(
        "IMPOSSIBLE", 7, 1, 15, (3, 6), 1, True, 20
    )
    assert TeachingPlanGenerator().generate(request) == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_week_number": 15, "end_week_number": 1},
        {"allowed_durations": (3, 0)},
        {"max_sessions_per_week": 0},
        {"max_candidate_plans": 0},
    ],
)
def test_generation_request_validates_boundary(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "part_code": "JAVA01_LT",
        "total_periods": 45,
        "start_week_number": 1,
        "end_week_number": 15,
        "allowed_durations": (3, 6),
        "max_sessions_per_week": 1,
        "allows_intensive": False,
        "max_candidate_plans": 20,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        TeachingPlanGenerationRequest(**values)  # type: ignore[arg-type]


def test_session_expander_preserves_week_duration_and_stability_group() -> None:
    plan = GeneratedTeachingPlan(
        1,
        "JAVA01_LT_AUTO_01",
        "Tự động: 3 buổi x 3 tiết",
        False,
        (
            GeneratedTeachingPlanItem(1, 1, 1, 3, 1),
            GeneratedTeachingPlanItem(2, 2, 1, 3, 1),
            GeneratedTeachingPlanItem(3, 3, 1, 3, 1),
        ),
    )
    sessions = SessionExpander().expand(plan, LocationType.PHYSICAL_ROOM)

    assert len(sessions) == 3
    assert sessions[1] == ExpandedClassSession(
        2, 2, 3, 1, LocationType.PHYSICAL_ROOM
    )


def test_scenario_planner_is_bounded_and_deterministic() -> None:
    candidates = {
        1: (
            ScenarioPlanCandidate(1, 11, 1, False),
            ScenarioPlanCandidate(1, 12, 2, True),
            ScenarioPlanCandidate(1, 13, 3, True),
        ),
        2: (
            ScenarioPlanCandidate(2, 21, 1, False),
            ScenarioPlanCandidate(2, 22, 2, False),
        ),
    }
    planner = PlanningScenarioCandidatePlanner()
    selections = planner.generate(candidates, 4)

    assert selections == planner.generate(candidates, 4)
    assert len(selections) == 4
    assert [plan.teaching_plan_id for plan in selections[0].plans] == [11, 21]
    assert selections[0].plan_rank_penalty == 0
    assert [selection.candidate_rank for selection in selections] == [1, 2, 3, 4]


def test_scenario_request_enforces_scope_contract() -> None:
    request = AutomaticScenarioRequest("HK1", ScenarioScopeType.FULL_TERM)
    assert request.max_scenario_candidates == 10

    with pytest.raises(ValueError):
        AutomaticScenarioRequest("HK1", ScenarioScopeType.SUBSET)
    with pytest.raises(ValueError):
        AutomaticScenarioRequest("HK1", ScenarioScopeType.FULL_TERM, frozenset({1}))
