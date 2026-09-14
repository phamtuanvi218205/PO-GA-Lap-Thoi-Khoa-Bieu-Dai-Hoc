"""Ba thuat toan toi uu lien tuc dung trong benchmark.

Muc dich cua file nay la so sanh co che tim kiem tren cac ham so hoc.
File khong ma hoa, giai ma hoac xu ly rang buoc thoi khoa bieu.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np


ObjectiveFunction = Callable[[np.ndarray], np.ndarray]


@dataclass
class OptimizationResult:
    algorithm: str
    best_position: np.ndarray
    best_value: float
    history_evaluations: list[int]
    history_best_values: list[float]
    evaluations_used: int


def _evaluate(objective: ObjectiveFunction, population: np.ndarray) -> np.ndarray:
    values = np.asarray(objective(population), dtype=float)
    if values.shape != (len(population),):
        raise ValueError("Ham muc tieu phai tra ve mot fitness cho moi ca the.")
    return values


def _best_from_population(
    population: np.ndarray, fitness: np.ndarray
) -> tuple[np.ndarray, float]:
    best_index = int(np.argmin(fitness))
    return population[best_index].copy(), float(fitness[best_index])


def _validate_budget(population_size: int, max_evaluations: int) -> int:
    if max_evaluations < population_size:
        raise ValueError("max_evaluations phai it nhat bang population_size.")
    remaining = max_evaluations - population_size
    if remaining % population_size != 0:
        raise ValueError(
            "De ba thuat toan dung dung cung FE, "
            "(max_evaluations - population_size) phai chia het cho population_size."
        )
    return remaining // population_size


def _tournament_selection(
    population: np.ndarray,
    fitness: np.ndarray,
    number_to_select: int,
    tournament_size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Chon cha me; trong moi tournament, ca the co fitness nho nhat thang."""

    selected = np.empty((number_to_select, population.shape[1]), dtype=float)
    population_size = len(population)
    for selected_index in range(number_to_select):
        competitors = rng.integers(0, population_size, size=tournament_size)
        winner = competitors[int(np.argmin(fitness[competitors]))]
        selected[selected_index] = population[winner]
    return selected


def _sbx_pair(
    first_parent: np.ndarray,
    second_parent: np.ndarray,
    crossover_probability: float,
    distribution_index: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Lai ghep Simulated Binary Crossover cho vector so thuc."""

    if rng.random() > crossover_probability:
        return first_parent.copy(), second_parent.copy()

    random_values = rng.random(first_parent.size)
    beta = np.empty_like(random_values)
    lower_half = random_values <= 0.5
    beta[lower_half] = (2.0 * random_values[lower_half]) ** (
        1.0 / (distribution_index + 1.0)
    )
    beta[~lower_half] = (
        1.0 / (2.0 * (1.0 - random_values[~lower_half]))
    ) ** (1.0 / (distribution_index + 1.0))

    first_child = 0.5 * (
        (1.0 + beta) * first_parent + (1.0 - beta) * second_parent
    )
    second_child = 0.5 * (
        (1.0 - beta) * first_parent + (1.0 + beta) * second_parent
    )
    return first_child, second_child


def _polynomial_mutation(
    children: np.ndarray,
    lower_bound: float,
    upper_bound: float,
    mutation_probability: float,
    distribution_index: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Dot bien polynomial cho ca ma tran con, moi gene boc tham rieng."""

    mutated = np.clip(children.copy(), lower_bound, upper_bound)
    width = upper_bound - lower_bound
    mutation_mask = rng.random(mutated.shape) <= mutation_probability
    random_values = rng.random(mutated.shape)
    distance_to_lower = (mutated - lower_bound) / width
    distance_to_upper = (upper_bound - mutated) / width
    mutation_power = 1.0 / (distribution_index + 1.0)

    lower_expression = (
        2.0 * random_values
        + (1.0 - 2.0 * random_values)
        * (1.0 - distance_to_lower) ** (distribution_index + 1.0)
    )
    lower_change = lower_expression**mutation_power - 1.0

    upper_expression = (
        2.0 * (1.0 - random_values)
        + 2.0
        * (random_values - 0.5)
        * (1.0 - distance_to_upper) ** (distribution_index + 1.0)
    )
    upper_change = 1.0 - upper_expression**mutation_power
    changes = np.where(random_values <= 0.5, lower_change, upper_change)

    mutated = mutated + np.where(mutation_mask, changes * width, 0.0)
    return np.clip(mutated, lower_bound, upper_bound)


def _create_ga_children(
    population: np.ndarray,
    fitness: np.ndarray,
    number_of_children: int,
    lower_bound: float,
    upper_bound: float,
    rng: np.random.Generator,
) -> np.ndarray:
    dimensions = population.shape[1]
    parents = _tournament_selection(
        population=population,
        fitness=fitness,
        number_to_select=number_of_children + number_of_children % 2,
        tournament_size=3,
        rng=rng,
    )

    children: list[np.ndarray] = []
    for pair_start in range(0, len(parents), 2):
        first_child, second_child = _sbx_pair(
            parents[pair_start],
            parents[pair_start + 1],
            crossover_probability=0.9,
            distribution_index=15.0,
            rng=rng,
        )
        children.append(first_child)
        if len(children) < number_of_children:
            children.append(second_child)

    children_array = np.asarray(children[:number_of_children], dtype=float)
    return _polynomial_mutation(
        children_array,
        lower_bound,
        upper_bound,
        mutation_probability=1.0 / dimensions,
        distribution_index=20.0,
        rng=rng,
    )


def levy_flight(dimensions: int, rng: np.random.Generator) -> np.ndarray:
    """Sinh buoc Levy theo cong thuc Mantegna cua PO V2, beta = 1.5."""

    beta = 1.5
    sigma = (
        math.gamma(1.0 + beta)
        * math.sin(math.pi * beta / 2.0)
        / (
            math.gamma((1.0 + beta) / 2.0)
            * beta
            * 2.0 ** ((beta - 1.0) / 2.0)
        )
    ) ** (1.0 / beta)

    u = rng.standard_normal(dimensions) * sigma
    v = rng.standard_normal(dimensions)
    safe_denominator = np.maximum(
        np.abs(v) ** (1.0 / beta), np.finfo(float).eps
    )
    return u / safe_denominator


def _po_position(
    current: np.ndarray,
    current_index: int,
    strategy: int,
    best_position: np.ndarray,
    population_mean: np.ndarray,
    iteration: int,
    max_iterations: int,
    alpha: float,
    theta: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Ap dung dung mot trong bon hanh vi PO V2 cho mot ca the."""

    progress = iteration / max_iterations
    remaining_progress = 1.0 - progress
    dimensions = current.size

    if strategy == 1:
        # Hanh vi 1: kiem an.
        return (
            (current - best_position) * levy_flight(dimensions, rng)
            + rng.random()
            * remaining_progress ** (2.0 * progress)
            * population_mean
        )

    if strategy == 2:
        # Hanh vi 2: luu tru, theo cong thuc PO V2 da chot.
        return (
            current
            + best_position * levy_flight(dimensions, rng)
            + rng.standard_normal()
            * remaining_progress
            * np.ones(dimensions)
        )

    if strategy == 3:
        # Hanh vi 3: giao tiep, moi ca the boc mot trong hai nhanh.
        if rng.random() < 0.5:
            return current + alpha * remaining_progress * (
                current - population_mean
            )

        random_denominator = max(rng.random(), np.finfo(float).eps)
        exponential_term = math.exp(
            -(current_index + 1) / (random_denominator * max_iterations)
        )
        return current + alpha * remaining_progress * exponential_term

    # Hanh vi 4: so nguoi la.
    return (
        current
        + rng.random()
        * math.cos(math.pi * iteration / (2.0 * max_iterations))
        * (best_position - current)
        - math.cos(theta)
        * progress ** (2.0 / max_iterations)
        * (current - best_position)
    )


def _create_po_children(
    source_population: np.ndarray,
    source_indices: np.ndarray,
    best_position: np.ndarray,
    population_mean: np.ndarray,
    iteration: int,
    max_iterations: int,
    lower_bound: float,
    upper_bound: float,
    rng: np.random.Generator,
) -> np.ndarray:
    alpha = rng.random() / 5.0
    theta = rng.random() * math.pi
    children = np.empty_like(source_population)

    for local_index, current in enumerate(source_population):
        strategy = int(rng.integers(1, 5))
        original_index = int(source_indices[local_index])
        new_position = _po_position(
            current=current,
            current_index=original_index,
            strategy=strategy,
            best_position=best_position,
            population_mean=population_mean,
            iteration=iteration,
            max_iterations=max_iterations,
            alpha=alpha,
            theta=theta,
            rng=rng,
        )
        children[local_index] = np.clip(
            new_position, lower_bound, upper_bound
        )

    return children


def run_ga(
    objective: ObjectiveFunction,
    initial_population: np.ndarray,
    lower_bound: float,
    upper_bound: float,
    max_evaluations: int,
    seed: int,
) -> OptimizationResult:
    """Chay real-coded GA voi tournament, SBX va polynomial mutation."""

    population = np.asarray(initial_population, dtype=float).copy()
    population_size = len(population)
    max_iterations = _validate_budget(population_size, max_evaluations)
    rng = np.random.default_rng(seed)

    fitness = _evaluate(objective, population)
    best_position, best_value = _best_from_population(population, fitness)
    history_evaluations = [population_size]
    history_best_values = [best_value]

    for iteration in range(1, max_iterations + 1):
        children = _create_ga_children(
            population,
            fitness,
            population_size,
            lower_bound,
            upper_bound,
            rng,
        )
        child_fitness = _evaluate(objective, children)

        # Elitism: giu lai nghiem tot nhat neu the he con lam mat no.
        worst_child_index = int(np.argmax(child_fitness))
        if best_value < child_fitness[worst_child_index]:
            children[worst_child_index] = best_position.copy()
            child_fitness[worst_child_index] = best_value

        population = children
        fitness = child_fitness
        generation_position, generation_value = _best_from_population(
            population, fitness
        )
        if generation_value < best_value:
            best_position = generation_position
            best_value = generation_value

        history_evaluations.append(population_size * (iteration + 1))
        history_best_values.append(best_value)

    return OptimizationResult(
        "GA",
        best_position,
        best_value,
        history_evaluations,
        history_best_values,
        max_evaluations,
    )


def run_po(
    objective: ObjectiveFunction,
    initial_population: np.ndarray,
    lower_bound: float,
    upper_bound: float,
    max_evaluations: int,
    seed: int,
) -> OptimizationResult:
    """Chay PO V2 theo dung thu tu cap nhat trong ma MATLAB cua tac gia."""

    population = np.asarray(initial_population, dtype=float).copy()
    population_size = len(population)
    max_iterations = _validate_budget(population_size, max_evaluations)
    rng = np.random.default_rng(seed)

    fitness = _evaluate(objective, population)
    # PO.m sap xep quan the khoi tao theo fitness truoc khi bat dau tim kiem.
    initial_order = np.argsort(fitness)
    population = population[initial_order]
    fitness = fitness[initial_order]
    best_position = population[0].copy()
    best_value = float(fitness[0])
    history_evaluations = [population_size]
    history_best_values = [best_value]

    for iteration in range(1, max_iterations + 1):
        population_mean = np.mean(population, axis=0)
        alpha = rng.random() / 5.0
        theta = rng.random() * math.pi
        children = np.empty_like(population)
        child_fitness = np.empty(population_size, dtype=float)

        # PO.m danh gia va cap nhat GBest ngay trong vong lap j. Vi vay ca the
        # phia sau co the dung best moi vua tim thay trong cung mot iteration.
        for current_index, current in enumerate(population):
            strategy = int(rng.integers(1, 5))
            new_position = _po_position(
                current=current,
                current_index=current_index,
                strategy=strategy,
                best_position=best_position,
                population_mean=population_mean,
                iteration=iteration,
                max_iterations=max_iterations,
                alpha=alpha,
                theta=theta,
                rng=rng,
            )
            new_position = np.clip(new_position, lower_bound, upper_bound)
            new_fitness = float(
                _evaluate(objective, new_position.reshape(1, -1))[0]
            )
            children[current_index] = new_position
            child_fitness[current_index] = new_fitness

            if new_fitness < best_value:
                best_position = new_position.copy()
                best_value = new_fitness

        population = children
        fitness = child_fitness

        history_evaluations.append(population_size * (iteration + 1))
        history_best_values.append(best_value)

    return OptimizationResult(
        "PO V2",
        best_position,
        best_value,
        history_evaluations,
        history_best_values,
        max_evaluations,
    )


def run_hybrid(
    objective: ObjectiveFunction,
    initial_population: np.ndarray,
    lower_bound: float,
    upper_bound: float,
    max_evaluations: int,
    seed: int,
    ga_ratio: float = 0.5,
) -> OptimizationResult:
    """Chay pipeline lai: chia A/B, tao A'/B', hop cha va con, giu N tot nhat."""

    population = np.asarray(initial_population, dtype=float).copy()
    population_size = len(population)
    max_iterations = _validate_budget(population_size, max_evaluations)
    rng = np.random.default_rng(seed)

    number_of_ga_agents = int(round(population_size * ga_ratio))
    if number_of_ga_agents <= 0 or number_of_ga_agents >= population_size:
        raise ValueError("ga_ratio phai tao duoc ca nhom GA va nhom PO.")

    fitness = _evaluate(objective, population)
    best_position, best_value = _best_from_population(population, fitness)
    history_evaluations = [population_size]
    history_best_values = [best_value]

    for iteration in range(1, max_iterations + 1):
        population_mean = np.mean(population, axis=0)

        shuffled_indices = rng.permutation(population_size)
        ga_indices = shuffled_indices[:number_of_ga_agents]
        po_indices = shuffled_indices[number_of_ga_agents:]

        ga_population = population[ga_indices]
        ga_fitness = fitness[ga_indices]
        ga_children = _create_ga_children(
            ga_population,
            ga_fitness,
            len(ga_population),
            lower_bound,
            upper_bound,
            rng,
        )
        po_children = _create_po_children(
            source_population=population[po_indices],
            source_indices=po_indices,
            best_position=best_position,
            population_mean=population_mean,
            iteration=iteration,
            max_iterations=max_iterations,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            rng=rng,
        )

        children = np.vstack((ga_children, po_children))
        child_fitness = _evaluate(objective, children)

        # C = P(t) union A' union B', sau do giu N ca the tot nhat.
        candidate_population = np.vstack((population, children))
        candidate_fitness = np.concatenate((fitness, child_fitness))
        survivor_indices = np.argsort(candidate_fitness)[:population_size]
        population = candidate_population[survivor_indices]
        fitness = candidate_fitness[survivor_indices]

        # Xao tron de vi tri ca the khong bi dong khung o the he sau.
        next_order = rng.permutation(population_size)
        population = population[next_order]
        fitness = fitness[next_order]

        generation_position, generation_value = _best_from_population(
            population, fitness
        )
        if generation_value < best_value:
            best_position = generation_position
            best_value = generation_value

        history_evaluations.append(population_size * (iteration + 1))
        history_best_values.append(best_value)

    return OptimizationResult(
        "GA-PO",
        best_position,
        best_value,
        history_evaluations,
        history_best_values,
        max_evaluations,
    )


ALGORITHMS = {
    "GA": run_ga,
    "PO V2": run_po,
    "GA-PO": run_hybrid,
}
