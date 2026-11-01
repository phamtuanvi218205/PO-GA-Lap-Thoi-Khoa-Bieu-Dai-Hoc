"""Read-only replay of D155 ISLAND80 best schedules; never runs an optimizer."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from gapo_timetabling.core.snapshot import prepare_snapshot_for_optimization, canonical_json
from gapo_timetabling.core.placement_decoder import PlacementDecoder
from gapo_timetabling.core.constraints import validate_timetable
from gapo_timetabling.core.fitness import calculate_fitness


def main():
    project = Path(__file__).resolve().parents[1]
    historical = project / 'test_results/island_official_stress_20261101'
    published = project / 'benchmark_results/island80_stress_d155'
    archive = None if historical.exists() else ZipFile(published / 'evidence/d155.zip')
    def historical_bytes(relative):
        return ((historical / relative).read_bytes() if archive is None else archive.read(relative))
    rows = []
    for case in ('small', 'medium', 'large'):
        snapshot = project / f'benchmark_configs/stress/data/{case}.json'
        original = project / f'test_results/scalability_stress_20261101/data/{case}.json'
        if original.exists():
            assert snapshot.read_bytes() == original.read_bytes()
        else:
            with ZipFile(published / 'evidence/d150_inputs.zip') as inputs:
                assert snapshot.read_bytes() == inputs.read(f'data/{case}.json')
        prepared = prepare_snapshot_for_optimization(snapshot)
        problem, domains = prepared.problem, prepared.option_domains
        for seed in range(1, 11):
            raw = historical_bytes(f'runs/{case}/ISLAND80/seed_{seed}.json')
            payload = json.loads(raw)
            checkpoint = json.loads(historical_bytes(f'checkpoints/{case}/ISLAND80/seed_{seed}.json'))
            assert checkpoint['result_sha'] == sha256(raw).hexdigest()
            value = payload['result']
            solution = value['best_solution']
            engine = PlacementDecoder()
            result = engine(problem, domains, tuple(solution['vector']), 20000)
            assert result.is_success and result.repaired_vector == tuple(solution['vector'])
            assert list(result.selected_option_indices) == solution['selected_option_indices']
            assert len(result.selected_options) == len(problem.class_sessions)
            assert validate_timetable(problem, result.selected_options).is_valid
            fitness = asdict(calculate_fitness(problem, result.selected_options, domains))
            assert json.loads(canonical_json(fitness)) == value['best_fitness']
            entries = []
            for option in result.selected_options:
                entries.append(dict(
                    class_session_id=problem.class_sessions[option.session_index].class_session_id,
                    lecturer_code=problem.lecturers[problem.option_lecturer_index(option)].lecturer_code,
                    term_code=problem.term.term_code, teaching_date=option.teaching_date.isoformat(),
                    location_id=problem.locations[option.location_index].location_id,
                    location_type=problem.locations[option.location_index].location_type.value,
                    start_period=option.start_period, end_period=option.end_period))
            assert sorted(entries, key=lambda row: row['class_session_id']) == value['timetable_entries']
            assert engine.stats['soft_option_scores'] == 0
            assert value['metrics']['completed_iterations'] == 20
            assert value['metrics']['fitness_evaluations'] <= 630
            rows.append(dict(case=case, seed=seed, hard_violations=0,
                             soft_queries=0, coverage=len(entries), source_sha=checkpoint['result_sha']))
    if archive is not None:
        archive.close()
    audit = dict(verified=len(rows), optimizer_reruns=0, rows=rows)
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(audit, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(verified=len(rows), hard_violations=0, soft_queries=0, optimizer_reruns=0)))


if __name__ == '__main__':
    main()
