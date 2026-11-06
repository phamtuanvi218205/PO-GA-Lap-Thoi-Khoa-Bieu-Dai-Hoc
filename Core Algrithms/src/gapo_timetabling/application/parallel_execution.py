"""Web-only decoder prefetch. Serial optimizer/RNG/FE semantics stay authoritative.

Patches live ONLY in a disposable coordinator process, never in the API or CLI.
Workers decode/repair/validate ahead, but never calculate Fitness. The coordinator
scores only candidates actually requested by the unmodified serial optimizer.
Speculative decoder work is extra physical work, not extra search or extra FE.
"""
from __future__ import annotations

from collections import deque
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from dataclasses import replace
import inspect
import logging
import multiprocessing as mp
import os
from random import Random
from threading import Lock
from time import monotonic
import traceback
from unittest.mock import patch

from .run_contract import execute_prepared_run_request as serial_execute

_allocation_lock = Lock()
_allocated_workers = 0
LOGGER = logging.getLogger(__name__)


def available_memory_bytes():
    """Avoid requiring psutil in the demo installation."""
    if os.name == 'nt':
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong),
                ('total',ctypes.c_ulonglong),('available',ctypes.c_ulonglong),
                ('page_total',ctypes.c_ulonglong),('page_available',ctypes.c_ulonglong),
                ('virtual_total',ctypes.c_ulonglong),('virtual_available',ctypes.c_ulonglong),
                ('extended',ctypes.c_ulonglong)]
        state=MemoryStatus(); state.length=ctypes.sizeof(state)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
            return state.available
    try: return os.sysconf('SC_AVPHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
    except (AttributeError,ValueError,OSError): return 2*1024**3


def recommended_workers():
    raw=os.getenv('GAPO_EVALUATION_WORKERS','auto').strip().lower()
    cpu=max(1,(os.cpu_count() or 2)//2)
    # Reserve 1 GiB for Windows/browser; conservative 192 MiB per evaluator.
    memory=max(1,(available_memory_bytes()-1024**3)//(192*1024**2))
    if raw=='auto': return max(1,min(cpu,8,memory))
    value=int(raw)
    if value<1: raise ValueError('GAPO_EVALUATION_WORKERS must be >= 1 or auto')
    return max(1,min(value,os.cpu_count() or 1,memory))


def _init_evaluator(problem,domains,config):
    global _problem,_domains,_config
    _problem,_domains,_config=problem,domains,config
    from ..core import population
    from ..core.models import FitnessBreakdown,FitnessResult
    # This placeholder never participates in optimizer selection or a saved run.
    neutral=FitnessResult(0.,0.,FitnessBreakdown(0,0,0.,0.,0.,0.,()))
    population.calculate_fitness=lambda *args,**kwargs: neutral


def _decode_only(vector):
    from ..core.population import evaluate_candidate
    value=evaluate_candidate(_problem,_domains,vector,_config)
    return replace(value,fitness_evaluations=0)


class _Prefetch:
    def __init__(self,pool,problem,domains,config,workers,stop):
        self.pool=pool; self.problem=problem; self.domains=domains; self.config=config
        self.workers=workers; self.stop=stop; self.queue=deque(); self.generator=iter(())
        self.ga_population=None
        self.stats=dict(workers=workers,submitted_decodes=0,consumed_decodes=0,
            speculative_decodes=0,fitness_calls=0,completed_decode_nodes=0,
            completed_decode_backtracks=0,discarded_completed_decodes=0)

    def check(self):
        if self.stop.is_set(): raise RuntimeError('Parallel execution interrupted')

    def _account(self,value):
        self.stats['completed_decode_nodes']+=value.total_decode_nodes
        self.stats['completed_decode_backtracks']+=value.total_decode_backtracks

    def clear(self):
        for vector,future in self.queue:
            if future.done() and not future.cancelled():
                self._account(future.result()); self.stats['discarded_completed_decodes']+=1
            else: future.cancel()
        self.queue.clear(); self.generator=iter(()); self.ga_population=None

    def start(self,generator):
        self.clear(); self.generator=iter(generator); self.fill()

    def fill(self):
        self.check()
        while len(self.queue)<self.workers:
            try: vector=next(self.generator)
            except StopIteration: break
            self.queue.append((vector,self.pool.submit(_decode_only,vector)))
            self.stats['submitted_decodes']+=1

    def evaluate(self,problem,domains,vector,config):
        assert problem is self.problem and domains is self.domains and config==self.config
        self.check()
        if not self.queue: raise RuntimeError('Prefetch stream exhausted unexpectedly')
        expected,future=self.queue.popleft()
        if expected!=vector: raise RuntimeError('Prefetch/RNG mismatch; refusing changed search')
        while True:
            self.check()
            try: value=future.result(timeout=.1); break
            except TimeoutError: continue
        self._account(value); self.stats['consumed_decodes']+=1
        self.fill()
        if value.is_success:
            from ..core.fitness import calculate_fitness
            real=calculate_fitness(problem,value.individual.selected_options,domains)
            value=replace(value,individual=replace(value.individual,fitness=real),fitness_evaluations=1)
            self.stats['fitness_calls']+=1
        return value


def _coordinator(connection,stop,request,prepared,workers):
    from ..core import ga,hybrid,po,population,target_hybrid
    from . import run_contract
    pool=None; stream=None
    try:
        pool=ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'),
            initializer=_init_evaluator,initargs=(prepared.problem,prepared.option_domains,request.evaluation_config))
        stream=_Prefetch(pool,prepared.problem,prepared.option_domains,request.evaluation_config,workers,stop)
        original_init=population.initialize_population
        original_ga=ga._create_offspring_vector
        original_po=po._create_and_evaluate_po_offspring
        signature=inspect.signature(original_po)
        original_target=target_hybrid._create_and_evaluate_target_offspring
        target_signature=inspect.signature(original_target)

        def initialization(*args,**kwargs):
            rng=Random(kwargs['seed'])
            def vectors():
                for _ in range(kwargs['max_initialization_attempts']):
                    yield tuple(rng.random() for _ in range(prepared.problem.dimension))
            stream.start(vectors())
            try: return original_init(*args,**kwargs)
            finally: stream.clear()

        def ga_vector(*args,**kwargs):
            bound=inspect.signature(original_ga).bind(*args,**kwargs).arguments
            vector=original_ga(*args,**kwargs)
            if stream.ga_population is not bound['population']:
                rng=Random(); rng.setstate(bound['rng'].getstate())
                def vectors():
                    yield vector
                    while True:
                        yield original_ga(bound['population'],bound['config'],bound['dimension'],rng)
                stream.start(vectors()); stream.ga_population=bound['population']
            return vector

        def po_child(*args,**kwargs):
            b=signature.bind(*args,**kwargs).arguments
            rng=Random(); rng.setstate(b['rng'].getstate())
            def vectors():
                for _ in range(b['config'].max_offspring_attempts):
                    yield po.clip_vector_to_unit_interval(po.create_po_position(
                        b['current_individual'].vector,b['current_index'],b['behavior'],
                        b['best_individual'].vector,b['population_mean'],b['iteration'],
                        b['max_iterations'],b['alpha'],b['theta'],rng))
            stream.start(vectors())
            try: return original_po(*args,**kwargs)
            finally: stream.clear()

        def target_child(*args,**kwargs):
            b=target_signature.bind(*args,**kwargs).arguments
            rng=Random(); rng.setstate(b['rng'].getstate())
            def vectors():
                for _ in range(b['config'].max_offspring_attempts):
                    yield target_hybrid.propose(
                        b['anchor'],b['pool'],b['guide'],b['mask'],b['index'],
                        b['behavior'],b['generation'],b['alpha'],b['theta'],rng,
                        max_iterations=b['max_iterations'])
            stream.start(vectors())
            try: return original_target(*args,**kwargs)
            finally: stream.clear()

        def progress(value):
            stream.check(); connection.send(('progress',value))
            while not connection.poll(.1): stream.check()
            if connection.recv()!='continue': raise RuntimeError('Parent stopped run')

        # These module objects exist only inside this disposable process.
        with patch.object(run_contract,'initialize_population',initialization), \
             patch.object(ga,'_create_offspring_vector',ga_vector), \
             patch.object(hybrid,'_create_offspring_vector',ga_vector), \
             patch.object(population,'evaluate_candidate',stream.evaluate), \
             patch.object(ga,'evaluate_candidate',stream.evaluate), \
             patch.object(hybrid,'evaluate_candidate',stream.evaluate), \
             patch.object(target_hybrid,'evaluate_candidate',stream.evaluate), \
             patch.object(po,'evaluate_candidate',stream.evaluate), \
             patch.object(po,'_create_and_evaluate_po_offspring',po_child), \
             patch.object(hybrid,'_create_and_evaluate_po_offspring',po_child), \
             patch.object(target_hybrid,'_create_and_evaluate_target_offspring',target_child):
            result=serial_execute(request,prepared,progress_callback=progress)
        stream.clear()
        stream.stats['speculative_decodes']=stream.stats['submitted_decodes']-stream.stats['consumed_decodes']
        result['execution']={'mode':'ordered-decoder-prefetch','search_semantics':'serial',
            'speculative_work_in_optimizer_metrics':False,
            'note':'Extra speculative decode work is not extra Fitness; partial terminated work not fully measured.',**stream.stats}
        connection.send(('result',result))
    except BaseException:
        if not stop.is_set(): connection.send(('error',traceback.format_exc()))
    finally:
        if pool is not None:
            pool.shutdown(wait=False,cancel_futures=True)
        # No database connections in these workers; unfinished speculation may be stopped.
        for child in mp.active_children():
            child.terminate(); child.join(timeout=2)
        connection.close()


def execute_web_run_request(request,prepared,*,progress_callback=None,check_interruption=None):
    """Keep SQL and callbacks in the caller; compute in isolated subprocesses."""
    global _allocated_workers
    budget=recommended_workers()
    # On tiny problems process startup/IPC is slower than the whole solver.
    if os.getenv('GAPO_EVALUATION_WORKERS','auto').strip().lower()=='auto' and prepared.problem.session_dimension<100:
        budget=1
    with _allocation_lock:
        workers=max(1,budget-_allocated_workers)
        if workers>1: _allocated_workers+=workers
    if workers<=1 or not prepared.is_ready:
        if workers>1:
            with _allocation_lock: _allocated_workers-=workers
        return serial_execute(request,prepared,progress_callback=progress_callback)
    context=mp.get_context('spawn'); parent,child=context.Pipe(); stop=context.Event()
    process=context.Process(target=_coordinator,args=(child,stop,request,prepared,workers),name='gapo-demo-coordinator')
    started=monotonic()
    try:
        process.start(); child.close()
        while True:
            if check_interruption is not None: check_interruption()
            if parent.poll(.2):
                kind,value=parent.recv()
                if kind=='progress':
                    if progress_callback is not None: progress_callback(value)
                    parent.send('continue')
                elif kind=='result':
                    value['execution']['wall_seconds']=monotonic()-started
                    LOGGER.info('Demo parallel execution: %s',value['execution'])
                    return value
                else: raise RuntimeError('Parallel demo failed:\n'+value)
            elif not process.is_alive():
                raise RuntimeError(f'Parallel demo process exited unexpectedly ({process.exitcode})')
    finally:
        stop.set(); parent.close(); child.close()
        if process.pid is not None:
            process.join(timeout=8)
            if process.is_alive(): process.terminate(); process.join(timeout=2)
            process.close()
        with _allocation_lock: _allocated_workers-=workers
