"""Single-factor research adapters; never imported by the web/production engine.

Each adapter runs in its own process. FULL is only a parity-test path; the
benchmark CLI never schedules FULL, GA, PO, or Greedy again.
"""
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import patch

from gapo_timetabling.core import target_hybrid as engine

VARIANTS = ("TARGET_RAND80", "NO_FEEDBACK", "RANDOM_GROUP")
ProductionTargeter = engine.Targeter


class MatchedRandomTargeter(ProductionTargeter):
    """Randomize group identity, retaining the selected type and gene count.

The dominant-penalty rule still determines group type/size. This ablation
does not remove all information about the objective.
"""

    def choose(self, item, rng):
        state = rng.getstate()
        original, _, reason = super().choose(item, rng)
        rng.setstate(state)
        p = self.p
        assignments = [j for j in original if j < p.schedule_gene_offset]
        if assignments:
            selected = []
            for index in assignments:
                original_key = p.assignment_keys[index]
                footprint = self.section.count(original_key)
                available = [key for key in self.assignment if key not in selected
                    and self.section.count(key) == footprint
                    and (reason != "workload" or len(p.eligible_assignment_lecturers(key)) > 1)]
                if not available:
                    raise RuntimeError("No matched assignment group for RANDOM_GROUP.")
                selected.append(rng.choices(available)[0])
            groups = [g for g, key in enumerate(self.section) if key in selected]
            mask = {self.assignment[key] for key in selected}
        else:
            count = sum(p.schedule_gene_offset <= j < p.placement_gene_offset for j in original)
            available = list(range(len(self.groups)))
            groups = []
            for _ in range(count):
                group = rng.choices(available)[0]
                groups.append(group)
                available.remove(group)
            mask = set()
        mask.update(p.schedule_gene_offset + g for g in groups)
        mask.update(p.placement_gene_offset + g for g in groups)
        assert len(mask) == len(original)
        assert sum(j < p.schedule_gene_offset for j in mask) == len(assignments)
        return tuple(sorted(mask)), frozenset(s for g in groups for s in self.groups[g]), reason


def uniform_proposal(anchor, pool, guide, mask, index, behavior, generation,
                     alpha, theta, rng, *, max_iterations):
    vector = list(anchor.vector)
    for index in mask:
        vector[index] = rng.random()
    return tuple(vector)


def run_variant(problem, domains, initialization, config, *, variant,
                progress_callback=None):
    if variant not in (*VARIANTS, "FULL"):
        raise ValueError(f"Unknown research variant: {variant}")
    survivor_calls = 0
    original_survivors = engine.ga.select_survivors

    def no_feedback_survivors(parents, children, size):
        nonlocal survivor_calls
        survivor_calls += 1
        # Production calls survivor selection twice per generation: GA first,
        # then PO proposals. Only the latter loses its incoming proposals.
        if survivor_calls % 2 == 0:
            children = ()
        return original_survivors(parents, children, size)

    with ExitStack() as stack:
        if variant == "TARGET_RAND80":
            stack.enter_context(patch.object(engine, "propose", uniform_proposal))
        elif variant == "NO_FEEDBACK":
            stack.enter_context(patch.object(engine.ga, "select_survivors", no_feedback_survivors))
        elif variant == "RANDOM_GROUP":
            stack.enter_context(patch.object(engine, "Targeter", MatchedRandomTargeter))
        result = engine.run_target_hybrid(problem, domains, initialization, config,
                                         progress_callback=progress_callback)
    if variant == "FULL":
        return result
    activity = dict(result.hybrid_activity)
    counts = dict(activity["counts"])
    if variant == "TARGET_RAND80":
        counts["random_calls"] = counts.pop("formula_calls", 0)
    if variant == "NO_FEEDBACK":
        assert survivor_calls == 2 * result.metrics.completed_iterations
        counts["injected"] = 0
    events = [dict(event, injected=(event["accepted"] and variant != "NO_FEEDBACK"))
              for event in activity["events"]]
    activity.update(counts=counts, events=events, research_variant=variant,
                    feedback=(variant != "NO_FEEDBACK"),
                    random_control=(variant == "TARGET_RAND80"),
                    random_group=(variant == "RANDOM_GROUP"))
    return replace(result, hybrid_activity=activity)
