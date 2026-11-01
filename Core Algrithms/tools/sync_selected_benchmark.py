"""Publish byte-preserving evidence packages; never invokes an optimizer.

--sync copies selected reports and creates compressed archives in a NEW target.
--verify checks every ZIP member hash and all D155 run/checkpoint/cohort links.
The package is self-contained: verification needs no ignored test_results files.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

CORE = Path(__file__).resolve().parents[1]
TARGET = CORE / 'benchmark_results/island80_stress_d155'
SOURCES = {
    'd155': CORE / 'test_results/island_official_stress_20261101',
    'd159': CORE / 'test_results/island80_production_confirmation_d159_20261101',
}


def digest_bytes(value):
    return sha256(value).hexdigest()


def file_sha(path):
    h = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def evidence_files(source):
    # Ignore interpreter caches only; include original logs/progress/source/results.
    return sorted(path for path in source.rglob('*') if path.is_file()
                  and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.tmp'))


def create_package(target=TARGET):
    if (target / 'manifest.json').exists() or (target / 'evidence').exists():
        raise FileExistsError('Published evidence already exists; use --verify, never overwrite it.')
    if read(SOURCES['d155'] / 'status.json')['status'] != 'COMPLETED':
        raise ValueError('D155 not completed.')
    if read(SOURCES['d159'] / 'status.json')['status'] != 'COMPLETED':
        raise ValueError('D159 not completed.')
    if not read(SOURCES['d159'] / 'independent_audit.json')['passed']:
        raise ValueError('D159 independent audit failed.')
    manifest = dict(schema_version='selected-timetable-benchmark-package.v1',
        benchmark='D155', integration_confirmation='D159',
        historical_methods=['GA', 'PO', 'HYBRID50', 'ISLAND80'],
        production_method_mapping={'GA_PO': 'ISLAND80'},
        optimizer_runs=120, baselines=3, confirmation_runs=3,
        new_optimizer_runs_during_publication=0,
        archives={}, copies={}, current_suite={})
    for label, source in SOURCES.items():
        archive_path = target / f'evidence/{label}.zip'
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        members = {}
        with ZipFile(archive_path, 'x', compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for path in evidence_files(source):
                relative = path.relative_to(source).as_posix()
                before = file_sha(path)
                archive.write(path, relative)
                if before != file_sha(path):
                    raise ValueError(f'Source changed while copying: {path}')
                members[relative] = dict(sha256=before, bytes=path.stat().st_size)
                accessible = (path.parent == source or relative.startswith('analysis/')
                              or relative in ('independent_audit.json', 'summary.json')
                              or relative.startswith('checks/'))
                if accessible and path.suffix in ('.md', '.json', '.csv', '.png'):
                    destination = target / label / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists():
                        raise FileExistsError(destination)
                    shutil.copyfile(path, destination)
                    if file_sha(destination) != before:
                        raise ValueError(f'Copy mismatch: {destination}')
                    manifest['copies'][destination.relative_to(target).as_posix()] = dict(
                        archive=label, member=relative, sha256=before)
        manifest['archives'][label] = dict(
            path=archive_path.relative_to(target).as_posix(), sha256=file_sha(archive_path),
            bytes=archive_path.stat().st_size, members=members,
            original_root=source.relative_to(CORE).as_posix())
        print(f'PACKED {label}: {len(members)} files, {archive_path.stat().st_size/1024**2:.1f} MiB', flush=True)
    # Include D150 data/config/witnesses used by D155, independent of ignored roots.
    data_root = CORE / 'test_results/scalability_stress_20261101'
    archive_path = target / 'evidence/d150_inputs.zip'
    members = {}
    with ZipFile(archive_path, 'x', compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for folder in ('data', 'configs'):
            for path in evidence_files(data_root / folder):
                relative = path.relative_to(data_root).as_posix()
                archive.write(path, relative)
                members[relative] = dict(sha256=file_sha(path), bytes=path.stat().st_size)
    manifest['archives']['d150_inputs'] = dict(path='evidence/d150_inputs.zip',
        sha256=file_sha(archive_path), bytes=archive_path.stat().st_size, members=members,
        original_root=data_root.relative_to(CORE).as_posix())
    for path in evidence_files(CORE / 'benchmark_configs/stress'):
        if path.suffix in ('.json', '.md'):
            manifest['current_suite'][path.relative_to(CORE).as_posix()] = file_sha(path)
    write_new(target / 'manifest.json', manifest)
    return verify_package(target)


def verify_package(target=TARGET):
    manifest = read(target / 'manifest.json')
    verified_members = 0
    archives = {}
    try:
        for label, info in manifest['archives'].items():
            path = target / info['path']
            if file_sha(path) != info['sha256']:
                raise ValueError(f'Archive checksum mismatch: {path}')
            archive = ZipFile(path)
            archives[label] = archive
            if set(archive.namelist()) != set(info['members']):
                raise ValueError(f'Member inventory mismatch: {label}')
            for name, expected in info['members'].items():
                data = archive.read(name)
                if len(data) != expected['bytes'] or digest_bytes(data) != expected['sha256']:
                    raise ValueError(f'Member checksum mismatch: {label}/{name}')
                verified_members += 1
        for name, expected in manifest['copies'].items():
            data = (target / name).read_bytes()
            if digest_bytes(data) != expected['sha256']:
                raise ValueError(f'Accessible copy checksum mismatch: {name}')
            if data != archives[expected['archive']].read(expected['member']):
                raise ValueError(f'Accessible copy differs from archived original: {name}')
        for name, checksum in manifest['current_suite'].items():
            if file_sha(CORE / name) != checksum:
                raise ValueError(f'Published current suite changed: {name}')
        old, confirmation = archives['d155'], archives['d159']
        def payload(archive, name):
            return json.loads(archive.read(name))
        counts = dict(optimizer_runs=0, baselines=0, shared_initial_cohorts=0, confirmation_runs=0)
        expected_runs = set()
        expected_details = set()
        expected_checkpoints = set()
        for case in ('small', 'medium', 'large'):
            if archives['d150_inputs'].read(f'data/{case}.json') != (CORE / f'benchmark_configs/stress/data/{case}.json').read_bytes():
                raise ValueError(f'D150 input bytes mismatch: {case}')
            for seed in range(1, 11):
                initial = payload(old, f'initial/{case}/seed_{seed}.json')
                vectors = [row['vector'] for row in initial['records']]
                vector_sha = digest_bytes(json.dumps(vectors, sort_keys=True, separators=(',', ':')).encode())
                assert len(vectors) == 30 and initial['initial_sha'] == vector_sha
                counts['shared_initial_cohorts'] += 1
                for method in ('GA', 'PO', 'HYBRID50', 'ISLAND80'):
                    relative = f'{case}/{method}/seed_{seed}.json'
                    run_name, detail_name, check_name = (f'runs/{relative}', f'details/{relative}', f'checkpoints/{relative}')
                    expected_runs.add(run_name)
                    expected_details.add(detail_name)
                    expected_checkpoints.add(check_name)
                    value, detail, checkpoint = payload(old, run_name), payload(old, detail_name), payload(old, check_name)
                    assert value['status'] == 'COMPLETED' and value['algorithm'] == method
                    assert digest_bytes(old.read(run_name)) == checkpoint['result_sha']
                    assert digest_bytes(old.read(detail_name)) == checkpoint['detail_sha']
                    assert checkpoint['initial_sha'] == detail['initial_sha'] == initial['initial_sha']
                    assert detail['records'][:30] == initial['records']
                    assert detail['hard_violations'] == detail['decoder_work']['soft_option_scores'] == 0
                    result = value['result']
                    assert len(detail['records']) == result['metrics']['fitness_evaluations'] <= 630
                    assert result['metrics']['completed_iterations'] == 20
                    assert len(result['convergence_history']) == 21
                    counts['optimizer_runs'] += 1
            relative = f'{case}/GREEDY_FIRST_FEASIBLE/seed_1.json'
            for prefix, inventory in (('runs', expected_runs), ('details', expected_details), ('checkpoints', expected_checkpoints)):
                inventory.add(f'{prefix}/{relative}')
            baseline, checkpoint = payload(old, f'runs/{relative}'), payload(old, f'checkpoints/{relative}')
            assert baseline['status'] == 'COMPLETED'
            assert digest_bytes(old.read(f'runs/{relative}')) == checkpoint['result_sha']
            assert digest_bytes(old.read(f'details/{relative}')) == checkpoint['detail_sha']
            counts['baselines'] += 1
            fresh, historic = payload(confirmation, f'runs/{case}.json'), payload(old, f'runs/{case}/ISLAND80/seed_1.json')
            a, b = fresh['result'], historic['result']
            for key in a:
                if key != 'metrics':
                    assert a[key] == b[key], (case, key)
            assert {k:v for k,v in a['metrics'].items() if k != 'runtime_seconds'} == {
                k:v for k,v in b['metrics'].items() if k != 'runtime_seconds'}
            new_details = payload(confirmation, f'details/{case}.json')
            old_details = payload(old, f'details/{case}/ISLAND80/seed_1.json')
            assert new_details['records'] == old_details['records']
            assert new_details['dense_trace'] == old_details['dense_trace']
            assert payload(confirmation, f'checks/{case}.json')['passed']
            counts['confirmation_runs'] += 1
        for prefix, expected in (('runs/', expected_runs), ('details/', expected_details), ('checkpoints/', expected_checkpoints)):
            assert {name for name in old.namelist() if name.startswith(prefix)} == expected
        audit = payload(old, 'analysis/independent_audit.json')
        assert audit['full_replay_hard0'] and audit['full_coverage'] and audit['soft_queries'] == 0
        assert audit['comparisons']['final']['GA']['all'] == [16, 0, 14]
        assert audit['comparisons']['final']['PO']['all'] == [17, 0, 13]
        assert audit['comparisons']['common']['PO']['all'] == [13, 0, 17]
        report = dict(passed=True, verified_members=verified_members,
                      accessible_copies=len(manifest['copies']), **counts,
                      optimizer_runs_during_sync=0, original_labels_preserved=True)
        print(json.dumps(report), flush=True)
        return report
    finally:
        for archive in archives.values():
            archive.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--sync', action='store_true')
    action.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    result = create_package() if args.sync else verify_package()
    if args.sync:
        write_new(TARGET / 'sync_audit.json', result)
