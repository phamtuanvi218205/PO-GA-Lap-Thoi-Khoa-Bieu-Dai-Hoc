"""Portable launcher for three ablations only; reuse completed FULL T50 results."""
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
from zipfile import ZipFile

CORE = Path(__file__).resolve().parents[1]
CONFIG = CORE / "benchmark_configs/target_po80_part_t50"
TEMPLATES = CORE / "benchmark/target_ablation_t50"
sys.path.insert(0, str(CORE / "tools"))
from check_part_t50_benchmark import verify_suite

VARIANTS = ("TARGET_RAND80", "NO_FEEDBACK", "RANDOM_GROUP")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(data):
    return sha256(data).hexdigest()


def preflight():
    checked = verify_suite()
    ref = read(CONFIG / "references/full_t50_reference.manifest.json")
    archive = CONFIG / "references" / ref["archive"]
    if digest(archive.read_bytes()) != ref["archive_sha256"]:
        raise ValueError("FULL reference archive checksum differs.")
    if ref["optimizer_results"] != 30 or ref["initial_cohorts"] != 30:
        raise ValueError("Expected exactly 30 saved FULL results and 30 initial cohorts.")
    with ZipFile(archive) as z:
        if set(z.namelist()) != set(ref["entries_sha256"]):
            raise ValueError("Unexpected entries in the FULL reference archive.")
        for name in z.namelist():
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("Unsafe archive entry.")
            if digest(z.read(name)) != ref["entries_sha256"][name]:
                raise ValueError(f"Reference entry changed: {name}")
        protocol = read(CONFIG / "protocol.json")
        for scale in ("small", "medium", "large"):
            for seed in range(1, 11):
                key = f"{scale}_{seed}"
                meta = json.loads(z.read(f"cohorts/{key}.json"))
                if (meta["initial_sha"] != protocol["initial_sha256"][key]
                        or meta["snapshot_checksum"] != protocol["cases"][scale]["snapshot_checksum"]):
                    raise ValueError(f"Wrong shared initial cohort in reference bundle: {key}")
                if digest(z.read(f"cohorts/{key}.pkl")) != meta["pickle_sha"]:
                    raise ValueError(f"Wrong initial pickle checksum: {key}")
    checked["reference_main_optimizer_runs"] = checked.pop("optimizer_runs")
    checked["reference_main_greedy_runs"] = checked.pop("greedy_runs")
    checked.update(variants=list(VARIANTS), new_ablation_runs=90, new_greedy_runs=0,
                   reused_full_results=30, rerun_main_algorithms=0)
    return checked


def prepare(output: Path, variants):
    preflight()
    if output.exists():
        raise FileExistsError("Use a new output root, or --resume for a previously prepared run.")
    # Resolve and validate before any generated data is copied.
    output = output.resolve()
    protected = [CORE / "src", CORE / "benchmark_configs", CORE / "benchmark_results", TEMPLATES]
    if any(output == p or output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError("Output root overlaps repository inputs/source/reference data.")
    output.mkdir(parents=True)
    source = output / "source"
    source.mkdir()
    package = CORE / "src/gapo_timetabling"
    for path in package.rglob("*.py"):
        target = source / "gapo_timetabling" / path.relative_to(package)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    for name in ("controller.py", "evidence.py", "variants.py", "report.py"):
        shutil.copyfile(TEMPLATES / name, source / name)
    for name in ("protocol.json", "ablation_protocol.json"):
        shutil.copyfile(CONFIG / name, output / name)
    (output / "inputs").mkdir()
    for scale in ("small", "medium", "large"):
        shutil.copyfile(CONFIG / f"data/{scale}.json", output / f"inputs/{scale}.json")
    ref = read(CONFIG / "references/full_t50_reference.manifest.json")
    shutil.copyfile(CONFIG / "references/full_t50_reference.manifest.json", output / "reference_manifest.json")
    with ZipFile(CONFIG / "references" / ref["archive"]) as z:
        for name in ref["entries_sha256"]:
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(z.read(name))
    for directory in ("runs", "details", "checkpoints", "progress", "logs", "analysis"):
        (output / directory).mkdir(exist_ok=True)
    templates_sha = {name: digest((source / name).read_bytes().replace(b"\r\n", b"\n"))
                     for name in ("controller.py", "evidence.py", "variants.py", "report.py")}
    fingerprint = digest(json.dumps(dict(protocol=read(CONFIG / "protocol.json"),
        ablation=read(CONFIG / "ablation_protocol.json"), templates=templates_sha,
        reference_archive_sha=ref["archive_sha256"]), sort_keys=True).encode("utf-8"))
    frozen = [output / "protocol.json", output / "ablation_protocol.json", output / "reference_manifest.json",
              *source.rglob("*.py"), *(output / "inputs").glob("*.json"), *(output / "cohorts").glob("*")]
    manifest = dict(schema_version="target-t50-ablation-manifest.v1", variants=list(variants),
        study_fingerprint=fingerprint, planned_ablation_runs=30*len(variants), reused_full_results=30,
        rerun_main_algorithms=0, frozen_sha256={p.relative_to(output).as_posix(): digest(p.read_bytes()) for p in frozen})
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CORE.parent, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    provenance = dict(python=sys.version, platform=platform.platform(), repository_revision=revision,
        dependencies={name: importlib.metadata.version(name) for name in ("numpy", "matplotlib", "psutil")},
        authority="Frozen source/input/reference hashes; no optimizer results are relabeled or overwritten.")
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2)+"\n", encoding="utf-8")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("check", help="Verify all files/references; never execute an optimizer")
    run = commands.add_parser("run", help="Run only ablations, with independent process workers")
    run.add_argument("--output-root", type=Path, required=True)
    run.add_argument("--variant", choices=("ALL", *VARIANTS), default="ALL")
    run.add_argument("--workers", type=int, default=0, help="Default: available logical CPUs, respecting cgroup v2 quota")
    run.add_argument("--resume", action="store_true", help="Keep completed checkpoints; restart only unfinished jobs")
    report = commands.add_parser("report", help="Replay and report saved results only")
    report.add_argument("--output-root", type=Path, required=True)
    merge = commands.add_parser("merge", help="Merge three completed ablation parts; no optimizer execution")
    merge.add_argument("--output-root", type=Path, required=True)
    merge.add_argument("--part-root", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "check":
            print(json.dumps(preflight(), indent=2))
            return 0
        output = args.output_root.resolve()
        if args.mode == "run":
            if args.workers < 0:
                raise ValueError("--workers must be positive, or omitted for auto")
            variants = VARIANTS if args.variant == "ALL" else (args.variant,)
            if args.resume:
                manifest = read(output / "manifest.json")
                if manifest["variants"] != list(variants):
                    raise ValueError("Resume must keep the same variant selection.")
            else:
                output = prepare(output, variants)
        elif args.mode == "merge":
            output = prepare(output, VARIANTS)
        else:
            if not (output / "manifest.json").exists():
                raise ValueError("No prepared output to report.")
        command = [sys.executable, "-u", str(output / "source/controller.py"), args.mode]
        if args.mode == "run":
            command += ["--workers", str(args.workers)]
            if args.resume:
                command.append("--resume")
        elif args.mode == "merge":
            for part in args.part_root:
                command += ["--part-root", str(part.resolve())]
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONPATH=str(output / "source"),
                   OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
        return subprocess.call(command, cwd=output, env=env)
    except (OSError, ValueError, KeyError, importlib.metadata.PackageNotFoundError) as error:
        print(f"ABLATION SETUP FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
