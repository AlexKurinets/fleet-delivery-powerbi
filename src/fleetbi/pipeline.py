"""One pipeline run: extract every source, build silver and gold, run the data-quality rules, and only
then refresh the semantic model, so the model never reads half-loaded tables and never refreshes over
a load that a blocking rule rejected."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import clock, db, refresh
from .config import Settings
from .extract.api import ApiClient, extract_api
from .extract.erp import extract_erp
from .extract.files import extract_fuel

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    run_id: int
    status: str
    refresh_status: str
    landed: dict = field(default_factory=dict)
    dq: list = field(default_factory=list)
    affected_dates: int = 0


def run(s: Settings, client: ApiClient | None = None, refresher=None, now: datetime | None = None) -> RunResult:
    refresher = refresher or refresh.from_settings(s)
    now = (now or clock.now(s.state_dir)).astimezone(timezone.utc).replace(tzinfo=None)
    conn = db.connect(s, s.dw_db)
    run_id = int(db.scalar(conn, "SELECT ISNULL(MAX(run_id), 0) + 1 FROM meta.run"))
    db.execute(conn, "INSERT meta.run (run_id, started_utc, source_clock_utc, status) "
                     "VALUES (%s, SYSUTCDATETIME(), %s, 'running')", (run_id, now))
    result = RunResult(run_id, "running", "skipped")
    try:
        result.landed.update(extract_erp(conn, s, run_id))
        result.landed.update(extract_api(conn, s, run_id, client))
        result.landed.update(extract_fuel(conn, s, run_id))
        for proc in ("silver.load_erp", "silver.load_api", "silver.load_fuel", "silver.collect_affected_dates",
                     "gold.load_dims", "gold.load_fact_delivery_stop", "gold.load_fact_invoice_line",
                     "gold.load_fact_route_trip", "gold.load_fact_fuel"):
            db.call(conn, proc, run_id)
        result.affected_dates = int(db.scalar(conn, "SELECT COUNT(*) FROM meta.affected_date WHERE run_id = %s",
                                              (run_id,)))
        result.dq = db.call(conn, "dq.run_rules", run_id, now)
        blocking = [r["rule_code"] for r in result.dq if r["blocks_refresh"]]
        if blocking:
            result.status = "blocked"
            message = "refresh skipped, blocking rule breached: " + ", ".join(blocking)
            log.warning("run %d: %s", run_id, message)
        else:
            result.status = "succeeded"
            result.refresh_status = refresher.refresh(run_id)
            message = None
        db.execute(conn, "UPDATE meta.run SET finished_utc = SYSUTCDATETIME(), status = %s, refresh_status = %s, "
                         "message = %s WHERE run_id = %s", (result.status, result.refresh_status, message, run_id))
    except Exception as exc:
        result.status = "failed"
        db.execute(conn, "UPDATE meta.run SET finished_utc = SYSUTCDATETIME(), status = 'failed', "
                         "refresh_status = 'skipped', message = %s WHERE run_id = %s", (str(exc)[:400], run_id))
        raise
    finally:
        conn.close()
    log.info("run %d %s: %d dates rebuilt, refresh %s", run_id, result.status, result.affected_dates,
             result.refresh_status)
    return result
