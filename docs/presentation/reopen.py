"""Verify transferred bytes, independently recompute tiny accounts, optionally native-replay."""
from pathlib import Path
import hashlib,json,math,subprocess,sys
P=Path(__file__).resolve().parent
manifest=json.loads((P/'MANIFEST.json').read_text())
for n,h in manifest.items():assert hashlib.sha256((P/n).read_bytes()).hexdigest()==h,n
rows=[]
for latency in (0,55):
 p=P/f'latency-{latency}';r=json.loads((p/'result.json').read_text());c=json.loads((p/'config.json').read_text());assert hashlib.sha256((p/'input.csv').read_bytes()).hexdigest()==c['input_sha256'];notional=sum(f['price']*f['quantity'] for f in r['fills']);fees=sum((f['price']*f['quantity']*c['scenario']['fee_ppm']+999999)//1000000 for f in r['fills']);quantity=sum(f['quantity'] for f in r['fills']);assert (r['cash'],r['fees'],r['inventory'],r['filled'])==(notional-fees,fees,-quantity,quantity);assert r['cash']==(695 if latency==0 else 693);assert json.loads((p/'sql.json').read_text())['violations']==[]
 if '--native' in sys.argv:
  out=subprocess.run([sys.executable,'-B','-m','queuecraft','verify',str(p)],text=True,capture_output=True,check=True);assert json.loads(out.stdout)['replay']=='exact'
 rows.append({'latency_ms':latency,'cash':r['cash'],'fees':fees,'filled':quantity,'nativeReplay':'--native' in sys.argv})
print(json.dumps({'allMemberHashes':len(manifest),'independentIntegerAccount':rows}))
