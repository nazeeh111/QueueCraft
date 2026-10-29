"""Independent DuckDB integer joins and windows, with bounded CSV batching."""
from __future__ import annotations
import csv
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence
from .sdk import Simulation


def reconcile_many(results: Sequence[Simulation]) -> list[dict]:
    import duckdb
    if not results:return []
    reports=[{'engine':'DuckDB','version':duckdb.__version__,'transitions':len(r.ledger),'fills':len(r.fills),'violations':[]}for r in results]
    fields={
      'orders':('order_id','observation_ns','decision_ns','arrival_ns','quantity','filled','status'),
      'fills':('fill_id','order_id','price','quantity','notional','fee','arrival_ns','recorded_receive_ns','side'),
      'ledger':('step','order_id','time_ns','cash','inventory','fees','filled'),
      'runs':('fee_ppm','deadline_ns','side','quantity','filled','unfilled','cash','inventory','fees','benchmark2','penalty_ticks','shortfall2')}
    con=duckdb.connect(':memory:',config={'threads':1,'memory_limit':'512MB'})
    try:
      with TemporaryDirectory(prefix='queuecraft-sql-') as folder:
        for table,names in fields.items():
          path=Path(folder)/(table+'.csv')
          with path.open('w',newline='') as output:
            writer=csv.writer(output,lineterminator='\n');writer.writerow(('run_id',)+names)
            for run_id,result in enumerate(results):
              if table=='runs':
                row={**result.as_dict(),**result.intent.__dict__,**result.scenario.__dict__}
                writer.writerow([run_id]+[row[name] for name in names])
              else:
                for row in getattr(result,table):writer.writerow([run_id]+[row[name]for name in names])
          types={name:('VARCHAR'if name in {'side','status'}else 'BIGINT')for name in ('run_id',)+names}
          con.read_csv(str(path),header=True,columns=types).create_view(table)
        for run_id,kind,identifier in con.execute(files('queuecraft').joinpath('reconcile.sql').read_text()).fetchall():
          reports[run_id]['violations'].append([kind,identifier])
    finally:con.close()
    return reports


def reconcile(result: Simulation) -> dict:
    return reconcile_many([result])[0]
