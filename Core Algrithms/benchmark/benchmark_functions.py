"""Bộ 12 hàm benchmark CEC 2022 dùng chung cho cả ba thuật toán.

Mỗi hàm nhận ma trận X kích thước ``(số cá thể, số chiều)`` và trả một vector
fitness. Toàn bộ thí nghiệm là bài toán tối thiểu hóa và chỉ dùng evaluator C++
chính thức của CEC 2022.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


PopulationObjective = Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class BenchmarkFunction:
    """Mô tả thống nhất một bài toán benchmark tối thiểu hóa.

    ``lower_bound`` và ``upper_bound`` áp dụng cho mọi chiều của vector.
    ``optimum_value`` là giá trị tối ưu đã biết dùng để tính sai số cuối.
    ``evaluate_population`` nhận ma trận ``(N, D)`` và trả N giá trị fitness.
    """

    name: str
    lower_bound: float
    upper_bound: float
    optimum_value: float
    evaluate_population: PopulationObjective
    category: str


def get_cec2022_suite(dimensions: int) -> list[BenchmarkFunction]:
    """Tạo 12 bài toán bằng evaluator C++ chính thức của CEC 2022.

    CEC 2022 chỉ công bố dữ liệu chính thức cho một số số chiều; benchmark này
    giới hạn ở D=10 hoặc D=20. Mỗi wrapper giữ số thứ tự hàm riêng và chuyển
    toàn bộ quần thể sang adapter C++ khi được gọi.
    """

    from cec2022_official import evaluate_population as evaluate_cec2022

    if dimensions not in (10, 20):
        raise ValueError("CEC 2022 trong project chi ho tro D=10 hoac D=20.")

    optimum_values = (
        300.0,
        400.0,
        600.0,
        800.0,
        900.0,
        1800.0,
        2000.0,
        2200.0,
        2300.0,
        2400.0,
        2600.0,
        2700.0,
    )

    suite: list[BenchmarkFunction] = []
    for function_number, optimum_value in enumerate(optimum_values, start=1):
        def evaluate_population(
            population: np.ndarray,
            wrapped_number=function_number,
        ) -> np.ndarray:
            """Đánh giá quần thể bằng đúng hàm CEC được đóng trong closure."""

            return evaluate_cec2022(population, wrapped_number)

        if function_number == 1:
            category = "Unimodal"
        elif function_number <= 5:
            category = "Basic"
        elif function_number <= 8:
            category = "Hybrid"
        else:
            category = "Composition"

        suite.append(
            BenchmarkFunction(
                name=f"CEC2022-F{function_number}",
                lower_bound=-100.0,
                upper_bound=100.0,
                optimum_value=optimum_value,
                evaluate_population=evaluate_population,
                category=category,
            )
        )

    return suite
