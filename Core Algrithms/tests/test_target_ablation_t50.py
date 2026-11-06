"""Single-factor adapters and portable T50 handoff; no official reruns."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
from random import Random
import subprocess
import sys
from unittest.mock import patch

import pytest

from gapo_timetabling.core import target_hybrid as production
from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.encoder import build_option_domains
from gapo_timetabling.core.hybrid import HybridConfig
from gapo_timetabling.core.population import CandidateEvaluationConfig, initialize_population
from tests.test_part_target_integration import flexible_problem

CORE = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


variants = load("t50_research_variants", CORE / "benchmark/target_ablation_t50/variants.py")
checker = load("t50_suite_checker", CORE / "tools/check_part_t50_benchmark.py")


@pytest.fixture
def toy():
    problem = flexible_problem()
    domains = build_option_domains(problem)
    evaluation = CandidateEvaluationConfig(500, True, 3)
    initial = initialize_population(problem, domains, 30, 5000, 1, evaluation)
    assert initial.is_success
    return problem, domains, initial, HybridConfig(1530, 5, 1, evaluation)


def without_runtime(result):
    return replace(result, metrics=replace(result.metrics, runtime_seconds=0))


def test_published_suite_is_v3_t50_and_locks_49_production_files():
    result = checker.verify_suite()
    assert result["passed"] and result["package_files"] == 49
    assert result["fitness_cap"] == 1530 and result["iterations"] == 50
    assert [(c["dimension"],c["sessions"]) for c in result["cases"]] == [(72,232),(108,343),(144,454)]


def test_full_adapter_path_is_identical_to_production_t50(toy):
    args = toy
    actual = variants.run_variant(*args, variant="FULL")
    expected = production.run_target_hybrid(*args)
    assert without_runtime(actual) == without_runtime(expected)


@pytest.mark.parametrize("variant", variants.VARIANTS)
def test_three_adapters_preserve_t50_budget_population_and_validity(toy, variant):
    result = variants.run_variant(*toy, variant=variant)
    assert result.metrics.completed_iterations == 50
    assert 30 <= result.metrics.fitness_evaluations <= 1530
    assert len(result.convergence_history) == 51
    assert len(result.final_population) == 30
    assert result.hybrid_activity["counts"]["ga_slots"] == 1200
    assert result.hybrid_activity["counts"]["target_slots"] == 300
    assert validate_timetable(toy[0], result.best_individual.selected_options).is_valid


def test_random_formula_control_never_calls_po_formula(toy):
    with patch.object(production.po, "create_po_position", side_effect=AssertionError("PO formula called by RAND")):
        result = variants.run_variant(*toy, variant="TARGET_RAND80")
    assert result.hybrid_activity["counts"]["random_calls"] >= 300
    assert "formula_calls" not in result.hybrid_activity["counts"]
    assert result.hybrid_activity["feedback"] is True


def test_uniform_proposal_changes_only_the_mask(toy):
    anchor = toy[2].individuals[0]
    mask = (0, 2)
    result = variants.uniform_proposal(anchor, [anchor], anchor, mask, 0, None, 1, .1, .2, Random(4), max_iterations=50)
    assert all(result[j] == anchor.vector[j] for j in range(len(result)) if j not in mask)
    assert all(0 <= x < 1 for x in result)


def test_no_feedback_removes_only_second_survivor_inputs(toy):
    original = production.ga.select_survivors
    seen = []

    def observe(parents, children, size):
        seen.append(tuple(children))
        return original(parents, children, size)

    with patch.object(production.ga, "select_survivors", observe):
        result = variants.run_variant(*toy, variant="NO_FEEDBACK")
    assert len(seen) == 100
    assert all(len(seen[i]) == 0 for i in range(1,100,2))
    assert all(len(seen[i]) == 24 for i in range(0,100,2))
    assert result.hybrid_activity["counts"]["injected"] == 0
    assert all(not event["injected"] for event in result.hybrid_activity["events"])
    assert result.hybrid_activity["counts"]["formula_calls"] >= 300


def test_random_group_preserves_type_size_and_keeps_original_po(toy):
    problem, _, initial, _ = toy
    direct = production.Targeter(problem)
    random_group = variants.MatchedRandomTargeter(problem)
    for item in initial.individuals:
        for seed in range(5):
            original, _, reason = direct.choose(item, Random(seed))
            matched, _, matched_reason = random_group.choose(item, Random(seed))
            assert len(original) == len(matched)
            assert reason == matched_reason
            assert sum(j < problem.schedule_gene_offset for j in original) == sum(j < problem.schedule_gene_offset for j in matched)
    with patch.object(production.po, "create_po_position", wraps=production.po.create_po_position) as formula:
        result = variants.run_variant(*toy, variant="RANDOM_GROUP")
    assert formula.call_count > 0
    assert result.hybrid_activity["feedback"] is True


def test_adapters_restore_production_functions_on_exception(toy):
    original_propose, original_targeter = production.propose, production.Targeter
    with patch.object(production, "run_target_hybrid", side_effect=ValueError("test")):
        for variant in variants.VARIANTS:
            with pytest.raises(ValueError, match="test"):
                variants.run_variant(*toy, variant=variant)
    assert production.propose is original_propose
    assert production.Targeter is original_targeter


@pytest.mark.parametrize("forbidden", ["GA", "PO", "FULL", "GA_PO", "GREEDY"])
def test_launcher_cannot_schedule_main_algorithms(tmp_path, forbidden):
    output = tmp_path / "must_not_be_created"
    process = subprocess.run([sys.executable, str(CORE / "tools/run_target_ablation_t50.py"),
        "run", "--variant", forbidden, "--output-root", str(output)], capture_output=True)
    assert process.returncode == 2
    assert not output.exists()


def test_portable_reference_bundle_prepares_without_any_optimizer(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(CORE / "tools"))
    launcher = load("t50_ablation_launcher", CORE / "tools/run_target_ablation_t50.py")
    result = launcher.preflight()
    assert result["rerun_main_algorithms"] == 0 and result["new_greedy_runs"] == 0
    output = launcher.prepare(tmp_path / "prepared", launcher.VARIANTS)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["planned_ablation_runs"] == 90
    assert manifest["reused_full_results"] == 30
    assert not (output / "status.json").exists()
    assert len(list((output / "checkpoints").glob("*.json"))) == 0
    assert len(list((output / "full/checkpoints").glob("*.json"))) == 30
    assert len(list((output / "cohorts").glob("*.pkl"))) == 30
    # The copied worker imports only the frozen package and reads its own
    # hash-locked initial population; this subprocess does not call optimize.
    code = ("import evidence as w; w.verify_source(); "
            "initial,meta=w.load_initial('small',1,w.prepared('small')); "
            "assert len(initial.individuals)==30; print(meta['initial_sha'])")
    process = subprocess.run([sys.executable, "-c", code], cwd=output / "source", capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    assert checker.read(checker.DEFAULT_SUITE.parent / "protocol.json")["initial_sha256"]["small_1"] in process.stdout
    with pytest.raises(FileExistsError):
        launcher.prepare(output, launcher.VARIANTS)


def test_controller_plans_only_90_ablation_jobs_and_can_split_30_per_machine(monkeypatch):
    monkeypatch.syspath_prepend(str(CORE / "benchmark/target_ablation_t50"))
    controller = load("t50_ablation_controller_test", CORE / "benchmark/target_ablation_t50/controller.py")
    tasks = controller.build_tasks(variants.VARIANTS)
    assert len(tasks) == len(set(tasks)) == 90
    assert {m for _,_,m in tasks} == set(variants.VARIANTS)
    for variant in variants.VARIANTS:
        assert len(controller.build_tasks([variant])) == 30
    for forbidden in ([], ["GA"], ["PO"], ["FULL"], ["GREEDY"], ["NO_FEEDBACK", "NO_FEEDBACK"]):
        with pytest.raises(ValueError):
            controller.build_tasks(forbidden)


def test_report_pair_order_and_exact_sign_test(monkeypatch):
    monkeypatch.syspath_prepend(str(CORE / "benchmark/target_ablation_t50"))
    report = load("t50_ablation_report_test", CORE / "benchmark/target_ablation_t50/report.py")
    assert report.compare([.1,.9], [.2,.1]) == "W"
    assert report.compare([.1,.2], [.1,.1]) == "L"
    assert report.compare([.1,.2], [.1,.2]) == "T"
    from collections import Counter
    assert report.sign(Counter(W=25,L=5)) == pytest.approx(.00032491423189640045)
