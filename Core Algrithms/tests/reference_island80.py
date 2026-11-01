"""Isolated full-chromosome GA/PO islands. No decoder or operator changes."""
from dataclasses import replace
import math
from random import Random
from time import perf_counter

from gapo_timetabling.core import ga, po
from gapo_timetabling.core.hybrid import _initial_metrics, _create_convergence_point
from gapo_timetabling.core.metrics import OptimizationResult, accumulate_candidate_evaluation
from gapo_timetabling.core.models import OptimizationAlgorithm
from gapo_timetabling.core.population import evaluate_candidate, best_individual


def phenotype(item):
    return item.selected_options


def order(item):
    return item.fitness_key, item.vector


def unique_best(items, limit):
    result = []
    seen = set()
    for item in sorted(items, key=order):
        if phenotype(item) not in seen:
            result.append(item)
            seen.add(phenotype(item))
            if len(result) == limit:
                break
    return tuple(result)


def migrate(source, destination):
    """One best novel schedule replaces worst non-elite; no fitness evaluation."""
    existing = {phenotype(i) for i in destination}
    migrant = next((i for i in sorted(source, key=order) if phenotype(i) not in existing), None)
    if migrant is None:
        return destination, None
    protected = min(range(len(destination)), key=lambda i: order(destination[i]))
    worst = max((i for i in range(len(destination)) if i != protected),
                key=lambda i: order(destination[i]))
    updated = list(destination)
    updated[worst] = migrant
    return tuple(updated), migrant


def run_islands(problem, domains, initial, config, *, random_control=False, progress_callback=None):
    started = perf_counter()
    ga_config, po_config = config.create_ga_config(), config.create_po_config()
    generations = ga._validate_ga_run_inputs(problem, domains, initial, ga_config)
    population_size = len(initial.individuals)
    n_ga = round(.8 * population_size)
    if min(n_ga, population_size-n_ga) < 2:
        raise ValueError('Each island needs at least two individuals.')
    indices = list(range(population_size))
    Random(config.seed ^ 0x1548020).shuffle(indices)
    ga_pool = tuple(initial.individuals[i] for i in indices[:n_ga])
    po_pool = tuple(initial.individuals[i] for i in indices[n_ga:])
    po_archive = unique_best(po_pool, 6)
    po_best = best_individual(po_pool)
    best = best_individual(initial.individuals)
    metrics = _initial_metrics(initial)
    history = [_create_convergence_point(0, metrics, best)]
    rng = Random(config.seed)
    counts = dict(ga_slots=0, po_slots=0, ga_success=0, po_success=0,
                  ga_global_improvements=0, po_global_improvements=0,
                  ga_meaningful_improvements=0, po_meaningful_improvements=0,
                  po_valid_worse_accepted=0, ga_to_po=0, po_to_ga=0,
                  po_discovered_to_ga=0, ga_parent_po_discovered=0,
                  ga_novel_vectors=0, po_novel_vectors=0,
                  ga_novel_phenotypes=0, po_novel_phenotypes=0,
                  po_formula_calls=0)
    behaviors = {behavior.name: 0 for behavior in po.PoBehavior}
    seen_vectors = {i.vector for i in initial.individuals}
    seen_phenotypes = {phenotype(i) for i in initial.individuals}
    po_discovered = set()
    events = []

    def accept(item, branch):
        nonlocal best
        if item.vector not in seen_vectors:
            counts[branch+'_novel_vectors'] += 1
            if branch == 'po':
                po_discovered.add(item.vector)
        if phenotype(item) not in seen_phenotypes:
            counts[branch+'_novel_phenotypes'] += 1
        seen_vectors.add(item.vector)
        seen_phenotypes.add(phenotype(item))
        if order(item) < order(best):
            counts[branch+'_global_improvements'] += 1
            a, b = item.fitness_key, best.fitness_key
            if a[0] < b[0]-1e-12 or (abs(a[0]-b[0]) <= 1e-12 and a[1] < b[1]-1e-12):
                counts[branch+'_meaningful_improvements'] += 1
            best = item

    # This wrapper only records actual tournament selections, consuming no RNG.
    original_tournament = ga.tournament_select
    def observed_tournament(*args, **kwargs):
        parent = original_tournament(*args, **kwargs)
        counts['ga_parent_po_discovered'] += int(parent.vector in po_discovered)
        return parent

    ga.tournament_select = observed_tournament
    try:
        for generation in range(1, generations+1):
            children = []
            for _ in range(n_ga):
                counts['ga_slots'] += 1
                for _attempt in range(config.max_offspring_attempts):
                    vector = ga._create_offspring_vector(ga_pool, ga_config, problem.dimension, rng)
                    value = evaluate_candidate(problem, domains, vector, config.evaluation_config)
                    metrics = accumulate_candidate_evaluation(metrics, value)
                    if value.is_success:
                        children.append(value.individual)
                        counts['ga_success'] += 1
                        accept(value.individual, 'ga')
                        break
                else:
                    metrics = replace(metrics, discarded_offspring_count=metrics.discarded_offspring_count+1)
            ga_pool = ga.select_survivors(ga_pool, tuple(children), n_ga)
            mean = po.calculate_population_mean(tuple(i.vector for i in po_pool))
            alpha, theta = rng.random()/5., rng.random()*math.pi
            next_po = list(po_pool)
            for index, parent in enumerate(po_pool):
                counts['po_slots'] += 1
                behavior = po.PoBehavior(rng.randint(1, 4))
                behaviors[behavior.name] += 1
                if not random_control:
                    outcome = po._create_and_evaluate_po_offspring(
                        problem, domains, parent, index, behavior, po_best, mean,
                        generation, generations, alpha, theta, rng, po_config, metrics)
                    metrics = outcome.metrics
                    counts['po_formula_calls'] += outcome.attempts_used
                    child = outcome.individual
                else:
                    child = None
                    for _attempt in range(config.max_offspring_attempts):
                        vector = tuple(rng.random() for _ in range(problem.dimension))
                        value = evaluate_candidate(problem, domains, vector, config.evaluation_config)
                        metrics = accumulate_candidate_evaluation(metrics, value)
                        if value.is_success:
                            child = value.individual
                            break
                    if child is None:
                        metrics = replace(metrics, discarded_offspring_count=metrics.discarded_offspring_count+1)
                if child is not None:
                    next_po[index] = child
                    counts['po_success'] += 1
                    counts['po_valid_worse_accepted'] += int(child.fitness_key > parent.fitness_key)
                    accept(child, 'po')
                    po_archive = unique_best(po_archive+(child,), 6)
                    if order(child) < order(po_best):
                        po_best = child
            po_pool = tuple(next_po)
            if generation % 2 == 0 and generation < generations:
                # Both directions use pre-migration sources, not a ping-pong copy.
                old_ga, old_po = ga_pool, po_pool
                ga_pool, from_po = migrate(po_archive+old_po, old_ga)
                po_pool, from_ga = migrate(old_ga, old_po)
                counts['po_to_ga'] += int(from_po is not None)
                counts['ga_to_po'] += int(from_ga is not None)
                counts['po_discovered_to_ga'] += int(from_po is not None and from_po.vector in po_discovered)
                if from_ga is not None:
                    po_archive = unique_best(po_archive+(from_ga,), 6)
                    if order(from_ga) < order(po_best):
                        po_best = from_ga
                events.append(dict(generation=generation, ga_to_po=from_ga is not None,
                    po_to_ga=from_po is not None,
                    po_discovered_to_ga=from_po is not None and from_po.vector in po_discovered))
            assert len(ga_pool) == n_ga and len(po_pool) == population_size-n_ga
            assert metrics.fitness_evaluations <= config.max_fitness_evaluations
            metrics = replace(metrics, completed_iterations=generation)
            history.append(_create_convergence_point(generation, metrics, best))
            if progress_callback:
                progress_callback(generation, metrics, best)
    finally:
        ga.tournament_select = original_tournament
    metrics = replace(metrics, runtime_seconds=perf_counter()-started)
    return OptimizationResult(algorithm=OptimizationAlgorithm.GA_PO, best_individual=best,
                              final_population=ga_pool+po_pool, metrics=metrics,
                              convergence_history=tuple(history)), dict(counts=counts, behaviors=behaviors,
                                migrations=events, random_control=random_control,
                                ga_size=n_ga, po_size=population_size-n_ga)
