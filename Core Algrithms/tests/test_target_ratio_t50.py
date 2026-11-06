"""Setup-only tests. Never initialize or execute an optimizer."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

CORE = Path(__file__).resolve().parents[1]


def load(name,path):
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def launcher(monkeypatch):
    monkeypatch.syspath_prepend(str(CORE/'tools'))
    return load('ratio_launcher_test',CORE/'tools/run_target_ratio_t50.py')


def test_reference_compatibility_and_exact_design_no_optimizer(launcher):
    from gapo_timetabling.core import target_hybrid
    with patch.object(target_hybrid,'run_target_hybrid',side_effect=AssertionError('optimizer forbidden')):
        result = launcher.preflight()
    assert result['passed'] and result['production_files']==49
    assert result['new_ratio_runs']==60 and result['reused_80_20_runs']==30
    assert result['new_ga_po_greedy_ablation_runs']==0 and not result['optimizer_executed']
    assert result['ratios']==dict(GA70_PO30=.7,GA60_PO40=.6)


def test_running_requires_explicit_compute_ack_without_creating_output(launcher,tmp_path):
    root = tmp_path/'must_not_exist'
    assert launcher.main(['run','--ratio','GA70_PO30','--output-root',str(root)])==1
    assert not root.exists()


@pytest.mark.parametrize('ratio',['GA70_PO30','GA60_PO40'])
def test_prepare_freezes_source_reference_and_has_no_results(launcher,tmp_path,ratio):
    output = launcher.prepare(tmp_path/ratio,[ratio])
    manifest = launcher.read(output/'manifest.json')
    assert manifest['planned_ratio_runs']==30
    assert len(list((output/'cohorts').glob('*.json')))==30
    assert len(list((output/'full/checkpoints').glob('*.json')))==30
    assert not (output/'status.json').exists()
    assert not list((output/'runs').glob('*'))
    with pytest.raises(FileExistsError): launcher.prepare(output,[ratio])
    # Subprocess only loads a saved cohort and constructs configs/task lists.
    code = (
        "import evidence as w; import controller as c; from dataclasses import asdict; "
        "w.verify_source(); initial,meta=w.load_initial('small',1,w.prepared('small')); "
        "assert len(initial.individuals)==30; "
        "a=w.config_for('GA70_PO30',1); b=w.config_for('GA60_PO40',1); "
        "x,y=asdict(a),asdict(b); assert x.pop('ga_ratio')==.7 and y.pop('ga_ratio')==.6 and x==y; "
        "assert len(c.build_tasks(w.METHODS))==60; "
        "assert all(m in w.METHODS for s,k,m in c.build_tasks(w.METHODS)); "
        "print('prepared-only-ok')"
    )
    proc = subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=output/'source',capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    assert 'prepared-only-ok' in proc.stdout
    # Verify the worker delegates to production with only ga_ratio changed.
    # The production runner is replaced by a sentinel BEFORE optimize is called.
    delegate = "\n".join([
        "import evidence as w",
        "from unittest.mock import patch",
        f"method = {ratio!r}",
        "with patch.object(w, 'run_target_hybrid', side_effect=RuntimeError('STOP_BEFORE_OPTIMIZER')) as engine:",
        "    try: w.optimize('small', 1, method)",
        "    except RuntimeError as exc: assert str(exc)=='STOP_BEFORE_OPTIMIZER'",
        "    else: raise AssertionError('Expected sentinel')",
        "    engine.assert_called_once()",
        "    cfg = engine.call_args.args[3]",
        "    assert cfg.ga_ratio == w.RATIOS[method]",
        "    assert cfg.max_fitness_evaluations == 1530 and cfg.max_offspring_attempts == 5",
        "    assert len(engine.call_args.args[2].individuals) == 30",
        "assert not list((w.ROOT/'runs').glob('*'))",
        "assert not list((w.ROOT/'checkpoints').glob('*'))",
        "print('delegation-only-ok')",
    ])
    proc = subprocess.run([sys.executable,'-X','utf8','-c',delegate],cwd=output/'source',capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    assert 'delegation-only-ok' in proc.stdout


def test_invalid_ratio_never_prepares(launcher,tmp_path):
    with pytest.raises(ValueError): launcher.prepare(tmp_path/'invalid',['FULL'])
    assert not (tmp_path/'invalid').exists()


def test_notebook_has_no_executed_cells_and_requires_ratio_selection():
    nb = json.loads((CORE/'benchmark/target_ratio_t50/Kaggle_Colab_ratio_T50.ipynb').read_text(encoding='utf-8'))
    assert nb['nbformat']==4
    cells = [c for c in nb['cells'] if c['cell_type']=='code']
    assert all(c['execution_count'] is None and c['outputs']==[] for c in cells)
    assert any("RATIO = 'SET_ME'" in ''.join(c['source']) for c in cells)


def test_statistics_and_holm_use_two_reference_comparisons(monkeypatch):
    import types
    from collections import Counter
    monkeypatch.setitem(sys.modules,'evidence',types.ModuleType('evidence'))
    report = load('ratio_report_test',CORE/'benchmark/target_ratio_t50/report.py')
    assert report.compare([.1,.9],[.2,.1])=='W'
    assert report.compare([.1,.2],[.1,.1])=='L'
    assert report.sign(Counter(W=25,L=5))==pytest.approx(.00032491423189640045)
    assert report.holm({'a':.01,'b':.04})=={'a':.02,'b':.04}
