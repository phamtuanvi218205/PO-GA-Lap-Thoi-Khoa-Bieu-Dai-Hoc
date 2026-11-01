"""Phân định tính hợp lệ và tối ưu mềm trong priority decoder."""

from dataclasses import replace
from unittest.mock import patch

from gapo_timetabling.core import fitness
from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.decoder import (
    SOFT_PRIORITY_ENCODING, decode_saved_vector, decode_vector,
)
from gapo_timetabling.core.models import AvailabilityType
from gapo_timetabling.core.models import AvailabilityWindow, AvailabilityScopeType
from gapo_timetabling.core.encoder import build_option_domains
from gapo_timetabling.core.priority_decoder import PriorityDecoder
from tests.priority_scenarios import make_priority_repair_case
from tests.test_constraints import ConstraintFixture


def case():
    fixture = ConstraintFixture()
    fixture.setUp()
    problem, domains, priority = make_priority_repair_case(fixture)
    return problem, domains, priority + (0.0,) * problem.schedule_dimension


def test_feasibility_never_scores_soft_options_or_partial_schedule():
    problem, domains, vector = case()
    from gapo_timetabling.core.placement_decoder import PlacementDecoder
    decoder = PlacementDecoder()
    with patch.object(decoder, '_score', side_effect=AssertionError('soft score')):
        with patch.object(decoder, '_state', side_effect=AssertionError('partial state')):
            with patch.object(fitness, 'calculate_fitness', side_effect=AssertionError('full fitness')):
                decoded = decoder(problem, domains, vector, 100)
    assert decoded.is_success and decoded.backtracks > 0
    assert decoder.stats['soft_option_scores'] == 0
    assert decoder.stats['pattern_features_built'] == 0
    assert not decoder.data and not decoder.score_cache and not decoder.preferences
    assert decoded.repaired_vector == vector
    assert validate_timetable(problem, decoded.selected_options).is_valid


def test_preferences_do_not_change_feasibility_decisions():
    problem, domains, vector = case()
    changed = replace(problem, lecturer_availabilities=tuple(
        replace(window, availability_type=AvailabilityType.DISCOURAGED,
                preference_weight=100.) for window in problem.lecturer_availabilities
    ))
    first = decode_vector(problem, domains, vector, 100)
    second = decode_vector(changed, domains, vector, 100)
    assert first.is_success and first.selected_options == second.selected_options
    assert first.nodes_explored == second.nodes_explored


def test_backtracking_respects_budget_and_stops_at_first_feasible_leaf():
    problem, domains, vector = case()
    limited = decode_vector(problem, domains, vector, 4)
    complete = decode_vector(problem, domains, vector, 100)
    assert not limited.is_success and limited.nodes_explored == 4
    assert complete.is_success and complete.backtracks > 0
    assert complete.nodes_explored < 100
    assert complete == decode_vector(problem, domains, vector, 100)


def test_soft_history_has_explicit_separate_replay():
    problem, domains, vector = case()
    vector = vector[:problem.placement_gene_offset]
    assert decode_saved_vector(problem, domains, vector, 100,
                               encoding=SOFT_PRIORITY_ENCODING) == PriorityDecoder(soft=True)(
                                   problem, domains, vector, 100)


def test_order_changes_can_change_fitness_without_soft_selection():
    fixture = ConstraintFixture()
    fixture.setUp()
    problem = replace(fixture.problem, lecturer_availabilities=(AvailabilityWindow(
        resource_index=1, scope_type=AvailabilityScopeType.DATE,
        calendar_date=fixture.tuesday.calendar_date, start_period=1, end_period=3,
        availability_type=AvailabilityType.PREFERRED, preference_weight=1.,
    ),))
    # Một phòng dùng chung làm thứ tự xếp ảnh hưởng giờ của người có ưu tiên.
    domains = tuple(tuple(o for o in domain if o.location_index != 1)
                    for domain in build_option_domains(problem))
    vectors = ((.1, .2, .3, .4), (.4, .3, .2, .1), (.2, .1, .4, .3))
    results = [decode_vector(problem, domains, vector + (0.0,) * problem.schedule_dimension, 1000) for vector in vectors]
    assert all(item.is_success for item in results)
    assert len({item.selected_options for item in results}) > 1
    scores = [fitness.calculate_fitness(problem, item.selected_options, domains) for item in results]
    assert len({(f.general_quality_score, f.lecturer_preference_score) for f in scores}) > 1
