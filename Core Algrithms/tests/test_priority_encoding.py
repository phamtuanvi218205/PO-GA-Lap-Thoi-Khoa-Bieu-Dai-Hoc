"""Priority feasibility mặc định và tương thích decoder mềm lịch sử."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from math import isclose
from pathlib import Path
from threading import Barrier

import pytest

from gapo_timetabling.core import decoder as decoder_module, fitness
from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.decoder import (
    DIRECT_ENCODING, PRIORITY_ENCODING, DEFAULT_ENCODING, clear_decode_cache,
    decode_direct_vector, decode_saved_vector, decode_vector,
)
from gapo_timetabling.core.encoder import build_option_domains
from gapo_timetabling.core.hybrid import HybridConfig, run_hybrid
from gapo_timetabling.core.ga import run_ga
from gapo_timetabling.core.po import run_po
from gapo_timetabling.core.population import CandidateEvaluationConfig, initialize_population
from gapo_timetabling.core.priority_decoder import PriorityDecoder
from gapo_timetabling.core.placement_decoder import PlacementDecoder
from gapo_timetabling.core.snapshot import prepare_snapshot_for_optimization
from gapo_timetabling.application.run_contract import load_run_request
from tests import test_dynamic_lecturer_assignment as fixture_module


def inputs():
    problem = fixture_module.TestDynamicLecturerAssignment().build_problem(first_lecturer_unavailable=False)
    return problem, build_option_domains(problem), CandidateEvaluationConfig(1000, True, 3)


def stable_result(result):
    payload = asdict(result)
    payload['metrics'].pop('runtime_seconds')
    return payload


def test_priority_order_tie_break_and_preservation():
    problem, domains, _ = inputs()
    decoder = PlacementDecoder()
    vector = (.1,) * problem.assignment_dimension + (.5,) * problem.schedule_dimension + (0.,) * problem.schedule_dimension
    result = decoder(problem, domains, vector, 1000)
    assert result.is_success and result.repaired_vector == vector
    assert result == decoder(problem, domains, vector, 1000)
    assert decoder.last_order == tuple(sorted(
        range(problem.schedule_dimension),
        key=lambda group: min(problem.class_sessions[i].class_session_id
                              for i in problem.schedule_groups[group]),
    ))
    reversed_vector = vector[:problem.assignment_dimension] + tuple(
        (problem.schedule_dimension - group) / (problem.schedule_dimension + 1)
        for group in range(problem.schedule_dimension)
    )
    reversed_vector += vector[problem.placement_gene_offset:]
    decoder(problem, domains, reversed_vector, 1000)
    assert decoder.last_order == tuple(reversed(range(problem.schedule_dimension)))


def test_default_entry_point_is_feasibility_priority_not_direct():
    problem, domains, _ = inputs()
    vector = (.1,) * problem.dimension
    assert decode_vector(problem, domains, vector, 1000) == PlacementDecoder()(problem, domains, vector, 1000)


@pytest.mark.parametrize('algorithm', ('GA', 'PO', 'GA_PO'))
def test_all_three_optimizers_replay_without_rewriting_priority(algorithm):
    problem, domains, evaluation = inputs()
    initial = initialize_population(problem, domains, 6, 1000, 44, evaluation)
    assert initial.is_success
    config = HybridConfig(24, 3, 44, evaluation, ga_ratio=0.5)
    if algorithm == 'GA':
        run = lambda: run_ga(problem, domains, initial, config.create_ga_config())
    elif algorithm == 'PO':
        run = lambda: run_po(problem, domains, initial, config.create_po_config())
    else:
        run = lambda: run_hybrid(problem, domains, initial, config)
    first, second = run(), run()
    assert stable_result(first) == stable_result(second)
    assert first.metrics.fitness_evaluations <= 24
    for item in first.final_population + (first.best_individual,):
        replay = decode_vector(problem, domains, item.vector, 1000)
        assert replay.selected_options == item.selected_options
        assert replay.repaired_vector == item.vector
        assert validate_timetable(problem, replay.selected_options).is_valid


@pytest.mark.parametrize('case', ('small', 'medium', 'large'))
def test_real_snapshot_replay_and_partial_score_matches_final_fitness(case):
    root = Path(__file__).resolve().parents[1]
    request = load_run_request(root / f'benchmark_configs/distributed/request_{case}_2027_HK1.json')
    prepared = prepare_snapshot_for_optimization(request.snapshot.path, expected_checksum=request.snapshot.checksum)
    problem, domains = prepared.problem, prepared.option_domains
    initial = initialize_population(problem, domains, 2, 30000, 39001, request.evaluation_config)
    assert initial.is_success
    item = initial.individuals[0]
    decoder = PlacementDecoder()
    replay = decoder(problem, domains, item.vector, 20000)
    assert replay.selected_options == item.selected_options
    direct = decode_direct_vector(problem, domains, decoder.direct_vector(problem, domains, item), 20000)
    assert direct.selected_options == item.selected_options
    assert fitness.calculate_fitness(problem, replay.selected_options, domains) == item.fitness
    for group in problem.schedule_groups:
        assert len({(item.selected_options[i].teaching_date.isoweekday(),
                     item.selected_options[i].start_period,
                     item.selected_options[i].location_index) for i in group}) == 1
    context = decoder.context
    by_section, _, _ = decoder_module._select_lecturers(problem, item.vector)
    teachers = [by_section[part.section_code] for part in context.parts]
    assigned = {}
    for group, sessions in enumerate(problem.schedule_groups):
        target = tuple(item.selected_options[i] for i in sessions)
        assigned[group] = next(i for i, pattern in enumerate(context.patterns[group, teachers[group]])
                               if pattern.session_options == target)
    last = max(assigned)
    index = assigned.pop(last)
    # Chỉ hậu kiểm công thức của decoder SOFT lịch sử; decoder mặc định phía
    # trên không gọi các hàm này khi xây lịch.
    score = decoder._score(problem, context, assigned, teachers, last, index,
                           decoder._state(problem, context, assigned, teachers))
    expected_general = item.fitness.general_quality_score - (
        fitness._get_soft_weight(problem, 'SOFT_WORKLOAD_BALANCE')
        * item.fitness.breakdown.workload_balance_component
    )
    assert isclose(score[0], expected_general, abs_tol=1e-12)
    time_weight = fitness._get_soft_weight(problem, 'SOFT_LECTURER_TIME_PREFERENCE')
    suitability_weight = fitness._get_soft_weight(problem, 'SOFT_COURSE_SUITABILITY')
    expected_time = (item.fitness.lecturer_preference_score * (time_weight + suitability_weight)
                     - suitability_weight * item.fitness.breakdown.course_suitability_component) / time_weight
    assert isclose(score[1], expected_time, abs_tol=1e-12)


def test_cache_cold_hot_and_new_snapshot_do_not_change_answer():
    problem, domains, _ = inputs()
    vector = (.1,) * problem.dimension
    first = decode_vector(problem, domains, vector, 1000)
    assert first == decode_vector(problem, domains, vector, 1000)
    clear_decode_cache()
    assert first == decode_vector(problem, domains, vector, 1000)
    blocked = replace(problem, lecturers=tuple(replace(x, max_teaching_periods=1) for x in problem.lecturers))
    failure = decode_vector(blocked, build_option_domains(blocked), vector, 1000)
    assert not failure.is_success and 'vượt giới hạn' in failure.reason
    assert first == decode_vector(problem, domains, vector, 1000)


def test_thread_local_cache_does_not_share_search_or_context():
    problem, domains, _ = inputs()
    barrier = Barrier(2)
    def worker():
        clear_decode_cache()
        result = decode_vector(problem, domains, (.1,) * problem.dimension, 1000)
        context_id = id(decoder_module._PRIORITY_LOCAL.decoder.context)
        barrier.wait(timeout=10)
        return context_id, result
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda _: worker(), range(2)))
    assert a[0] != b[0] and a[1] == b[1]


def test_saved_vector_dispatches_by_explicit_encoding():
    problem, domains, _ = inputs()
    vector = (.1,) * problem.dimension
    old = vector[:problem.placement_gene_offset]
    assert decode_saved_vector(problem, domains, old, 1000) == decode_direct_vector(problem, domains, old, 1000)
    assert decode_saved_vector(problem, domains, old, 1000, encoding=DIRECT_ENCODING) == decode_direct_vector(problem, domains, old, 1000)
    assert decode_saved_vector(problem, domains, old, 1000, encoding=PRIORITY_ENCODING) == PriorityDecoder()(problem, domains, old, 1000)
    assert decode_saved_vector(problem, domains, vector, 1000, encoding=DEFAULT_ENCODING) == decode_vector(problem, domains, vector, 1000)
    with pytest.raises(ValueError, match='biểu diễn'):
        decode_saved_vector(problem, domains, vector, 1000, encoding='UNKNOWN')


def test_priority_still_has_many_to_one_mapping():
    problem, domains, _ = inputs()
    a = (.1,) * problem.assignment_dimension + tuple((g + 1) / (problem.schedule_dimension + 2)
                                                     for g in range(problem.schedule_dimension))
    b = a[:problem.assignment_dimension] + tuple(.1 + .8 * x for x in a[problem.assignment_dimension:])
    a += (0.,) * problem.schedule_dimension
    b += (0.,) * problem.schedule_dimension
    assert a != b
    assert decode_vector(problem, domains, a, 1000).selected_options == decode_vector(problem, domains, b, 1000).selected_options
