"""End to end on SQL Server: sources -> landing -> silver -> gold -> data quality, checked against the
synthetic world's ground truth (what the truck actually did), not against the warehouse's own output."""

from collections import defaultdict

import pytest

from fleetbi import db
from helpers import check_stop_rows, expected_arrival, trunc, truth, visible_stops, visit_map

pytestmark = pytest.mark.db


def test_first_run_succeeds_and_reconciles_to_every_source(loaded):
    assert loaded.first_run.status == "succeeded"
    assert loaded.first_run.refresh_status == "not configured"
    conn = loaded.conn()
    completed = [p for p in visible_stops(loaded).values() if p["status"] == "completed"]
    facts = db.scalar(conn, "SELECT COUNT(*) FROM gold.fact_delivery_stop")
    quarantined = db.scalar(conn, "SELECT COUNT(*) FROM dq.quarantine")
    assert facts + quarantined == len(completed)

    erp = db.connect(loaded.s, loaded.s.erp_db)
    erp_revenue, erp_lines = db.query(erp, "SELECT SUM(revenue) AS r, COUNT(*) AS n FROM dbo.invoice_line")[0].values()
    gold = db.query(conn, "SELECT SUM(revenue) AS r, COUNT(*) AS n FROM gold.fact_invoice_line")[0]
    assert (gold["r"], gold["n"]) == (erp_revenue, erp_lines)

    route_days = [rd for rd in loaded.world.route_days if rd.d <= loaded.world.as_of]
    assert db.scalar(conn, "SELECT COUNT(*) FROM gold.fact_route_trip") == len(route_days)
    fuel_rows = sum(len(f.read_text().splitlines()) - 1 for f in loaded.s.sftp_dir.glob("fuel_*.csv"))
    assert db.scalar(conn, "SELECT COUNT(*) FROM gold.fact_fuel") == fuel_rows
    assert db.scalar(conn, "SELECT COUNT(*) FROM gold.fact_delivery_stop WHERE branch_key = -1 OR customer_key = -1 "
                           "OR route_key = -1 OR driver_key = -1 OR truck_key = -1") == 0


def test_on_time_is_scored_on_the_geofence_arrival_in_branch_local_time(loaded):
    rows = db.query(loaded.conn(), "SELECT stop_id, arrival_minute, arrival_source, window_end_minute, is_on_time, "
                                   "is_on_time_tms FROM gold.fact_delivery_stop")
    assert check_stop_rows(loaded.world, rows, truth(loaded)) == []
    on_time = sum(r["is_on_time"] for r in rows) / len(rows)
    on_tms = sum(r["is_on_time_tms"] for r in rows) / len(rows)
    assert 0.80 <= on_time <= 0.90 and on_tms - on_time > 0.04


def test_backfilled_entries_are_caught_without_false_alarms(loaded):
    stops = truth(loaded)
    rows = db.query(loaded.conn(), "SELECT stop_id, is_backfilled FROM gold.fact_delivery_stop WHERE has_geofence = 1")
    flagged = {r["stop_id"] for r in rows if r["is_backfilled"]}
    actual = {r["stop_id"] for r in rows if stops[r["stop_id"]].backfilled}
    assert flagged <= actual  # every flag is a real back-filled entry
    # The 60-minute rule misses some last-stop entries typed soon after the truck got back.
    assert len(flagged) / len(actual) > 0.75


def test_in_full_uses_the_cases_recorded_at_the_stop_after_corrections(loaded):
    visible = visible_stops(loaded)
    rows = db.query(loaded.conn(), "SELECT stop_id, short_cases, refused_cases, is_in_full, delivered_cases, "
                                   "ordered_cases FROM gold.fact_delivery_stop")
    for r in rows:
        p = visible[r["stop_id"]]
        assert (r["short_cases"], r["refused_cases"]) == (p["short_cases"], p["refused_cases"])
        assert r["is_in_full"] == int(p["short_cases"] + p["refused_cases"] == 0)
        assert r["delivered_cases"] == r["ordered_cases"] - r["short_cases"] - r["refused_cases"]


def test_only_gps_clock_glitches_are_quarantined(loaded):
    stops = truth(loaded)
    ids = [r["record_id"] for r in db.query(loaded.conn(), "SELECT record_id FROM dq.quarantine")]
    assert ids and all(stops[i].glitch for i in ids)


def test_data_health_flags_the_branch_with_the_faulty_telematics_unit(loaded):
    rows = db.query(loaded.conn(), """
        SELECT b.branch_code, COUNT(*) AS days, SUM(r.breached) AS breached
        FROM dq.result r JOIN gold.dim_branch b ON b.branch_key = r.branch_key
        WHERE r.rule_code = 'GEOFENCE_MISSING' GROUP BY b.branch_code""")
    share = {r["branch_code"]: r["breached"] / r["days"] for r in rows}
    assert share["RED"] > 0.5
    assert share["COR"] < 0.1 and share["MAR"] < 0.1


def test_reconciliation_view_matches_ground_truth(loaded):
    stops = truth(loaded)
    conn = loaded.conn()
    quarantined = {r["record_id"] for r in db.query(conn, "SELECT record_id FROM dq.quarantine")}
    visits = visit_map(loaded.world)
    expect = defaultdict(lambda: [0, 0])
    for s in stops.values():
        if s.d <= loaded.world.as_of and s.id not in quarantined:
            _, arrival = expected_arrival(loaded.world, s, visits)
            key = (s.branch, s.d.strftime("%Y-%m"))
            expect[key][0] += 1
            expect[key][1] += arrival <= s.window_end
    rows = db.query(conn, "SELECT branch_code, year_month, stops, on_time_pct FROM rpt.kpi_branch_month")
    assert len(rows) == len(expect)
    for r in rows:
        n, on = expect[(r["branch_code"], r["year_month"])]
        assert r["stops"] == n
        assert float(r["on_time_pct"]) == pytest.approx(on / n, abs=0.00006)


def test_customer_keys_follow_the_branch_history(loaded):
    rows = db.query(loaded.conn(), """
        SELECT COUNT(*) AS n FROM gold.fact_delivery_stop f
        JOIN gold.dim_customer c ON c.customer_key = f.customer_key
        WHERE f.service_date NOT BETWEEN c.valid_from AND c.valid_to""")
    assert rows[0]["n"] == 0


def test_a_run_with_nothing_new_rebuilds_only_the_overlap_and_changes_nothing(loaded):
    conn = loaded.conn()
    before = db.query(conn, "SELECT (SELECT COUNT(*) FROM gold.fact_delivery_stop) AS stops, "
                            "(SELECT SUM(revenue) FROM gold.fact_invoice_line) AS revenue, "
                            "(SELECT SUM(is_on_time) FROM gold.fact_delivery_stop) AS on_time")[0]
    result = loaded.run()
    after = db.query(conn, "SELECT (SELECT COUNT(*) FROM gold.fact_delivery_stop) AS stops, "
                           "(SELECT SUM(revenue) FROM gold.fact_invoice_line) AS revenue, "
                           "(SELECT SUM(is_on_time) FROM gold.fact_delivery_stop) AS on_time")[0]
    assert result.status == "succeeded"
    assert before == after
    assert result.landed["erp_invoice_line"] == 0 and result.landed["fuel_rows"] == 0
    # The 48-hour re-read touches the last few operating days and the stops corrected inside it, not the history.
    assert 0 < result.affected_dates <= 6
