"""Hop cac shard seed CEC 2022 va tao artifact ket qua day du."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from algorithms import ALGORITHMS
from benchmark_functions import get_cec2022_suite
from experiment import (
    CONVERGENCE_FIELDS,
    RAW_RESULT_FIELDS,
    _read_csv,
    _run_key,
    calculate_ranks_and_tests,
    summarize_results,
    write_csv,
)
from plotting import (
    plot_convergence,
    plot_final_error_boxplots,
    plot_rank_heatmap,
    plot_runtime,
)
from ordering import function_sort_key
from run_benchmark import _write_or_validate_config, get_profile


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hop cac shard CEC 2022.")
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _config_without_seeds(path: Path) -> tuple[dict[str, object], set[int]]:
    with path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    seeds = {int(seed) for seed in config.pop("seeds")}
    return config, seeds


def _validate_finite(rows: list[dict[str, object]], fields: tuple[str, ...]) -> None:
    for row in rows:
        for field in fields:
            if not math.isfinite(float(row[field])):
                raise ValueError(f"Gia tri khong huu han tai {field}: {row}")


def main() -> None:
    arguments = parse_arguments()
    official_config = get_profile("cec2022")
    expected_seeds = set(official_config.seeds)
    expected_functions = {
        function.name for function in get_cec2022_suite(official_config.dimensions)
    }
    expected_keys = {
        (function, algorithm, seed)
        for function in expected_functions
        for algorithm in ALGORITHMS
        for seed in expected_seeds
    }

    reference_config = None
    all_seeds: set[int] = set()
    raw_by_key: dict[tuple[str, str, int], dict[str, object]] = {}
    convergence_rows: list[dict[str, object]] = []

    for input_directory in arguments.inputs:
        shard_config, shard_seeds = _config_without_seeds(
            input_directory / "config.json"
        )
        if reference_config is None:
            reference_config = shard_config
        elif shard_config != reference_config:
            raise ValueError("Cac shard khong cung cau hinh/giao thuc.")
        if all_seeds.intersection(shard_seeds):
            raise ValueError("Cac shard bi trung seed.")
        all_seeds.update(shard_seeds)

        for row in _read_csv(input_directory / "raw_results.csv"):
            key = _run_key(row)
            if key in raw_by_key:
                raise ValueError(f"Trung run key: {key}")
            raw_by_key[key] = row
        convergence_rows.extend(
            _read_csv(input_directory / "convergence.csv")
        )

    if all_seeds != expected_seeds:
        raise ValueError(
            f"Tap seed shard khong du. Co={sorted(all_seeds)}, "
            f"can={sorted(expected_seeds)}"
        )
    if set(raw_by_key) != expected_keys:
        missing = expected_keys.difference(raw_by_key)
        extra = set(raw_by_key).difference(expected_keys)
        raise ValueError(f"Run key khong du: missing={len(missing)}, extra={len(extra)}")

    raw_rows = sorted(
        raw_by_key.values(),
        key=lambda row: (
            function_sort_key(str(row["function"])),
            int(row["seed"]),
            str(row["algorithm"]),
        ),
    )
    convergence_rows.sort(
        key=lambda row: (
            function_sort_key(str(row["function"])),
            int(row["seed"]),
            str(row["algorithm"]),
            int(row["evaluations"]),
        )
    )
    _validate_finite(raw_rows, ("best_value", "final_error", "runtime_seconds"))
    _validate_finite(convergence_rows, ("evaluations", "best_error"))

    convergence_keys = {_run_key(row) for row in convergence_rows}
    if convergence_keys != expected_keys:
        raise ValueError("Convergence khong bao phu dung toan bo run key.")

    output_directory = arguments.output
    output_directory.mkdir(parents=True, exist_ok=True)
    _write_or_validate_config(output_directory / "config.json", official_config)
    write_csv(output_directory / "raw_results.csv", raw_rows, RAW_RESULT_FIELDS)
    write_csv(
        output_directory / "convergence.csv",
        convergence_rows,
        CONVERGENCE_FIELDS,
    )
    summarize_results(raw_rows, output_directory)
    rank_rows, average_rank_rows = calculate_ranks_and_tests(
        raw_rows, output_directory
    )
    plot_convergence(convergence_rows, output_directory)
    plot_final_error_boxplots(raw_rows, output_directory)
    plot_rank_heatmap(rank_rows, output_directory)
    plot_runtime(raw_rows, output_directory)

    metadata = {
        "execution": "parallel independent seed shards",
        "inputs": [str(path) for path in arguments.inputs],
        "runtime_warning": (
            "Wall-clock runtimes were measured while shards competed for CPU; "
            "do not treat them as isolated single-process timings."
        ),
    }
    with (output_directory / "merge_metadata.json").open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(metadata, file, indent=2, ensure_ascii=False)

    print("Hoan tat hop shard. Average rank:")
    for row in sorted(average_rank_rows, key=lambda item: item["average_rank"]):
        print(f"  {row['algorithm']:<5}: {row['average_rank']:.3f}")


if __name__ == "__main__":
    main()
