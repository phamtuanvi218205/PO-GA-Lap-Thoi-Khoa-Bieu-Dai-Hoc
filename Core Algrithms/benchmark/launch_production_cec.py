"""Freeze the numerical benchmark and launch its controller reproducibly."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent

def prepare_source(output: Path, *, benchmark_directory: Path=HERE) -> Path:
    """Create a new, recoverable output tree; never replace existing results."""
    output=output.resolve()
    if output.exists():
        raise FileExistsError('Choose a new output directory, or explicitly --resume the frozen run.')
    # Check official cache before creating the output directory.
    sys.path.insert(0,str(benchmark_directory))
    from prepare_cec2022 import prepare, ARCHIVE_PATH, ARCHIVE_SHA256, SOURCE_DIRECTORY, LIBRARY_PATH
    prepare()
    sha=lambda data:hashlib.sha256(data).hexdigest()
    assert sha(ARCHIVE_PATH.read_bytes())==ARCHIVE_SHA256
    with zipfile.ZipFile(ARCHIVE_PATH) as z:
        name=next(n for n in z.namelist() if n.endswith('C-Code/cec22_test_func.cpp'))
        official=z.read(name)
    assert sha(official)==sha((SOURCE_DIRECTORY/'cec22_test_func.cpp').read_bytes())
    frozen=output/'source/benchmark';frozen.mkdir(parents=True)
    for p in benchmark_directory.glob('*.py'):shutil.copy2(p,frozen/p.name)
    for name in ['cec2022_native_wrapper.cpp']:
        shutil.copy2(benchmark_directory/name,frozen/name)
    shutil.copytree(benchmark_directory/'tests',frozen/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(benchmark_directory/'.cache',frozen/'.cache',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(benchmark_directory.parent/'src',output/'source/src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(benchmark_directory/'PRODUCTION_CEC_PROTOCOL.md',output/'PROTOCOL.md')
    import numpy, scipy
    environment=dict(Python=sys.version,Python_executable=sys.executable,platform=platform.platform(),
        numpy=numpy.__version__,scipy=scipy.__version__,search_rng='Python random.Random',
        initial_rng='numpy.random.default_rng (PCG64)',BLAS_threads_per_worker=1,
        official_cpp_sha256=sha(official),wrapper_sha256=sha((frozen/'cec2022_native_wrapper.cpp').read_bytes()),
        dll_sha256=sha(LIBRARY_PATH.read_bytes()))
    (output/'runtime_environment.json').write_text(json.dumps(environment,indent=2),encoding='utf8')
    return frozen/'run_production_cec.py'

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=14)
    p.add_argument('--resume',action='store_true')
    a=p.parse_args();out=a.output.resolve()
    if not 1<=a.workers<=16:raise ValueError('workers must be in 1..16')
    if a.resume:
        runner=out/'source/benchmark/run_production_cec.py'
        if not runner.exists():raise FileNotFoundError('No frozen controller to resume.')
    else:runner=prepare_source(out)
    args=[sys.executable,'-X','utf8',str(runner),'--output',str(out),'--workers',str(a.workers)]
    if a.resume:args.append('--resume')
    raise SystemExit(subprocess.call(args))

if __name__=='__main__':main()
