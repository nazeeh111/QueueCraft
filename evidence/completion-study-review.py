#!/usr/bin/env python3
"""Independent saved-artifact audit. Never calls a strategy or measures its work.

Run only after production and its concurrent benchmark have finished. Source
under queuecraft/ is read-only; this script writes its own evidence JSON only.
"""
from __future__ import annotations
import argparse, bisect, collections, csv, hashlib, itertools, json, math
from pathlib import Path
import random, statistics, sys

NS = 10**9
HEADER = 'event,exchange_ns,receive_ns,kind,side,price,quantity\n'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while b := f.read(1024**2): h.update(b)
    return h.hexdigest()


def check(condition, message):
    if not condition: raise AssertionError(message)


def load_events(path):
    events = []
    with path.open() as f:
        for r in csv.DictReader(f):
            eid, recv = int(r['event']), int(r['receive_ns'])
            if eid == len(events):
                events.append({'id': eid, 'time': recv, 'kind': r['kind'], 'rows': []})
            event = events[eid]
            check(event['time'] == recv and event['kind'] == r['kind'], 'mixed source event')
            check(int(r['exchange_ns']) == -1 and r['kind'] in ('S', 'G'), 'unexpected archive semantics')
            event['rows'].append((r['side'], int(r['price']), int(r['quantity'])))
    return events


def quantile(values, p):
    return sorted(values)[max(0, math.ceil(p * len(values))-1)]


def summary(rows, dimensions):
    groups = collections.defaultdict(list)
    for row in rows: groups[tuple(row[k] for k in dimensions)].append(row)
    result = []
    for key, group in sorted(groups.items()):
        result.append(dict(zip(dimensions, key)) | {
            'windows': len({r['session'] for r in group}), 'trials': len(group),
            'mean_cost': statistics.fmean(r['cost_ticks_per_lot'] for r in group),
            'p95_cost': quantile([r['cost_ticks_per_lot'] for r in group], .95),
            'mean_completion': statistics.fmean(r['completion'] for r in group),
            'fees': sum(r['fees'] for r in group), 'unfilled': sum(r['unfilled'] for r in group),
            'sql_transitions': sum(r['sql_transitions'] for r in group),
            'sql_fills': sum(r['sql_fills'] for r in group)})
    return result


def audit(root, study, sessions, output, rerun_sql):
    result = json.loads((study/'results.json').read_text())
    check(result['status'] == 'complete' and json.loads((study/'status.json').read_text())['status'] == 'complete', 'study incomplete')
    reg = json.loads((study/'registration.json').read_text())
    check(result['registration'] == reg, 'registration mismatch')
    plan = reg['plan']; manifest = json.loads((sessions/'manifest.json').read_text())
    calibration = json.loads((study/'calibration.json').read_text())
    check(digest(study/'calibration.json') == reg['calibration_sha256'], 'calibration changed')
    check(digest(sessions/'manifest.json') == reg['manifest_sha256'], 'manifest changed')
    check(digest(root/'docs/PROSPECTIVE_PLAN.json') == reg['plan_sha256'], 'plan changed')
    for name, sha in reg['source_hashes'].items(): check(digest(root/'queuecraft'/name) == sha, 'source changed '+name)
    check(digest(root/'queuecraft/_native.cpython-314-darwin.so') == reg['native_binary_sha256'], 'native binary changed')
    check(digest(root/'data/15m-archive'/plan['source']['file'])==reg['raw_archive_sha256']==plan['source']['sha256'], 'raw archive identity')
    identity={k:reg[k] for k in ['plan_sha256','manifest_sha256','source_hashes','raw_archive_sha256']}
    identity['planning_config']=reg['planning_config']
    check(calibration['identity']==identity,'calibration frozen identity')
    windows = {w['market_slug']: w for w in manifest['windows']}
    check(len(windows) == 265 and sum(w['status']=='included' for w in windows.values()) == 209, 'population mismatch')
    events = {}
    for name, sha in reg['session_hashes'].items():
        check(digest(sessions/name) == sha, 'session changed '+name)
    for slug, window in windows.items():
        expected_split = 'development' if window['opening_utc_day'] in plan['development_opening_utc_days'] else 'confirmation' if window['opening_utc_day'] in plan['confirmation_opening_utc_days'] else 'excluded_day'
        check(window['split'] == expected_split, 'day split mismatch')
        if window['status'] == 'included':
            events[slug] = load_events(sessions/window['file'])
            check(window['parent_start_ns'] == window['opening_ns']+60*NS and window['recording_end_ns'] == window['opening_ns']+90*NS, 'source bounds')
    selected = sorted((w for w in windows.values() if w['status']=='included' and w['split']=='development'), key=lambda w:(w['parent_start_ns'],w['coin'],w['market_slug']))[:32]
    expected_prefixes=[]
    for w in selected:
        prefix=[e for e in events[w['market_slug']] if e['time']<=w['parent_start_ns']]
        text=''.join(HEADER+''.join(f"{e['id']},-1,{e['time']},{e['kind']},{side},{price},{qty}\n" for side,price,qty in e['rows']) for e in prefix)
        expected_prefixes.append({'session':w['market_slug'],'day':w['opening_utc_day'],'prefix_sha256':hashlib.sha256(text.encode()).hexdigest()})
    check(calibration['prefixes']==expected_prefixes, 'development calibration prefixes differ')
    check(calibration['shared_decision_budget_ns']==NS and calibration['samples_per_policy']==5000 and calibration['warmups_per_prefix_per_policy']==1, 'calibration protocol')
    durations={}
    for policy in plan['policies']:
        item=calibration['policies'][policy]; raw=item['raw_ns']
        check(len(raw)==5000 and all(type(x) is int and x>=0 for x in raw), 'calibration timing values')
        for field,p in [('p50_ns',.5),('p95_ns',.95),('p99_ns',.99)]: check(item[field]==quantile(raw,p), 'calibration percentile')
        duration=max(10**6,math.ceil(item['p99_ns']/10**6)*10**6)
        check(item['declared_duration_ns']==duration, 'calibration rounding')
        durations[policy]=duration
    print(json.dumps({'phase':'identities_and_calibration_checked','windows':len(windows),'calibrated_durations_ns':durations}),flush=True)

    modes=plan['policy_compute_sensitivity']['modes']
    worlds=[s['name']+'/'+mode for s,mode in itertools.product(plan['scenarios'],modes)]
    grid=list(itertools.product(plan['policies'],plan['sides'],plan['quantities_lots'],plan['deadlines_seconds'],worlds))
    expected={(slug,)+cell for slug in windows for cell in grid}
    observed=set(); rows=[]; totals=collections.Counter(); compute=collections.defaultdict(collections.Counter)
    sql_batch=[]; batch_session=None; sql_reruns=0

    def sql_flush():
        nonlocal sql_reruns
        if not sql_batch:return
        if rerun_sql:
            from queuecraft.sdk import Intent, Scenario, Simulation
            from queuecraft.reconcile import reconcile_many
            converted=[]
            for saved, old_sql in sql_batch:
                fields=dict(saved); fields['intent']=Intent(**fields['intent']); fields['scenario']=Scenario(**fields['scenario'])
                converted.append(Simulation(**fields))
            checked=reconcile_many(converted)
            check(checked==[x[1] for x in sql_batch], 'saved SQL reports do not reproduce')
            sql_reruns+=1
        sql_batch.clear()

    with (study/'traces.jsonl').open() as trace:
        for line_no,line in enumerate(trace,1):
            item=json.loads(line); row=item['labels']; sim=item['simulation']; intent=sim['intent']; scenario=sim['scenario']; sql=item['sql']
            slug=row['session']; w=windows[slug]
            key=(slug,row['policy'],row['side'],row['size'],row['deadline_s'],row['scenario'])
            check(key in expected and key not in observed, 'unexpected/duplicate trace')
            observed.add(key); check(w['status']=='included', 'excluded session executed')
            check(all(row[k]==v for k,v in [('split',w['split']),('coin',w['coin']),('opening_day',w['opening_utc_day']),('condition',w['condition'])]), 'trace strata')
            check(intent['start_ns']==w['parent_start_ns'] and intent['deadline_ns']==intent['start_ns']+row['deadline_s']*NS and sim['recording_end_ns']==w['recording_end_ns'], 'trace bounds')
            source=events[slug]; times=[e['time'] for e in source]
            initial=source[bisect.bisect_right(times,intent['start_ns'])-1]
            check(initial['kind']=='S','initial valid source')
            bids=[p for side,p,q in initial['rows'] if side=='B']; asks=[p for side,p,q in initial['rows'] if side=='A']
            benchmark=max(bids)+min(asks)
            check(row['benchmark2']==sim['benchmark2']==benchmark and row['benchmark_event']==initial['id'] and row['benchmark_capture_ns']==initial['time'], 'common evaluation benchmark')
            check('benchmark2' not in intent, 'benchmark leaked into intent')
            duration=0 if row['compute_mode']=='zero_compute_baseline' else durations[row['policy']]
            check(scenario['policy_duration_ns']==row['policy_duration_ns']==duration and scenario['decision_budget_ns']==NS and scenario['max_staleness_ns']==5*NS, 'compute/staleness settings')
            specification=next(s for s in plan['scenarios'] if s['name']==row['execution_scenario'])
            check(all(scenario[k]==v for k,v in specification.items() if k!='name'), 'execution scenario differs')
            for decision in sim['decisions']:
                idx=bisect.bisect_right(times,decision['time_ns']-scenario['observation_delay_ns'])-1
                e=source[idx] if idx>=0 else None
                valid=bool(e and e['kind']=='S' and decision['time_ns']-e['time']<=5*NS and decision['time_ns']<=sim['recording_end_ns'])
                check(decision['valid']==valid and decision['event']==(idx if e else -1), 'decision prefix/validity')
                check(decision['observed_receive_ns']==(e['time'] if e else -1), 'future observation')
                missed=duration>NS
                check(decision['fallback']==('noop' if missed else 'none'), 'deadline fallback')
                check(not missed or decision['quantity']==0, 'late policy submitted order')
            check(row['missed_decisions']==sum(d['fallback']=='noop' for d in sim['decisions']), 'missed-decision count')
            orders={o['order_id']:o for o in sim['orders']}
            check(len(orders)==len(sim['orders']), 'duplicate order')
            per_order=collections.defaultdict(lambda:collections.Counter())
            for fill in sim['fills']:
                order=orders[fill['order_id']]; q,p=fill['quantity'],fill['price']; n=q*p; fee=(n*scenario['fee_ppm']+999999)//1000000
                check(fill['side']==intent['side'], 'fill side differs from parent')
                check(q>0 and p>0 and fill['notional']==n and fill['fee']==fee, 'integer fill/fee arithmetic')
                check(fill['arrival_ns']==order['arrival_ns']<=min(intent['deadline_ns'],sim['recording_end_ns']), 'fill deadline/coverage')
                check(fill['recorded_receive_ns']<=fill['arrival_ns'] and fill['arrival_ns']-fill['recorded_receive_ns']<=5*NS, 'fill timing/staleness')
                # Pending arrivals precede tied source events only under the
                # declared alternative. A newly submitted zero-delay order
                # follows its same-clock decision and already-applied market.
                pending_tie=scenario['tie']=='arrival_first' and order['decision_ns']<order['arrival_ns']
                applicable=(bisect.bisect_left(times,fill['arrival_ns']) if pending_tie else bisect.bisect_right(times,fill['arrival_ns']))-1
                source_event=source[applicable] if applicable>=0 else None
                check(source_event is not None and source_event['kind']=='S' and fill['event']==source_event['id'] and fill['recorded_receive_ns']==source_event['time'] and fill['exchange_ns']==-1, 'fill source event/tie differs')
                opposing='A' if intent['side']=='buy' else 'B'
                ladder={price:quantity for side,price,quantity in source_event['rows'] if side==opposing}
                check(p in ladder and q<=ladder[p], 'fill price/quantity outside recorded opposing ladder')
                c=per_order[fill['order_id']]; c['filled']+=q;c['fees']+=fee;c['notional']+=n;c['cash']+=(-n-fee if intent['side']=='buy' else n-fee);c['inventory']+=(q if intent['side']=='buy' else -q)
            running=collections.Counter(); seen_ledger=set()
            for step,ledger in enumerate(sim['ledger']):
                oid=ledger['order_id']; check(oid not in seen_ledger and oid in orders and ledger['step']==step,'ledger coverage/order');seen_ledger.add(oid)
                running.update(per_order[oid]);check(ledger['time_ns']==orders[oid]['arrival_ns'],'ledger timestamp')
                check(all(ledger[k]==running[k] for k in ['cash','inventory','fees','filled']), 'nonclosing ledger transition')
            closing=collections.Counter()
            for oid,order in orders.items():
                c=per_order[oid]; closing.update(c)
                check(order['filled']==c['filled']<=order['quantity'], 'order conservation')
                check(order['arrival_ns']==order['decision_ns']+duration+scenario['latency_ns'] and order['ack_ns']==order['arrival_ns']+scenario['ack_delay_ns'], 'order/ack latency')
                check(oid in seen_ledger, 'missing ledger')
            check(all(sim[k]==closing[k] for k in ['cash','inventory','fees','filled']), 'closing conservation')
            check(sim['unfilled']==intent['quantity']-closing['filled'], 'parent residual')
            shortfall=(1 if intent['side']=='buy' else -1)*(2*closing['notional']-closing['filled']*benchmark)+2*closing['fees']+2*sim['unfilled']*intent['penalty_ticks']
            check(shortfall==sim['shortfall2'], 'signed shortfall')
            check(all(row[k]==sim[k] for k in ['filled','unfilled','cash','inventory','fees','shortfall2']), 'row differs from trace')
            check(row['cost_ticks_per_lot']==shortfall/(2*intent['quantity']) and row['completion']==sim['filled']/intent['quantity'], 'normalized cost/completion')
            check(not sql['violations'] and sql['fills']==len(sim['fills'])==row['sql_fills'] and sql['transitions']==len(sim['ledger'])==row['sql_transitions'],'saved SQL status')
            if batch_session is not None and slug!=batch_session:sql_flush()
            batch_session=slug;sql_batch.append((sim,sql))
            rows.append(row); totals.update(trials=1,fills=len(sim['fills']),ledger_transitions=len(sim['ledger']))
            c=compute[(row['split'],row['policy'],row['compute_mode'])];c.update(trials=1,missed_decisions=row['missed_decisions'],filled=sim['filled'],unfilled=sim['unfilled'],quantity=intent['quantity'],shortfall2=shortfall,late_expired_orders=sum(o['arrival_ns']>intent['deadline_ns'] for o in sim['orders']))
            if line_no%10000==0:print(json.dumps({'phase':'trace_accounting','checked_trials':line_no,'sql_batches':sql_reruns}),flush=True)
    sql_flush()
    check(rows==result['rows'], 'result rows differ from trace labels')
    excluded=set()
    for exclusion in result['excluded']:
        expanded=set()
        for cell in grid:
            policy,side,size,deadline,world=cell
            if policy not in exclusion['policies']:continue
            if any(k in exclusion and exclusion[k]!=v for k,v in [('side',side),('size',size),('deadline_s',deadline),('scenario',world)]):continue
            expanded.add((exclusion['session'],)+cell)
        check(len(expanded)==exclusion['attempt_count'] and not expanded&excluded, 'excluded trial registry')
        excluded.update(expanded)
    check(not observed&excluded and observed|excluded==expected, 'attempts not exactly conserved')
    check(result['attempts']==len(expected)==84800 and result['executed']==len(rows) and result['excluded_trials']==len(excluded), 'reported attempt counts')
    check(result['eligible_window_attempts']==209*len(grid), 'eligible attempt count')
    condition_groups=collections.defaultdict(list)
    for w in windows.values():condition_groups[(w['split'],w['opening_utc_day'],w['coin'],w.get('condition') or 'unclassified',w['status'])].append(w)
    condition_coverage=[dict(zip(('split','opening_day','coin','condition','status'),key))|{'windows':len(v)} for key,v in sorted(condition_groups.items())]
    check(condition_coverage==result['condition_coverage'],'source coverage strata')
    executed_groups=collections.defaultdict(set)
    for r in rows:executed_groups[(r['split'],r['opening_day'],r['coin'],r['condition'])].add(r['session'])
    executed_coverage=[dict(zip(('split','opening_day','coin','condition'),key))|{'windows':len(v)} for key,v in sorted(executed_groups.items())]
    check(executed_coverage==result['executed_condition_coverage'],'executed coverage strata')
    dimensions=('split','policy','scenario','execution_scenario','compute_mode','side','size','deadline_s','condition')
    for name,dims in [('summary',dimensions),('asset_summary',dimensions+('coin',)),('day_summary',dimensions+('opening_day',))]:check(summary(rows,dims)==result[name],name+' differs')
    print(json.dumps({'phase':'trace_registry_and_summaries_checked','trials':len(rows),'excluded':len(excluded),'sql_batches':sql_reruns}),flush=True)
    indexed={(r['session'],r['policy'],r['scenario'],r['side'],r['size'],r['deadline_s']):r for r in rows}
    compute_pairs=collections.defaultdict(list)
    for r in rows:
        if r['compute_mode']!='zero_compute_baseline':continue
        measured=indexed.get((r['session'],r['policy'],r['execution_scenario']+'/measured_development_compute',r['side'],r['size'],r['deadline_s']))
        if measured is not None:compute_pairs[(r['split'],r['policy'],r['execution_scenario'])].append((r,measured))
    compute_pair_effects=[]
    for key,pairs in sorted(compute_pairs.items()):
        compute_pair_effects.append(dict(zip(('split','policy','execution_scenario'),key))|{
            'matched_trials':len(pairs), 'windows':len({a['session'] for a,b in pairs}),
            'mean_measured_minus_zero_cost_ticks_per_lot':statistics.fmean(b['cost_ticks_per_lot']-a['cost_ticks_per_lot'] for a,b in pairs),
            'mean_measured_minus_zero_completion':statistics.fmean(b['completion']-a['completion'] for a,b in pairs),
            'cost_changed_trials':sum(a['shortfall2']!=b['shortfall2'] for a,b in pairs),
            'completion_changed_trials':sum(a['filled']!=b['filled'] for a,b in pairs)})
    window_info={r['session']:r for r in rows}; bootstrap_cache={}; reviewed_cells=0; statuses=collections.Counter()
    for cell in result['stability']:
        split,condition,a,b,side,size,deadline=[cell[k] for k in ['split','condition','a','b','side','size','deadline_s']]
        eligible=sorted(s for s,r in window_info.items() if r['split']==split and (condition=='all' or r['condition']==condition))
        common=[s for s in eligible if all((s,p,world,side,size,deadline) in indexed for world in worlds for p in [a,b])]
        check(cell['common_windows']==len(common) and cell['unmatched_windows']==[s for s in eligible if s not in common],'paired common-window composition')
        means=[]; unresolved=False
        check([x['scenario'] for x in cell['scenarios']]==worlds, 'stability world coverage')
        for saved,world in zip(cell['scenarios'],worlds):
            values=tuple(indexed[(s,a,world,side,size,deadline)]['cost_ticks_per_lot']-indexed[(s,b,world,side,size,deadline)]['cost_ticks_per_lot'] for s in common)
            by_day=collections.defaultdict(list)
            for s,v in zip(common,values):by_day[window_info[s]['opening_day']].append(v)
            if values not in bootstrap_cache:
                if not values:interval=None
                elif min(values)==max(values):interval=[values[0],values[0]]
                else:
                    rng=random.Random(1234); sampled=[statistics.fmean(rng.choices(values,k=len(values))) for _ in range(reg['bootstrap_samples'])]
                    interval=[quantile(sampled,.025),quantile(sampled,.975)]
                bootstrap_cache[values]=interval
            interval=bootstrap_cache[values];mean=statistics.fmean(values) if values else None
            check(saved['windows']==len(common) and saved['days']==len(by_day) and saved['difference_a_minus_b']==mean and saved['window_bootstrap95']==interval, 'paired statistic/bootstrap')
            check(saved['day_means']=={day:statistics.fmean(v) for day,v in sorted(by_day.items())} and saved['day_interval'] is None,'day uncertainty')
            if mean is not None:means.append(mean)
            unresolved |= interval is None or interval[0]<=0<=interval[1]
        reversal=bool(means) and min(means)<0<max(means); status='unresolved' if unresolved else 'reversal' if reversal else 'stable'
        check(cell['status']==status and cell['mean_sign_reversal']==reversal,'stability classification');reviewed_cells+=1;statuses[(split,condition,status)]+=1
        if reviewed_cells%100==0:print(json.dumps({'phase':'paired_uncertainty','checked_cells':reviewed_cells}),flush=True)
    expected_cells=2*3*math.comb(len(plan['policies']),2)*len(plan['sides'])*len(plan['quantities_lots'])*len(plan['deadlines_seconds'])
    check(reviewed_cells==expected_cells,'stability cell count')
    check(any('one confirmation' in limit for limit in result['limits']),'confirmation-day limitation missing')
    artifact_bytes=sum(p.stat().st_size for p in study.iterdir() if p.is_file())
    check(artifact_bytes<=reg['output_limit_bytes']==1073741824,'study artifact output exceeds bound')
    report={'status':'pass','method':'streamed saved traces; independent integer fill/ledger/prefix/benchmark accounting; reconstructed complete attempt registry and summaries; independent paired-window means/bootstrap/statuses; optional exact per-window DuckDB reexecution; no strategies or clock measurements',
        'artifact_sha256':{n:digest(study/n) for n in ['registration.json','calibration.json','results.json','traces.jsonl']},
        'review_script_sha256':digest(Path(__file__)),'artifact_bytes':artifact_bytes,'counts':dict(totals),'attempts':len(expected),'excluded_trials':len(excluded),'executed_windows':len({r['session'] for r in rows}),'sql_window_batches_reexecuted':sql_reruns,'stability_cells':reviewed_cells,
        'statuses':[{'split':k[0],'condition':k[1],'status':k[2],'comparisons':v} for k,v in sorted(statuses.items())],
        'calibrated_durations_ns':durations,'compute_impacts':[dict(zip(('split','policy','compute_mode'),k))|dict(v) for k,v in sorted(compute.items())],
        'paired_compute_effects':compute_pair_effects,
        'source_condition_coverage':dict(collections.Counter(str((w['split'],w.get('condition'))) for w in windows.values() if w['status']=='included')),
        'executed_condition_coverage':executed_coverage,
        'limits':['snapshot archive cannot identify exchange-message continuity, network delay or queue identity','ordinary/stress are operational quote/depth proxies','one confirmation opening day; correlated window bootstrap conditional only','development p99 is fixed desktop work sensitivity, not a calibrated runtime distribution','negative signed cost is benchmark-relative execution, not strategy profit','artifact/source checks cannot prove absence of unseen prior trials']}
    output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':'pass','trials':len(rows),'attempts':len(expected),'excluded':len(excluded),'sql_batches':sql_reruns,'stability_cells':reviewed_cells,'output':str(output)}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--sql',action='store_true');args=p.parse_args()
    root=args.root.resolve();sys.path.insert(0,str(root))
    audit(root,root/'evidence/prospective-study-v1',root/'data/prospective-v2/sessions-v3',root/'evidence/completion-study-review.json',args.sql)
