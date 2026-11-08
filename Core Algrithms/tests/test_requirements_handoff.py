"""Read-only checks for installation without editable package metadata."""
from pathlib import Path
import configparser
import subprocess
import sys

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]


def test_requirements_are_standalone_and_keep_runtime_and_test_dependencies():
    lines = [line.strip() for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines()]
    entries = [line for line in lines if line and not line.startswith('#')]
    assert all(not line.startswith('-') for line in entries)
    actual = {r.name: str(r) for r in map(Requirement, entries)}
    assert set(actual) == {
        'fastapi', 'matplotlib', 'numpy', 'openpyxl', 'pydantic', 'pyodbc',
        'python-multipart', 'python-dotenv', 'psutil', 'scipy', 'uvicorn',
        'pytest', 'httpx',
    }
    assert 'standard' in Requirement(actual['uvicorn']).extras
    assert str(Requirement(actual['pydantic']).specifier) == '<3,>=2.0.3'
    assert str(Requirement(actual['httpx']).specifier) == '<1,>=0.27'
    assert not (ROOT / 'pyproject.toml').exists()


def test_pytest_source_and_test_paths_are_preserved():
    config = configparser.ConfigParser()
    config.read(ROOT / 'pytest.ini', encoding='utf-8')
    assert config['pytest']['pythonpath'] == '"Core Algrithms/src"'
    assert config['pytest']['testpaths'] == '"Core Algrithms/tests"'


def test_launcher_check_works_without_installing_the_project():
    result = subprocess.run(
        [sys.executable, '-E', '-B', str(ROOT / 'Script/start_demo.py'), '--check'],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'san sang' in result.stdout


def test_active_setup_instructions_no_longer_require_editable_install():
    for relative in (
        'CHAY_UNG_DUNG.cmd', 'HUONG_DAN_CAI_DAT.md', 'Core Algrithms/README.md',
        'Core Algrithms/benchmark_configs/target_po80_part_t50/README.md',
        'Core Algrithms/benchmark_configs/target_po80_part_t50/ABLATION.md',
    ):
        text = (ROOT / relative).read_text(encoding='utf-8')
        assert 'pip install -e' not in text
        assert 'pyproject.toml' not in text
        assert 'pip install -r requirements.txt' in text
