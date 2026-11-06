"""Replay saved results, then report every ratio/scale/seed, without optimization."""
from collections import Counter
from itertools import combinations
from math import comb
from statistics import median
import evidence as w

REFERENCE = 'GA80_PO20'


def compare(a,b):
    for x,y in zip(a,b,strict=True):
        if abs(x-y) > 1e-12:
            return 'W' if x < y else 'L'
    return 'T'


def sign(counts):
    n = counts['W'] + counts['L']
    return min(1.,2*sum(comb(n,k) for k in range(min(counts['W'],counts['L'])+1))/2**n) if n else 1.


def holm(raw):
    adjusted, previous = {}, 0.
    for index,method in enumerate(sorted(raw,key=raw.get)):
        previous = max(previous,min(1.,raw[method]*(len(raw)-index)))
        adjusted[method] = previous
    return adjusted


def report():
    w.verify_source()
    root = w.ROOT
    methods = w.read(root/'manifest.json')['variants']
    expected = {f'{s}_{seed}_{m}.json' for s in w.CASES for seed in range(1,11) for m in methods}
    for folder in ('runs','details','checkpoints'):
        if {p.name for p in (root/folder).glob('*.json')} != expected:
            raise ValueError(f'Missing/unexpected ratio records: {folder}')
    for rel,checksum in w.read(root/'reference_manifest.json')['entries_sha256'].items():
        if w.digest((root/rel).read_bytes()) != checksum:
            raise ValueError(f'Reference changed: {rel}')
    rows,pairs,audits,saved = [],[],[],{}
    all_methods = (REFERENCE,*methods)
    for scale in w.CASES:
        prep = w.prepared(scale)
        for seed in range(1,11):
            meta = w.read(root/'cohorts'/f'{scale}_{seed}.json')
            initial = min(r['quality'] for r in meta['records'])
            for method in all_methods:
                reference = method == REFERENCE
                base = root/'full' if reference else root
                key = f"{scale}_{seed}_{'TARGET_PO80' if reference else method}"
                payload = w.read(base/'runs'/f'{key}.json')
                detail = w.read(base/'details'/f'{key}.json')
                cp = w.read(base/'checkpoints'/f'{key}.json')
                assert cp['result_sha'] == w.digest((base/'runs'/f'{key}.json').read_bytes())
                assert cp['detail_sha'] == w.digest((base/'details'/f'{key}.json').read_bytes())
                assert cp['initial_sha'] == detail['initial_sha'] == meta['initial_sha']
                assert detail['records'][:30] == meta['records'] and detail['trace'][:30] == meta['trace']
                assert payload['snapshot_checksum'] == meta['snapshot_checksum'] == prep.snapshot_checksum
                assert detail['decoder_work']['soft_option_scores'] == 0
                if not reference:
                    assert payload['research_variant'] == method
                w.validate_trace(payload,detail)
                checked = w.audit(payload,prep)
                assert checked == detail['audit']
                data = payload['result']
                row = dict(scale=scale,seed=seed,method=method,
                    quality=[data['best_fitness']['general_quality_score'],data['best_fitness']['lecturer_preference_score']],
                    initial=initial,metrics=data['metrics'],history=data['convergence_history'],
                    activity_counts=data['hybrid_activity']['counts'],reused=reference)
                rows.append(row)
                saved[scale,seed,method] = dict(row=row,trace=detail['trace'])
                audits.append(dict(scale=scale,seed=seed,method=method,**checked))
    for a,b in combinations(all_methods,2):
        for scale in w.CASES:
            for seed in range(1,11):
                left,right = saved[scale,seed,a],saved[scale,seed,b]
                fe = min(len(left['trace']),len(right['trace']))
                pairs.append(dict(a=a,b=b,scale=scale,seed=seed,common_fe=fe,
                    final=compare(left['row']['quality'],right['row']['quality']),
                    common=compare(left['trace'][fe-1]['best'],right['trace'][fe-1]['best']),
                    quality_a=left['row']['quality'],quality_b=right['row']['quality'],
                    common_a=left['trace'][fe-1]['best'],common_b=right['trace'][fe-1]['best']))
    summary,aggregates = [],[]
    for a,b in combinations(all_methods,2):
        for scale in (*w.CASES,'ALL'):
            chosen = [p for p in pairs if p['a']==a and p['b']==b and (scale=='ALL' or p['scale']==scale)]
            summary.append(dict(a=a,b=b,scale=scale,
                final={k:sum(p['final']==k for p in chosen) for k in 'WTL'},
                common={k:sum(p['common']==k for p in chosen) for k in 'WTL'}))
    for method in all_methods:
        for scale in w.CASES:
            chosen = [r for r in rows if r['method']==method and r['scale']==scale]
            counts = Counter()
            for r in chosen: counts.update(r['activity_counts'])
            aggregates.append(dict(method=method,scale=scale,
                qg_median=median(r['quality'][0] for r in chosen),
                ql_median=median(r['quality'][1] for r in chosen),
                FE=sum(r['metrics']['fitness_evaluations'] for r in chosen),
                decode_fail=sum(r['metrics']['decode_failed_count'] for r in chosen),
                backtracks=sum(r['metrics']['total_decode_backtracks'] for r in chosen),
                qg_improved=sum(r['quality'][0] < r['initial'][0]-1e-12 for r in chosen),
                activity_counts=dict(counts)))
    tests = []
    if set(methods) == set(w.METHODS):
        for endpoint in ('final','common'):
            raw = {m:sign(Counter(p[endpoint] for p in pairs if p['a']==REFERENCE and p['b']==m)) for m in methods}
            adj = holm(raw)
            tests += [dict(endpoint=endpoint,reference=REFERENCE,other=m,p=raw[m],p_holm=adj[m],
                           family_size=2,exploratory=True) for m in methods]
    ranks = []
    if len(all_methods)==3:
        for endpoint in ('final','common_three_way'):
            for scale in w.CASES:
                totals = {m:dict(rank_sum=0.,best_count=0,pair_wins=0) for m in all_methods}
                for seed in range(1,11):
                    common = min(len(saved[scale,seed,m]['trace']) for m in all_methods)
                    q = {m:(saved[scale,seed,m]['row']['quality'] if endpoint=='final' else
                             saved[scale,seed,m]['trace'][common-1]['best']) for m in all_methods}
                    for m in all_methods:
                        better = sum(compare(q[x],q[m])=='W' for x in all_methods if x!=m)
                        tied = sum(compare(q[x],q[m])=='T' for x in all_methods if x!=m)
                        totals[m]['rank_sum'] += 1+better+tied/2
                        totals[m]['best_count'] += int(better==0)
                        totals[m]['pair_wins'] += sum(compare(q[m],q[x])=='W' for x in all_methods if x!=m)
                ranks += [dict(endpoint=endpoint,scale=scale,method=m,mean_rank=v['rank_sum']/10,
                               best_including_ties=v['best_count'],pair_wins=v['pair_wins']) for m,v in totals.items()]
    for name,data in [('rows',rows),('pairs',pairs),('summary',summary),('quality_summary',aggregates),
                      ('sign_tests',tests),('ranks',ranks)]:
        w.save(root/'analysis'/f'{name}.json',data)
    plot(rows,pairs,all_methods)
    w.save(root/'analysis/final_audit.json',dict(passed=True,new_ratio_runs=30*len(methods),
        reused_80_20_runs=30,new_main_or_ablation_runs=0,shared_cohorts=30,
        hard_violations=0,soft_queries=0,generations=50,fe_cap=1530,replays=audits))
    lines = ['# TARGET ratio sensitivity T50','',
        'GA80_PO20 is the saved reference. Only the selected 70/30 and/or 60/40 jobs are new.',
        'N30 / T50 / cap1530. Same TeachingPart snapshots and initial cohorts. W/T/L is from A toward B.',
        '', '| A | B | Scale | Final W/T/L | Exact common FE W/T/L |','|---|---|---|---|---|']
    for r in summary:
        count = lambda k:'/'.join(str(r[k][x]) for x in 'WTL')
        lines.append(f"|{r['a']}|{r['b']}|{r['scale']}|{count('final')}|{count('common')}|")
    lines += ['', 'All ratios/seeds, failures and unfavorable results are retained.',
        'Separate Q medians by scale are in quality_summary.json; do not pool Q across scales.',
        'Two reference comparisons use exploratory Holm2 only after both ratio parts are merged.',
        '70/30 vs 60/40 is descriptive, not an extra unadjusted confirmatory test.',
        'These are development fixtures, not independent validation after choosing a ratio.',
        'No runtime ranking across hosts or parallel workers. Ratio slots are not a runtime/FE fraction.']
    (root/'KET_QUA.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def plot(rows,pairs,methods):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    out = w.ROOT/'analysis'
    for scale in w.CASES:
        fig,axes = plt.subplots(1,2,figsize=(12,4.5))
        for method in methods:
            chosen = [r for r in rows if r['scale']==scale and r['method']==method]
            for ax,key in zip(axes,('general_quality_score','lecturer_preference_score')):
                a = np.array([[h[key] for h in r['history']] for r in chosen])
                lo,mid,hi = np.percentile(a,[25,50,75],axis=0)
                ax.plot(range(51),mid,label=method)
                ax.fill_between(range(51),lo,hi,alpha=.12)
                ax.set(xlabel='Generation',ylabel=key); ax.grid(alpha=.2); ax.legend()
        fig.suptitle(f'{scale.title()} / T50 ratio sensitivity / 10 seeds')
        fig.tight_layout(); fig.savefig(out/f'{scale}_convergence.png',dpi=160); plt.close(fig)
    fig,axes = plt.subplots(1,3,figsize=(13,4))
    for ax,scale in zip(axes,w.CASES):
        for method in methods[1:]:
            chosen = [p for p in pairs if p['scale']==scale and p['a']==REFERENCE and p['b']==method]
            ax.scatter([p['seed'] for p in chosen],[p['quality_a'][0]-p['quality_b'][0] for p in chosen],label=method)
        ax.axhline(0,color='black',linewidth=.8)
        ax.set(title=scale.title(),xlabel='Seed',ylabel='Qg 80/20 minus other'); ax.grid(alpha=.2); ax.legend()
    fig.tight_layout(); fig.savefig(out/'paired_comparison.png',dpi=160); plt.close(fig)
