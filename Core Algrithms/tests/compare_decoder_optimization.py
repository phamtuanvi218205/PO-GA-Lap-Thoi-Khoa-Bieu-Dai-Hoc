"""Đối chiếu kết quả và thời gian decoder trước/sau tối ưu trên cùng ca thử.

Chạy tại thư mục ``Core Algrithms``::

    python -m tests.compare_decoder_optimization

CSV hai phía phải có cùng seed, miền, giới hạn node và mọi kết quả giải mã
ngoại trừ thời gian. Script từ chối vẽ ảnh nếu kết quả chức năng thay đổi.
"""

import csv
import json
from pathlib import Path
from statistics import median


RESULT_ROOT = Path(__file__).resolve().parents[1] / "test_results" / "decoder_optimization"
BASELINE_PATH = RESULT_ROOT / "baseline" / "decoder_trials.csv"
OPTIMIZED_PATH = RESULT_ROOT / "optimized" / "decoder_trials.csv"
OUTPUT_DIR = RESULT_ROOT / "comparison"
KEY_FIELDS = ("domain_kind", "session_count", "seed", "max_decode_nodes")


def _read_indexed_rows(path):
    with path.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    indexed = {}
    for row in rows:
        key = tuple(row[field] for field in KEY_FIELDS)
        if key in indexed:
            raise ValueError(f"Khóa thử nghiệm bị trùng trong {path}: {key}")
        indexed[key] = row
    return indexed


def compare_trials():
    baseline = _read_indexed_rows(BASELINE_PATH)
    optimized = _read_indexed_rows(OPTIMIZED_PATH)
    if baseline.keys() != optimized.keys():
        raise AssertionError("Hai bản đo không có cùng bộ ca thử.")

    paired_rows = []
    for key, old_row in baseline.items():
        new_row = optimized[key]
        old_result = {k: v for k, v in old_row.items() if k != "elapsed_ms"}
        new_result = {k: v for k, v in new_row.items() if k != "elapsed_ms"}
        if old_result != new_result:
            raise AssertionError(f"Kết quả decoder thay đổi ở ca {key}.")

        before_ms = float(old_row["elapsed_ms"])
        after_ms = float(new_row["elapsed_ms"])
        paired_rows.append({
            **{field: old_row[field] for field in KEY_FIELDS},
            "status": old_row["status"],
            "nodes_explored": old_row["nodes_explored"],
            "backtracks": old_row["backtracks"],
            "before_ms": before_ms,
            "after_ms": after_ms,
            "speedup": before_ms / after_ms,
        })

    scaling = []
    for session_count in (4, 12, 24, 60):
        subset = [
            row for row in paired_rows
            if row["domain_kind"] == "scaling_stress"
            and int(row["session_count"]) == session_count
        ]
        if len(subset) != 10:
            raise AssertionError(f"Thiếu 10 seed cho quy mô {session_count} buổi.")
        before_median = median(row["before_ms"] for row in subset)
        after_median = median(row["after_ms"] for row in subset)
        scaling.append({
            "sessions": session_count,
            "trials": len(subset),
            "successes": sum(row["status"] == "SUCCESS" for row in subset),
            "before_median_ms": before_median,
            "after_median_ms": after_median,
            "median_speedup_ratio": before_median / after_median,
        })

    summary = {
        "description": "Paired local timing on synthetic decoder cases; not HUIT or GA–PO",
        "compared_trials": len(paired_rows),
        "identical_non_timing_results": True,
        "scaling": scaling,
    }
    return summary, paired_rows


def _plot(summary, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scaling = summary["scaling"]
    sessions = [row["sessions"] for row in scaling]
    speedups = [row["median_speedup_ratio"] for row in scaling]

    figure, axis = plt.subplots(figsize=(8.6, 4.8))
    axis.plot(sessions, speedups, marker="o", linewidth=2)
    axis.axhline(1, color="gray", linestyle="--", linewidth=1)
    axis.set_title("Decoder speed after same-day compatibility indexing")
    axis.set_xlabel("Number of sessions")
    axis.set_ylabel("Median speedup (before / after)")
    axis.set_xticks(sessions)
    axis.set_ylim(0, max(speedups) + 2.8)
    axis.grid(axis="y", alpha=0.25)

    for position, row in enumerate(scaling):
        precision = 2 if row["sessions"] == 4 else 1
        label = (
            f"{row['median_speedup_ratio']:.1f}x\n"
            f"{row['before_median_ms']:.{precision}f} → "
            f"{row['after_median_ms']:.{precision}f} ms"
        )
        if position == 0:
            horizontal_alignment = "left"
        elif position == len(scaling) - 1:
            horizontal_alignment = "right"
        else:
            horizontal_alignment = "center"
        axis.annotate(
            label,
            (row["sessions"], row["median_speedup_ratio"]),
            xytext=(0, 10), textcoords="offset points", ha=horizontal_alignment,
        )

    figure.text(
        0.5, 0.01,
        "10 paired seeds per size; all 320 non-timing outputs identical. "
        "Synthetic fixture, local timing only.",
        ha="center", fontsize=9,
    )
    figure.tight_layout(rect=(0, 0.05, 1, 1))
    figure.savefig(path, dpi=180)
    plt.close(figure)


def main():
    summary, paired_rows = compare_trials()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT_DIR / "paired_trials.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(paired_rows[0]))
        writer.writeheader()
        writer.writerows(paired_rows)

    summary_path = OUTPUT_DIR / "comparison.json"
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    image_path = OUTPUT_DIR / "decoder_speedup.png"
    _plot(summary, image_path)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Image: {image_path}")


if __name__ == "__main__":
    main()
