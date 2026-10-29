"""Measured public API overhead, with enough decision samples for tail estimates."""
from dataclasses import asdict
import hashlib,json,platform,resource,statistics,time
from pathlib import Path
from queuecraft import Intent,Observation,Scenario,run
from queuecraft.policies import POLICIES,TWAP
from queuecraft.sdk import events_from_csv


def percentiles(samples):
    values=sorted(samples)
    return {'samples':len(values),'p50_ns':values[len(values)//2],'p95_ns':values[int(len(values)*.95)],'p99_ns':values[int(len(values)*.99)],'p999_ns':values[min(len(values)-1,int(len(values)*.999))],'mean_ns':statistics.mean(values)}


def main():
    source=Path('examples/recorded.csv')
    data=source.read_text()
    events=events_from_csv(data)
    first=next(e for e in events if e.kind=='S')
    start=first.receive_ns
    intent=Intent('buy',25,start,start+5_000_000_000)
    bids=tuple(sorted(((p,q) for s,p,q in first.levels if s=='B'),reverse=True))
    asks=tuple(sorted((p,q) for s,p,q in first.levels if s=='A'))
    observation=Observation(start,-1,start,first.index,bids,asks,True,0,25,0,intent,Scenario())
    policies={}
    for name,cls in POLICIES.items():
        obj=cls()
        for _ in range(100):obj.decide(observation)
        samples=[]
        for _ in range(10_000):
            before=time.perf_counter_ns();obj.decide(observation);samples.append(time.perf_counter_ns()-before)
        policies[name]=percentiles(samples)
    samples=[]
    for _ in range(200):
        before=time.perf_counter_ns();run(events,intent,TWAP());samples.append(time.perf_counter_ns()-before)
    report={'platform':platform.platform(),'python':platform.python_version(),'clock':'perf_counter_ns','input_sha256':hashlib.sha256(data.encode()).hexdigest(),'policy_decide':policies,'python_end_to_end':percentiles(samples),'process_peak_rss_bytes_macos':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'limits':['desktop warm-process measurements, not colocated latency','end-to-end200samples does not support p999 inference','Python/native boundary, snapshots and policy overhead included in end-to-end','no controlled CPU frequency or isolated cores','no comparison to HftBacktest']}
    target=Path('evidence/python-benchmark-v1.json')
    with target.open('x') as output:json.dump(report,output,indent=2);output.write('\n')
    print(json.dumps(report))


if __name__=='__main__':main()
