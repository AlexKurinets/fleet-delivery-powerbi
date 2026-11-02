"""fleetbi command line: init, seed, run, advance, status, dq, kpi, and the model checks."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import timedelta
from pathlib import Path

from . import clock, config, db, pipeline, seed


def _table(rows: list[dict], cols: list[str] | None = None) -> str:
    if not rows:
        return "(no rows)"
    cols = cols or list(rows[0])
    text = [[("" if r[c] is None else str(r[c])) for c in cols] for r in rows]
    widths = [max(len(c), *(len(t[i]) for t in text)) for i, c in enumerate(cols)]
    line = "  ".join(c.ljust(w) for c, w in zip(cols, widths))
    out = [line, "  ".join("-" * w for w in widths)]
    out += ["  ".join(v.ljust(w) for v, w in zip(t, widths)) for t in text]
    return "\n".join(out)


def cmd_init(s, args):
    seed.init_databases(s)
    print(f"databases {s.erp_db} and {s.dw_db} ready on {s.sql_host}:{s.sql_port}")


def cmd_seed(s, args):
    print(json.dumps(seed.seed(s)))


def cmd_run(s, args):
    while True:
        r = pipeline.run(s)
        print(f"run {r.run_id}: {r.status}, {r.affected_dates} dates rebuilt, refresh {r.refresh_status}")
        print(_table(r.dq, ["rule_code", "severity", "breaches", "blocks_refresh"]))
        if not args.loop:
            return 0 if r.status == "succeeded" else 2
        time.sleep(args.interval)


def cmd_advance(s, args):
    now = clock.now(s.state_dir) + timedelta(days=args.days)
    clock.set_now(s.state_dir, now)
    counts = seed.seed(s)
    print(f"clock now {now.isoformat()}; {json.dumps(counts)}")


def cmd_status(s, args):
    conn = db.connect(s, s.dw_db)
    print(f"source clock: {clock.now(s.state_dir).isoformat()}")
    print("\nlast runs")
    print(_table(db.query(conn, "SELECT TOP (5) run_id, status, refresh_status, source_clock_utc, started_utc, "
                                "finished_utc FROM meta.run ORDER BY run_id DESC")))
    print("\ngold row counts")
    print(_table(db.query(conn, """
        SELECT 'fact_delivery_stop' AS [table], COUNT(*) AS [rows], MIN(service_date) AS first_date,
               MAX(service_date) AS last_date FROM gold.fact_delivery_stop
        UNION ALL SELECT 'fact_invoice_line', COUNT(*), MIN(posting_date), MAX(posting_date) FROM gold.fact_invoice_line
        UNION ALL SELECT 'fact_route_trip', COUNT(*), MIN(service_date), MAX(service_date) FROM gold.fact_route_trip
        UNION ALL SELECT 'fact_fuel', COUNT(*), MIN(txn_date), MAX(txn_date) FROM gold.fact_fuel
        UNION ALL SELECT 'dim_customer (versions)', COUNT(*), NULL, NULL FROM gold.dim_customer WHERE customer_key > 0
        UNION ALL SELECT 'dq.quarantine', COUNT(*), MIN(record_date), MAX(record_date) FROM dq.quarantine""")))
    print("\nheadline KPIs, all history")
    print(_table(db.query(conn, """
        SELECT COUNT(*) AS stops,
               CAST(100.0 * AVG(CAST(is_on_time AS float)) AS decimal(5,1)) AS on_time_pct,
               CAST(100.0 * AVG(CAST(is_on_time_tms AS float)) AS decimal(5,1)) AS on_time_tms_pct,
               CAST(100.0 * AVG(CAST(is_in_full AS float)) AS decimal(5,1)) AS in_full_pct,
               CAST(100.0 * AVG(CAST(is_otif AS float)) AS decimal(5,1)) AS otif_pct,
               CAST(100.0 * SUM(is_backfilled) / NULLIF(SUM(has_geofence), 0) AS decimal(5,1)) AS backfilled_pct,
               CAST(100.0 * AVG(CAST(has_geofence AS float)) AS decimal(5,1)) AS geofence_pct
        FROM gold.fact_delivery_stop""")))
    conn.close()


def cmd_dq(s, args):
    conn = db.connect(s, s.dw_db)
    print("last run, by rule (one result per branch and day, or per source for freshness)")
    print(_table(db.query(conn, """
        SELECT s.rule_code, s.severity, COUNT(r.rule_code) AS results, s.breaches, s.blocks_refresh
        FROM dq.run_summary s LEFT JOIN dq.result r ON r.rule_code = s.rule_code AND r.run_id = s.run_id
        WHERE s.run_id = (SELECT MAX(run_id) FROM dq.run_summary)
        GROUP BY s.rule_code, s.severity, s.breaches, s.blocks_refresh ORDER BY s.rule_code""")))
    print(f"\nbreaches in the last {args.days} days, by rule and branch")
    print(_table(db.query(conn, """
        SELECT r.rule_code, b.branch_name, COUNT(*) AS days_breached, SUM(r.failed_rows) AS failed_rows,
               CAST(100.0 * MAX(r.measured_value) AS decimal(6,1)) AS worst_pct
        FROM dq.result r JOIN gold.dim_branch b ON b.branch_key = r.branch_key
        WHERE r.breached = 1 AND r.rule_code <> 'SOURCE_STALE'
          AND r.check_date > DATEADD(day, -%s, (SELECT MAX(check_date) FROM dq.result WHERE rule_code <> 'SOURCE_STALE'))
        GROUP BY r.rule_code, b.branch_name ORDER BY r.rule_code, days_breached DESC""", (args.days,))))
    print("\nsource freshness (hours since the newest record)")
    print(_table(db.query(conn, """
        SELECT subject AS source, check_date, CAST(measured_value AS decimal(6,1)) AS hours_old, breached
        FROM dq.result WHERE rule_code = 'SOURCE_STALE'
          AND check_date = (SELECT MAX(check_date) FROM dq.result WHERE rule_code = 'SOURCE_STALE')
        ORDER BY subject""")))
    conn.close()


def cmd_kpi(s, args):
    conn = db.connect(s, s.dw_db)
    month = args.month or db.scalar(conn, "SELECT MAX(year_month) FROM rpt.kpi_branch_month")
    rows = db.query(conn, """
        SELECT branch_name, stops, CAST(100 * on_time_pct AS decimal(5,1)) AS on_time,
               CAST(100 * on_time_tms_pct AS decimal(5,1)) AS on_time_tms, CAST(100 * in_full_pct AS decimal(5,1)) AS in_full,
               CAST(100 * otif_pct AS decimal(5,1)) AS otif, CAST(revenue AS decimal(12,0)) AS revenue,
               CAST(100 * gross_margin_pct AS decimal(5,1)) AS gm_pct, CAST(fleet_cost AS decimal(12,0)) AS fleet_cost,
               CAST(cost_per_case AS decimal(6,2)) AS cost_per_case
        FROM rpt.kpi_branch_month WHERE year_month = %s ORDER BY branch_name""", (month,))
    print(f"KPIs for {month} (percentages; revenue and cost in dollars)")
    print(_table(rows))
    conn.close()


def cmd_serve_sources(s, args):
    import uvicorn

    uvicorn.run("fleetbi.sources.app:app", host="0.0.0.0", port=args.port, log_level="warning")


def cmd_model(s, args):
    from . import model

    bim = model.load_bim(Path(args.bim))
    if args.action == "bpa":
        problems = model.best_practice_violations(bim)
        for p in problems:
            print(p)
        print(f"{len(problems)} best-practice violations")
        return 1 if problems else 0
    out = Path(args.out)
    out.write_text(model.data_dictionary(bim), encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="fleetbi")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the ERP and warehouse databases and objects").set_defaults(fn=cmd_init)
    sub.add_parser("seed", help="load synthetic ERP rows and fuel files up to the clock").set_defaults(fn=cmd_seed)
    r = sub.add_parser("run", help="one pipeline run (extract, silver, gold, data quality, refresh)")
    r.add_argument("--loop", action="store_true")
    r.add_argument("--interval", type=int, default=7200)
    r.set_defaults(fn=cmd_run)
    a = sub.add_parser("advance", help="move the synthetic clock forward and seed the new days")
    a.add_argument("--days", type=int, default=1)
    a.set_defaults(fn=cmd_advance)
    sub.add_parser("status", help="runs, row counts and headline KPIs").set_defaults(fn=cmd_status)
    d = sub.add_parser("dq", help="data-quality results")
    d.add_argument("--days", type=int, default=30)
    d.set_defaults(fn=cmd_dq)
    k = sub.add_parser("kpi", help="the reconciliation view for one month")
    k.add_argument("--month", help="YYYY-MM, default the latest")
    k.set_defaults(fn=cmd_kpi)
    sv = sub.add_parser("serve-sources", help="run the mock TMS and telematics APIs")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(fn=cmd_serve_sources)
    m = sub.add_parser("model", help="checks and docs from the compiled semantic model (build/model.bim)")
    m.add_argument("action", choices=["bpa", "docs"])
    m.add_argument("--bim", default="build/model.bim")
    m.add_argument("--out", default="docs/data-dictionary.md")
    m.set_defaults(fn=cmd_model)
    args = p.parse_args(argv)
    rc = args.fn(config.load(), args)
    return int(rc or 0)


if __name__ == "__main__":
    sys.exit(main())
