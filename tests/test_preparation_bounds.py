"""Oversized compressed archives must be refused before Python row expansion."""
import hashlib
import importlib.util
import json
from pathlib import Path

import duckdb
import pytest

SPEC=importlib.util.spec_from_file_location('bounded_prepare',Path(__file__).parents[1]/'tools/prepare_prospective.py')
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize('rows,sessions',[(1_000_001,1),(10_001,10_001)])
def test_count_admission_precedes_bulk_materialization_and_output(monkeypatch,tmp_path,rows,sessions):
    archive=tmp_path/'compressed.parquet'
    slug="'btc-updown-15m-' || CAST(1787271300 + range % "+str(sessions)+" AS VARCHAR)"
    with duckdb.connect() as con:
        con.execute("SET threads=1")
        query="SELECT "+slug+" AS market_slug,'btc' AS coin,'15m' AS contract_length,'token' AS token_id," \
              "TIMESTAMP '2026-08-21 01:50:00' AS market_end_at,TIMESTAMP '2026-08-21 01:36:00' AS captured_at," \
              "[0.49] AS bid_prices,[100.0] AS bid_sizes,[0.50] AS ask_prices,[100.0] AS ask_sizes,'Up' AS outcome FROM range("+str(rows)+")"
        con.execute("COPY ("+query+") TO '"+str(archive).replace("'","''")+"' (FORMAT PARQUET,COMPRESSION ZSTD)")
        assert con.execute("SELECT count(*),count(DISTINCT market_slug) FROM read_parquet(?)",[str(archive)]).fetchone()==(rows,sessions)
    plan=json.loads((Path(__file__).parents[1]/'docs/PROSPECTIVE_PLAN.json').read_text())
    plan['source']['sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
    plan_path=tmp_path/'plan.json';plan_path.write_text(json.dumps(plan))
    known=tmp_path/'known.json';known.write_text('{"known_ids":[]}')
    real_connect=duckdb.connect;connections=[]

    class Guarded:
        def __init__(self):self.connection=real_connect();self.closed=False;connections.append(self)
        def execute(self,*args,**kwargs):self.connection.execute(*args,**kwargs);return self
        def fetchone(self):return self.connection.fetchone()
        def fetchall(self):raise AssertionError('oversized archive reached bulk Python materialization')
        def close(self):self.connection.close();self.closed=True
        def __enter__(self):return self
        def __exit__(self,*args):self.close()

    monkeypatch.setattr(duckdb,'connect',Guarded)
    out=tmp_path/'sessions'
    with pytest.raises(ValueError,match='session/row bounds'):
        MODULE.prepare(archive,out,plan_path,known)
    assert connections and all(c.closed for c in connections)
    assert not out.exists()
