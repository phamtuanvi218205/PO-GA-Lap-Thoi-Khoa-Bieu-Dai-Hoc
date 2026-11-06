"""TeachingPart assignment through TARGET_PO80, IO and real web workers."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from random import Random
from unittest.mock import patch

import pytest

from gapo_timetabling.application import parallel_execution
from gapo_timetabling.application.optimization_service import (
    OptimizationRunConfig, _optimization_config_payload, optimization_config_from_json,
)
from gapo_timetabling.application.run_contract import (
    execute_prepared_run_request, parse_run_request,
)
from gapo_timetabling.core import po, target_hybrid
from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.decoder import (
    PART_PLACEMENT_ENCODING, PLACEMENT_ENCODING, decode_saved_vector, decode_vector,
)
from gapo_timetabling.core.encoder import build_option_domains
from gapo_timetabling.core.fitness import calculate_fitness
from gapo_timetabling.core.models import OptimizationAlgorithm
from gapo_timetabling.core.population import CandidateEvaluationConfig, evaluate_candidate
from gapo_timetabling.core.snapshot import prepare_snapshot_for_optimization
from tests import test_part_assignment as part_fixture
from tests.test_run_contract import make_run_request_payload
from tests.test_snapshot import make_snapshot_payload


def split_payload():
    """One class, two parts, and disjoint lecturer capabilities."""
    payload = deepcopy(make_snapshot_payload())
    payload.update(schema_version='problem-instance.v3', lecturer_assignment_scope='TEACHING_PART')
    payload['lecturers'].append(dict(payload['lecturers'][0], lecturer_index=1,
        lecturer_code='GV002', full_name='Giảng viên 2'))
    payload['lecturer_course_capabilities'].append(dict(
        payload['lecturer_course_capabilities'][0], lecturer_index=1,
        can_teach_lecture=False, can_teach_practice=True, suitability_score=.7))
    payload['teaching_parts'].append(dict(payload['teaching_parts'][0],
        teaching_part_index=1, teaching_part_id=12, part_code='JAVA01-TH', part_type='PRACTICE'))
    payload['teaching_duration_rules'].append(dict(part_type='PRACTICE', duration_periods=3, standard=True))
    payload['teaching_plans'].append(dict(payload['teaching_plans'][0],
        teaching_plan_id=102, plan_code='PLAN-JAVA01-TH-01', teaching_part_index=1))
    payload['scenario']['items'].append(dict(teaching_part_index=1, teaching_plan_id=102))
    payload['class_sessions'].append(dict(payload['class_sessions'][0],
        session_index=1, class_session_id=1002, teaching_plan_id=102))
    return payload


def flexible_problem():
    problem = part_fixture.problem()
    # TH has only lecturer 0; LT can independently select lecturer 0 or 1.
    capabilities = tuple(replace(c, can_teach_lecture=True,
        can_teach_practice=(c.lecturer_index == 0)) for c in problem.lecturer_course_capabilities)
    return replace(problem, lecturer_course_capabilities=capabilities)


def anchor_and_mask():
    problem = flexible_problem()
    domains = build_option_domains(problem)
    evaluation = CandidateEvaluationConfig(1000, True, 3)
    anchor = evaluate_candidate(problem, domains, (.1,) * problem.dimension, evaluation).individual
    assert anchor is not None
    fields = dict(gap_component=0., lecturer_consecutive_component=0.,
        room_discouraged_component=0., workload_balance_component=1., course_suitability_component=0.)
    scored = replace(anchor, fitness=replace(anchor.fitness,
        breakdown=replace(anchor.fitness.breakdown, **fields)))
    # Selecting coordinates must use the existing breakdown, not add hidden FE.
    with patch.object(target_hybrid.fitness, 'calculate_fitness', side_effect=AssertionError('extra FE')):
        mask, affected, reason = target_hybrid.Targeter(problem).choose(scored, Random(42))
    return problem, domains, anchor, mask, affected, reason


def test_target_mask_uses_part_assignment_and_does_not_expand_to_sibling_part():
    problem, _, _, mask, affected, reason = anchor_and_mask()
    assert reason == 'workload'
    assert target_hybrid.Targeter(problem).section == list(problem.assignment_keys)
    assert set(mask) == {0, problem.schedule_gene_offset, problem.placement_gene_offset}
    assert affected == frozenset(problem.schedule_groups[0])
    assert 1 not in mask  # TH's lecturer gene remains outside this LT proposal.


@pytest.mark.parametrize('behavior', list(po.PoBehavior))
def test_each_original_po_formula_changes_only_selected_part_coordinates(behavior):
    problem, _, anchor, mask, _, _ = anchor_and_mask()
    actual = target_hybrid.propose(anchor, [anchor] * 6, anchor, mask, 0,
        behavior, 1, .1, .3, Random(91), max_iterations=2)
    selected = tuple(anchor.vector[j] for j in mask)
    mean = tuple(sum(item.vector[j] for item in [anchor] * 6) / 6 for j in mask)
    expected = po.clip_vector_to_unit_interval(po.create_po_position(
        selected, 0, behavior, selected, mean, 1, 2, .1, .3, Random(91)))
    assert tuple(actual[j] for j in mask) == expected
    assert all(actual[j] == anchor.vector[j] for j in range(problem.dimension) if j not in mask)


def test_changing_lt_assignment_does_not_force_th_lecturer_to_change():
    problem = flexible_problem()
    domains = build_option_domains(problem)
    vector = (.1,) * problem.dimension
    before = decode_vector(problem, domains, vector, 1000)
    after = decode_vector(problem, domains, (.9,) + vector[1:], 1000)
    assert before.is_success and after.is_success
    assert before.selected_lecturer_indices == (0, 0)
    assert after.selected_lecturer_indices == (1, 0)
    assert validate_timetable(problem, after.selected_options).is_valid


@pytest.mark.parametrize('method', ['GA', 'PO', 'GA_PO'])
def test_split_part_json_run_and_real_parallel_execution_match(method, monkeypatch):
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS', '2')
    prepared = prepare_snapshot_for_optimization(split_payload())
    assert prepared.problem.assignment_dimension == 2
    request_payload = make_run_request_payload('unused.json', algorithm=method)
    request_payload['max_fitness_evaluations'] = 30
    request = parse_run_request(request_payload, base_directory=Path.cwd())
    serial = execute_prepared_run_request(request, prepared)
    parallel = parallel_execution.execute_web_run_request(request, prepared)
    execution = parallel.pop('execution')
    assert serial['status'] == parallel['status'] == 'COMPLETED'
    assert execution['workers'] == 2
    assert execution['fitness_calls'] == parallel['result']['metrics']['fitness_evaluations']
    assert serial['solver_pipeline'] == PART_PLACEMENT_ENCODING
    best = serial['result']['best_solution']
    assert best['vector_encoding'] == PART_PLACEMENT_ENCODING
    replay = decode_saved_vector(prepared.problem, prepared.option_domains,
        tuple(best['vector']), 100, encoding=best['vector_encoding'])
    assert replay.is_success and replay.selected_lecturer_indices == (0, 1)
    assert list(replay.selected_option_indices) == best['selected_option_indices']
    assert validate_timetable(prepared.problem, replay.selected_options).is_valid
    fitness = calculate_fitness(prepared.problem, replay.selected_options, prepared.option_domains)
    assert fitness.general_quality_score == serial['result']['best_fitness']['general_quality_score']
    assert fitness.lecturer_preference_score == serial['result']['best_fitness']['lecturer_preference_score']
    if method == 'GA_PO':
        counts = serial['result']['hybrid_activity']['counts']
        assert counts['ga_slots'] == 16 and counts['target_slots'] == 4
    for result in (serial, parallel):
        result['result']['metrics'].pop('runtime_seconds')
    assert serial == parallel


def test_decoder_cache_keeps_old_and_new_assignment_scopes_separate():
    current = flexible_problem()
    legacy = part_fixture.dynamic_fixture.TestDynamicLecturerAssignment().build_problem(
        first_lecturer_unavailable=False)

    def evaluate(problem):
        domains = build_option_domains(problem)
        result = decode_vector(problem, domains, (.1,) * problem.dimension, 1000)
        assert result.is_success
        assert len(result.selected_lecturer_indices) == problem.assignment_dimension
        assert validate_timetable(problem, result.selected_options).is_valid
        return problem.dimension

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(evaluate, [current, legacy] * 4)) == [6, 5] * 4


@pytest.mark.parametrize('size', [30, 60])
def test_v3_target_preserves_80_20_slots_for_benchmark_and_demo_sizes(size):
    prepared = prepare_snapshot_for_optimization(split_payload())
    payload = make_run_request_payload('unused.json')
    payload.update(population_size=size, max_fitness_evaluations=size * 3,
        max_initialization_attempts=200)
    request = parse_run_request(payload, base_directory=Path.cwd())
    result = execute_prepared_run_request(request, prepared)
    assert result['status'] == 'COMPLETED'
    data = result['result']
    counts = data['hybrid_activity']['counts']
    assert counts['ga_slots'] == round(size * .8) * 2
    assert counts['target_slots'] == (size - round(size * .8)) * 2
    assert data['metrics']['completed_iterations'] == 2
    assert data['metrics']['fitness_evaluations'] <= size * 3
    assert len(data['best_solution']['vector']) == 6
    assert {row['lecturer_code'] for row in data['timetable_entries']} == {'GV001', 'GV002'}


def test_new_persisted_config_refuses_pending_section_assignment():
    config = OptimizationRunConfig(algorithm=OptimizationAlgorithm.GA_PO,
        population_size=10, max_fitness_evaluations=30, random_seed=42,
        algorithm_version='part-assignment-test', max_initialization_attempts=100,
        max_offspring_attempts=5)
    payload = _optimization_config_payload(config)
    assert payload['solver_pipeline'] == PART_PLACEMENT_ENCODING
    assert optimization_config_from_json(json.dumps(payload)) == config
    payload['solver_pipeline'] = PLACEMENT_ENCODING
    with pytest.raises(ValueError, match='LT/TH'):
        optimization_config_from_json(json.dumps(payload))
