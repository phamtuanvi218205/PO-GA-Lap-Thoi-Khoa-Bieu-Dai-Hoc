"""Đo decoder trên fixture 12 buổi và tạo ảnh từ dữ liệu chạy thật.

Chạy tại thư mục ``Core Algrithms``::

    PYTHONPATH=src python -m tests.run_decoder_multisession_experiment

Cần matplotlib để vẽ PNG. Đây là phép kiểm thử decoder trên dữ liệu tổng hợp,
không phải benchmark GA/PO và không đại diện cho cả học kỳ HUIT.
"""

import argparse
import csv
import json
from pathlib import Path
import platform
import random
from statistics import median
from time import perf_counter

from gapo_timetabling.constraints import validate_timetable
from gapo_timetabling.decoder import DecodeStatus, decode_vector
from gapo_timetabling.encoder import build_option_domains
from tests.decoder_scenarios import make_multisession_problem, make_stress_domains


SEED_COUNT = 40
NODE_BUDGETS = (12, 14, 16, 18, 24, 40)
SCALING_WEEKS = (1, 3, 6, 15)
SCALING_SEED_COUNT = 10
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "test_results" / "decoder_multisession"


def _gene_selects_index(gene: float, option_count: int) -> int:
    return min(int(gene * option_count), option_count - 1)


def _run_one(problem, domains, vector, budget, seed, domain_kind):
    started = perf_counter()
    result = decode_vector(problem, domains, vector, max_decode_nodes=budget)
    elapsed_ms = (perf_counter() - started) * 1000

    if result.status == DecodeStatus.SUCCESS:
        if not validate_timetable(problem, result.selected_options).is_valid:
            raise AssertionError("Decoder trả SUCCESS cho lịch không hợp lệ.")
        for session_index, selected_index in enumerate(result.selected_option_indices):
            decoded_index = _gene_selects_index(
                result.repaired_vector[session_index],
                len(domains[session_index]),
            )
            if decoded_index != selected_index:
                raise AssertionError("Vector đã đồng bộ không khớp option được chọn.")

    return {
        "domain_kind": domain_kind,
        "session_count": problem.dimension,
        "seed": seed,
        "max_decode_nodes": budget,
        "status": result.status.value,
        "selected_option_indices": json.dumps(result.selected_option_indices),
        "repaired_vector": json.dumps(result.repaired_vector),
        "nodes_explored": result.nodes_explored,
        "backtracks": result.backtracks,
        "elapsed_ms": round(elapsed_ms, 6),
        "failed_session_index": result.failed_session_index,
        "reason": result.reason,
    }


def run_experiment():
    problem = make_multisession_problem(3)
    stress_domains = make_stress_domains(problem)
    encoder_domains = build_option_domains(problem)

    rows = []
    for seed in range(SEED_COUNT):
        rng = random.Random(seed)
        vector = tuple(rng.random() for _ in range(problem.dimension))

        for budget in NODE_BUDGETS:
            rows.append(
                _run_one(problem, stress_domains, vector, budget, seed, "stress")
            )
        rows.append(
            _run_one(
                problem,
                encoder_domains,
                vector,
                max(NODE_BUDGETS),
                seed,
                "full_encoder",
            )
        )

    # Thử kích thước lớn hơn trên cùng mẫu tổng hợp. Đây là số đo cục bộ,
    # không phải giới hạn hiệu năng hoặc dữ liệu cả học kỳ HUIT.
    for week_count in SCALING_WEEKS:
        scaled_problem = make_multisession_problem(week_count)
        scaled_domains = make_stress_domains(scaled_problem)
        budget = 4 * scaled_problem.dimension
        for seed in range(SCALING_SEED_COUNT):
            rng = random.Random(seed)
            vector = tuple(rng.random() for _ in range(scaled_problem.dimension))
            rows.append(
                _run_one(
                    scaled_problem,
                    scaled_domains,
                    vector,
                    budget,
                    seed,
                    "scaling_stress",
                )
            )

    return problem, rows


def _summarize(problem, rows):
    stress_by_budget = {}
    for budget in NODE_BUDGETS:
        subset = [
            row for row in rows
            if row["domain_kind"] == "stress"
            and row["max_decode_nodes"] == budget
        ]
        successes = [row for row in subset if row["status"] == "SUCCESS"]
        stress_by_budget[str(budget)] = {
            "successes": len(successes),
            "trials": len(subset),
            "success_rate": len(successes) / len(subset),
            "median_elapsed_ms": median(row["elapsed_ms"] for row in subset),
        }

    full_budget = max(NODE_BUDGETS)
    stress_full = [
        row for row in rows
        if row["domain_kind"] == "stress"
        and row["max_decode_nodes"] == full_budget
    ]
    encoder_full = [row for row in rows if row["domain_kind"] == "full_encoder"]
    scaling = []
    for week_count in SCALING_WEEKS:
        session_count = 4 * week_count
        subset = [
            row for row in rows
            if row["domain_kind"] == "scaling_stress"
            and row["session_count"] == session_count
        ]
        scaling.append({
            "weeks": week_count,
            "sessions": session_count,
            "successes": sum(row["status"] == "SUCCESS" for row in subset),
            "trials": len(subset),
            "median_elapsed_ms": median(row["elapsed_ms"] for row in subset),
            "min_elapsed_ms": min(row["elapsed_ms"] for row in subset),
            "max_elapsed_ms": max(row["elapsed_ms"] for row in subset),
            "median_nodes": median(row["nodes_explored"] for row in subset),
        })

    return {
        "description": "Synthetic decoder check, not HUIT or GA–PO benchmark",
        "python_version": platform.python_version(),
        "weeks": 3,
        "sessions": problem.dimension,
        "seed_count": SEED_COUNT,
        "seeds": list(range(SEED_COUNT)),
        "node_budgets": list(NODE_BUDGETS),
        "scaling_seed_count": SCALING_SEED_COUNT,
        "scaling_seeds": list(range(SCALING_SEED_COUNT)),
        "scaling_budget_rule": "4 * session_count",
        "stress_by_budget": stress_by_budget,
        "stress_full_budget": {
            "successes": sum(row["status"] == "SUCCESS" for row in stress_full),
            "nodes_min": min(row["nodes_explored"] for row in stress_full),
            "nodes_median": median(row["nodes_explored"] for row in stress_full),
            "nodes_max": max(row["nodes_explored"] for row in stress_full),
            "backtracks_median": median(row["backtracks"] for row in stress_full),
        },
        "full_encoder": {
            "successes": sum(row["status"] == "SUCCESS" for row in encoder_full),
            "nodes_median": median(row["nodes_explored"] for row in encoder_full),
        },
        "scaling_stress": scaling,
    }


def _plot(summary, rows, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    budgets = list(NODE_BUDGETS)
    success_rates = [
        100 * summary["stress_by_budget"][str(budget)]["success_rate"]
        for budget in budgets
    ]
    full_budget = max(NODE_BUDGETS)
    stress_full = sorted(
        (
            row for row in rows
            if row["domain_kind"] == "stress"
            and row["max_decode_nodes"] == full_budget
        ),
        key=lambda row: row["seed"],
    )

    figure, (success_axis, nodes_axis) = plt.subplots(1, 2, figsize=(11, 4.2))
    figure.suptitle("Decoder check: 12 sessions, 3 weeks, 40 seeded vectors")

    success_axis.plot(budgets, success_rates, marker="o", linewidth=2)
    success_axis.set_xlabel("Maximum decode nodes")
    success_axis.set_ylabel("Valid schedules (%)")
    success_axis.set_xticks(budgets)
    success_axis.set_ylim(-3, 105)
    success_axis.grid(axis="y", alpha=0.25)
    for budget, rate in zip(budgets, success_rates):
        success_axis.annotate(f"{rate:g}%", (budget, rate), xytext=(0, 7),
                              textcoords="offset points", ha="center")

    seed_ids = [row["seed"] for row in stress_full]
    node_counts = [row["nodes_explored"] for row in stress_full]
    backtracks = [row["backtracks"] for row in stress_full]
    nodes_axis.plot(seed_ids, node_counts, marker="o", markersize=3,
                    linewidth=1, label="Nodes explored")
    nodes_axis.plot(seed_ids, backtracks, marker="s", markersize=3,
                    linewidth=1, label="Backtracks")
    nodes_axis.set_xlabel("Seed")
    nodes_axis.set_ylabel("Count (budget = 40)")
    nodes_axis.set_ylim(bottom=0)
    nodes_axis.grid(axis="y", alpha=0.25)
    nodes_axis.legend(frameon=False)

    figure.text(
        0.5, 0.01,
        "Synthetic restricted domains; each success independently validated. "
        "Not a GA/PO or HUIT-scale result.",
        ha="center", fontsize=9,
    )
    figure.tight_layout(rect=(0, 0.055, 1, 0.96))
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _plot_scaling(summary, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scaling = summary["scaling_stress"]
    sessions = [row["sessions"] for row in scaling]
    medians = [row["median_elapsed_ms"] for row in scaling]
    lower_errors = [
        row["median_elapsed_ms"] - row["min_elapsed_ms"] for row in scaling
    ]
    upper_errors = [
        row["max_elapsed_ms"] - row["median_elapsed_ms"] for row in scaling
    ]

    figure, axis = plt.subplots(figsize=(7.5, 4.3))
    axis.errorbar(
        sessions, medians, yerr=(lower_errors, upper_errors),
        marker="o", linewidth=2, capsize=4,
    )
    axis.set_title("Decoder timing on repeated synthetic weeks")
    axis.set_xlabel("Number of sessions")
    axis.set_ylabel("Decode time per vector (ms)")
    axis.set_xticks(sessions)
    axis.set_ylim(bottom=0)
    axis.grid(axis="y", alpha=0.25)
    for session_count, value in zip(sessions, medians):
        axis.annotate(f"{value:.1f} ms", (session_count, value),
                      xytext=(0, 8), textcoords="offset points", ha="center")
    figure.text(
        0.5, 0.01,
        "Median and min-max of 10 seeded vectors per size; local indicative timing only.",
        ha="center", fontsize=9,
    )
    figure.tight_layout(rect=(0, 0.05, 1, 1))
    figure.savefig(path, dpi=180)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Thư mục lưu CSV, JSON và ảnh; mặc định là test_results/decoder_multisession.",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()

    problem, rows = run_experiment()
    summary = _summarize(problem, rows)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "decoder_trials.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary_path = output_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    image_path = output_dir / "decoder_stability.png"
    _plot(summary, rows, image_path)
    scaling_image_path = output_dir / "decoder_scaling.png"
    _plot_scaling(summary, scaling_image_path)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"CSV: {csv_path}")
    print(f"Image: {image_path}")
    print(f"Scaling image: {scaling_image_path}")


if __name__ == "__main__":
    main()
