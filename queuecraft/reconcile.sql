-- Integer money/timestamps. Every join and window is partitioned by run_id.
WITH per_order AS (
 SELECT o.run_id,o.order_id,
  COALESCE(SUM(f.quantity),0)::HUGEINT AS filled,
  COALESCE(SUM(CASE WHEN f.side='buy' THEN -f.notional-f.fee ELSE f.notional-f.fee END),0)::HUGEINT AS cash_delta,
  COALESCE(SUM(CASE WHEN f.side='buy' THEN f.quantity ELSE -f.quantity END),0)::HUGEINT AS inventory_delta,
  COALESCE(SUM(f.fee),0)::HUGEINT AS fee_delta
 FROM orders o LEFT JOIN fills f USING(run_id,order_id)
 GROUP BY o.run_id,o.order_id
), expected AS (
 SELECT l.*,
  SUM(p.cash_delta) OVER w AS expected_cash,
  SUM(p.inventory_delta) OVER w AS expected_inventory,
  SUM(p.fee_delta) OVER w AS expected_fees,
  SUM(p.filled) OVER w AS expected_filled
 FROM ledger l JOIN per_order p USING(run_id,order_id)
 WINDOW w AS(PARTITION BY l.run_id ORDER BY l.step ROWS UNBOUNDED PRECEDING)
), totals AS (
 SELECT r.run_id,COALESCE(SUM(f.quantity),0)::HUGEINT AS filled,
  COALESCE(SUM(f.notional),0)::HUGEINT AS notional,
  COALESCE(SUM(CASE WHEN f.side='buy' THEN -f.notional-f.fee ELSE f.notional-f.fee END),0)::HUGEINT AS cash,
  COALESCE(SUM(CASE WHEN f.side='buy' THEN f.quantity ELSE -f.quantity END),0)::HUGEINT AS inventory,
  COALESCE(SUM(f.fee),0)::HUGEINT AS fees
 FROM runs r LEFT JOIN fills f USING(run_id) GROUP BY r.run_id
)
SELECT run_id,'ledger' AS kind,order_id AS id FROM expected
WHERE cash!=expected_cash OR inventory!=expected_inventory OR fees!=expected_fees OR filled!=expected_filled
UNION ALL
SELECT f.run_id,'fill_arithmetic',f.fill_id FROM fills f JOIN runs r USING(run_id)
WHERE f.price::HUGEINT*f.quantity!=f.notional
 OR f.fee!=(f.notional::HUGEINT*r.fee_ppm+999999)//1000000
 OR f.quantity<=0 OR f.price<=0
UNION ALL
SELECT f.run_id,'fill_timing',f.fill_id FROM fills f LEFT JOIN orders o USING(run_id,order_id) JOIN runs r USING(run_id)
WHERE o.order_id IS NULL OR f.arrival_ns!=o.arrival_ns
 OR o.observation_ns>o.decision_ns OR o.decision_ns>o.arrival_ns
 OR f.recorded_receive_ns>f.arrival_ns OR f.arrival_ns>r.deadline_ns OR f.arrival_ns>r.recording_end_ns
 OR f.side NOT IN('buy','sell') OR f.side!=r.side
UNION ALL
SELECT o.run_id,'order_size',o.order_id FROM orders o LEFT JOIN per_order p USING(run_id,order_id)
WHERE p.filled>o.quantity OR p.filled!=o.filled
UNION ALL
SELECT run_id,'duplicate_fill',fill_id FROM fills GROUP BY run_id,fill_id HAVING count(*)!=1
UNION ALL
SELECT run_id,'duplicate_ledger',order_id FROM ledger GROUP BY run_id,order_id HAVING count(*)!=1
UNION ALL
SELECT o.run_id,'missing_ledger',o.order_id FROM orders o LEFT JOIN ledger l USING(run_id,order_id)
WHERE (o.status!='canceled' OR o.filled>0) AND l.order_id IS NULL
UNION ALL
SELECT o.run_id,'canceled_fill',o.order_id FROM orders o JOIN per_order p USING(run_id,order_id)
WHERE o.status='canceled' AND(p.filled!=0 OR o.filled!=0)
UNION ALL
SELECT l.run_id,'orphan_ledger',l.order_id FROM ledger l LEFT JOIN orders o USING(run_id,order_id)
WHERE o.order_id IS NULL
UNION ALL
SELECT l.run_id,'ledger_timing',l.order_id FROM ledger l JOIN orders o USING(run_id,order_id)
WHERE l.time_ns!=o.arrival_ns
UNION ALL
SELECT run_id,'ledger_step',min(step) FROM ledger GROUP BY run_id
HAVING min(step)!=0 OR max(step)!=count(*)-1 OR count(DISTINCT step)!=count(*)
UNION ALL
SELECT run_id,'duplicate_order',order_id FROM orders GROUP BY run_id,order_id HAVING count(*)!=1
UNION ALL
SELECT r.run_id,'closing_totals',0 FROM runs r JOIN totals t USING(run_id)
WHERE r.filled!=t.filled OR r.cash!=t.cash OR r.inventory!=t.inventory OR r.fees!=t.fees
UNION ALL
SELECT run_id,'parent_conservation',0 FROM runs WHERE filled+unfilled!=quantity
UNION ALL
SELECT r.run_id,'shortfall_units',0 FROM runs r JOIN totals t USING(run_id)
WHERE r.shortfall2!=(CASE WHEN r.side='buy' THEN 1 ELSE -1 END)*(2*t.notional-t.filled*r.benchmark2::HUGEINT)+2*t.fees+2*r.unfilled::HUGEINT*r.penalty_ticks
UNION ALL
SELECT run_id,'missing_orders_field',coalesce(order_id,-1) FROM orders WHERE order_id IS NULL OR observation_ns IS NULL OR decision_ns IS NULL OR arrival_ns IS NULL OR quantity IS NULL OR filled IS NULL OR status IS NULL
UNION ALL
SELECT run_id,'missing_fills_field',coalesce(fill_id,-1) FROM fills WHERE fill_id IS NULL OR order_id IS NULL OR price IS NULL OR quantity IS NULL OR notional IS NULL OR fee IS NULL OR arrival_ns IS NULL OR recorded_receive_ns IS NULL OR side IS NULL
UNION ALL
SELECT run_id,'missing_ledger_field',coalesce(order_id,-1) FROM ledger WHERE step IS NULL OR order_id IS NULL OR time_ns IS NULL OR cash IS NULL OR inventory IS NULL OR fees IS NULL OR filled IS NULL
UNION ALL
SELECT run_id,'missing_runs_field',coalesce(run_id,-1) FROM runs WHERE fee_ppm IS NULL OR deadline_ns IS NULL OR recording_end_ns IS NULL OR side IS NULL OR quantity IS NULL OR filled IS NULL OR unfilled IS NULL OR cash IS NULL OR inventory IS NULL OR fees IS NULL OR benchmark2 IS NULL OR penalty_ticks IS NULL OR shortfall2 IS NULL;
