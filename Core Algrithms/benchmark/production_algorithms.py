"""Numerical adapter for the production GA, PO and ISLAND80 mechanisms.

Search takes place in [0,1]^D, exactly as in the application. Only evaluation
maps u to x = lower + (upper-lower)*u and calls the CEC objective. There is no
timetable decoder or repair. A distinct numerical vector is the phenotype for
archive/migration. Production operators/selectors are imported, not retyped.
The small orchestration adapter is checked trajectory-for-trajectory against
the production loops with a numerical evaluation gateway in unit tests.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from random import Random
from typing import Callable

import numpy as np

from gapo_timetabling.core.ga import GAConfig, _create_offspring_vector, select_survivors
from gapo_timetabling.core.hybrid import (
    MIGRATION_INTERVAL, PO_ARCHIVE_SIZE, _migrate, _unique_best,
    _individual_order_key, validate_island_sizes,
)
from gapo_timetabling.core.po import (
    PoBehavior, calculate_population_mean, clip_vector_to_unit_interval, create_po_position,
)
from gapo_timetabling.core.population import CandidateEvaluationConfig, best_individual


@dataclass(frozen=True, slots=True)
class NumericalIndividual:
    vector: tuple[float, ...]
    value: float

    @property
    def fitness_key(self):
        return self.value, 0.0

    @property
    def selected_options(self):
        # No discrete timetable exists on CEC. Exact vector identity only;
        # neither rounding nor a tuned diversity-distance threshold is used.
        return self.vector


@dataclass
class NumericalResult:
    algorithm: str
    best_position: np.ndarray
    best_value: float
    history_evaluations: list[int]
    history_best_values: list[float]
    evaluations: int
    best_unit_position: tuple[float, ...]
    final_population: tuple[NumericalIndividual, ...]
    diagnostics: dict


def run_numerical(objective: Callable, initial_population: np.ndarray,
                  lower_bound: float, upper_bound: float, max_evaluations: int,
                  seed: int, *, algorithm: str) -> NumericalResult:
    initial = np.asarray(initial_population, dtype=float)
    if initial.ndim != 2 or not np.isfinite(initial).all() or initial.shape[1] < 1:
        raise ValueError('A finite (N,D) initial population is required.')
    n, dimension = initial.shape
    if n < 2 or not lower_bound < upper_bound:
        raise ValueError('Invalid population size or bounds.')
    if np.any(initial < lower_bound) or np.any(initial > upper_bound):
        raise ValueError('Initial population is outside the objective domain.')
    if max_evaluations < n or (max_evaluations-n) % n:
        raise ValueError('Budget must include initial N and full generations.')
    if algorithm not in ('GA', 'PO', 'ISLAND80'):
        raise ValueError('Unknown algorithm.')
    generations = (max_evaluations-n)//n
    width = upper_bound-lower_bound
    unit = (initial-lower_bound)/width
    rng = Random(seed)
    config = GAConfig(max_evaluations, 1, seed, CandidateEvaluationConfig(1, False))
    diag = dict(ga_offspring=0, po_offspring=0, po_worse_accepted=0,
                ga_best_gains=0, po_best_gains=0, ga_to_po=0, po_to_ga=0,
                migration_events=0, po_behaviors=[0,0,0,0])
    evaluations = 0

    def evaluate(vector):
        nonlocal evaluations
        v = np.asarray(vector, dtype=float)
        if not np.isfinite(v).all() or np.any(v < 0) or np.any(v > 1):
            raise ValueError('Operator generated a non-finite or unbounded vector.')
        values = np.asarray(objective((lower_bound+width*v).reshape(1,-1)), dtype=float)
        if values.shape != (1,) or not np.isfinite(values).all():
            raise ValueError('Objective must return one finite value.')
        evaluations += 1
        return NumericalIndividual(tuple(float(x) for x in v), float(values[0]))

    population = tuple(evaluate(v) for v in unit)
    best = best_individual(population)
    history_fe, history_best = [evaluations], [best.value]
    if algorithm == 'ISLAND80':
        n_ga = validate_island_sizes(n, .8)
        indices = list(range(n)); Random(seed ^ 0x1548020).shuffle(indices)
        ga = tuple(population[i] for i in indices[:n_ga])
        po = tuple(population[i] for i in indices[n_ga:])
        archive = _unique_best(po, PO_ARCHIVE_SIZE)
        po_best = best_individual(po)

    def accept(child, branch, *, lex=True):
        nonlocal best
        better = (_individual_order_key(child) < _individual_order_key(best)
                  if lex else child.fitness_key < best.fitness_key)
        if better:
            if child.value < best.value:
                diag[branch+'_best_gains'] += 1
            best = child

    def po_generation(pool, branch_best, generation):
        mean = calculate_population_mean(tuple(i.vector for i in pool))
        alpha, theta = rng.random()/5., rng.random()*math.pi
        children = []
        for index, parent in enumerate(pool):
            behavior = PoBehavior(rng.randint(1,4))
            vector = clip_vector_to_unit_interval(create_po_position(
                parent.vector, index, behavior, branch_best.vector, mean,
                generation, generations, alpha, theta, rng))
            child = evaluate(vector)
            diag['po_behaviors'][int(behavior)-1] += 1
            diag['po_offspring'] += 1
            diag['po_worse_accepted'] += int(child.value > parent.value)
            children.append(child)
            accept(child, 'po', lex=algorithm == 'ISLAND80')
            if algorithm == 'ISLAND80':
                nonlocal archive
                archive = _unique_best(archive+(child,), PO_ARCHIVE_SIZE)
                if _individual_order_key(child) < _individual_order_key(branch_best):
                    branch_best = child
            elif child.fitness_key < branch_best.fitness_key:
                branch_best = child
        return tuple(children), branch_best

    for generation in range(1,generations+1):
        if algorithm in ('GA','ISLAND80'):
            parents = population if algorithm == 'GA' else ga
            children = tuple(evaluate(_create_offspring_vector(parents, config, dimension, rng))
                             for _ in range(len(parents)))
            diag['ga_offspring'] += len(children)
            if algorithm == 'GA':
                population = select_survivors(parents, children, n)
                accept(best_individual(population), 'ga')
            else:
                for child in children: accept(child, 'ga')
                ga = select_survivors(parents, children, n_ga)
        if algorithm == 'PO':
            population, _ = po_generation(population, best, generation)
        elif algorithm == 'ISLAND80':
            po, po_best = po_generation(po, po_best, generation)
            if generation % MIGRATION_INTERVAL == 0 and generation < generations:
                old_ga, old_po = ga, po
                ga, from_po = _migrate(archive+old_po, old_ga)
                po, from_ga = _migrate(old_ga, old_po)
                diag['migration_events'] += 1
                diag['po_to_ga'] += int(from_po is not None)
                diag['ga_to_po'] += int(from_ga is not None)
                if from_ga is not None:
                    archive = _unique_best(archive+(from_ga,), PO_ARCHIVE_SIZE)
                    if _individual_order_key(from_ga) < _individual_order_key(po_best):
                        po_best = from_ga
            assert len(ga) == n_ga and len(po) == n-n_ga
            population = ga+po
        history_fe.append(evaluations); history_best.append(best.value)
    assert evaluations == max_evaluations
    return NumericalResult(algorithm, lower_bound+width*np.asarray(best.vector), best.value,
                           history_fe, history_best, evaluations, best.vector,
                           population, diag)


def run_ga(*args, **kwargs):
    return run_numerical(*args, **kwargs, algorithm='GA')


def run_po(*args, **kwargs):
    return run_numerical(*args, **kwargs, algorithm='PO')


def run_island80(*args, **kwargs):
    return run_numerical(*args, **kwargs, algorithm='ISLAND80')


ALGORITHMS = {'GA': run_ga, 'PO': run_po, 'ISLAND80': run_island80}
