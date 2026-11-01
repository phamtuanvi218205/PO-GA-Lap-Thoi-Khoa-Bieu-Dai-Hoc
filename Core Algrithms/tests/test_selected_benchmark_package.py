"""Published evidence stays separate from historical data and future runs."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

CORE = Path(__file__).resolve().parents[1]
PACKAGE = CORE / 'benchmark_results/island80_stress_d155'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def test_published_package_preserves_protocol_labels_and_counts():
    manifest = read(PACKAGE / 'manifest.json')
    assert manifest['historical_methods'] == ['GA', 'PO', 'HYBRID50', 'ISLAND80']
    assert manifest['production_method_mapping'] == {'GA_PO': 'ISLAND80'}
    assert manifest['optimizer_runs'] == 120
    assert manifest['baselines'] == manifest['confirmation_runs'] == 3
    assert manifest['new_optimizer_runs_during_publication'] == 0
    audit = read(PACKAGE / 'sync_audit.json')
    assert audit['passed'] and audit['original_labels_preserved']
    assert audit['optimizer_runs'] == 120 and audit['shared_initial_cohorts'] == 30
    assert audit['baselines'] == audit['confirmation_runs'] == 3


def test_archives_and_accessible_reports_have_published_checksums():
    manifest = read(PACKAGE / 'manifest.json')
    for info in manifest['archives'].values():
        path = PACKAGE / info['path']
        assert sha256(path.read_bytes()).hexdigest() == info['sha256']
        with ZipFile(path) as archive:
            assert set(archive.namelist()) == set(info['members'])
            assert all(not name.startswith(('/', '../')) and '/..' not in name
                       for name in archive.namelist())
    for name, item in manifest['copies'].items():
        assert sha256((PACKAGE / name).read_bytes()).hexdigest() == item['sha256']
    for name, checksum in manifest['current_suite'].items():
        assert sha256((CORE / name).read_bytes()).hexdigest() == checksum


def test_both_endpoints_and_integration_limitations_remain_published():
    audit = read(PACKAGE / 'd155/analysis/independent_audit.json')
    assert audit['comparisons']['final']['GA']['all'] == [16, 0, 14]
    assert audit['comparisons']['final']['PO']['all'] == [17, 0, 13]
    assert audit['comparisons']['common']['PO']['all'] == [13, 0, 17]
    assert audit['full_replay_hard0'] and audit['full_coverage']
    assert audit['soft_queries'] == 0
    confirmation = read(PACKAGE / 'd159/independent_audit.json')
    assert confirmation['passed'] and confirmation['new_optimizer_runs'] == 3
    assert len(confirmation['rows']) == 3
    assert sum(row['fe'] for row in confirmation['rows']) == 1774
    for row in confirmation['rows']:
        assert row['initial_and_all_fe_exact'] and row['result_and_metrics_exact_except_runtime']
