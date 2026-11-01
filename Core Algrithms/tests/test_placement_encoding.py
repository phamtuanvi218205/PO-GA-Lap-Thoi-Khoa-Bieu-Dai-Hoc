"""Hợp đồng production Priority + Placement; không phụ thuộc thư mục thử nghiệm."""

from dataclasses import replace
from random import Random
from unittest.mock import patch

import pytest

from gapo_timetabling.core import fitness
from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.decoder import (
    DEFAULT_ENCODING, PRIORITY_ENCODING, decode_saved_vector, decode_vector,
)
from gapo_timetabling.core.placement_decoder import PlacementDecoder, relative_indices
from gapo_timetabling.core.models import SessionOption
from gapo_timetabling.core.repair import repair_vector
from tests.priority_scenarios import make_priority_repair_case
from tests.test_constraints import ConstraintFixture


def fixture():
    value = ConstraintFixture()
    value.setUp()
    return value


@pytest.mark.parametrize('key,count,expected', (
    (.73, 5, (3, 4, 2, 1, 0)), (1., 5, (4, 3, 2, 1, 0)),
    (0., 3, (0, 1, 2)), (.2, 0, ()), (.8, 1, (0,)),
))
def test_relative_rank_boundaries_and_nearest_hard_fallback(key, count, expected):
    assert relative_indices(key, count) == expected


def test_placement_rank_uses_current_feasible_list_not_static_options():
    f = fixture()
    problem = f.problem
    first = tuple(SessionOption(0, 0, f.tuesday.calendar_date, a, a+2) for a in (1, 4, 7))
    domains = (first, tuple(replace(o, session_index=1) for o in first),
               (replace(f.valid_options[2], location_index=1),), (f.valid_options[3],))
    decoder = PlacementDecoder()
    a = decoder(problem, domains, (0., .2, .4, .6, 0., .6, 0., 0.), 100)
    first_decision = {d['group']: d for d in decoder.last_decisions}[1]
    b = decoder(problem, domains, (0., .2, .4, .6, 1., .6, 0., 0.), 100)
    second_decision = {d['group']: d for d in decoder.last_decisions}[1]
    assert a.is_success and b.is_success
    assert a.selected_options[1].start_period == 7
    assert b.selected_options[1].start_period == 4
    assert first_decision['feasible_count'] == second_decision['feasible_count'] == 2
    assert first_decision['preferred_rank'] == second_decision['preferred_rank'] == 1
    assert first_decision['preferred_raw_pattern'] != second_decision['preferred_raw_pattern']


def test_backtracking_is_hard_only_preserves_all_keys_and_is_repeatable():
    problem, domains, priority = make_priority_repair_case(fixture())
    vector = priority + (0.,) * problem.schedule_dimension
    engine = PlacementDecoder()
    with patch.object(engine, '_score', side_effect=AssertionError('soft scoring')):
        with patch.object(engine, '_state', side_effect=AssertionError('partial fitness')):
            with patch.object(fitness, 'calculate_fitness', side_effect=AssertionError('full fitness')):
                failed = engine(problem, domains, vector, 4)
                result = engine(problem, domains, vector, 100)
                repeated = engine(problem, domains, vector, 100)
    assert not failed.is_success and failed.nodes_explored == 4
    assert result.is_success and result == repeated
    assert result.repaired_vector == vector and result.backtracks > 0
    assert sum(d['overridden'] for d in engine.last_decisions) == 1
    assert engine.stats['soft_option_scores'] == engine.stats['pattern_features_built'] == 0
    assert validate_timetable(problem, result.selected_options).is_valid
    repair = repair_vector(problem, domains, vector, failed, 2, 4)
    assert repair.is_success
    assert repair.decode_result.repaired_vector[problem.placement_gene_offset:] == vector[problem.placement_gene_offset:]


def test_new_entry_point_rejects_old_shape_instead_of_inventing_placement_keys():
    problem, domains, priority = make_priority_repair_case(fixture())
    with pytest.raises(ValueError, match='gene'):
        decode_vector(problem, domains, priority, 100)
    old = decode_saved_vector(problem, domains, priority, 100, encoding=PRIORITY_ENCODING)
    assert old.is_success and old.repaired_vector == priority
    with pytest.raises(ValueError, match='gene'):
        decode_saved_vector(problem, domains, priority, 100, encoding=DEFAULT_ENCODING)


def test_different_chromosomes_can_produce_different_soft_fitness():
    from gapo_timetabling.core.encoder import build_option_domains
    problem = fixture().problem
    domains = build_option_domains(problem)
    rng = Random(33001)
    schedules = set()
    scores = set()
    for _ in range(24):
        vector = tuple(rng.random() for _ in range(problem.dimension))
        result = decode_vector(problem, domains, vector, 1000)
        assert result.is_success
        schedules.add(result.selected_options)
        scores.add(fitness.calculate_fitness(problem, result.selected_options, domains).fitness_key)
    assert len(schedules) > 1 and len(scores) > 1
