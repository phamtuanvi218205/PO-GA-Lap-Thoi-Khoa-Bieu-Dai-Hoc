"""Tạo bốn biểu đồ PNG từ dữ liệu benchmark đã tổng hợp.

Module dùng backend không giao diện để chạy được trong terminal. Màu của từng
thuật toán được giữ cố định giữa mọi biểu đồ nhằm tránh gây nhầm lẫn khi đọc.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from ordering import function_sort_key


ALGORITHM_COLORS = {
    # Một ánh xạ màu duy nhất dùng cho đường hội tụ, boxplot và runtime.
    "GA": "#2563EB",
    "PO V2": "#EA580C",
    "GA-PO": "#16A34A",
}


def _safe_error(values: np.ndarray) -> np.ndarray:
    """Thay sai số 0 bằng epsilon chỉ cho mục đích hiển thị trên thang log."""

    # Dữ liệu CSV vẫn giữ giá trị 0 thật; phép thay thế không ảnh hưởng thống kê.
    return np.maximum(values, 1e-16)


def plot_convergence(
    convergence_rows: list[dict[str, object]], output_directory: Path
) -> Path:
    """Vẽ median và khoảng tứ phân vị sai số theo FE cho từng hàm.

    Mỗi đường là trung vị qua các seed. Vùng mờ từ Q1 đến Q3 thể hiện độ phân
    tán của 50% lần chạy ở giữa, nhờ đó có thể quan sát cả tốc độ hội tụ và độ
    ổn định mà không để một vài ngoại lệ chi phối biểu đồ.
    """

    functions = sorted(
        {str(row["function"]) for row in convergence_rows},
        key=function_sort_key,
    )
    algorithms = list(ALGORITHM_COLORS.keys())
    number_of_columns = 3
    number_of_rows = int(np.ceil(len(functions) / number_of_columns))
    figure, axes = plt.subplots(
        number_of_rows,
        number_of_columns,
        figsize=(15, 4.2 * number_of_rows),
        squeeze=False,
    )

    for function_index, function_name in enumerate(functions):
        axis = axes.flat[function_index]
        for algorithm_name in algorithms:
            selected = [
                row
                for row in convergence_rows
                if row["function"] == function_name
                and row["algorithm"] == algorithm_name
            ]
            seeds = sorted({int(row["seed"]) for row in selected})
            evaluations = sorted(
                {int(row["evaluations"]) for row in selected}
            )
            curves = []
            for seed in seeds:
                seed_rows = sorted(
                    [row for row in selected if int(row["seed"]) == seed],
                    key=lambda row: int(row["evaluations"]),
                )
                curves.append(
                    [float(row["best_error"]) for row in seed_rows]
                )

            curve_array = _safe_error(np.asarray(curves, dtype=float))
            median = np.median(curve_array, axis=0)
            lower_quartile = np.percentile(curve_array, 25, axis=0)
            upper_quartile = np.percentile(curve_array, 75, axis=0)
            color = ALGORITHM_COLORS[algorithm_name]
            axis.plot(evaluations, median, label=algorithm_name, color=color)
            axis.fill_between(
                evaluations,
                lower_quartile,
                upper_quartile,
                color=color,
                alpha=0.16,
            )

        axis.set_title(function_name)
        axis.set_xlabel("So lan danh gia ham muc tieu (FE)")
        axis.set_ylabel("Sai so tot nhat (log)")
        axis.set_yscale("log")
        axis.grid(True, alpha=0.25)

    for unused_index in range(len(functions), axes.size):
        axes.flat[unused_index].axis("off")

    handles, labels = axes.flat[0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.955),
        ncol=3,
        frameon=False,
    )
    figure.suptitle(
        "Duong hoi tu: trung vi va khoang 25%-75% qua cac lan chay",
        fontsize=15,
        y=0.995,
    )
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.90))
    path = output_directory / "01_convergence.png"
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return path


def plot_final_error_boxplots(
    raw_rows: list[dict[str, object]], output_directory: Path
) -> Path:
    """Vẽ boxplot sai số cuối để so sánh chất lượng và độ ổn định qua seed."""

    functions = sorted(
        {str(row["function"]) for row in raw_rows}, key=function_sort_key
    )
    algorithms = list(ALGORITHM_COLORS.keys())
    number_of_columns = 3
    number_of_rows = int(np.ceil(len(functions) / number_of_columns))
    figure, axes = plt.subplots(
        number_of_rows,
        number_of_columns,
        figsize=(15, 4.0 * number_of_rows),
        squeeze=False,
    )

    for function_index, function_name in enumerate(functions):
        axis = axes.flat[function_index]
        data = []
        for algorithm_name in algorithms:
            values = np.asarray(
                [
                    float(row["final_error"])
                    for row in raw_rows
                    if row["function"] == function_name
                    and row["algorithm"] == algorithm_name
                ],
                dtype=float,
            )
            data.append(_safe_error(values))

        boxes = axis.boxplot(data, tick_labels=algorithms, patch_artist=True)
        for box, algorithm_name in zip(boxes["boxes"], algorithms):
            box.set_facecolor(ALGORITHM_COLORS[algorithm_name])
            box.set_alpha(0.6)
        axis.set_title(function_name)
        axis.set_ylabel("Sai so cuoi (log)")
        axis.set_yscale("log")
        axis.grid(True, axis="y", alpha=0.25)

    for unused_index in range(len(functions), axes.size):
        axes.flat[unused_index].axis("off")

    figure.suptitle("Phan bo sai so cuoi cua tung thuat toan", fontsize=15)
    figure.tight_layout()
    path = output_directory / "02_final_error_boxplots.png"
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return path


def plot_rank_heatmap(
    rank_rows: list[dict[str, object]], output_directory: Path
) -> Path:
    """Vẽ ma trận thứ hạng từng thuật toán trên từng hàm benchmark."""

    functions = sorted(
        {str(row["function"]) for row in rank_rows}, key=function_sort_key
    )
    algorithms = list(ALGORITHM_COLORS.keys())
    rank_matrix = np.empty((len(functions), len(algorithms)), dtype=float)

    for function_index, function_name in enumerate(functions):
        for algorithm_index, algorithm_name in enumerate(algorithms):
            rank_matrix[function_index, algorithm_index] = next(
                float(row["rank"])
                for row in rank_rows
                if row["function"] == function_name
                and row["algorithm"] == algorithm_name
            )

    figure_height = max(4.5, 0.55 * len(functions) + 1.8)
    figure, axis = plt.subplots(figsize=(7.5, figure_height))
    image = axis.imshow(rank_matrix, cmap="RdYlGn_r", vmin=1.0, vmax=3.0)
    axis.set_xticks(range(len(algorithms)), labels=algorithms)
    axis.set_yticks(range(len(functions)), labels=functions)
    axis.set_title("Thu hang theo trung vi sai so (1 la tot nhat)")

    for row_index in range(rank_matrix.shape[0]):
        for column_index in range(rank_matrix.shape[1]):
            axis.text(
                column_index,
                row_index,
                f"{rank_matrix[row_index, column_index]:.1f}",
                ha="center",
                va="center",
                color="black",
                fontweight="bold",
            )

    figure.colorbar(image, ax=axis, label="Rank")
    figure.tight_layout()
    path = output_directory / "03_rank_heatmap.png"
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return path


def plot_runtime(
    raw_rows: list[dict[str, object]], output_directory: Path
) -> Path:
    """Vẽ runtime trung bình và độ lệch chuẩn với cùng ngân sách FE."""

    algorithms = list(ALGORITHM_COLORS.keys())
    means = []
    standard_deviations = []
    for algorithm_name in algorithms:
        runtimes = np.asarray(
            [
                float(row["runtime_seconds"])
                for row in raw_rows
                if row["algorithm"] == algorithm_name
            ],
            dtype=float,
        )
        means.append(float(np.mean(runtimes)))
        standard_deviations.append(float(np.std(runtimes, ddof=1)))

    figure, axis = plt.subplots(figsize=(8, 5))
    bars = axis.bar(
        algorithms,
        means,
        yerr=standard_deviations,
        capsize=5,
        color=[ALGORITHM_COLORS[name] for name in algorithms],
        alpha=0.8,
    )
    axis.bar_label(bars, fmt="%.2f s", padding=4)
    axis.set_ylabel("Thoi gian trung binh moi lan chay (giay)")
    axis.set_title("Chi phi thoi gian voi cung ngan sach FE")
    axis.grid(True, axis="y", alpha=0.25)
    figure.tight_layout()
    path = output_directory / "04_runtime.png"
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return path
