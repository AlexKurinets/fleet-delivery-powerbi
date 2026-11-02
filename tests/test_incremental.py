"""Incremental runs: new days, late corrections, the daylight saving change, a customer moving branch,
a blocking data-quality rule and a failed run. Uses its own databases."""

from datetime import date, timedelta

import pytest

from fleetbi import clock, db, pipeline, seed
from helpers import check_stop_rows, load, truth, visible_stops

pytestmark = pytest.mark.db
MOVE_DATE = date(2026, 11, 2)


@pytest.fixture(scope="module")
def advanced(tmp_path_factory):
    loaded = load(tmp_path_factory.mktemp("inc"), "inc")
    conn = loaded.conn()
    loaded.before = {r["source"]: r["value"] for r in db.query(conn, "SELECT source, value FROM meta.watermark")}
    # Six days on: Saturday 31 Oct, the DST change early on Sunday 1 Nov, and the branch move on Monday 2 Nov.
    clock.set_now(loaded.s.state_dir, clock.now(loaded.s.state_dir) + timedelta(days=6))
    seed.seed(loaded.s, loaded.world)
    loaded.second_run = loaded.run()
    return loaded


def test_new_days_land_and_watermarks_move(advanced):
    conn = advanced.conn()
    assert advanced.second_run.status == "succeeded"
    days = {r["d"] for r in db.query(conn, "SELECT DISTINCT service_date AS d FROM gold.fact_delivery_stop "
                                           "WHERE service_date > '2026-10-30'")}
    assert days == {date(2026, 10, 31), date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)}
    after = {r["source"]: r["value"] for r in db.query(conn, "SELECT source, value FROM meta.watermark")}
    assert all(after[k] > v for k, v in advanced.before.items() if k.startswith("t"))


def test_stops_after_the_dst_change_are_still_scored_in_local_time(advanced):
    rows = db.query(advanced.conn(), "SELECT stop_id, arrival_minute, arrival_source, window_end_minute, is_on_time, "
                                     "is_on_time_tms FROM gold.fact_delivery_stop WHERE service_date >= '2026-10-29'")
    assert len(rows) > 300
    assert check_stop_rows(advanced.world, rows, truth(advanced)) == []


def test_late_corrections_are_picked_up(advanced):
    visible = visible_stops(advanced)
    corrected = [s for s in advanced.world.stops if s.correction and date(2026, 10, 28) <= s.d <= date(2026, 10, 30)]
    assert corrected
    rows = {r["stop_id"]: r for r in db.query(
        advanced.conn(), "SELECT stop_id, short_cases, refused_cases FROM gold.fact_delivery_stop "
                         "WHERE service_date BETWEEN '2026-10-28' AND '2026-10-30'")}
    for s in corrected:
        if s.id in rows:
            assert (rows[s.id]["short_cases"], rows[s.id]["refused_cases"]) == s.correction[1:]
            assert visible[s.id]["short_cases"] == s.correction[1]


def test_customer_move_creates_a_second_version_and_new_stops_use_it(advanced):
    conn = advanced.conn()
    movers = [c.number for c in advanced.world.customers.values() if c.moves]
    assert movers
    versions = db.query(conn, "SELECT customer_number, customer_key, branch_code, valid_from, valid_to, is_current "
                              "FROM gold.dim_customer WHERE customer_number IN (%s) ORDER BY customer_number, valid_from"
                        % ", ".join(f"'{m}'" for m in movers))
    for m in movers:
        mine = [v for v in versions if v["customer_number"] == m]
        assert [(v["branch_code"], v["is_current"]) for v in mine] == [("COR", False), ("MAR", True)]
        assert mine[0]["valid_to"] == MOVE_DATE - timedelta(days=1) and mine[1]["valid_from"] == MOVE_DATE
    facts = db.query(conn, "SELECT f.service_date, c.branch_code AS customer_branch, b.branch_code AS route_branch "
                           "FROM gold.fact_delivery_stop f JOIN gold.dim_customer c ON c.customer_key = f.customer_key "
                           "JOIN gold.dim_branch b ON b.branch_key = f.branch_key WHERE c.customer_number IN (%s)"
                     % ", ".join(f"'{m}'" for m in movers))
    after = [f for f in facts if f["service_date"] >= MOVE_DATE]
    before = [f for f in facts if f["service_date"] < MOVE_DATE]
    assert after and before
    assert all(f["customer_branch"] == "MAR" == f["route_branch"] for f in after)
    assert all(f["customer_branch"] == "COR" == f["route_branch"] for f in before)


def test_revenue_still_reconciles_after_incremental_loads(advanced):
    erp = db.connect(advanced.s, advanced.s.erp_db)
    assert db.scalar(erp, "SELECT SUM(revenue) FROM dbo.invoice_line") == \
        db.scalar(advanced.conn(), "SELECT SUM(revenue) FROM gold.fact_invoice_line")


class Recorder:
    def __init__(self):
        self.calls = []

    def refresh(self, run_id):
        self.calls.append(run_id)
        return "triggered"


def test_a_blocking_rule_stops_the_refresh(advanced):
    conn = advanced.conn()
    db.execute(conn, "UPDATE dq.rule_def SET block_threshold = -1 WHERE rule_code = 'ARRIVAL_BEFORE_DISPATCH'")
    try:
        rec = Recorder()
        result = advanced.run(refresher=rec)
        assert result.status == "blocked" and result.refresh_status == "skipped" and rec.calls == []
        row = db.query(conn, "SELECT status, refresh_status, message FROM meta.run WHERE run_id = %s",
                       (result.run_id,))[0]
        assert row["status"] == "blocked" and "ARRIVAL_BEFORE_DISPATCH" in row["message"]
    finally:
        db.execute(conn, "UPDATE dq.rule_def SET block_threshold = 0.02 WHERE rule_code = 'ARRIVAL_BEFORE_DISPATCH'")
    rec = Recorder()
    result = advanced.run(refresher=rec)
    assert result.status == "succeeded" and rec.calls == [result.run_id]


class BrokenClient:
    retries = 0

    def iter_records(self, path, since):
        raise ConnectionError("TMS API unreachable")


def test_a_failed_run_is_recorded_and_never_refreshes(advanced):
    rec = Recorder()
    with pytest.raises(ConnectionError):
        pipeline.run(advanced.s, client=BrokenClient(), refresher=rec)
    row = db.query(advanced.conn(), "SELECT TOP 1 status, refresh_status, message FROM meta.run ORDER BY run_id DESC")[0]
    assert row == {"status": "failed", "refresh_status": "skipped", "message": "TMS API unreachable"}
    assert rec.calls == []
