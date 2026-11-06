"""Objective-directed masked PO; isolated research, unchanged production decoder."""
from collections import Counter, defaultdict
from dataclasses import replace
from random import Random
from time import perf_counter
import math
from gapo_timetabling.core import ga, po, fitness
from gapo_timetabling.core.hybrid import _initial_metrics, _create_convergence_point
from gapo_timetabling.core.metrics import OptimizationResult, accumulate_candidate_evaluation
from gapo_timetabling.core.models import OptimizationAlgorithm, AvailabilityType
from gapo_timetabling.core.population import evaluate_candidate, best_individual


def better(a,b):
    return a.fitness_key < b.fitness_key


class Targeter:
    def __init__(self, problem):
        self.p=problem
        self.groups=problem.schedule_groups
        self.sg={s:g for g,ss in enumerate(self.groups) for s in ss}
        parts={p.teaching_plan_id:p for p in problem.teaching_plans}
        self.section=[problem.teaching_parts[parts[problem.class_sessions[ss[0]].teaching_plan_id].teaching_part_index].section_code for ss in self.groups]
        self.assignment={s:i for i,s in enumerate(problem.assignment_section_codes)}

    def choose(self, item, rng):
        p=self.p; b=item.fitness.breakdown
        components={'gap':b.gap_component*fitness._get_soft_weight(p,'SOFT_LECTURER_GAP'),
            'consecutive':b.lecturer_consecutive_component*fitness._get_soft_weight(p,'SOFT_LECTURER_CONSECUTIVE'),
            'room':b.room_discouraged_component*fitness._get_soft_weight(p,'SOFT_ROOM_DISCOURAGED'),
            'workload':b.workload_balance_component*fitness._get_soft_weight(p,'SOFT_WORKLOAD_BALANCE')}
        reason=max(components,key=components.get)
        if components[reason]<=1e-15:
            reason='suitability' if b.course_suitability_component>0 else 'preference'
        signal=Counter(); assignment=False
        options=item.selected_options
        if reason=='workload':
            loads=Counter()
            for o in options: loads[p.option_lecturer_index(o)]+=o.end_period-o.start_period+1
            eligible={l for s in p.assignment_section_codes for l in p.eligible_lecturer_indices(s)}
            mean=sum(loads.values())/len(eligible)
            sections=Counter()
            for o in options:
                excess=max(0,loads[p.option_lecturer_index(o)]-mean)
                sections[self.section[self.sg[o.session_index]]]+=excess*(o.end_period-o.start_period+1)
            available=[s for s in sections if sections[s]>0 and len(p.eligible_lecturer_indices(s))>1]
            selected=[]
            while available and len(selected)<2:
                s=rng.choices(available,weights=[sections[s] for s in available])[0]
                selected.append(s); available.remove(s)
            gs=[g for g,s in enumerate(self.section) if s in selected]
            assignment=True
        else:
            if reason in ('gap','consecutive'):
                days=defaultdict(list)
                for o in options: days[p.option_lecturer_index(o),o.teaching_date].append(o)
                threshold=fitness._get_max_consecutive_periods(p)
                for day in days.values():
                    ordered=sorted(day,key=lambda o:o.start_period)
                    if reason=='gap':
                        for a,c in zip(ordered,ordered[1:]):
                            gap=max(0,c.start_period-a.end_period-1)
                            signal[self.sg[a.session_index]]+=gap
                            signal[self.sg[c.session_index]]+=gap
                    else:
                        streak=[]
                        def score_streak():
                            excess=max(0,sum(o.end_period-o.start_period+1 for o in streak)-threshold)
                            for o in streak: signal[self.sg[o.session_index]]+=excess
                        for o in ordered:
                            if streak and o.start_period!=streak[-1].end_period+1:
                                score_streak(); streak=[]
                            streak.append(o)
                        score_streak()
            elif reason=='room':
                for o in options:
                    periods=set()
                    for w in p.room_availabilities:
                        if w.resource_index==o.location_index and w.availability_type==AvailabilityType.DISCOURAGED and fitness._window_applies_to_date(w,o.teaching_date):
                            periods.update(range(max(w.start_period,o.start_period),min(w.end_period,o.end_period)+1))
                    signal[self.sg[o.session_index]]+=len(periods)
            else:
                penalties={r.lecturer_index:r.missed_preferred_penalty+r.discouraged_overlap_penalty for r in b.lecturer_breakdown}
                for o in options:
                    signal[self.sg[o.session_index]]+=penalties.get(p.option_lecturer_index(o),0)
                assignment=reason=='suitability'
            available=[g for g,v in signal.items() if v>0]
            gs=[]
            while available and len(gs)<2:
                g=rng.choices(available,weights=[signal[g] for g in available])[0]
                gs.append(g); available.remove(g)
        if not gs: gs=[rng.randrange(len(self.groups))]
        sections={self.section[g] for g in gs}
        if assignment:
            gs=[g for g,s in enumerate(self.section) if s in sections]
        mask={p.schedule_gene_offset+g for g in gs}|{p.placement_gene_offset+g for g in gs}
        if assignment: mask.update(self.assignment[s] for s in sections if s in self.assignment)
        return tuple(sorted(mask)), frozenset(s for g in gs for s in self.groups[g]), reason


def propose(anchor, pool, guide, mask, index, behavior, generation, alpha, theta, rng, random_control):
    if random_control:
        values=tuple(rng.random() for _ in mask)
    else:
        values=po.create_po_position(tuple(anchor.vector[j] for j in mask),index,behavior,
            tuple(guide.vector[j] for j in mask),
            tuple(sum(i.vector[j] for i in pool)/len(pool) for j in mask),generation,20,alpha,theta,rng)
        values=po.clip_vector_to_unit_interval(values)
    vector=list(anchor.vector)
    for j,v in zip(mask,values,strict=True): vector[j]=v
    assert all(v==anchor.vector[j] for j,v in enumerate(vector) if j not in mask)
    return tuple(vector)


def run_target(problem,domains,initial,config,*,random_control=False,progress_callback=None):
    start=perf_counter(); cfg=config.create_ga_config()
    assert ga._validate_ga_run_inputs(problem,domains,initial,cfg)==20
    indices=list(range(30)); Random(config.seed ^ 0x1548020).shuffle(indices)
    gp=tuple(initial.individuals[i] for i in indices[:24])
    pp=tuple(initial.individuals[i] for i in indices[24:])
    best=best_individual(initial.individuals); metrics=_initial_metrics(initial)
    history=[_create_convergence_point(0,metrics,best)]
    rng=Random(config.seed); position_rng=Random(config.seed ^ 0x6110501)
    targeter=Targeter(problem); counts=Counter(); events=[]
    seen={i.selected_options for i in initial.individuals}
    def observe(item,branch):
        nonlocal best
        counts[branch+'_success']+=1
        counts[branch+'_novel_phenotype']+=int(item.selected_options not in seen)
        counts[branch+'_duplicate_phenotype']+=int(item.selected_options in seen)
        seen.add(item.selected_options)
        if better(item,best): counts[branch+'_best_gain']+=1; best=item
    for gen in range(1,21):
        children=[]
        for slot in range(24):
            counts['ga_slots']+=1
            for attempt in range(5):
                vector=ga._create_offspring_vector(gp,cfg,problem.dimension,rng)
                value=evaluate_candidate(problem,domains,vector,config.evaluation_config)
                metrics=accumulate_candidate_evaluation(metrics,value)
                if value.is_success:
                    children.append(value.individual); observe(value.individual,'ga'); break
            else: metrics=replace(metrics,discarded_offspring_count=metrics.discarded_offspring_count+1)
        gp=ga.select_survivors(gp,tuple(children),24)
        anchors=tuple(sorted(gp,key=lambda i:(i.fitness_key,i.vector))[:6])
        old_pp=pp; new_pp=list(pp); improvements=[]
        alpha=position_rng.random()/5; theta=position_rng.random()*math.pi
        for slot,anchor in enumerate(anchors):
            counts['target_slots']+=1
            mask,sessions,reason=targeter.choose(anchor,rng)
            behavior=po.PoBehavior(rng.randint(1,4)); label=behavior.name
            counts['reason_'+reason]+=1; counts['behavior_'+label]+=1
            guide=best_individual(gp+old_pp)
            child=None
            for attempt in range(5):
                vector=propose(anchor,old_pp,guide,mask,slot,behavior,gen,alpha,theta,position_rng,random_control)
                counts['random_calls' if random_control else 'formula_calls']+=1
                value=evaluate_candidate(problem,domains,vector,config.evaluation_config)
                metrics=accumulate_candidate_evaluation(metrics,value)
                if value.is_success:
                    child=value.individual; break
            if child is None:
                metrics=replace(metrics,discarded_offspring_count=metrics.discarded_offspring_count+1); continue
            observe(child,'target'); new_pp[slot]=child
            accepted=better(child,anchor)
            counts['valid_'+label]+=1; counts['accepted_'+label]+=int(accepted)
            counts['worse_than_anchor']+=int(child.fitness_key>anchor.fitness_key)
            drift=sum(v!=child.vector[j] for j,v in enumerate(vector) if j not in mask)
            by_session={o.session_index:o for o in anchor.selected_options}
            outside=sum(o!=by_session[o.session_index] for o in child.selected_options if o.session_index not in sessions)
            counts['outside_sessions_changed']+=outside; counts['repair_outside_gene_changes']+=drift
            if accepted: improvements.append(child); counts['injected']+=1
            events.append(dict(gen=gen,slot=slot,reason=reason,behavior=label,mask=mask,
                anchor=anchor.fitness_key,child=child.fitness_key,accepted=accepted,
                changed_outside_sessions=outside,repair_outside_gene_changes=drift))
        pp=tuple(new_pp); gp=ga.select_survivors(gp,tuple(improvements),24)
        assert metrics.fitness_evaluations<=630
        metrics=replace(metrics,completed_iterations=gen)
        history.append(_create_convergence_point(gen,metrics,best))
        if progress_callback: progress_callback(gen,metrics,best)
    metrics=replace(metrics,runtime_seconds=perf_counter()-start)
    return OptimizationResult(algorithm=OptimizationAlgorithm.GA_PO,best_individual=best,
        final_population=gp+pp,metrics=metrics,convergence_history=tuple(history)),dict(counts=dict(counts),events=events,random_control=random_control)
