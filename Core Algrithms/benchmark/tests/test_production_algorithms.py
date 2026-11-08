"""Numerical adapter must reproduce production trajectories, not just a label."""
import sys
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import patch
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT), str(ROOT.parent/'src')]
from production_algorithms import run_numerical, NumericalIndividual
from gapo_timetabling.core import ga, po, hybrid
from gapo_timetabling.core.population import CandidateEvaluationConfig, PopulationInitializationStatus


class ProductionParityTests(unittest.TestCase):
    def check_parity(self, method, seed, constant=False, n=10, d=4, g=8, objective=None):
        u=np.random.default_rng(seed).uniform(size=(n,d))
        if objective is None:
            objective=lambda a: np.full(len(a),3.) if constant else np.sum((a-.37)**2,axis=1)
        numerical_trace=[]
        def tracked(a):
            numerical_trace.extend(tuple(x) for x in a)
            return objective(a)
        result=run_numerical(tracked,u,0.,1.,n*(g+1),seed,algorithm=method)
        items=tuple(NumericalIndividual(tuple(v),float(objective(v.reshape(1,-1))[0])) for v in u)
        # Only evaluation data/gateway is substituted. The complete production
        # algorithm loops, RNG, selectors, operators and migrations run intact.
        initialization=NS(status=PopulationInitializationStatus.SUCCESS,individuals=items,
            requested_population_size=n,fitness_evaluations=n,candidate_attempts=n,
            decode_failed_count=0,validation_failed_count=0,repaired_individual_count=0,
            failed_repair_count=0,total_repair_attempts=0,total_decode_nodes=0,total_decode_backtracks=0)
        problem=NS(dimension=d,session_dimension=0)
        production_trace=[tuple(v) for v in u]
        def evaluate(_p,_domains,vector,_config):
            production_trace.append(vector)
            item=NumericalIndividual(vector,float(objective(np.asarray(vector).reshape(1,-1))[0]))
            return NS(is_success=True,individual=item)
        def accumulate(metrics,evaluation):
            return replace(metrics,candidate_attempts=metrics.candidate_attempts+1,
                           fitness_evaluations=metrics.fitness_evaluations+1)
        # Core convergence points access the two scores; supply them without
        # changing core objective comparison semantics.
        fitness=property(lambda i:NS(general_quality_score=i.value,lecturer_preference_score=0.))
        module={'GA':ga,'PO':po,'ISLAND80':hybrid}[method]
        cfg={'GA':ga.GAConfig,'PO':po.PoConfig,'ISLAND80':hybrid.HybridConfig}[method](
            n*(g+1),1,seed,CandidateEvaluationConfig(1,False))
        with patch.object(NumericalIndividual,'fitness',fitness,create=True), \
             patch.object(ga,'evaluate_candidate',evaluate), \
             patch.object(po,'evaluate_candidate',evaluate), \
             patch.object(hybrid,'evaluate_candidate',evaluate), \
             patch.object(ga,'accumulate_candidate_evaluation',accumulate), \
             patch.object(po,'accumulate_candidate_evaluation',accumulate), \
             patch.object(hybrid,'accumulate_candidate_evaluation',accumulate):
            actual=module.run_island_hybrid(problem,(),initialization,cfg) if method=='ISLAND80' else (
                module.run_ga(problem,(),initialization,cfg) if method=='GA' else
                module.run_po(problem,(),initialization,cfg))
        self.assertEqual(numerical_trace,production_trace)
        self.assertEqual(result.best_unit_position,actual.best_individual.vector)
        self.assertEqual(result.history_best_values,[p.general_quality_score for p in actual.convergence_history])
        self.assertEqual(result.history_evaluations,[p.fitness_evaluations for p in actual.convergence_history])
        self.assertEqual(result.final_population,actual.final_population)
        self.assertEqual(len(numerical_trace),n*(g+1))

    def test_all_three_complete_trajectories_match_production(self):
        for method in ('GA','PO','ISLAND80'):
            for seed in (1,17,42):
                for constant in (False,True):
                    with self.subTest(method=method,seed=seed,constant=constant):
                        self.check_parity(method,seed,constant)

    def test_affine_mapping_and_budget(self):
        observed=[]
        u=np.random.default_rng(4).uniform(-100,100,(30,20))
        def objective(x):
            self.assertTrue(np.all(x>=-100) and np.all(x<=100))
            observed.extend(x.tolist())
            return np.sum(x*x,axis=1)
        r=run_numerical(objective,u,-100,100,330,4,algorithm='ISLAND80')
        self.assertEqual(len(observed),330)
        np.testing.assert_array_equal(r.best_position,-100+200*np.asarray(r.best_unit_position))
        self.assertEqual(r.diagnostics['ga_offspring'],240)
        self.assertEqual(r.diagnostics['po_offspring'],60)
        self.assertEqual(r.diagnostics['migration_events'],4)
        self.assertTrue(all(x>0 for x in r.diagnostics['po_behaviors']))
        self.assertTrue(r.diagnostics['po_worse_accepted']>0)

    def test_production_size_and_official_cec_trajectory(self):
        from benchmark_functions import get_cec2022_suite
        for method in ('GA','PO','ISLAND80'):
            self.check_parity(method,17,n=30,d=20,g=20)
            fn=get_cec2022_suite(20)[0]
            self.check_parity(method,1,n=30,d=20,g=4,
                objective=lambda u:fn.evaluate_population(-100+200*u))

    def test_invalid_budget_rejected(self):
        with self.assertRaises(ValueError):
            run_numerical(lambda x:np.sum(x*x,axis=1),np.zeros((30,20)),0,1,331,1,algorithm='GA')

if __name__=='__main__': unittest.main()
