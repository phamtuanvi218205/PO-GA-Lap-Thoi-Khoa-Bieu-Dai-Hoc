"""Prepare, transfer and run ONLY 70/30 and 60/40 TARGET sensitivity jobs."""
from __future__ import annotations
import argparse
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

CORE = Path(__file__).resolve().parents[1]
TEMPLATES = CORE / 'benchmark/target_ratio_t50'
SHARED = CORE / 'benchmark/target_ablation_t50'
CONFIG = CORE / 'benchmark_configs/target_po80_part_t50'
sys.path.insert(0, str(CORE / 'tools'))
from run_target_ablation_t50 import preflight as check_reference

METHODS = ('GA70_PO30', 'GA60_PO40')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(data):
    return sha256(data).hexdigest()


def controller_text():
    # Reuse the established CPU/quota, checkpoint, lock and merge machinery.
    # Only labels and the ALL merge count change. No optimizer code is patched.
    value = (SHARED / 'controller.py').read_text(encoding='utf-8')
    value = value.replace('three V3/T50 ablations', 'two V3/T50 ratio variants')
    value = value.replace('three named ablations', 'two named ratio variants')
    value = value.replace('three completed ablation', 'two completed ratio')
    value = value.replace('ablation', 'ratio')
    old = 'completed_ratio=90, planned_ratio=90'
    if value.count(old) != 1:
        raise ValueError('Shared controller changed; review before preparing this study.')
    return value.replace(old, 'completed_ratio=60, planned_ratio=60')


def preflight():
    checked = check_reference()
    study = read(TEMPLATES / 'protocol.json')
    if study['ratios'] != dict(GA70_PO30=.7, GA60_PO40=.6):
        raise ValueError('Ratio design changed.')
    if (study['population'], study['iterations'], study['fitness_cap_including_initial']) != (30,50,1530):
        raise ValueError('Wrong ratio budget.')
    for name in ('evidence.py', 'report.py'):
        if not (TEMPLATES / name).is_file():
            raise FileNotFoundError(name)
    controller_text()
    return dict(passed=checked['passed'], production_files=checked['package_files'],
        ratios=study['ratios'], new_ratio_runs=60, reused_80_20_runs=30,
        new_ga_po_greedy_ablation_runs=0, optimizer_executed=False,
        cases=checked['cases'], population=30, generations=50, fe_cap=1530,
        reference_compatible=True, initial_cohorts=30)


def prepare(output, selected):
    preflight()
    if not selected or len(set(selected)) != len(selected) or any(x not in METHODS for x in selected):
        raise ValueError('Only named ratio variants may be prepared.')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Output exists. Use --resume explicitly, or a new root.')
    protected = [CORE/'src', CORE/'tools', CORE/'benchmark', CORE/'benchmark_configs', CORE/'benchmark_results']
    if any(output == p or output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('Output overlaps protected source/config/reference paths.')
    if any((p/'manifest.json').exists() for p in output.parents):
        raise ValueError('Do not create a study inside an existing experiment.')
    output.mkdir(parents=True)
    source = output/'source'
    source.mkdir()
    for path in (CORE/'src/gapo_timetabling').rglob('*.py'):
        target = source/'gapo_timetabling'/path.relative_to(CORE/'src/gapo_timetabling')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    for origin, dest in [(SHARED/'evidence.py', 'reference_evidence.py'),
                         (SHARED/'variants.py', 'variants.py'),
                         (TEMPLATES/'evidence.py', 'evidence.py'),
                         (TEMPLATES/'report.py', 'report.py')]:
        shutil.copyfile(origin, source/dest)
    (source/'controller.py').write_text(controller_text(), encoding='utf-8', newline='\n')
    shutil.copyfile(CONFIG/'protocol.json', output/'protocol.json')
    shutil.copyfile(TEMPLATES/'protocol.json', output/'ratio_protocol.json')
    (output/'inputs').mkdir()
    for scale in ('small','medium','large'):
        shutil.copyfile(CONFIG/f'data/{scale}.json', output/f'inputs/{scale}.json')
    ref = read(CONFIG/'references/full_t50_reference.manifest.json')
    shutil.copyfile(CONFIG/'references/full_t50_reference.manifest.json', output/'reference_manifest.json')
    with ZipFile(CONFIG/'references'/ref['archive']) as z:
        for name in ref['entries_sha256']:
            target = output/name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as handle:
                handle.write(z.read(name))
    for name in ('runs','details','checkpoints','progress','logs','analysis'):
        (output/name).mkdir(exist_ok=True)
    frozen = [output/'protocol.json',output/'ratio_protocol.json',output/'reference_manifest.json',
              *source.rglob('*.py'),*(output/'inputs').glob('*.json'),*(output/'cohorts').glob('*')]
    hashes = {p.relative_to(output).as_posix():digest(p.read_bytes()) for p in frozen}
    normalized = {p.relative_to(output).as_posix():digest(p.read_bytes().replace(b'\r\n',b'\n'))
                  for p in source.rglob('*.py')}
    fingerprint = digest(json.dumps(dict(protocol=read(output/'protocol.json'),
        ratio=read(output/'ratio_protocol.json'), source_lf=normalized,
        reference=ref['archive_sha256']), sort_keys=True).encode())
    manifest = dict(schema_version='target-ratio-t50-manifest.v1', variants=list(selected),
        study_fingerprint=fingerprint, planned_ratio_runs=30*len(selected),
        reused_full_results=30, rerun_main_algorithms=0, frozen_sha256=hashes)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    try:
        revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=CORE.parent,text=True).strip()
    except (OSError,subprocess.CalledProcessError):
        revision = None
    provenance = dict(python=sys.version,platform=platform.platform(),repository_revision=revision,
        dependencies={n:importlib.metadata.version(n) for n in ('numpy','matplotlib','psutil')},
        authority='Frozen hashes are authoritative; source is unchanged, only ga_ratio differs.')
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf-8')
    return output


def bundle(destination):
    preflight()
    destination = destination.resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Explicit allowlist: no Word, private context, credentials, DB, old studies or results.
    files = [CORE.parent/'pyproject.toml', Path(__file__),
        CORE/'tools/run_target_ablation_t50.py',CORE/'tools/check_part_t50_benchmark.py',
        *TEMPLATES.glob('*'), SHARED/'evidence.py', SHARED/'variants.py', SHARED/'controller.py',
        *(CORE/'src/gapo_timetabling').rglob('*.py'), *CONFIG.rglob('*')]
    files = sorted({p for p in files if p.is_file() and p.suffix not in ('.pyc',)}, key=str)
    with ZipFile(destination,'x',compression=ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(CORE.parent).as_posix())
    checksum = digest(destination.read_bytes())
    print(json.dumps(dict(bundle=str(destination),sha256=checksum,files=len(files),optimizer_executed=False),indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode',required=True)
    modes.add_parser('check',help='Read-only preflight. No initialization or optimizer.')
    pack = modes.add_parser('bundle',help='Portable allowlisted ZIP; does not run anything')
    pack.add_argument('--zip',type=Path,required=True)
    for name in ('prepare','run','report','merge'):
        p = modes.add_parser(name)
        p.add_argument('--output-root',type=Path,required=True)
        if name in ('prepare','run'):
            p.add_argument('--ratio',choices=('ALL',*METHODS),default='ALL')
        if name == 'run':
            p.add_argument('--workers',type=int,default=0)
            p.add_argument('--resume',action='store_true')
            p.add_argument('--acknowledge-compute',action='store_true',help='Required before starting any optimizer')
        if name == 'merge':
            p.add_argument('--part-root',action='append',type=Path,required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == 'check':
            print(json.dumps(preflight(),indent=2)); return 0
        if args.mode == 'bundle':
            bundle(args.zip); return 0
        if args.mode == 'run' and not args.acknowledge_compute:
            raise ValueError('No optimizer started. Add --acknowledge-compute on the intended remote machine only.')
        if args.mode == 'run' and args.workers < 0:
            raise ValueError('--workers must be nonnegative.')
        output = args.output_root.resolve()
        if args.mode in ('prepare','run'):
            selected = METHODS if args.ratio == 'ALL' else (args.ratio,)
            if args.mode == 'run' and args.resume:
                manifest = read(output/'manifest.json')
                if manifest['variants'] != list(selected):
                    raise ValueError('Resume must retain the original ratio selection.')
            else:
                prepare(output,selected)
            if args.mode == 'prepare':
                print(json.dumps(dict(prepared=str(output),new_runs=30*len(selected),optimizer_executed=False),indent=2)); return 0
        elif args.mode == 'merge':
            prepare(output,METHODS)
        elif not (output/'manifest.json').exists():
            raise ValueError('No prepared ratio output.')
        command = [sys.executable,'-u',str(output/'source/controller.py'),args.mode]
        if args.mode == 'run':
            command += ['--workers',str(args.workers)]
            if args.resume: command.append('--resume')
        if args.mode == 'merge':
            for part in args.part_root: command += ['--part-root',str(part.resolve())]
        env = os.environ.copy()
        env.update(PYTHONUTF8='1',PYTHONUNBUFFERED='1',PYTHONPATH=str(output/'source'),
            OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
        return subprocess.call(command,cwd=output,env=env)
    except (OSError,ValueError,KeyError,importlib.metadata.PackageNotFoundError) as exc:
        print(f'RATIO SETUP FAILED: {exc}',file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
