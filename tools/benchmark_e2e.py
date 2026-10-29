"""Raw snapshot journal through normalization, policy execution and durable export."""
from __future__ import annotations
import hashlib,json,os,platform,resource,statistics,time
from pathlib import Path
from tempfile import TemporaryDirectory
import duckdb
from queuecraft.capture import RawCapture,read_capture
from queuecraft.data import validate_snapshot
from queuecraft.sdk import Event,Intent,events_from_csv,run
from queuecraft.policies import TWAP


def main():
 root=Path(__file__).resolve().parents[1]
 source_paths=['queuecraft/capture.py','queuecraft/data.py','queuecraft/sdk.py','queuecraft/policies.py','tools/benchmark_e2e.py']
 source_hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest()for name in source_paths}
 con=duckdb.connect(':memory:',config={'threads':1})
 raw=root/'data/raw/btc.parquet'
 query="SELECT epoch_ns(captured_at) AS captured_at,bid_prices,bid_sizes,ask_prices,ask_sizes FROM read_parquet(?) WHERE outcome='Up' AND market_slug='btc-updown-5m-1787475900' AND epoch_ns(captured_at)>=1787475903000000000 AND epoch_ns(captured_at)<=1787475934000000000 ORDER BY captured_at"
 names=('captured_at','bid_prices','bid_sizes','ask_prices','ask_sizes')
 messages=[(r[0],json.dumps(dict(zip(names,r)),separators=(',',':')).encode())for r in con.execute(query,[str(raw)]).fetchall()]
 con.close()
 if not messages:raise ValueError('no bounded raw projection')
 times=[];checks=set();total_bytes=sum(len(p)for _,p in messages)
 with TemporaryDirectory(prefix='queuecraft-e2e-')as directory:
  base=Path(directory)
  for sample in range(1000):
   before=time.perf_counter_ns()
   capture_path=base/f'{sample}.qcraw';ledger_path=base/f'{sample}.json'
   with RawCapture(capture_path)as capture:
    for timestamp,payload in messages:capture.append(payload,timestamp)
   events=[]
   previous=None
   for timestamp,payload in read_capture(capture_path):
    if previous is not None and timestamp-previous>5_000_000_000:
     events.append(Event(len(events),-1,previous+5_000_000_001,'G',(('B',1,0),)))
    previous=timestamp
    row=json.loads(payload)
    try:levels=tuple(validate_snapshot(row));kind='S'
    except ValueError:levels=(('B',1,0),);kind='G'
    events.append(Event(len(events),-1,timestamp,kind,levels))
   text=events[0].csv()+''.join(e.csv().split('\n',1)[1]for e in events[1:])
   parsed=events_from_csv(text)
   first=next(e for e in parsed if e.kind=='S')
   result=run(parsed,Intent('buy',25,first.receive_ns,first.receive_ns+5_000_000_000),TWAP(),recording_end_ns=1787475934000000000)
   encoded=json.dumps(result.as_dict(),sort_keys=True,separators=(',',':')).encode()
   with ledger_path.open('xb')as output:output.write(encoded);output.flush();os.fsync(output.fileno())
   checks.add(hashlib.sha256(encoded).hexdigest())
   times.append(time.perf_counter_ns()-before)
   capture_path.unlink();ledger_path.unlink()
 if len(checks)!=1:raise AssertionError('nondeterministic pipeline')
 values=sorted(times)
 report={'status':'pass','samples':1000,'raw_projected_messages_per_operation':len(messages),'raw_projected_bytes_per_operation':total_bytes,'p50_ns':values[499],'p95_ns':values[949],'p99_ns':values[989],'mean_ns':statistics.mean(values),'operations_per_second':1000/(sum(values)/1e9),'peak_process_rss_bytes_macos':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'raw_archive_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'result_sha256':next(iter(checks)),'platform':platform.platform(),'scope':'label-free genuine snapshot JSON projection -> append-only journal+fsync -> CRC restore -> fixed-point normalization -> native parser -> book/observation/policy/IOC/ledger -> JSON export+fsync','limits':['not original exchange wire messages; projected archive snapshots','no network download or SQL analytical audit inside timed operation','1000samples supports empiricalp99 with10upper-tail observations; no p999 inference','shared desktop, filesystem durability via fsync, no physical-device power-loss guarantee']}
 report['source_hashes']=source_hashes
 for name,digest in source_hashes.items():
  if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise ValueError('benchmark source changed')
 with(root/'evidence/e2e-benchmark-v2.json').open('x')as output:output.write(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report))


if __name__=='__main__':main()
