import hashlib
import json
import random
from types import SimpleNamespace
import pytest
from queuecraft import CSVEvents, Event, Intent, OrderRequest, Scenario, stream, run
from queuecraft.sdk import HEADER, events_from_csv
from queuecraft.policies import Immediate, TWAP
from batch_reference import batch_run
import batch_reference


def events(n=30, spacing=1):
    return [Event(i,-1,i//spacing,'S',(('B',100+i%3,100000),('A',104+i%3,100000))) for i in range(n)]


class Cancel:
    def decide(self,o):
        return OrderRequest(min(1,o.remaining), (1,) if o.now_ns % 2 else ())


@pytest.mark.parametrize('seed',range(40))
def test_exact_batch_result_and_event_order(seed,monkeypatch):
    rng=random.Random(seed)
    source=events(30,rng.randint(1,4))
    intent=Intent('buy' if seed%2 else 'sell',3,3,15,1)
    scenario=Scenario(latency_ns=rng.randrange(5),observation_delay_ns=rng.randrange(4),ack_delay_ns=rng.randrange(5),
                      cancel_latency_ns=rng.randrange(4),tie='arrival_first' if seed%2 else 'recorded_first',
                      missed_decision_every=seed%5,policy_duration_ns=seed%3,fee_ppm=seed*100,liquidity_ppm=500000)
    policy=[Immediate,TWAP,Cancel][seed%3]
    order=[]
    pop=batch_reference.heapq.heappop
    def capture(heap):
        row=pop(heap)
        order.append((row[0],row[1],row[3],row[4].index if row[3] in {'market','observe'} else row[4]))
        return row
    with monkeypatch.context() as patch:
        patch.setattr(batch_reference,'heapq',SimpleNamespace(heappush=batch_reference.heapq.heappush,heappop=capture))
        expected=batch_run(source,intent,policy(),scenario,recording_end_ns=40,trace_books=True)
    replay=stream(iter(source),intent,policy(),scenario,recording_end_ns=40,trace_books=True,collect=True)
    records=list(replay)
    assert replay.status=='complete',records[-1]
    assert replay.result.as_dict()==expected.as_dict()
    actual=[(r['time_ns'],r['priority'],r['kind'],r['data'].get('event') if r['kind'] in {'market','observe'} else r['data'].get('order_id')) for r in records[:-1]]
    assert actual==order


def test_bounded_prefix_and_noncollection():
    counts=[0]
    class Prefix:
        def decide(self,o):
            assert counts[0] <= 7
            return OrderRequest(o.remaining)
    def source():
        for e in events(10000):
            counts[0]+=1
            yield e
    replay=stream(source(),Intent('buy',1,5,5,1),Prefix(),Scenario(observation_delay_ns=5),recording_end_ns=10000)
    for record in replay: pass
    assert replay.status=='complete'
    assert replay.result.filled==1 and replay.result.fills==[] and replay.result.orders==[]
    assert replay.stats['peak_pending_observations']<=6
    assert replay.stats['peak_active_orders']==1


def test_incomplete_and_close():
    def broken():
        yield events(1)[0]
        raise RuntimeError('source broke')
    replay=stream(broken(),Intent('buy',1,0,0),Immediate(),recording_end_ns=10)
    assert list(replay)[-1]['kind']=='incomplete'
    assert replay.result is None and str(replay.exception)=='source broke'
    with pytest.raises(RuntimeError,match='source broke'):
        run(broken(),Intent('buy',1,0,0),Immediate(),recording_end_ns=10)
    replay=stream(iter(events(20,20)),Intent('buy',1,0,0),Immediate(),recording_end_ns=10,max_pending_events=3)
    assert list(replay)[-1]['kind']=='incomplete'
    assert replay.stats['peak_pending_events']==3
    closed=[]
    def source():
        try: yield from events(3)
        finally: closed.append(True)
    replay=stream(source(),Intent('buy',1,0,0),Immediate(),recording_end_ns=10)
    next(replay);replay.close()
    assert closed==[True] and replay.status=='closed' and replay.result is None


def test_source_single_owner_and_detachment():
    from concurrent.futures import ThreadPoolExecutor
    class OnePass:
        def __init__(self): self.calls=0;self.index=0;self.closed=0
        def __iter__(self):
            self.calls+=1
            assert self.calls==1
            return self
        def __next__(self):
            if self.index==5:raise StopIteration
            e=events(5)[self.index];self.index+=1;return e
        def close(self): self.closed+=1
    src=OnePass();replay=stream(src,Intent('buy',1,0,0),Immediate(),recording_end_ns=10,trace_books=True,collect=True)
    first=next(replay);first['data'].clear()
    with ThreadPoolExecutor(1) as pool:
        with pytest.raises(RuntimeError,match='consuming thread'):pool.submit(next,replay).result()
    list(replay);replay.close()
    assert src.closed==1 and replay.result.filled==1


def test_csv_exact_and_late_lexical_failure(tmp_path):
    path=tmp_path/'input.csv';data=HEADER+''.join(e.csv()[len(HEADER):] for e in events(8))
    path.write_text(data)
    source=CSVEvents(path)
    assert tuple(source)==events_from_csv(data)
    assert source.complete and source.sha256==hashlib.sha256(data.encode()).hexdigest()
    path.write_text(data+'8,-1,8,S,B,+100,10000\n8,-1,8,S,A,104,10000\n')
    replay=stream(CSVEvents(path),Intent('buy',1,0,0),Immediate(),recording_end_ns=20)
    records=list(replay)
    assert records[-1]['kind']=='incomplete' and len(records)>3 and replay.result is None
    path.write_text(HEADER+'0,-1,0,S,B,'+'0'*5000+'1,1\n')
    with pytest.raises(ValueError,match='row exceeds'):list(CSVEvents(path))


@pytest.mark.parametrize('tie',['recorded_first','arrival_first'])
def test_gap_coverage_and_every_registered_policy(tie):
    from queuecraft.policies import POLICIES
    source=events(8)
    source[2]=Event(2,-1,2,'G',(('B',1,0),))
    for factory in POLICIES.values():
        scenario=Scenario(observation_delay_ns=1,latency_ns=1,ack_delay_ns=2,tie=tie)
        intent=Intent('buy',2,1,12,1)
        expected=batch_run(source,intent,factory(),scenario,recording_end_ns=8)
        replay=stream(source,intent,factory(),scenario,recording_end_ns=8,collect=True)
        list(replay)
        assert replay.result.as_dict()==expected.as_dict()


def test_cli_exclusive_output_and_failure(tmp_path,monkeypatch):
    from queuecraft.cli import main
    from queuecraft import stream_cli
    source=tmp_path/'input.csv';source.write_text(HEADER+''.join(e.csv()[len(HEADER):] for e in events(8)))
    out=tmp_path/'output.ndjson'
    argv=['stream',str(source),'--out',str(out),'--start-ns','0','--deadline-ns','5','--interval-ns','1','--recording-end-ns','10','--size','1']
    with monkeypatch.context() as patch:
        patch.setattr(stream_cli.os,'fsync',lambda _:(_ for _ in ()).throw(OSError('late failure')))
        with pytest.raises(SystemExit):main(argv)
    assert not out.exists() and list(tmp_path.glob('.*.tmp'))==[]
    assert main(argv)==0
    records=[json.loads(line) for line in out.read_text().splitlines()]
    assert records[-1]['kind']=='complete' and records[-1]['input']['complete']
    original=out.read_bytes()
    with pytest.raises(SystemExit):main(argv)
    assert out.read_bytes()==original
    out.unlink()
    assert main(argv+['--max-pending-events','1','--observation-ns','5'])==2
    records=[json.loads(line) for line in out.read_text().splitlines()]
    assert records[-1]['kind']=='incomplete' and records[-1]['input']['sha256'] is None
    assert list(tmp_path.glob('.*.tmp'))==[]


def test_cleanup_failure_is_incomplete_and_close_once():
    class Source:
        def __init__(self):self.iterator=iter(events(3));self.closes=0
        def __iter__(self):return self
        def __next__(self):return next(self.iterator)
        def close(self):self.closes+=1;raise OSError('close failure')
    src=Source();replay=stream(src,Intent('buy',1,0,0),Immediate(),recording_end_ns=10)
    assert list(replay)[-1]['kind']=='incomplete'
    replay.close()
    assert src.closes==1 and replay.result is None
