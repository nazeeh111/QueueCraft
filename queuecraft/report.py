"""Portable, accessible evidence views with no network or third-party assets."""
import html
import json


CSS = """
:root{font-family:system-ui,-apple-system,sans-serif;color:#142d42;background:#f5f4ef;line-height:1.6}*{box-sizing:border-box}body{margin:0}main{max-width:1160px;margin:auto;padding:48px 32px}header{border-top:6px solid #175da0;padding:26px 0;border-bottom:1px solid #b9c8ce}h1{font-size:clamp(2rem,5vw,3.7rem);line-height:1.1;letter-spacing:-.04em;margin:12px 0}h2{font-size:1.4rem;margin-top:36px}p{max-width:78ch}.eyebrow{font-family:monospace;text-transform:uppercase;letter-spacing:.14em;color:#175da0}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1px;background:#b9c8ce;border:1px solid #b9c8ce;margin:28px 0}.metric{padding:18px;background:#fff}.value{display:block;font-size:1.9rem;font-variant-numeric:tabular-nums;font-weight:650}.label{font-size:.85rem;color:#465d6d}.notice{border-left:4px solid #a46c19;background:#fff5df;padding:14px 20px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;background:#fff;font-size:.86rem}caption{text-align:left;font-weight:600;margin:12px 0}th,td{padding:10px 13px;border-bottom:1px solid #d7e0e4;text-align:left;white-space:nowrap;font-variant-numeric:tabular-nums}th{background:#e8eef2;color:#264b65}a{color:#164e87}a:focus-visible,summary:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #ab5c00;outline-offset:3px}summary{cursor:pointer;padding:13px 0;color:#164e87}pre{background:#112c40;color:#e5eef6;padding:20px;overflow:auto;font-size:.82rem}code{font-family:ui-monospace,monospace}.controls{display:flex;gap:16px;flex-wrap:wrap;margin:20px 0}label{display:grid;gap:4px}input,select{font:inherit;padding:7px;border:1px solid #718696;border-radius:2px;background:white}footer{margin-top:48px;border-top:1px solid #b9c8ce;padding-top:16px;font-size:.85rem;color:#465d6d}@media(max-width:600px){main{padding:24px 16px}th,td{padding:8px}}
"""


def table(rows, columns, caption):
    heads = "".join(f"<th scope=col>{html.escape(label)}</th>" for _, label in columns)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(row.get(key, '')))}</td>" for key, _ in columns) + "</tr>" for row in rows)
    return f'<div class=scroll><table><caption>{html.escape(caption)}</caption><thead><tr>{heads}</tr></thead><tbody>{body}</tbody></table></div>'


def shell(title, body):
    return f'<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style><main>{body}<footer>QueueCraft 0.1.0 · Local execution research · No order route · Integer accounting</footer></main></html>'


def simulation_report(result, sql):
    i, s = result.intent, result.scenario
    metrics = [(f"{result.filled}/{i.quantity}","Lots completed"),(str(result.shortfall2),"Signed cost, twice-money units"),(str(result.fees),"Fees, money units"),(str(result.unfilled),"Unfinished lots")]
    body = '<header><div class=eyebrow>QueueCraft / Execution record</div><h1>Follow every lot.</h1><p>Inspect the decision prefix, hypothetical arrival, fills and account changes for this exact order.</p></header>'
    body += '<div class=metrics>'+''.join(f'<div class=metric><span class=value>{html.escape(v)}</span><span class=label>{html.escape(k)}</span></div>' for v,k in metrics)+'</div>'
    body += f'<p><strong>{html.escape(result.policy)}</strong> · {i.side} · quantity {i.quantity} lots · modeled latency {s.latency_ns} ns · {s.tie}.</p>'
    body += '<p class=notice>Hypothetical fills consume modeled liquidity. Recorded markets never react to this order. Archive capture times are not exchange timestamps; unknown exchange time remains −1. Scenario assumptions are not calibrated guarantees.</p>'
    body += f'<h2>Replay or change the order</h2><p>This export includes <a href="input.csv">input.csv</a>, <a href="result.json">result.json</a> and <a href="config.json">config.json</a>. Run a fresh order from the CLI, using a new output directory.</p><pre>queuecraft simulate input.csv --size 25 --policy twap --recording-end-ns {result.recording_end_ns} --out changed-order</pre>'
    body += table(result.orders,[("order_id","Order"),("observation_ns","Observed capture ns"),("decision_ns","Decision ns"),("arrival_ns","Arrival ns"),("ack_ns","Acknowledgement ns"),("quantity","Requested lots"),("filled","Filled lots"),("status","Outcome")],"Hypothetical order lifecycle")
    body += table(result.fills,[("order_id","Order"),("event","Recorded event"),("price","Price ticks"),("quantity","Lots"),("notional","Tick × lot"),("fee","Fee"),("exchange_ns","Exchange ns"),("recorded_receive_ns","Capture ns"),("arrival_ns","Arrival ns")],"Modeled fills against recorded depth")
    body += table(result.ledger,[("step","Step"),("time_ns","Arrival ns"),("cash","Cash delta"),("inventory","Inventory lots"),("fees","Cumulative fees"),("filled","Cumulative lots")],"Exact account after every execution")
    body += '<details><summary>Decision prefixes and remaining intent</summary>'+table(result.decisions,[("time_ns","Decision ns"),("event","Observed event"),("quantity","Requested lots"),("remaining","Available intent"),("reserved","In flight"),("fallback","Fallback")],"Policy-visible prefixes")+'</details>'
    body += '<details><summary>Observed book snapshots</summary><p>These levels are recorded state; hypothetical consumption is reflected in subsequent fills, not rewritten into the historical book.</p><pre>'+html.escape("\n".join(result.book_trace))+'</pre></details>'
    body += '<h2>Independent SQL reconciliation</h2><pre>'+html.escape(json.dumps(sql,indent=2))+'</pre>'
    return shell("QueueCraft execution record",body)


def study_report(report):
    counts = {k:sum(s["status"]==k for s in report["stability"]) for k in ("stable","reversal","unresolved")}
    body='<header><div class=eyebrow>QueueCraft / Registered study</div><h1>Where does the ranking hold?</h1><p>Execution-policy comparisons across recorded market windows and declared timing and liquidity assumptions.</p></header>'
    body+='<div class=metrics>'+''.join(f'<div class=metric><span class=value>{v}</span><span class=label>{k}</span></div>' for k,v in [("Executed trials",report["executed"]),("Stable cells",counts["stable"]),("Reversal cells",counts["reversal"]),("Unresolved cells",counts["unresolved"])])+'</div>'
    body+='<p class=notice>Correlated short market windows and imperfect snapshots. The registered UTC-day split and actual day counts limit inference; window bootstrap intervals do not establish independent market-day evidence. A mean sign change may remain unresolved. No profitability or observed queue claim.</p>'
    confirmation=[cell for cell in report["stability"] if cell["split"]=="confirmation"]
    if confirmation:
        unresolved=sum(cell["status"]=="unresolved" for cell in confirmation)
        body+=f'<p><strong>Confirmation: {unresolved} of {len(confirmation)} stratified comparison cells are unresolved.</strong> Cells distinguish policy pair, side, size, deadline and quote/depth group. The metric cards above cover both development and confirmation.</p>'
    if not any(row["condition"]=="ordinary" for row in report["rows"]):
        body+='<p class=notice>The registered initial-spread rule placed every window in one category. There are no ordinary-category windows, so this study cannot compare ordinary and stressed market sessions. The frozen classification is retained.</p>'
    body+='<p>Lower signed cost is better. Cost includes a shared fixed penalty for unfinished lots. Fees are hypothetical constant scenarios, not the venue’s dynamic schedule. <a href="results.json">Full results and registration</a> · <a href="traces.jsonl">Complete executed traces</a></p>'
    body+='<div class=controls><label>Data region<select id=split><option value=confirmation>Confirmation</option><option value=development>Development</option></select></label><label>Search pair, scenario, side or status<input id=filter type=search placeholder="e.g. buy or unresolved"></label></div>'
    rows=[]
    for cell in report["stability"]:
        for scenario in cell["scenarios"]:
            rows.append({**{k:v for k,v in cell.items() if k!="scenarios"},"condition":cell.get("condition","all"),**scenario})
    body+=table(rows,[("split","Region"),("condition","Quote/depth group"),("a","Policy A"),("b","Policy B"),("side","Side"),("size","Lots"),("deadline_s","Deadline s"),("status","Stability"),("scenario","Scenario / compute"),("windows","Windows"),("difference_a_minus_b","A − B cost/lot"),("window_bootstrap95","Window interval")],"Stability map: paired differences in ticks per lot")
    body+='<details><summary>Completion, tail costs, fees and unfinished lots</summary>'+table(report["summary"],[("split","Region"),("policy","Policy"),("scenario","Scenario"),("side","Side"),("size","Lots"),("deadline_s","Deadline s"),("condition","Condition"),("windows","Windows"),("mean_cost","Mean cost"),("p95_cost","95th percentile cost"),("mean_completion","Completion"),("fees","Fees"),("unfilled","Unfinished lots")],"Measured outcomes")+'</details>'
    body+='<details><summary>Retained exclusions</summary><pre>'+html.escape(json.dumps(report["excluded"],indent=2))+'</pre></details>'
    body+='<details><summary>Scope, session days and inference limits</summary><pre>'+html.escape(json.dumps(report.get("limits",[]),indent=2))+'</pre></details>'
    body+='''<script>const split=document.getElementById('split'),filter=document.getElementById('filter');function update(){for(const row of document.querySelector('table').tBodies[0].rows){row.hidden=row.cells[0].textContent!==split.value||!row.textContent.toLowerCase().includes(filter.value.toLowerCase())}}split.addEventListener('change',update);filter.addEventListener('input',update);update()</script>'''
    return shell("QueueCraft stability study",body)
