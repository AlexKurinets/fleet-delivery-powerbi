"""Create the databases and load the synthetic ERP and fuel card files up to the clock's business date.

The TMS and telematics records are not seeded: the mock API service generates them from the same
synthetic world and serves whatever exists at the current clock.
"""

from __future__ import annotations

import csv
import logging
from datetime import date, timedelta

from . import clock, db, synth
from .config import Settings

log = logging.getLogger(__name__)

SECURITY_USERS = [
    ("hal.manager@example.com", ["HAL"]),
    ("ash.manager@example.com", ["ASH"]),
    ("cor.manager@example.com", ["COR"]),
    ("mar.manager@example.com", ["MAR"]),
    ("mountain.regional@example.com", ["RED", "SIL"]),
]


def init_databases(s: Settings) -> None:
    master = db.connect(s, "master")
    for name in (s.erp_db, s.dw_db):
        db.execute(master, f"IF DB_ID('{name}') IS NULL CREATE DATABASE [{name}]")
    master.close()
    erp = db.connect(s, s.erp_db)
    for path in sorted((db.SQL_DIR / "erp").glob("*.sql")):
        db.run_script(erp, path)
    db.execute(erp, "IF OBJECT_ID('dbo.seed_state') IS NULL "
                    "CREATE TABLE dbo.seed_state (id int PRIMARY KEY, seeded_through date NOT NULL)")
    erp.close()
    dw = db.connect(s, s.dw_db)
    for path in sorted((db.SQL_DIR / "dw").glob("*.sql")):
        db.run_script(dw, path)
    dw.close()
    log.info("databases %s and %s are ready", s.erp_db, s.dw_db)


def seeded_through(erp) -> date | None:
    return db.scalar(erp, "SELECT seeded_through FROM dbo.seed_state WHERE id = 1")


def seed(s: Settings, world: synth.World | None = None) -> dict:
    """Bring the ERP database and the fuel drop folder up to the clock's business date. Idempotent."""
    target = clock.business_date(clock.now(s.state_dir))
    erp = db.connect(s, s.erp_db)
    done = seeded_through(erp)
    if done is not None and done >= target:
        erp.close()
        return {"seeded_through": target.isoformat(), "orders": 0, "invoice_lines": 0, "fuel_files": 0}
    world = world or synth.World()
    first = done is None
    d1 = world.start if first else done + timedelta(days=1)
    counts = {"orders": 0, "invoice_lines": 0, "fuel_files": 0}

    if first:
        db.insert_rows(erp, "dbo.branch", ["branch_code", "branch_name", "region", "time_zone"],
                       [(b.code, b.name, b.region, b.tz_windows) for b in world.branches])
        db.insert_rows(erp, "dbo.category", ["category_code", "category_name", "temp_zone"],
                       [(c.code, c.name, c.temp_zone) for c in synth.CATEGORIES])
        db.insert_rows(erp, "dbo.truck", ["truck_code", "branch_code", "model_year", "reefer_type"],
                       [(t.code, t.branch, t.model_year, t.reefer_type) for t in world.trucks.values()])
        db.insert_rows(erp, "dbo.driver", ["driver_code", "driver_name", "branch_code", "hourly_rate"],
                       [(d.code, d.name, d.branch, d.hourly_rate) for d in world.drivers.values()])
        db.insert_rows(erp, "dbo.customer", ["customer_number", "customer_name", "segment", "branch_code"],
                       [(c.number, c.name, c.segment, world.routes[c.route_on(target)].branch)
                        for c in world.customers.values()])

    # Branch assignment history: initial rows on the first seed, then each move once its date arrives.
    history = [h for h in world.customer_branch_history() if h[3] <= target and (first or h[3] >= d1)]
    db.insert_rows(erp, "dbo.customer_branch_history", ["customer_number", "branch_code", "segment", "effective_from"],
                   history)
    if not first:
        for number, branch, _, eff in history:
            db.execute(erp, "UPDATE dbo.customer SET branch_code = %s WHERE customer_number = %s", (branch, number))

    orders, lines = world.erp_documents(d1, target)
    counts["orders"] = db.insert_rows(erp, "dbo.sales_order",
                                      ["order_number", "customer_number", "service_date", "tms_stop_id", "order_type"],
                                      orders)
    counts["invoice_lines"] = db.insert_rows(
        erp, "dbo.invoice_line",
        ["invoice_number", "line_no", "order_number", "customer_number", "posting_date", "category_code", "cases",
         "revenue", "cost", "original_invoice_number"], lines)

    s.sftp_dir.mkdir(parents=True, exist_ok=True)
    d = d1
    while d <= target:
        rows = world.fuel_rows(d)
        if rows:
            path = s.sftp_dir / f"fuel_{d:%Y%m%d}.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            counts["fuel_files"] += 1
        d += timedelta(days=1)

    if first:
        db.execute(erp, "INSERT dbo.seed_state (id, seeded_through) VALUES (1, %s)", (target,))
        dw = db.connect(s, s.dw_db)
        db.execute(dw, "DELETE FROM sec.user_branch")
        db.insert_rows(dw, "sec.user_branch", ["user_principal_name", "branch_code"],
                       [(u, b) for u, branches in SECURITY_USERS for b in branches
                        if b in {x.code for x in world.branches}])
        dw.close()
    else:
        db.execute(erp, "UPDATE dbo.seed_state SET seeded_through = %s WHERE id = 1", (target,))
    erp.close()
    counts["seeded_through"] = target.isoformat()
    log.info("seeded ERP and fuel files through %s: %s", target, counts)
    return counts
