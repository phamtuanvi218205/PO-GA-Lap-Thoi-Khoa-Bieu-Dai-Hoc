"""Điều phối nhiều lần chạy, lưu checkpoint và tổng hợp thống kê.

Mỗi bộ ba ``(function, algorithm, seed)`` là một lần chạy độc lập. Module bảo
đảm ba thuật toán nhận cùng quần thể khởi tạo cho cùng function/seed, đo cùng
ngân sách FE và lưu đủ dữ liệu để tiếp tục nếu tiến trình bị gián đoạn.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.stats import friedmanchisquare, rankdata, wilcoxon

from ordering import function_sort_key

from algorithms import ALGORITHMS
from benchmark_functions import BenchmarkFunction


MAX_CONVERGENCE_POINTS_PER_RUN = 501
OPTIMUM_TOLERANCE = 1e-10
RAW_RESULT_FIELDS = (
    "profile",
    "function",
    "category",
    "algorithm",
    "seed",
    "dimensions",
    "population_size",
    "max_evaluations",
    "best_value",
    "optimum_value",
    "final_error",
    "runtime_seconds",
)
CONVERGENCE_FIELDS = (
    "function",
    "algorithm",
    "seed",
    "evaluations",
    "best_error",
)


@dataclass(frozen=True)
class ExperimentConfig:
    """Cấu hình quy mô dùng chung cho một profile benchmark.

    ``seeds`` biểu diễn các lần chạy độc lập. Cấu hình không chứa danh sách hàm
    vì suite được runner lựa chọn riêng theo tên profile.
    """

    profile_name: str
    dimensions: int
    population_size: int
    max_evaluations: int
    seeds: tuple[int, ...]


def create_initial_population(
    function: BenchmarkFunction,
    dimensions: int,
    population_size: int,
    seed: int,
) -> np.ndarray:
    """Cung function va seed se luon tao dung cung mot quan the ban dau."""

    rng = np.random.default_rng(seed)
    return rng.uniform(
        function.lower_bound,
        function.upper_bound,
        size=(population_size, dimensions),
    )


def _algorithm_seed(run_seed: int, algorithm_index: int) -> int:
    """Tạo seed riêng, xác định và tái lập được cho từng thuật toán."""

    # Tao random stream rieng nhung lap lai duoc cho tung thuat toan.
    seed_sequence = np.random.SeedSequence([run_seed, algorithm_index, 2026])
    return int(seed_sequence.generate_state(1, dtype=np.uint32)[0])


def _run_key(row: dict[str, object]) -> tuple[str, str, int]:
    """Tạo khóa duy nhất function–algorithm–seed cho checkpoint và merge."""

    return str(row["function"]), str(row["algorithm"]), int(row["seed"])


def _read_csv(path: Path) -> list[dict[str, object]]:
    """Đọc CSV UTF-8 có BOM; file chưa tồn tại hoặc rỗng được xem là chưa có dữ liệu."""

    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def _append_csv(
    path: Path,
    rows: list[dict[str, object]],
    fieldnames: tuple[str, ...],
) -> None:
    """Ghi nối tiếp các dòng và chỉ tạo header khi file còn rỗng."""

    if not rows:
        return
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def _sample_history(
    evaluations: list[int],
    best_values: list[float],
    maximum_points: int = MAX_CONVERGENCE_POINTS_PER_RUN,
) -> list[tuple[int, float]]:
    """Lay mau deu va luon giu moc FE dau/cuoi de gioi han kich thuoc CSV."""

    if len(evaluations) != len(best_values):
        raise ValueError("Lich su FE va best fitness phai co cung do dai.")
    if maximum_points < 2:
        raise ValueError("maximum_points phai it nhat bang 2.")
    if len(evaluations) <= maximum_points:
        return list(zip(evaluations, best_values))

    indices = np.linspace(
        0, len(evaluations) - 1, num=maximum_points, dtype=int
    )
    unique_indices = np.unique(indices)
    return [
        (evaluations[int(index)], best_values[int(index)])
        for index in unique_indices
    ]


def run_experiment(
    functions: list[BenchmarkFunction],
    config: ExperimentConfig,
    output_directory: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Chạy mọi tổ hợp function, seed và algorithm trong cấu hình.

    Hàm hỗ trợ resume bằng ``raw_results.csv``: một run chỉ được xem là hoàn
    tất khi dòng raw tương ứng đã được ghi. Kết quả trả về gồm dữ liệu cuối mỗi
    run và lịch sử hội tụ đã lấy mẫu để phục vụ thống kê và vẽ biểu đồ.
    """

    output_directory.mkdir(parents=True, exist_ok=True)
    raw_path = output_directory / "raw_results.csv"
    convergence_path = output_directory / "convergence.csv"

    expected_keys = {
        (function.name, algorithm_name, seed)
        for function in functions
        for seed in config.seeds
        for algorithm_name in ALGORITHMS
    }

    # raw_results.csv la dau moc hoan tat cua mot lan chay. Neu chuong trinh
    # tung bi ngat sau khi ghi convergence, cac dong chua co raw tuong ung se
    # bi loai de lan resume khong tao du lieu trung.
    raw_by_key = {
        _run_key(row): row
        for row in _read_csv(raw_path)
        if _run_key(row) in expected_keys
    }
    raw_rows = list(raw_by_key.values())
    completed_keys = set(raw_by_key)
    convergence_rows = [
        row
        for row in _read_csv(convergence_path)
        if _run_key(row) in completed_keys
    ]
    write_csv(raw_path, raw_rows, RAW_RESULT_FIELDS)
    write_csv(convergence_path, convergence_rows, CONVERGENCE_FIELDS)

    total_runs = len(functions) * len(config.seeds) * len(ALGORITHMS)
    completed_runs = len(completed_keys)
    if completed_runs:
        print(
            f"Tiep tuc tu checkpoint: {completed_runs}/{total_runs} "
            "lan chay da hoan tat."
        )

    for function in functions:
        for seed in config.seeds:
            # Cùng function và seed tạo đúng một quần thể gốc; mỗi thuật toán
            # nhận bản sao để so sánh không bị lệch điểm xuất phát.
            initial_population = create_initial_population(
                function,
                config.dimensions,
                config.population_size,
                seed,
            )

            for algorithm_index, (algorithm_name, algorithm) in enumerate(
                ALGORITHMS.items(), start=1
            ):
                run_key = (function.name, algorithm_name, seed)
                if run_key in completed_keys:
                    continue

                started_at = time.perf_counter()
                result = algorithm(
                    objective=function.evaluate_population,
                    initial_population=initial_population.copy(),
                    lower_bound=function.lower_bound,
                    upper_bound=function.upper_bound,
                    max_evaluations=config.max_evaluations,
                    seed=_algorithm_seed(seed, algorithm_index),
                )
                runtime_seconds = time.perf_counter() - started_at
                signed_error = result.best_value - function.optimum_value
                # Một giá trị thấp hơn optimum đã biết thường báo hiệu adapter,
                # dữ liệu CEC hoặc phép tính đang sai; không được âm thầm ép 0.
                allowed_roundoff = OPTIMUM_TOLERANCE * max(
                    1.0, abs(function.optimum_value)
                )
                if signed_error < -allowed_roundoff:
                    raise ValueError(
                        f"{function.name} tra best_value={result.best_value} "
                        f"thap hon optimum={function.optimum_value}. "
                        "Dung benchmark de kiem tra evaluator/adapter."
                    )
                final_error = max(signed_error, 0.0)

                raw_row = {
                    "profile": config.profile_name,
                    "function": function.name,
                    "category": function.category,
                    "algorithm": algorithm_name,
                    "seed": seed,
                    "dimensions": config.dimensions,
                    "population_size": config.population_size,
                    "max_evaluations": config.max_evaluations,
                    "best_value": result.best_value,
                    "optimum_value": function.optimum_value,
                    "final_error": final_error,
                    "runtime_seconds": runtime_seconds,
                }

                run_convergence_rows = []
                for evaluations, best_value in _sample_history(
                    result.history_evaluations,
                    result.history_best_values,
                ):
                    run_convergence_rows.append(
                        {
                            "function": function.name,
                            "algorithm": algorithm_name,
                            "seed": seed,
                            "evaluations": evaluations,
                            "best_error": max(
                                best_value - function.optimum_value, 0.0
                            ),
                        }
                    )

                # Ghi convergence truoc, raw sau. raw la commit marker; neu bi
                # ngat o giua, lan resume se don cac dong convergence mo coi.
                _append_csv(
                    convergence_path,
                    run_convergence_rows,
                    CONVERGENCE_FIELDS,
                )
                _append_csv(raw_path, [raw_row], RAW_RESULT_FIELDS)
                convergence_rows.extend(run_convergence_rows)
                raw_rows.append(raw_row)
                completed_keys.add(run_key)

                completed_runs += 1
                print(
                    f"[{completed_runs:>3}/{total_runs}] "
                    f"{function.name:<14} | {algorithm_name:<5} | "
                    f"seed={seed:<3} | error={final_error:.6e} | "
                    f"{runtime_seconds:.2f}s"
                )

    return raw_rows, convergence_rows


def write_csv(
    path: Path,
    rows: list[dict[str, object]],
    fieldnames: tuple[str, ...] | None = None,
) -> None:
    """Ghi lại toàn bộ CSV theo thứ tự field xác định, thay thế file cũ."""

    if fieldnames is None:
        if not rows:
            return
        fieldnames = tuple(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize_results(
    raw_rows: list[dict[str, object]], output_directory: Path
) -> list[dict[str, object]]:
    """Tổng hợp sai số và runtime qua các seed cho từng function/algorithm."""

    summary_rows: list[dict[str, object]] = []
    functions = sorted(
        {str(row["function"]) for row in raw_rows}, key=function_sort_key
    )
    algorithms = list(ALGORITHMS.keys())

    for function_name in functions:
        for algorithm_name in algorithms:
            selected = [
                row
                for row in raw_rows
                if row["function"] == function_name
                and row["algorithm"] == algorithm_name
            ]
            errors = np.asarray(
                [float(row["final_error"]) for row in selected], dtype=float
            )
            runtimes = np.asarray(
                [float(row["runtime_seconds"]) for row in selected], dtype=float
            )
            summary_rows.append(
                {
                    "function": function_name,
                    "algorithm": algorithm_name,
                    "runs": len(errors),
                    "best_error": float(np.min(errors)),
                    "worst_error": float(np.max(errors)),
                    "mean_error": float(np.mean(errors)),
                    "median_error": float(np.median(errors)),
                    "std_error": float(np.std(errors, ddof=1))
                    if len(errors) > 1
                    else 0.0,
                    "mean_runtime_seconds": float(np.mean(runtimes)),
                }
            )

    write_csv(output_directory / "summary.csv", summary_rows)
    return summary_rows


def calculate_ranks_and_tests(
    raw_rows: list[dict[str, object]], output_directory: Path
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Xếp hạng theo median và thực hiện các kiểm định thống kê không tham số.

    Với mỗi hàm, thuật toán có median error thấp nhất nhận hạng 1. Friedman kiểm
    tra khác biệt tổng thể giữa ba thuật toán; Wilcoxon so sánh từng cặp và Holm
    điều chỉnh p-value để hạn chế sai lầm khi thực hiện nhiều phép kiểm định.
    """

    functions = sorted(
        {str(row["function"]) for row in raw_rows}, key=function_sort_key
    )
    algorithms = list(ALGORITHMS.keys())
    rank_rows: list[dict[str, object]] = []
    median_matrix: list[list[float]] = []

    for function_name in functions:
        medians: list[float] = []
        for algorithm_name in algorithms:
            values = [
                float(row["final_error"])
                for row in raw_rows
                if row["function"] == function_name
                and row["algorithm"] == algorithm_name
            ]
            medians.append(float(np.median(values)))

        ranks = rankdata(medians, method="average")
        median_matrix.append(medians)
        for algorithm_name, median_error, rank in zip(
            algorithms, medians, ranks
        ):
            rank_rows.append(
                {
                    "function": function_name,
                    "algorithm": algorithm_name,
                    "median_error": median_error,
                    "rank": float(rank),
                }
            )

    average_rank_rows = []
    for algorithm_name in algorithms:
        algorithm_ranks = [
            float(row["rank"])
            for row in rank_rows
            if row["algorithm"] == algorithm_name
        ]
        average_rank_rows.append(
            {
                "algorithm": algorithm_name,
                "average_rank": float(np.mean(algorithm_ranks)),
            }
        )

    write_csv(output_directory / "ranks.csv", rank_rows)
    write_csv(output_directory / "average_ranks.csv", average_rank_rows)

    statistical_rows: list[dict[str, object]] = []
    if len(functions) >= 3:
        columns = np.asarray(median_matrix, dtype=float).T
        friedman = friedmanchisquare(*columns)
        statistical_rows.append(
            {
                "test": "Friedman on per-function median errors",
                "comparison": "GA vs PO V2 vs GA-PO",
                "statistic": float(friedman.statistic),
                "p_value": float(friedman.pvalue),
                "holm_adjusted_p": "",
            }
        )

        pairwise: list[dict[str, object]] = []
        for first_index in range(len(algorithms)):
            for second_index in range(first_index + 1, len(algorithms)):
                try:
                    test = wilcoxon(
                        columns[first_index],
                        columns[second_index],
                        zero_method="zsplit",
                    )
                    p_value = float(test.pvalue)
                    statistic = float(test.statistic)
                except ValueError:
                    p_value = 1.0
                    statistic = 0.0
                pairwise.append(
                    {
                        "test": "Wilcoxon on per-function median errors",
                        "comparison": (
                            f"{algorithms[first_index]} vs "
                            f"{algorithms[second_index]}"
                        ),
                        "statistic": statistic,
                        "p_value": p_value,
                    }
                )

        # Holm: p nho nhat nhan m, p ke tiep nhan m-1; dam bao khong giam.
        sorted_indices = sorted(
            range(len(pairwise)), key=lambda index: pairwise[index]["p_value"]
        )
        previous_adjusted = 0.0
        for order, pairwise_index in enumerate(sorted_indices):
            multiplier = len(pairwise) - order
            adjusted = min(
                1.0, float(pairwise[pairwise_index]["p_value"]) * multiplier
            )
            adjusted = max(adjusted, previous_adjusted)
            pairwise[pairwise_index]["holm_adjusted_p"] = adjusted
            previous_adjusted = adjusted
        statistical_rows.extend(pairwise)

    write_csv(output_directory / "statistical_tests.csv", statistical_rows)
    return rank_rows, average_rank_rows
