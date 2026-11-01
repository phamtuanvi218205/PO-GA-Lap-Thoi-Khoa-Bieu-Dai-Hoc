"""Không diễn giải hoặc trộn nhầm kết quả DIRECT cũ với priority mới."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from gapo_timetabling.application import distributed_benchmark as distributed
from gapo_timetabling.application import experiment
from gapo_timetabling.application.optimization_service import (
    OptimizationRunConfig, _optimization_config_payload, optimization_config_from_json,
)
from gapo_timetabling.application.run_contract import execute_run_request, parse_run_request
from gapo_timetabling.core.decoder import DIRECT_ENCODING, PRIORITY_ENCODING, DEFAULT_ENCODING, SOFT_PRIORITY_ENCODING, decode_saved_vector
from gapo_timetabling.core.models import OptimizationAlgorithm
from gapo_timetabling.core.snapshot import prepare_snapshot_for_optimization
from tests.test_run_contract import make_run_request_payload
from tests.test_snapshot import make_snapshot_payload


@pytest.mark.parametrize('algorithm', ('GA', 'PO', 'GA_PO'))
def test_completed_result_tags_priority_and_replays_exactly(tmp_path, algorithm):
    snapshot = tmp_path / 'snapshot.json'
    snapshot.write_text(json.dumps(make_snapshot_payload()), encoding='utf-8')
    request = parse_run_request(make_run_request_payload(str(snapshot), algorithm=algorithm), base_directory=tmp_path)
    result = execute_run_request(request)
    assert result['status'] == 'COMPLETED' and result['solver_pipeline'] == DEFAULT_ENCODING
    solution = result['result']['best_solution']
    assert solution['vector_encoding'] == DEFAULT_ENCODING
    prepared = prepare_snapshot_for_optimization(snapshot)
    assert prepared.gene_option_mapping['schema_version'] == 'gene-option-mapping.v5'
    assert prepared.gene_option_mapping['vector_encoding'] == DEFAULT_ENCODING
    assert all(g['gene_type'] == 'RECURRING_PRIORITY' for g in prepared.gene_option_mapping['genes'])
    replay = decode_saved_vector(prepared.problem, prepared.option_domains, tuple(solution['vector']),
                                 100, encoding=solution['vector_encoding'])
    assert replay.is_success and list(replay.selected_option_indices) == solution['selected_option_indices']


@pytest.mark.parametrize('old_pipeline', (None, PRIORITY_ENCODING, SOFT_PRIORITY_ENCODING))
def test_pending_config_has_pipeline_and_rejects_legacy_resume(old_pipeline):
    config = OptimizationRunConfig(algorithm=OptimizationAlgorithm.GA_PO, population_size=4, ga_ratio=0.5,
                                   max_fitness_evaluations=8, random_seed=42,
                                   algorithm_version='test', max_initialization_attempts=20,
                                   max_offspring_attempts=2)
    payload = _optimization_config_payload(config)
    assert optimization_config_from_json(json.dumps(payload)) == config
    payload.pop('solver_pipeline')
    if old_pipeline is not None:
        payload['solver_pipeline'] = old_pipeline
    with pytest.raises(ValueError, match='Run chờ'):
        optimization_config_from_json(json.dumps(payload))


def tiny_config(tmp_path):
    snapshot = tmp_path / 'snapshot.json'
    snapshot.write_text(json.dumps(make_snapshot_payload()), encoding='utf-8')
    request = tmp_path / 'request.json'
    request.write_text(json.dumps(make_run_request_payload(str(snapshot))), encoding='utf-8')
    return experiment.ExperimentConfig(
        experiment_id='priority-test', base_request_path=request,
        algorithms=(OptimizationAlgorithm.GA,), seeds=(1,),
        include_greedy_baseline=False, create_plots=False,
    )


def test_experiment_refuses_to_overwrite_or_resume_legacy_results(tmp_path):
    config = tiny_config(tmp_path)
    run = tmp_path / 'output/runs/GA/seed_1.json'
    run.parent.mkdir(parents=True)
    run.write_text(json.dumps({'status': 'COMPLETED', 'algorithm': 'GA'}), encoding='utf-8')
    original = run.read_bytes()
    for resume in (True, False):
        with patch.object(experiment, 'execute_run_request') as optimizer:
            with pytest.raises(experiment.ExperimentContractError, match='pipeline cũ'):
                experiment.run_experiment(config, tmp_path / 'output', resume_completed=resume)
            optimizer.assert_not_called()
        assert run.read_bytes() == original


def test_worker_refuses_old_output_before_touching_manifest(tmp_path):
    manifest = tmp_path / 'worker_manifest.json'
    manifest.write_text(json.dumps({'status': 'COMPLETED'}), encoding='utf-8')
    original = manifest.read_bytes()
    suite = distributed.DistributedBenchmarkSuite('test', ())
    with patch.object(distributed, '_git_source_state', return_value={'git_revision': 'same', 'git_dirty': False}):
        with pytest.raises(experiment.ExperimentContractError, match='output-root mới'):
            distributed.run_worker_suite(suite, OptimizationAlgorithm.GA, tmp_path)
    assert manifest.read_bytes() == original


def test_merge_rejects_mixed_pipeline_before_copying_any_result(tmp_path):
    roots = []
    for algorithm in OptimizationAlgorithm:
        root = tmp_path / algorithm.value
        root.mkdir()
        payload = dict(schema_version=distributed.WORKER_MANIFEST_SCHEMA_VERSION,
                       suite_id='test', status='COMPLETED', worker=algorithm.value,
                       environment={'git_revision': 'same', 'git_dirty': False})
        if algorithm is OptimizationAlgorithm.GA:
            payload['solver_pipeline'] = PRIORITY_ENCODING
        (root / 'worker_manifest.json').write_text(json.dumps(payload), encoding='utf-8')
        roots.append(root)
    with pytest.raises(experiment.ExperimentContractError, match='encode/decode khác'):
        distributed._load_worker_manifests(distributed.DistributedBenchmarkSuite('test', ()), roots)


@pytest.mark.parametrize('encoding', (DIRECT_ENCODING, PRIORITY_ENCODING, SOFT_PRIORITY_ENCODING, DEFAULT_ENCODING))
def test_timetable_plot_replays_saved_encoding_not_current_default(tmp_path, encoding):
    from gapo_timetabling.core.decoder import historical_problem
    from gapo_timetabling.core.priority_decoder import PriorityDecoder
    from gapo_timetabling.core import decoder as decoder_module

    config = tiny_config(tmp_path)
    run = tmp_path / 'output/runs/GA/seed_1.json'
    run.parent.mkdir(parents=True)
    request = parse_run_request(make_run_request_payload(str(tmp_path / 'snapshot.json'), algorithm='GA'),
                                base_directory=tmp_path)
    prepared = prepare_snapshot_for_optimization(request.snapshot.path)
    if encoding != DEFAULT_ENCODING:
        prepared = replace(prepared, problem=historical_problem(prepared.problem))
    # Generate a genuine legacy result using its original dimension and decoder.
    engine = PriorityDecoder(soft=encoding == SOFT_PRIORITY_ENCODING)
    decoder_module.clear_decode_cache()
    try:
        if encoding != DEFAULT_ENCODING:
            decoder_module._PRIORITY_LOCAL.decoder = engine
        with patch('gapo_timetabling.application.run_contract.prepare_snapshot_for_optimization',
                   return_value=prepared):
            result = execute_run_request(request)
    finally:
        decoder_module.clear_decode_cache()
    solution = result['result']['best_solution']
    if encoding == DIRECT_ENCODING:
        from types import SimpleNamespace
        vector = tuple(solution['vector'])
        decoded = engine(prepared.problem, prepared.option_domains, vector, 100)
        direct = engine.direct_vector(prepared.problem, prepared.option_domains,
                                     SimpleNamespace(vector=vector, selected_options=decoded.selected_options))
        solution['vector'] = list(direct)
        result.pop('solver_pipeline')
        solution.pop('vector_encoding')
    else:
        result['solver_pipeline'] = encoding
        solution['vector_encoding'] = encoding
    run.write_text(json.dumps(result), encoding='utf-8')
    with patch.object(experiment, 'decode_saved_vector', wraps=decode_saved_vector) as replay:
        images, failures = experiment._export_best_timetable_images(config, tmp_path / 'output')
        assert not failures and len(images) == 1
        assert replay.call_args.kwargs['encoding'] == encoding
