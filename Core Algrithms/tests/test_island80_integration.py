"""Production equivalence to the frozen D155 candidate, without a heavy rerun."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
from pathlib import Path
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gapo_timetabling.core import ga, hybrid, decoder
from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.encoder import build_option_domains
from gapo_timetabling.core.placement_decoder import PlacementDecoder
from gapo_timetabling.core.population import CandidateEvaluationConfig, initialize_population
from gapo_timetabling.application.api import OptimizationRunStartRequest
from gapo_timetabling.application.optimization_service import (
    OptimizationRunConfig, _optimization_config_payload, optimization_config_from_json,
)
from gapo_timetabling.core.models import OptimizationAlgorithm
from tests.reference_island80 import run_islands
from tests.test_constraints import ConstraintFixture
from tests import test_dynamic_lecturer_assignment as dynamic_fixture
from tests.test_run_contract import make_run_request_payload
from gapo_timetabling.application.run_contract import parse_run_request
from gapo_timetabling.core.snapshot import prepare_snapshot_for_optimization
from gapo_timetabling.application.distributed_benchmark import load_suite
from gapo_timetabling.application.experiment import load_experiment_config, ExperimentContractError, run_experiment


def inputs(seed=42, dynamic=False, nodes=1000):
    fixture = ConstraintFixture()
    fixture.setUp()
    problem = (dynamic_fixture.TestDynamicLecturerAssignment().build_problem(first_lecturer_unavailable=False)
               if dynamic else fixture.problem)
    domains = build_option_domains(problem)
    evaluation = CandidateEvaluationConfig(nodes, True, 3)
    initial = initialize_population(problem, domains, 10, 1000, seed, evaluation)
    assert initial.is_success
    return problem, domains, initial, hybrid.HybridConfig(110, 5, seed + 1, evaluation)


def stable(result):
    value = asdict(result)
    value['metrics'].pop('runtime_seconds')
    return value


@pytest.mark.parametrize('seed', [1, 7, 42])
@pytest.mark.parametrize('dynamic', [False, True])
def test_exact_frozen_reference_trajectory(seed, dynamic):
    assert sha256(Path(__file__).with_name('reference_island80.py').read_bytes()).hexdigest() == (
        '60082436cb2c3abfb62c25af296ac9f7068ae531a1c5b82aa2f2bb5bc7e0e555')
    problem, domains, initial, config = inputs(seed, dynamic)
    reference, stats = run_islands(problem, domains, initial, config)
    current = hybrid.run_island_hybrid(problem, domains, initial, config)
    # Entire final pool, vector, fitness, FE/fail/backtrack and every history point.
    assert stable(current) == stable(reference)
    assert stats['ga_size'] == 8 and stats['po_size'] == 2
    assert stats['counts']['ga_slots'] == 80 and stats['counts']['po_slots'] == 20
    for item in current.final_population + (current.best_individual,):
        replay = PlacementDecoder()(problem, domains, item.vector, 1000)
        assert replay.selected_options == item.selected_options
        assert replay.selected_option_indices == item.selected_option_indices
        assert validate_timetable(problem, replay.selected_options).is_valid


def test_original_four_po_behaviors_full_chromosome_and_migration_timing():
    problem, domains, initial, config = inputs(481)
    config = replace(config, max_fitness_evaluations=210)
    with patch.object(hybrid, '_create_and_evaluate_po_offspring',
                      wraps=hybrid._create_and_evaluate_po_offspring) as po_step, \
         patch.object(hybrid, '_migrate', wraps=hybrid._migrate) as migration:
        result = hybrid.run_island_hybrid(problem, domains, initial, config)
    assert {call.kwargs['behavior'].value for call in po_step.call_args_list} == {1, 2, 3, 4}
    assert po_step.call_count == 40
    assert all(len(call.kwargs['population_mean']) == problem.dimension
               for call in po_step.call_args_list)
    assert migration.call_count == 18  # two directions at 2,4,...,18, not20.
    assert result.metrics.completed_iterations == 20
    assert result.metrics.fitness_evaluations <= 210


def test_exact_reference_with_official_population_and_generation_budget():
    problem, domains, _, config = inputs(481, dynamic=True)
    initial = initialize_population(problem, domains, 30, 1000, 481, config.evaluation_config)
    assert initial.is_success
    config = replace(config, max_fitness_evaluations=630)
    reference, stats = run_islands(problem, domains, initial, config)
    current = hybrid.run_island_hybrid(problem, domains, initial, config)
    assert stable(current) == stable(reference)
    assert stats['ga_size'] == 24 and stats['po_size'] == 6
    assert stats['counts']['ga_slots'] == 480 and stats['counts']['po_slots'] == 120
    assert len(stats['migrations']) == 9


def test_migration_protects_best_and_skips_duplicate_phenotype():
    def fake(tag, score):
        return SimpleNamespace(vector=(tag,), selected_options=(tag,), fitness_key=(score, 0.))
    best, worst, migrant = fake(1, 0.), fake(2, .5), fake(3, .7)
    assert hybrid._migrate((migrant,), (best, worst)) == ((best, migrant), migrant)
    assert hybrid._migrate((best, worst), (best, worst)) == ((best, worst), None)


def test_no_soft_scores_and_no_global_monkeypatch_with_parallel_jobs():
    args = inputs(481)
    tournament = ga.tournament_select
    engine = PlacementDecoder()
    decoder.clear_decode_cache()
    decoder._PRIORITY_LOCAL.decoder = engine
    try:
        with patch.object(engine, '_score', side_effect=AssertionError('soft score')):
            expected = stable(hybrid.run_island_hybrid(*args))
        assert engine.stats['soft_option_scores'] == 0
    finally:
        decoder.clear_decode_cache()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: stable(hybrid.run_island_hybrid(*args)), range(3)))
    assert all(result == expected for result in results)
    assert ga.tournament_select is tournament


def test_cancel_callback_stops_before_next_offspring():
    args = inputs()
    def stop(progress):
        if progress.metrics.fitness_evaluations > 10:
            raise InterruptedError('cancel')
    with pytest.raises(InterruptedError, match='cancel'):
        hybrid.run_island_hybrid(*args, progress_callback=stop)


def test_default_and_small_population_validation_across_entry_points(tmp_path):
    assert inputs()[3].ga_ratio == .8
    assert hybrid.validate_island_sizes(30, .8) == 24
    with pytest.raises(ValueError, match='two individuals'):
        hybrid.validate_island_sizes(7, .8)
    with pytest.raises(ValueError, match='population_size >= 8'):
        OptimizationRunStartRequest(population_size=4, max_fitness_evaluations=8)
    OptimizationRunStartRequest(algorithm='GA', population_size=2, max_fitness_evaluations=4)
    payload = make_run_request_payload('snapshot.json')
    payload.pop('hybrid')
    assert parse_run_request(payload, base_directory=tmp_path).ga_ratio == .8


def test_pending_old_hybrid_is_not_silently_resumed():
    config = OptimizationRunConfig(
        algorithm=OptimizationAlgorithm.GA_PO, population_size=10,
        max_fitness_evaluations=20, random_seed=1, algorithm_version='test',
        max_initialization_attempts=100, max_offspring_attempts=5,
    )
    payload = _optimization_config_payload(config)
    assert payload['hybrid_mechanism'] == hybrid.HYBRID_MECHANISM
    assert optimization_config_from_json(json.dumps(payload)) == config
    payload.pop('hybrid_mechanism')
    with pytest.raises(ValueError, match='cơ chế lai cũ'):
        optimization_config_from_json(json.dumps(payload))


@pytest.mark.parametrize('case,dimension,occurrences,raw_sha', [
    ('small', 60, 232, '1615e827453cbfa693d502f0c5a017292f5b9b28014b7f45ad25123437c27dd7'),
    ('medium', 90, 343, '6f9fd09dd2503b71f90629a9c5d40ef887cd6fae7cc5e9b8033523e206d8245b'),
    ('large', 120, 454, 'de290ccb769fa9136b46366b321838a0660808acc4880cf040010a311cc27b31'),
])
def test_stress_suite_preserves_d150_snapshot_bytes_and_d155_protocol(case, dimension, occurrences, raw_sha):
    root = Path(__file__).resolve().parents[1] / 'benchmark_configs/stress'
    suite = load_suite(root / 'timetable_stress_suite.json')
    item = next(item for item in suite.cases if item.case_id == case)
    config = load_experiment_config(item.experiment_config_path)
    raw = json.loads(config.base_request_path.read_text(encoding='utf-8'))
    request = parse_run_request(raw, base_directory=root)
    assert sha256(request.snapshot.path.read_bytes()).hexdigest() == raw_sha
    prepared = prepare_snapshot_for_optimization(request.snapshot.path, expected_checksum=request.snapshot.checksum)
    assert item.dimension == prepared.problem.dimension == dimension
    assert item.class_session_count == len(prepared.problem.class_sessions) == occurrences
    assert config.seeds == tuple(range(1, 11))
    assert request.ga_ratio == .8
    assert request.population_size == 30 and request.max_fitness_evaluations == 630
    assert request.max_offspring_attempts == 5 and request.max_initialization_attempts == 30000
    assert request.evaluation_config.max_decode_nodes == 20000


def test_sequential_resume_refuses_old_hybrid_even_with_current_encoder(tmp_path):
    root = Path(__file__).resolve().parents[1] / 'benchmark_configs/stress'
    config = load_experiment_config(root / 'experiment_small.json')
    output = tmp_path / 'runs/GA_PO'
    output.mkdir(parents=True)
    path = output / 'seed_1.json'
    saved = {'solver_pipeline': decoder.DEFAULT_ENCODING, 'algorithm': 'GA_PO'}
    path.write_text(json.dumps(saved), encoding='utf-8')
    with pytest.raises(ExperimentContractError, match='cơ chế lai cũ'):
        run_experiment(config, tmp_path)
    assert json.loads(path.read_text(encoding='utf-8')) == saved
