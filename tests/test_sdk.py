from dataclasses import replace
import time
import unittest

from queuecraft import Event, Intent, Observation, OrderRequest, Scenario, run
from queuecraft.policies import Immediate, POLICIES, TWAP
from queuecraft.sdk import events_from_csv
from queuecraft.reconcile import reconcile

NS = 1_000_000_000


def stream(n=12):
    return tuple(Event(i, -1, i*NS, "S", (("B", 100, 100_000), ("A", 102, 100_000))) for i in range(n))


class CancelReplace:
    def decide(self, o):
        if o.now_ns == 0:
            return OrderRequest(o.remaining)
        if o.now_ns == NS:
            return OrderRequest(cancel=(1,))
        return OrderRequest(o.remaining)


class SDKTests(unittest.TestCase):
    def test_buy_sell_exact_account_and_sql_each_transition(self):
        for side in ("buy", "sell"):
            r = run(stream(), Intent(side, 100, 0, 5*NS), TWAP(), Scenario(fee_ppm=1000), recording_end_ns=11*NS)
            self.assertEqual(r.filled, 100)
            self.assertEqual(r.inventory, 100 if side == "buy" else -100)
            self.assertEqual(reconcile(r)["violations"], [])
            self.assertGreater(len(r.ledger), 1)

    def test_prefix_isolation_all_registered_policies(self):
        initial = stream()
        changed = tuple(replace(e, levels=(("B", 200, 100_000), ("A", 210, 100_000))) if e.receive_ns > 5*NS else e for e in initial)
        for cls in POLICIES.values():
            a = run(initial, Intent("buy", 100, 0, 10*NS), cls(), Scenario(latency_ns=NS), recording_end_ns=11*NS)
            b = run(changed, Intent("buy", 100, 0, 10*NS), cls(), Scenario(latency_ns=NS), recording_end_ns=11*NS)
            self.assertEqual([d for d in a.decisions if d["time_ns"] <= 5*NS], [d for d in b.decisions if d["time_ns"] <= 5*NS])

    def test_wall_clock_replay_speed_cannot_change_result(self):
        def slowed():
            for e in stream():
                time.sleep(.001)
                yield e
        args = Intent("buy", 100, 0, 5*NS)
        self.assertEqual(run(stream(), args, TWAP(), recording_end_ns=11*NS).as_dict(), run(slowed(), args, TWAP(), recording_end_ns=11*NS).as_dict())

    def test_delayed_observation_prefix_hides_received_but_unavailable_event(self):
        original=stream()
        changed=tuple(replace(e,levels=(("B",200,100_000),("A",202,100_000))) if e.receive_ns==3*NS else e for e in original)
        for cls in POLICIES.values():
            scenario=Scenario(observation_delay_ns=2*NS,latency_ns=NS)
            a=run(original,Intent("buy",100,0,8*NS),cls(),scenario, recording_end_ns=11*NS)
            b=run(changed,Intent("buy",100,0,8*NS),cls(),scenario, recording_end_ns=11*NS)
            self.assertEqual([d for d in a.decisions if d["time_ns"]<5*NS],[d for d in b.decisions if d["time_ns"]<5*NS])
            self.assertTrue(all(d["observed_receive_ns"]+2*NS<=d["time_ns"] for d in a.decisions if d["valid"]))

    def test_tie_order_is_declared_and_can_change_fill_price(self):
        events = (stream()[0], Event(1,-1,NS,"S",(("B",200,100_000),("A",202,100_000))), *stream()[2:])
        a = run(events, Intent("buy", 100, 0, 5*NS), Immediate(), Scenario(latency_ns=NS), recording_end_ns=11*NS)
        b = run(events, Intent("buy", 100, 0, 5*NS), Immediate(), Scenario(latency_ns=NS,tie="arrival_first"), recording_end_ns=11*NS)
        self.assertEqual((a.fills[0]["price"], b.fills[0]["price"]), (202,102))

    def test_ack_delay_reserves_unobserved_fills(self):
        r = run(stream(), Intent("buy",100,0,5*NS),Immediate(),Scenario(ack_delay_ns=3*NS), recording_end_ns=11*NS)
        self.assertEqual(r.decisions[1]["reserved"],100)
        self.assertEqual(r.decisions[1]["remaining"],0)
        self.assertEqual(r.filled,100)

    def test_cancel_and_replace_waits_for_ack_and_arrival(self):
        r=run(stream(),Intent("buy",100,0,10*NS),CancelReplace(),Scenario(latency_ns=3*NS,cancel_latency_ns=0,ack_delay_ns=NS), recording_end_ns=11*NS)
        self.assertEqual(r.orders[0]["status"],"canceled")
        self.assertEqual(r.orders[0]["filled"],0)
        self.assertEqual(r.orders[0]["ack_ns"],2*NS)
        self.assertEqual(r.filled,100)
        self.assertGreaterEqual(r.fills[0]["arrival_ns"],5*NS)
        self.assertEqual(reconcile(r)["violations"],[])

    def test_missed_deadline_declared_noop_and_no_future_rerun(self):
        r=run(stream(),Intent("buy",100,0,5*NS),Immediate(),Scenario(policy_duration_ns=2*NS,decision_budget_ns=NS), recording_end_ns=11*NS)
        self.assertEqual(r.filled,0)
        self.assertEqual(r.shortfall2,2000)
        self.assertTrue(all(d["fallback"]=="noop" for d in r.decisions))

    def test_arrival_after_deadline_expires_and_penalizes_same_parent(self):
        r=run(stream(),Intent("buy",100,0,NS),Immediate(),Scenario(latency_ns=2*NS), recording_end_ns=11*NS)
        self.assertEqual((r.filled,r.unfilled),(0,100))
        self.assertEqual(r.orders[0]["status"],"expired")

    def test_no_fill_beyond_recorded_coverage(self):
        r=run(stream(1),Intent("buy",1,0,5*NS),Immediate(),Scenario(latency_ns=1), recording_end_ns=0)
        self.assertEqual((r.filled,r.unfilled),(0,1))

    def test_append_future_event_does_not_change_earlier_callbacks_or_acks(self):
        # The recorder declared coverage through t=2 before any book message.
        # A quiet prefix and that same prefix plus a later update have identical
        # available information before t=2, including hypothetical fill ACKs.
        short=(stream()[0],)
        extended=(stream()[0],stream()[2])
        extended=(extended[0],replace(extended[1],index=1))
        intent=Intent("buy",25,0,2*NS)
        for cls in POLICIES.values():
            for latency in (0,NS):
                scenario=Scenario(latency_ns=latency)
                a=run(short,intent,cls(),scenario,recording_end_ns=2*NS)
                b=run(extended,intent,cls(),scenario,recording_end_ns=2*NS)
                self.assertEqual([d for d in a.decisions if d["time_ns"]<2*NS],[d for d in b.decisions if d["time_ns"]<2*NS])
                self.assertEqual([f for f in a.fills if f["arrival_ns"]<2*NS],[f for f in b.fills if f["arrival_ns"]<2*NS])
                self.assertEqual([l for l in a.ledger if l["time_ns"]<2*NS],[l for l in b.ledger if l["time_ns"]<2*NS])

    def test_recording_terminal_metadata_is_required_and_checked(self):
        with self.assertRaises(TypeError):
            run(stream(),Intent("buy",25,0,5*NS),TWAP())
        with self.assertRaises(ValueError):
            run(stream(),Intent("buy",25,0,5*NS),TWAP(),recording_end_ns=NS)

    def test_evaluation_benchmark_cannot_change_strategy_information(self):
        intent=Intent("buy",25,0,5*NS)
        for cls in POLICIES.values():
            a=run(stream(),intent,cls(),recording_end_ns=11*NS,benchmark2=202)
            b=run(stream(),intent,cls(),recording_end_ns=11*NS,benchmark2=400)
            self.assertEqual(a.decisions,b.decisions)
            self.assertEqual(a.fills,b.fills)
            self.assertNotEqual(a.shortfall2,b.shortfall2)

    def test_policy_duration_is_counted_in_completion_schedule(self):
        r=run(stream(),Intent("buy",100,0,5*NS),TWAP(),Scenario(policy_duration_ns=NS,latency_ns=NS), recording_end_ns=11*NS)
        self.assertEqual(r.filled,100)

    def test_original_csv_cannot_be_laundered_by_python_reader(self):
        text=stream()[0].csv()
        for bad in (text.rstrip("\n"), text.replace(",102,",",+102,"),text.replace(",102,",',"102",')):
            with self.assertRaises((ValueError,OverflowError)):
                events_from_csv(bad)

    def test_size_and_invalid_books_preserve_limits(self):
        with self.assertRaises(ValueError):
            run(stream(),Intent("buy",1001,0,5*NS),Immediate(), recording_end_ns=11*NS)
        with self.assertRaises(ValueError):
            Scenario(latency_ns=-1)

    def test_sql_detects_nonclosing_error_bad_units_and_future_fill(self):
        from copy import deepcopy
        clean=run(stream(),Intent("buy",100,0,5*NS),TWAP(),Scenario(fee_ppm=1000), recording_end_ns=11*NS)
        for field, value in (("cash",1),("inventory",1),("fees",1)):
            r=deepcopy(clean)
            r.ledger[0][field]+=value
            self.assertTrue(reconcile(r)["violations"])
        r=deepcopy(clean)
        r.fills[0]["notional"]*=1000
        self.assertTrue(any(v[0]=="fill_arithmetic" for v in reconcile(r)["violations"]))
        r=deepcopy(clean)
        r.fills[0]["recorded_receive_ns"]=r.fills[0]["arrival_ns"]+1
        self.assertTrue(any(v[0]=="fill_timing" for v in reconcile(r)["violations"]))
        r=deepcopy(clean)
        r.fills.append(r.fills[0].copy())
        self.assertTrue(any(v[0]=="duplicate_fill" for v in reconcile(r)["violations"]))
        r=deepcopy(clean)
        r.ledger=[]
        self.assertTrue(any(v[0]=="missing_ledger" for v in reconcile(r)["violations"]))
        r=deepcopy(clean)
        r.ledger[-1]["order_id"]=999
        self.assertTrue(any(v[0]=="orphan_ledger" for v in reconcile(r)["violations"]))
        r=deepcopy(clean)
        r.orders[0]["status"]="canceled"
        r.ledger=[]
        self.assertTrue(any(v[0]=="canceled_fill" for v in reconcile(r)["violations"]))

    def test_batched_sql_keeps_overlapping_order_ids_separate(self):
        from queuecraft.reconcile import reconcile_many
        from copy import deepcopy
        a=run(stream(),Intent("buy",25,0,5*NS),TWAP(),Scenario(fee_ppm=1000), recording_end_ns=11*NS)
        b=run(stream(),Intent("sell",100,0,5*NS),TWAP(),Scenario(fee_ppm=2000), recording_end_ns=11*NS)
        clean=reconcile_many([a,b])
        self.assertEqual([r["violations"]for r in clean],[[],[]])
        self.assertEqual(clean,[reconcile(a),reconcile(b)])
        bad=deepcopy(b);bad.ledger[0]["cash"]+=1
        checked=reconcile_many([a,bad])
        self.assertEqual(checked[0]["violations"],[])
        self.assertTrue(checked[1]["violations"])

    def test_sql_missing_fields_are_violations_not_unknown_comparisons(self):
        from copy import deepcopy
        clean=run(stream(),Intent("buy",25,0,5*NS),TWAP(), recording_end_ns=11*NS)
        mutations=[("ledger","cash"),("fills","price"),("orders","observation_ns")]
        for table,field in mutations:
            bad=deepcopy(clean);getattr(bad,table)[0][field]=None
            self.assertTrue(any(v[0]=="missing_"+table+"_field" for v in reconcile(bad)["violations"]))
        for field in ("cash","shortfall2","benchmark2"):
            bad=deepcopy(clean);setattr(bad,field,None)
            self.assertTrue(any(v[0]=="missing_runs_field" for v in reconcile(bad)["violations"]))


if __name__=="__main__":
    unittest.main()
