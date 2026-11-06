"""Frozen-output controller: only the three V3/T50 ablations are scheduled."""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from time import monotonic, sleep

import psutil
import evidence as w

ROOT = w.ROOT


def build_tasks(selected):
    if not selected or len(set(selected)) != len(selected) or any(m not in w.METHODS for m in selected):
        raise ValueError("Only the three named ablations may be scheduled.")
    return [(scale, seed, method) for seed in range(1,11) for scale in w.CASES for method in selected]


def checkpoint_valid(key, *, replay=False):
    checkpoint = ROOT / "checkpoints" / f"{key}.json"
    if not checkpoint.exists():
        return False
    cp = w.read(checkpoint)
    for folder, field in (("runs", "result_sha"), ("details", "detail_sha")):
        if w.digest((ROOT / folder / f"{key}.json").read_bytes()) != cp[field]:
            raise ValueError(f"Saved result changed: {key}/{folder}")
    scale, seed, _ = key.split("_", 2)
    meta = w.read(ROOT / "cohorts" / f"{scale}_{seed}.json")
    detail = w.read(ROOT / "details" / f"{key}.json")
    payload = w.read(ROOT / "runs" / f"{key}.json")
    if detail["records"][:30] != meta["records"] or detail["trace"][:30] != meta["trace"]:
        raise ValueError(f"Saved run did not use the shared initial cohort: {key}")
    if not cp["initial_sha"] == detail["initial_sha"] == meta["initial_sha"]:
        raise ValueError(f"Wrong initial cohort: {key}")
    w.validate_trace(payload, detail)
    if replay:
        assert w.audit(payload, w.prepared(scale)) == detail["audit"]
    return True


def cpu_limit():
    limit = os.cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        limit = min(limit, len(os.sched_getaffinity(0)))
    path = Path("/sys/fs/cgroup/cpu.max")
    if path.exists():
        quota, period = path.read_text().split()
        if quota != "max":
            limit = min(limit, max(1, int(quota) // int(period)))
    return max(1, limit)


def take_lock():
    path = ROOT / "controller.lock.json"
    if path.exists():
        prior = w.read(path)
        if prior["host"] != socket.gethostname():
            raise RuntimeError("Lock belongs to another host. Confirm the other controller is stopped before copying/resuming.")
        try:
            process = psutil.Process(prior["pid"])
            if abs(process.create_time() - prior["created"]) < 1:
                raise RuntimeError("Another controller is still running for this output root.")
        except psutil.NoSuchProcess:
            pass
        path.unlink()
    for item in w.read(ROOT / "status.json").get("running", []) if (ROOT / "status.json").exists() else []:
        try:
            process = psutil.Process(item["pid"])
            if str(ROOT / "source/evidence.py") in " ".join(process.cmdline()):
                raise RuntimeError("A worker is still running; do not start a second controller.")
        except psutil.NoSuchProcess:
            pass
    with path.open("x", encoding="utf-8") as handle:
        json.dump(dict(host=socket.gethostname(), pid=os.getpid(),
                       created=psutil.Process().create_time()), handle)
    return path


def run(workers, resume=False):
    w.verify_source()
    manifest = w.read(ROOT / "manifest.json")
    selected = manifest["variants"]
    if (ROOT / "status.json").exists() and not resume:
        raise ValueError("Output already started. Use --resume explicitly; completed runs are not rerun.")
    lock = take_lock()
    running = {}
    failures = []
    started = w.now()
    t0 = monotonic()
    tasks = build_tasks(selected)
    completed = 0
    queue = deque()
    for scale, seed, method in tasks:
        key = f"{scale}_{seed}_{method}"
        if checkpoint_valid(key):
            completed += 1
        else:
            # If publication was interrupted after a result was saved, preserve
            # the partial artifacts before rerunning this uncheckpointed job.
            partial = [ROOT / folder / f"{key}.json" for folder in ("runs", "details")]
            for path in partial:
                if path.exists():
                    target = ROOT / "incomplete" / f"{key}_{int(datetime.now().timestamp()*1000000)}_{path.parent.name}.json"
                    target.parent.mkdir(exist_ok=True)
                    shutil.move(str(path), str(target))
            queue.append((scale, seed, method))
    max_workers = min(workers or cpu_limit(), cpu_limit())

    def status(state, **extra):
        w.save(ROOT / "status.json", dict(status=state, pid=os.getpid(),
            host=socket.gethostname(), started=started, updated=w.now(),
            elapsed_seconds=monotonic()-t0, workers_max=max_workers,
            completed_ablation=completed, planned_ablation=len(tasks),
            reused_full_results=30, rerun_main_algorithms=0, queued=len(queue),
            running=[dict(key=k, pid=v[0].pid) for k,v in running.items()],
            failures=failures, **extra))
    try:
        status("RUNNING")
        while queue or running:
            while queue and not failures and len(running) < max_workers:
                if psutil.virtual_memory().available < 1570 * 1024**2:
                    break
                scale, seed, method = queue.popleft()
                key = f"{scale}_{seed}_{method}"
                logs = ROOT / "logs"
                logs.mkdir(exist_ok=True)
                attempt = len(list(logs.glob(f"{key}.*.stdout.log"))) + 1
                out = (logs / f"{key}.{attempt}.stdout.log").open("xb")
                err = (logs / f"{key}.{attempt}.stderr.log").open("xb")
                env = os.environ.copy()
                env.update(PYTHONUNBUFFERED="1", PYTHONUTF8="1", PYTHONPATH=str(ROOT / "source"),
                    OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
                command = [sys.executable, "-u", str(ROOT / "source/evidence.py"), scale,
                           "--seed", str(seed), "--variant", method]
                process = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err, env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                running[key] = (process, out, err)
                print("START", key, "PID", process.pid, flush=True)
            for key, (process, out, err) in list(running.items()):
                code = process.poll()
                if code is None:
                    continue
                out.close(); err.close(); del running[key]
                if code or not checkpoint_valid(key):
                    failures.append(dict(key=key, exit_code=code))
                    queue.clear()
                else:
                    completed += 1
                print("DONE" if not code else "FAILED", key, completed, "/", len(tasks), flush=True)
            status("FAILED" if failures else "RUNNING")
            sleep(2)
        if failures:
            status("FAILED", finished=w.now())
            return 1
        status("REPORTING")
        from report import report
        report()
        status("COMPLETED", finished=w.now())
        return 0
    except KeyboardInterrupt:
        for process, _, _ in running.values():
            if process.poll() is None:
                process.terminate()
        for process, out, err in running.values():
            process.wait(); out.close(); err.close()
        running.clear()
        status("STOPPED_BY_USER", finished=w.now())
        return 130
    except BaseException:
        # No automatic retry/tuning. Persist the state and keep all saved data.
        status("FAILED", finished=w.now())
        raise
    finally:
        lock.unlink(missing_ok=True)


def merge(parts):
    w.verify_source()
    own = w.read(ROOT / "manifest.json")
    for part in parts:
        part = part.resolve()
        other = w.read(part / "manifest.json")
        if w.read(part / "status.json")["status"] != "COMPLETED":
            raise ValueError("Only completed ablation parts can be merged.")
        if other["study_fingerprint"] != own["study_fingerprint"]:
            raise ValueError("Cannot merge different source/config/reference bundles.")
        for cp_path in (part / "checkpoints").glob("*.json"):
            key = cp_path.stem
            if key.split("_", 2)[2] not in w.METHODS:
                raise ValueError("Only ablation checkpoints can be merged.")
            cp = w.read(cp_path)
            for folder, field in (("runs", "result_sha"), ("details", "detail_sha")):
                source = part / folder / cp_path.name
                assert w.digest(source.read_bytes()) == cp[field]
            for folder in ("runs", "details", "checkpoints"):
                source = part / folder / cp_path.name
                target = ROOT / folder / cp_path.name
                target.parent.mkdir(exist_ok=True)
                if target.exists() and target.read_bytes() != source.read_bytes():
                    raise ValueError(f"Conflicting duplicate result: {key}")
                if not target.exists():
                    shutil.copyfile(source, target)
    from report import report
    report()
    w.save(ROOT / "status.json", dict(status="COMPLETED", finished=w.now(),
        completed_ablation=90, planned_ablation=90, reused_full_results=30,
        rerun_main_algorithms=0, running=[], queued=0, failures=[]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "report", "merge"))
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--part-root", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.workers < 0:
        parser.error("--workers must be positive, or omitted for auto")
    if args.mode == "run":
        raise SystemExit(run(args.workers, args.resume))
    if args.mode == "merge":
        merge(args.part_root)
    else:
        w.verify_source()
        from report import report
        report()
        prior = w.read(ROOT / "status.json") if (ROOT / "status.json").exists() else {}
        count = 30 * len(w.read(ROOT / "manifest.json")["variants"])
        prior.update(status="COMPLETED", finished=w.now(), updated=w.now(),
            completed_ablation=count, planned_ablation=count, reused_full_results=30,
            rerun_main_algorithms=0, running=[], queued=0, failures=[])
        w.save(ROOT / "status.json", prior)
