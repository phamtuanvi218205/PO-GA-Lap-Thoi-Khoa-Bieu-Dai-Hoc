"""Cac ham benchmark so hoc dung chung cho ca ba thuat toan.

Moi ham nhan mot ma tran X co kich thuoc (so_ca_the, so_chieu) va tra ve
mot vector fitness. Bai toan benchmark deu la bai toan toi thieu hoa.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


PopulationObjective = Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class BenchmarkFunction:
    """Mo ta day du mot bai toan benchmark."""

    name: str
    lower_bound: float
    upper_bound: float
    optimum_value: float
    evaluate_population: PopulationObjective
    category: str


def sphere(population: np.ndarray) -> np.ndarray:
    return np.sum(population**2, axis=1)


def bent_cigar(population: np.ndarray) -> np.ndarray:
    first_coordinate = population[:, 0] ** 2
    remaining_coordinates = np.sum(population[:, 1:] ** 2, axis=1)
    return first_coordinate + 1_000_000.0 * remaining_coordinates


def rosenbrock(population: np.ndarray) -> np.ndarray:
    left = population[:, :-1]
    right = population[:, 1:]
    return np.sum(100.0 * (right - left**2) ** 2 + (left - 1.0) ** 2, axis=1)


def rastrigin(population: np.ndarray) -> np.ndarray:
    dimensions = population.shape[1]
    return 10.0 * dimensions + np.sum(
        population**2 - 10.0 * np.cos(2.0 * np.pi * population), axis=1
    )


def ackley(population: np.ndarray) -> np.ndarray:
    mean_square = np.mean(population**2, axis=1)
    mean_cosine = np.mean(np.cos(2.0 * np.pi * population), axis=1)
    return (
        -20.0 * np.exp(-0.2 * np.sqrt(mean_square))
        - np.exp(mean_cosine)
        + 20.0
        + np.e
    )


def griewank(population: np.ndarray) -> np.ndarray:
    dimensions = population.shape[1]
    coordinate_numbers = np.arange(1, dimensions + 1, dtype=float)
    sum_term = np.sum(population**2, axis=1) / 4000.0
    product_term = np.prod(
        np.cos(population / np.sqrt(coordinate_numbers)), axis=1
    )
    return sum_term - product_term + 1.0


def schwefel(population: np.ndarray) -> np.ndarray:
    dimensions = population.shape[1]
    return 418.9828872724338 * dimensions - np.sum(
        population * np.sin(np.sqrt(np.abs(population))), axis=1
    )


def levy(population: np.ndarray) -> np.ndarray:
    transformed = 1.0 + (population - 1.0) / 4.0
    first_term = np.sin(np.pi * transformed[:, 0]) ** 2
    middle = transformed[:, :-1]
    middle_term = np.sum(
        (middle - 1.0) ** 2
        * (1.0 + 10.0 * np.sin(np.pi * middle + 1.0) ** 2),
        axis=1,
    )
    last = transformed[:, -1]
    last_term = (last - 1.0) ** 2 * (
        1.0 + np.sin(2.0 * np.pi * last) ** 2
    )
    return first_term + middle_term + last_term


def zakharov(population: np.ndarray) -> np.ndarray:
    dimensions = population.shape[1]
    coordinate_numbers = np.arange(1, dimensions + 1, dtype=float)
    weighted_sum = np.sum(0.5 * coordinate_numbers * population, axis=1)
    return (
        np.sum(population**2, axis=1)
        + weighted_sum**2
        + weighted_sum**4
    )


def get_classical_suite() -> list[BenchmarkFunction]:
    """Tra ve bo ham co ban gom ca don dinh va da dinh."""

    return [
        BenchmarkFunction("Sphere", -100.0, 100.0, 0.0, sphere, "Unimodal"),
        BenchmarkFunction(
            "Bent Cigar", -100.0, 100.0, 0.0, bent_cigar, "Ill-conditioned"
        ),
        BenchmarkFunction(
            "Rosenbrock", -30.0, 30.0, 0.0, rosenbrock, "Valley"
        ),
        BenchmarkFunction(
            "Rastrigin", -5.12, 5.12, 0.0, rastrigin, "Multimodal"
        ),
        BenchmarkFunction(
            "Ackley", -32.768, 32.768, 0.0, ackley, "Multimodal"
        ),
        BenchmarkFunction(
            "Griewank", -600.0, 600.0, 0.0, griewank, "Multimodal"
        ),
        BenchmarkFunction(
            "Schwefel", -500.0, 500.0, 0.0, schwefel, "Deceptive"
        ),
        BenchmarkFunction("Levy", -10.0, 10.0, 0.0, levy, "Multimodal"),
        BenchmarkFunction(
            "Zakharov", -5.0, 10.0, 0.0, zakharov, "Non-separable"
        ),
    ]


def get_cec2022_suite(dimensions: int) -> list[BenchmarkFunction]:
    """Nap 12 ham bang evaluator C++ chinh thuc cua CEC 2022."""

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
