"""Diem chay chinh cua bo benchmark.

Vi du:
    python run_benchmark.py --profile smoke
    python run_benchmark.py --profile standard
    python run_benchmark.py --profile cec2022
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from benchmark_functions import get_cec2022_suite, get_classical_suite
from experiment import (
    ExperimentConfig,
    calculate_ranks_and_tests,
    run_experiment,
    summarize_results,
)
from plotting import (
    plot_convergence,
    plot_final_error_boxplots,
    plot_rank_heatmap,
    plot_runtime,
)


BENCHMARK_PROTOCOL = {
    "version": "cec2022-official-native-v1-2026-09-14",
    "objective": "minimize max(f_best - f_optimum, 0)",
    "optimum_guard": "reject best below f_optimum beyond 1e-10 relative tolerance",
    "boundary_control": "clip",
    "initial_population": "same function/seed population for all algorithms",
    "po_reference": {
        "repository": "https://github.com/junbolian/PO",
        "commit": "21621a3e709a4a9dd75f6eab7a5c1241e3109a93",
        "file": "Parrot-optimizer-Algorithm-and-applications-to-medical-problems-main/PO.m",
        "levy_beta": 1.5,
    },
    "cec2022_reference": {
        "repository": "https://github.com/P-N-Suganthan/2022-SO-BO",
        "commit": "de20505283b76ec6bf17a2e8fc6052e655830691",
        "archive_sha256": "dd46b9efcfe79253c1dc0cb0f09c7f0ed0e24d5eb235ee14ca09be29f7def626",
        "implementation": "official C++ evaluator through ctypes",
    },
    "ga": {
        "tournament_size": 3,
        "sbx_probability": 0.9,
        "sbx_eta": 15.0,
        "mutation_probability": "1/D",
        "mutation_eta": 20.0,
        "elitism": "replace worst child with global best when better",
    },
    "hybrid": {
        "ga_ratio": 0.5,
        "survivor_selection": "P(t) union A' union B'; keep N best; shuffle",
    },
}


def get_profile(profile_name: str) -> ExperimentConfig:
    """Dinh nghia ro quy mo cua tung muc chay."""

    if profile_name == "smoke":
        return ExperimentConfig(
            profile_name="smoke",
            dimensions=10,
            population_size=30,
            max_evaluations=3_000,
            seeds=(1, 2, 3),
        )

    if profile_name == "standard":
        return ExperimentConfig(
            profile_name="standard",
            dimensions=20,
            population_size=30,
            max_evaluations=30_000,
            seeds=tuple(range(1, 11)),
        )

    if profile_name == "cec2022_pilot":
        # Pilot chi kiem tra ky thuat va uoc luong runtime. Khong dung de
        # tuning tham so hoac lam ket qua bao cao chinh thuc.
        return ExperimentConfig(
            profile_name="cec2022_pilot",
            dimensions=20,
            population_size=30,
            max_evaluations=30_000,
            seeds=(1, 2, 3),
        )

    if profile_name == "cec2022":
        # Cau hinh thuc nghiem chinh da thong nhat: 12 ham, D=20,
        # 30 lan chay doc lap va 300,000 FE cho moi lan.
        return ExperimentConfig(
            profile_name="cec2022",
            dimensions=20,
            population_size=30,
            max_evaluations=300_000,
            seeds=tuple(range(1, 31)),
        )

    raise ValueError(f"Profile khong hop le: {profile_name}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="So sanh GA, PO V2 va GA-PO bang cung ngan sach FE."
    )
    parser.add_argument(
        "--profile",
        choices=("smoke", "standard", "cec2022_pilot", "cec2022"),
        default="smoke",
        help=(
            "smoke: kiem tra nhanh; standard: 9 ham co ban; "
            "cec2022_pilot: pilot ky thuat; cec2022: full."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Thu muc ket qua. Neu bo trong, chuong trinh tu tao theo thoi gian.",
    )
    parser.add_argument(
        "--seed-start",
        type=int,
        default=None,
        help="Seed dau tien cua shard (inclusive). Phai dung cung --seed-end.",
    )
    parser.add_argument(
        "--seed-end",
        type=int,
        default=None,
        help="Seed cuoi cua shard (inclusive). Phai dung cung --seed-start.",
    )
    return parser.parse_args()


def restrict_seed_range(
    config: ExperimentConfig,
    seed_start: int | None,
    seed_end: int | None,
) -> ExperimentConfig:
    """Tao config shard ma khong thay doi cac tham so benchmark khac."""

    if (seed_start is None) != (seed_end is None):
        raise ValueError("Phai truyen dong thoi --seed-start va --seed-end.")
    if seed_start is None:
        return config
    if seed_start > seed_end:
        raise ValueError("--seed-start khong duoc lon hon --seed-end.")

    selected = tuple(
        seed for seed in config.seeds if seed_start <= seed <= seed_end
    )
    if not selected or selected[0] != seed_start or selected[-1] != seed_end:
        raise ValueError("Khoang seed nam ngoai profile da chon.")
    return replace(config, seeds=selected)


def _write_or_validate_config(
    config_path: Path, config: ExperimentConfig
) -> None:
    """Khong cho resume nham ket qua cua mot cau hinh khac."""

    expected = asdict(config)
    expected["seeds"] = list(config.seeds)
    expected["protocol"] = BENCHMARK_PROTOCOL
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as file:
            existing = json.load(file)
        if existing != expected:
            raise ValueError(
                "Thu muc output da co config.json khac cau hinh hien tai. "
                "Hay chon thu muc output moi de khong tron ket qua."
            )
        return

    temporary_path = config_path.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(expected, file, indent=2, ensure_ascii=False)
    temporary_path.replace(config_path)


def main() -> None:
    arguments = parse_arguments()
    config = restrict_seed_range(
        get_profile(arguments.profile),
        arguments.seed_start,
        arguments.seed_end,
    )

    if arguments.profile in ("cec2022_pilot", "cec2022"):
        functions = get_cec2022_suite(config.dimensions)
    else:
        classical_suite = get_classical_suite()
        functions = classical_suite[:3] if arguments.profile == "smoke" else classical_suite

    script_directory = Path(__file__).resolve().parent
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_directory = arguments.output or (
        script_directory / "results" / f"{arguments.profile}_{timestamp}"
    )
    output_directory.mkdir(parents=True, exist_ok=True)

    _write_or_validate_config(output_directory / "config.json", config)

    print("=" * 72)
    print(f"Profile          : {config.profile_name}")
    print(f"So ham           : {len(functions)}")
    print(f"So chieu         : {config.dimensions}")
    print(f"Kich thuoc quan the: {config.population_size}")
    print(f"FE moi lan chay  : {config.max_evaluations:,}")
    print(f"So seed          : {len(config.seeds)}")
    print(f"Thu muc ket qua  : {output_directory}")
    print("=" * 72)

    raw_rows, convergence_rows = run_experiment(
        functions, config, output_directory
    )
    summarize_results(raw_rows, output_directory)
    rank_rows, average_rank_rows = calculate_ranks_and_tests(
        raw_rows, output_directory
    )

    image_paths = [
        plot_convergence(convergence_rows, output_directory),
        plot_final_error_boxplots(raw_rows, output_directory),
        plot_rank_heatmap(rank_rows, output_directory),
        plot_runtime(raw_rows, output_directory),
    ]

    print("\nHoan thanh. Average rank:")
    for row in sorted(average_rank_rows, key=lambda item: item["average_rank"]):
        print(f"  {row['algorithm']:<5}: {row['average_rank']:.3f}")
    print("Anh da tao:")
    for image_path in image_paths:
        print(f"  {image_path}")


if __name__ == "__main__":
    main()
