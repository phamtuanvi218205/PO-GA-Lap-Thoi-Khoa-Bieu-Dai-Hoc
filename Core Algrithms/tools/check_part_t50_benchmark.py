"""Read-only preflight for the published TeachingPart/TARGET_PO80 T50 suite."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / "src"))

from gapo_timetabling.application.distributed_benchmark import load_suite
from gapo_timetabling.application.experiment import load_experiment_config
from gapo_timetabling.application.run_contract import parse_run_request
from gapo_timetabling.core.decoder import clear_decode_cache, PART_PLACEMENT_ENCODING, encoding_for_problem
from gapo_timetabling.core.population import initialize_population
from gapo_timetabling.core.snapshot import canonical_json, prepare_snapshot_for_optimization

DEFAULT_SUITE = CORE / "benchmark_configs/target_po80_part_t50/timetable_part_t50_suite.json"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_suite(suite_path: Path = DEFAULT_SUITE) -> dict:
    suite_path = suite_path.resolve()
    root = suite_path.parent
    protocol = read(root / "protocol.json")
    suite = load_suite(suite_path)
    if suite.suite_id != protocol["suite_id"]:
        raise ValueError("Suite ID differs from the locked T50 protocol.")
    if (protocol["population_size"], protocol["iterations"], protocol["fitness_cap"]) != (30, 50, 1530):
        raise ValueError("Expected N30/T50/cap1530, including 30 initial evaluations.")
    expected_source = protocol["package_sha256_lf"]
    actual_source = {
        str(p.relative_to(CORE / "src")).replace("\\", "/"):
        sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for p in (CORE / "src/gapo_timetabling").rglob("*.py")
    }
    if actual_source != expected_source:
        changed = sorted(k for k in actual_source.keys() | expected_source.keys()
                         if actual_source.get(k) != expected_source.get(k))
        raise ValueError("Source differs from the published T50 engine: " + ", ".join(changed))
    if len(protocol["initial_sha256"]) != 30 or len(set(protocol["initial_sha256"].values())) != 30:
        raise ValueError("Expected 30 distinct reference initial-cohort fingerprints.")
    cases = []
    if [c.case_id for c in suite.cases] != ["small", "medium", "large"]:
        raise ValueError("Expected exactly Small/Medium/Large, in that order.")
    for case in suite.cases:
        locked = protocol["cases"][case.case_id]
        snapshot = root / locked["path"]
        if sha256(snapshot.read_bytes()).hexdigest() != locked["file_sha256"]:
            raise ValueError(f"Snapshot bytes changed: {case.case_id}")
        config = load_experiment_config(case.experiment_config_path)
        payload = read(config.base_request_path)
        request = parse_run_request(payload, base_directory=config.base_request_path.parent)
        if request.snapshot.path != snapshot.resolve() or request.snapshot.checksum != locked["snapshot_checksum"]:
            raise ValueError(f"Wrong snapshot reference: {case.case_id}")
        if config.seeds != tuple(range(1, 11)) or [a.value for a in config.algorithms] != ["GA", "PO", "GA_PO"]:
            raise ValueError("Expected three methods and seeds 1-10.")
        if not config.include_greedy_baseline or config.runtime_comparison_valid:
            raise ValueError("Greedy must be included; parallel runtime ranking is invalid.")
        if (request.population_size, request.max_fitness_evaluations,
                request.max_initialization_attempts, request.max_offspring_attempts) != (30, 1530, 30000, 5):
            raise ValueError(f"Wrong search budget: {case.case_id}")
        if payload["evaluation"] != dict(max_decode_nodes=20000, enable_repair=True,
                max_repair_attempts=3, max_decode_nodes_per_repair_attempt=20000):
            raise ValueError(f"Wrong Decoder/Repair budget: {case.case_id}")
        if payload["hybrid"] != dict(mechanism="GA_PO_TARGET_PO80.v1", ga_ratio=0.8):
            raise ValueError("Expected the current TARGET_PO80 hybrid, not the historical island method.")
        if payload["ga"] != dict(tournament_size=3, crossover_probability=0.9,
                crossover_distribution_index=15, mutation_probability=None, mutation_distribution_index=20):
            raise ValueError("GA parameters differ from the recorded T50 study.")
        prepared = prepare_snapshot_for_optimization(snapshot, expected_checksum=request.snapshot.checksum)
        p = prepared.problem
        if not prepared.is_ready or p.lecturer_assignment_scope != "TEACHING_PART":
            raise ValueError("Expected a ready V3 TeachingPart snapshot.")
        if (p.dimension, len(p.teaching_parts), p.schedule_dimension, len(p.class_sessions)) != (
                locked["dimension"], locked["parts"], locked["blocks"], locked["sessions"]):
            raise ValueError(f"Snapshot scale differs from protocol: {case.case_id}")
        if (case.dimension, case.class_session_count) != (p.dimension, len(p.class_sessions)):
            raise ValueError("Suite dimensions disagree with the snapshot.")
        if encoding_for_problem(p) != PART_PLACEMENT_ENCODING:
            raise ValueError("Wrong vector encoding.")
        cases.append(dict(scale=case.case_id, dimension=p.dimension, sessions=len(p.class_sessions)))
    return dict(passed=True, package_files=len(actual_source), cases=cases,
                population=30, iterations=50, fitness_cap=1530,
                optimizer_runs=90, greedy_runs=3, initial_cohort_fingerprints=30)


def verify_initial(scale: str, seed: int, suite_path: Path = DEFAULT_SUITE) -> dict:
    """Regenerate one initial cohort only; never execute an optimizer."""
    root = suite_path.resolve().parent
    protocol = read(root / "protocol.json")
    key = f"{scale}_{seed}"
    if key not in protocol["initial_sha256"]:
        raise ValueError("Initial check must use small/medium/large and a seed from 1 to 10.")
    request_path = root / f"request_{scale}.json"
    request = parse_run_request(read(request_path), base_directory=root)
    prepared = prepare_snapshot_for_optimization(request.snapshot.path, expected_checksum=request.snapshot.checksum)
    clear_decode_cache()
    initial = initialize_population(prepared.problem, prepared.option_domains,
        population_size=30, max_initialization_attempts=30000, seed=seed,
        evaluation_config=request.evaluation_config)
    if len(initial.individuals) != 30:
        raise ValueError(f"Could not regenerate the complete initial cohort: {key}")
    records = [dict(vector=list(i.vector), quality=list(i.fitness_key),
        phenotype=sha256(json.dumps([asdict(o) for o in i.selected_options], sort_keys=True,
            default=str, separators=(",", ":")).encode()).hexdigest()) for i in initial.individuals]
    checksum = sha256(canonical_json({"records": records}).encode("utf-8")).hexdigest()
    if checksum != protocol["initial_sha256"][key]:
        raise ValueError(f"Initial cohort differs from the recorded T50 study: {key}")
    return dict(passed=True, initial=key, initial_sha256=checksum, individuals=30)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--initial", metavar="SCALE:SEED", help="Optional: regenerate one initial cohort; no optimizer")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify_suite(args.suite), ensure_ascii=True, indent=2), flush=True)
        if args.initial:
            scale, seed = args.initial.split(":", 1)
            print(json.dumps(verify_initial(scale, int(seed), args.suite), ensure_ascii=True, indent=2))
    except (OSError, ValueError, KeyError) as error:
        print(f"PRECHECK FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
