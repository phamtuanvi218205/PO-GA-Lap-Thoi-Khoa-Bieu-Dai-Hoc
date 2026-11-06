"""Package saved T50 FULL evidence for teammates; no optimizer execution."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def package(source, output):
    source, output = source.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(f"Refuse to overwrite: {output}")
    status = json.loads((source / "status.json").read_text(encoding="utf-8"))
    if status["status"] != "COMPLETED" or status["completed_optimizer"] != 90:
        raise ValueError("Only the completed V3/T50 study can supply FULL references.")
    items = {}
    for scale in ("small", "medium", "large"):
        for seed in range(1, 11):
            key = f"{scale}_{seed}"
            for suffix in ("json", "pkl"):
                items[f"cohorts/{key}.{suffix}"] = source / f"cohorts/{key}.{suffix}"
            for folder in ("runs", "details", "checkpoints"):
                items[f"full/{folder}/{key}_TARGET_PO80.json"] = source / folder / f"{key}_TARGET_PO80.json"
    checksums = {}
    for relative, path in items.items():
        checksums[relative] = sha256(path.read_bytes()).hexdigest()
    for scale in ("small", "medium", "large"):
        for seed in range(1, 11):
            key = f"{scale}_{seed}_TARGET_PO80.json"
            cp = json.loads((source / "checkpoints" / key).read_text(encoding="utf-8"))
            assert checksums[f"full/runs/{key}"] == cp["result_sha"]
            assert checksums[f"full/details/{key}"] == cp["detail_sha"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "x", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, path in items.items():
            archive.write(path, relative)
    manifest = dict(schema_version="target-t50-full-reference.v1",
        original_study="target_po80_part_stress_t50_20261106", optimizer_results=30,
        initial_cohorts=30, archive=output.name,
        archive_sha256=sha256(output.read_bytes()).hexdigest(), entries_sha256=checksums)
    output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(archive=str(output), bytes=output.stat().st_size,
                          entries=len(items), sha256=manifest["archive_sha256"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package(args.source, args.output)
