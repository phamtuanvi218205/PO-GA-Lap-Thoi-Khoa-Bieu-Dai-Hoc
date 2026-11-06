"""TARGET_PO80: GA survivors with objective-directed, masked PO proposals.

The N30/T20 path preserves the frozen 05/11/2026 research RNG and operator
order. Other sizes use the configured budget; they are not D155 measurements.
Decoder, Repair, Validator, Fitness and the original PO formulas are shared.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
import math
from random import Random
from time import perf_counter
from typing import TYPE_CHECKING

from . import fitness, ga, po
from .metrics import (
    OptimizationProgress, OptimizationProgressCallback, OptimizationResult,
    accumulate_candidate_evaluation,
)
from .models import AvailabilityType, OptimizationAlgorithm, ProblemInstance
from .population import best_individual, evaluate_candidate

if TYPE_CHECKING:
    from .hybrid import HybridConfig


class Targeter:
    """Choose at most two blocks/assignment units from the anchor's breakdown.

    Block signals are heuristics for choosing coordinates, not another Fitness
    evaluation or a decomposition of the normalized objective by block.
    """

    def __init__(self, problem: ProblemInstance):
        self.p = problem
        self.groups = problem.schedule_groups
        self.sg = {s: g for g, sessions in enumerate(self.groups) for s in sessions}
        plans = {plan.teaching_plan_id: plan for plan in problem.teaching_plans}
        self.section = [
            problem.assignment_key_for_part(problem.teaching_parts[
                plans[problem.class_sessions[sessions[0]].teaching_plan_id].teaching_part_index
            ])
            for sessions in self.groups
        ]
        self.assignment = {s: i for i, s in enumerate(problem.assignment_keys)}

    def choose(self, item, rng: Random):
        p = self.p
        b = item.fitness.breakdown
        components = {
            'gap': b.gap_component * fitness._get_soft_weight(p, 'SOFT_LECTURER_GAP'),
            'consecutive': b.lecturer_consecutive_component * fitness._get_soft_weight(p, 'SOFT_LECTURER_CONSECUTIVE'),
            'room': b.room_discouraged_component * fitness._get_soft_weight(p, 'SOFT_ROOM_DISCOURAGED'),
            'workload': b.workload_balance_component * fitness._get_soft_weight(p, 'SOFT_WORKLOAD_BALANCE'),
        }
        reason = max(components, key=components.get)
        if components[reason] <= 1e-15:
            reason = 'suitability' if b.course_suitability_component > 0 else 'preference'
        signal = Counter()
        assignment = False
        options = item.selected_options
        if reason == 'workload':
            loads = Counter()
            for option in options:
                loads[p.option_lecturer_index(option)] += option.end_period - option.start_period + 1
            eligible = {j for s in p.assignment_keys for j in p.eligible_assignment_lecturers(s)}
            # Fixed-assignment v1 snapshots have no assignment genes. Their
            # workload cannot be redistributed; retain the random-block fallback.
            mean = sum(loads.values()) / len(eligible) if eligible else 0.0
            sections = Counter()
            for option in options:
                excess = max(0, loads[p.option_lecturer_index(option)] - mean)
                sections[self.section[self.sg[option.session_index]]] += excess * (option.end_period - option.start_period + 1)
            available = [s for s in sections if sections[s] > 0 and s in self.assignment and len(p.eligible_assignment_lecturers(s)) > 1]
            selected = []
            while available and len(selected) < 2:
                section = rng.choices(available, weights=[sections[s] for s in available])[0]
                selected.append(section)
                available.remove(section)
            groups = [g for g, s in enumerate(self.section) if s in selected]
            assignment = True
        else:
            if reason in ('gap', 'consecutive'):
                days = defaultdict(list)
                for option in options:
                    days[p.option_lecturer_index(option), option.teaching_date].append(option)
                threshold = fitness._get_max_consecutive_periods(p)
                for day in days.values():
                    ordered = sorted(day, key=lambda o: o.start_period)
                    if reason == 'gap':
                        for left, right in zip(ordered, ordered[1:]):
                            gap = max(0, right.start_period - left.end_period - 1)
                            signal[self.sg[left.session_index]] += gap
                            signal[self.sg[right.session_index]] += gap
                    else:
                        streak = []

                        def score_streak():
                            excess = max(0, sum(o.end_period - o.start_period + 1 for o in streak) - threshold)
                            for option in streak:
                                signal[self.sg[option.session_index]] += excess

                        for option in ordered:
                            if streak and option.start_period != streak[-1].end_period + 1:
                                score_streak()
                                streak = []
                            streak.append(option)
                        score_streak()
            elif reason == 'room':
                for option in options:
                    periods = set()
                    for window in p.room_availabilities:
                        if (window.resource_index == option.location_index
                                and window.availability_type == AvailabilityType.DISCOURAGED
                                and fitness._window_applies_to_date(window, option.teaching_date)):
                            periods.update(range(max(window.start_period, option.start_period), min(window.end_period, option.end_period) + 1))
                    signal[self.sg[option.session_index]] += len(periods)
            else:
                penalties = {r.lecturer_index: r.missed_preferred_penalty + r.discouraged_overlap_penalty for r in b.lecturer_breakdown}
                for option in options:
                    signal[self.sg[option.session_index]] += penalties.get(p.option_lecturer_index(option), 0)
                assignment = reason == 'suitability'
            available = [g for g, value in signal.items() if value > 0]
            groups = []
            while available and len(groups) < 2:
                group = rng.choices(available, weights=[signal[g] for g in available])[0]
                groups.append(group)
                available.remove(group)
        if not groups:
            groups = [rng.randrange(len(self.groups))]
        sections = {self.section[g] for g in groups}
        if assignment:
            groups = [g for g, section in enumerate(self.section) if section in sections]
        mask = {p.schedule_gene_offset + g for g in groups} | {p.placement_gene_offset + g for g in groups}
        if assignment:
            mask.update(self.assignment[s] for s in sections if s in self.assignment)
        return tuple(sorted(mask)), frozenset(s for g in groups for s in self.groups[g]), reason


def propose(anchor, pool, guide, mask, index, behavior, generation, alpha, theta, rng, *, max_iterations):
    """Apply an original PO formula only to the selected coordinates."""
    values = po.create_po_position(
        tuple(anchor.vector[j] for j in mask), index, behavior,
        tuple(guide.vector[j] for j in mask),
        tuple(sum(item.vector[j] for item in pool) / len(pool) for j in mask),
        generation, max_iterations, alpha, theta, rng,
    )
    values = po.clip_vector_to_unit_interval(values)
    vector = list(anchor.vector)
    for j, value in zip(mask, values, strict=True):
        vector[j] = value
    return tuple(vector)


def _create_and_evaluate_target_offspring(
    problem, domains, anchor, pool, guide, mask, index, behavior, generation,
    alpha, theta, rng, config, max_iterations, metrics,
):
    """One target slot, with bounded retries and the shared evaluation pipeline.

    Kept as an explicit boundary so the web coordinator can prefetch exactly
    these retry vectors using a cloned RNG, without changing the search.
    """
    for _ in range(config.max_offspring_attempts):
        vector = propose(anchor, pool, guide, mask, index, behavior, generation,
                         alpha, theta, rng, max_iterations=max_iterations)
        value = evaluate_candidate(problem, domains, vector, config.evaluation_config)
        metrics = accumulate_candidate_evaluation(metrics, value)
        if value.is_success:
            if value.individual is None:
                raise RuntimeError('A successful evaluation must return an individual.')
            return value.individual, vector, metrics
    return None, None, replace(metrics, discarded_offspring_count=metrics.discarded_offspring_count + 1)


def run_target_hybrid(problem, domains, initialization, config: HybridConfig, *, progress_callback: OptimizationProgressCallback | None = None):
    """Run the full method; no research ablation or random-control switches."""
    from .hybrid import _initial_metrics, _create_convergence_point, validate_target_sizes

    started = perf_counter()
    ga_config = config.create_ga_config()
    max_iterations = ga._validate_ga_run_inputs(problem, domains, initialization, ga_config)
    size = len(initialization.individuals)
    n_ga = validate_target_sizes(size, config.ga_ratio)
    n_po = size - n_ga
    indices = list(range(size))
    Random(config.seed ^ 0x1548020).shuffle(indices)
    ga_pool = tuple(initialization.individuals[i] for i in indices[:n_ga])
    po_pool = tuple(initialization.individuals[i] for i in indices[n_ga:])
    best = best_individual(initialization.individuals)
    metrics = _initial_metrics(initialization)
    history = [_create_convergence_point(0, metrics, best)]
    rng = Random(config.seed)
    position_rng = Random(config.seed ^ 0x6110501)
    targeter = Targeter(problem)
    counts = Counter()
    events = []
    seen = {item.selected_options for item in initialization.individuals}

    def observe(item, branch):
        nonlocal best
        counts[branch + '_success'] += 1
        counts[branch + '_novel_phenotype'] += int(item.selected_options not in seen)
        counts[branch + '_duplicate_phenotype'] += int(item.selected_options in seen)
        seen.add(item.selected_options)
        if item.fitness_key < best.fitness_key:
            counts[branch + '_best_gain'] += 1
            best = item

    def report(iteration):
        if progress_callback is not None:
            progress_callback(OptimizationProgress(
                algorithm=OptimizationAlgorithm.GA_PO, iteration=iteration,
                max_iterations=max_iterations, max_fitness_evaluations=config.max_fitness_evaluations,
                metrics=metrics, best_general_quality_score=best.fitness.general_quality_score,
                best_lecturer_preference_score=best.fitness.lecturer_preference_score,
            ))

    report(0)
    for generation in range(1, max_iterations + 1):
        children = []
        for _ in range(n_ga):
            counts['ga_slots'] += 1
            for _ in range(config.max_offspring_attempts):
                vector = ga._create_offspring_vector(ga_pool, ga_config, problem.dimension, rng)
                value = evaluate_candidate(problem, domains, vector, config.evaluation_config)
                metrics = accumulate_candidate_evaluation(metrics, value)
                if value.is_success:
                    if value.individual is None:
                        raise RuntimeError('A successful evaluation must return an individual.')
                    children.append(value.individual)
                    observe(value.individual, 'ga')
                    break
            else:
                metrics = replace(metrics, discarded_offspring_count=metrics.discarded_offspring_count + 1)
            report(generation - 1)
        ga_pool = ga.select_survivors(ga_pool, tuple(children), n_ga)
        anchors = tuple(sorted(ga_pool, key=lambda item: (item.fitness_key, item.vector))[:n_po])
        old_po = po_pool
        next_po = list(po_pool)
        improvements = []
        alpha = position_rng.random() / 5
        theta = position_rng.random() * math.pi
        for slot, anchor in enumerate(anchors):
            counts['target_slots'] += 1
            mask, sessions, reason = targeter.choose(anchor, rng)
            behavior = po.PoBehavior(rng.randint(1, 4))
            label = behavior.name
            counts['reason_' + reason] += 1
            counts['behavior_' + label] += 1
            guide = best_individual(ga_pool + old_po)
            attempts_before = metrics.candidate_attempts
            child, vector, metrics = _create_and_evaluate_target_offspring(
                problem, domains, anchor, old_po, guide, mask, slot, behavior,
                generation, alpha, theta, position_rng, config, max_iterations, metrics,
            )
            counts['formula_calls'] += metrics.candidate_attempts - attempts_before
            if child is not None:
                observe(child, 'target')
                next_po[slot] = child
                accepted = child.fitness_key < anchor.fitness_key
                counts['valid_' + label] += 1
                counts['accepted_' + label] += int(accepted)
                counts['worse_than_anchor'] += int(child.fitness_key > anchor.fitness_key)
                drift = sum(value != child.vector[j] for j, value in enumerate(vector) if j not in mask)
                by_session = {option.session_index: option for option in anchor.selected_options}
                outside = sum(option != by_session[option.session_index] for option in child.selected_options if option.session_index not in sessions)
                counts['outside_sessions_changed'] += outside
                counts['repair_outside_gene_changes'] += drift
                if accepted:
                    improvements.append(child)
                    counts['injected'] += 1
                events.append(dict(gen=generation, slot=slot, reason=reason, behavior=label, mask=mask,
                                   anchor=anchor.fitness_key, child=child.fitness_key, accepted=accepted,
                                   changed_outside_sessions=outside, repair_outside_gene_changes=drift))
            report(generation - 1)
        po_pool = tuple(next_po)
        ga_pool = ga.select_survivors(ga_pool, tuple(improvements), n_ga)
        if len(ga_pool) + len(po_pool) != size:
            raise RuntimeError('TARGET_PO80 must preserve population size.')
        if metrics.fitness_evaluations > config.max_fitness_evaluations:
            raise RuntimeError('TARGET_PO80 exceeded the shared FE cap.')
        metrics = replace(metrics, completed_iterations=generation)
        history.append(_create_convergence_point(generation, metrics, best))
        report(generation)
    return OptimizationResult(
        algorithm=OptimizationAlgorithm.GA_PO, best_individual=best,
        final_population=ga_pool + po_pool, convergence_history=tuple(history),
        metrics=replace(metrics, runtime_seconds=perf_counter() - started),
        hybrid_activity=dict(counts=dict(counts), events=events, random_control=False),
    )
