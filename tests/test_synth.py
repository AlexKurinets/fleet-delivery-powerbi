"""The synthetic world has the properties the warehouse is built to handle."""

from datetime import timedelta

from fleetbi import synth


def test_world_is_deterministic():
    a = synth.World(start=synth.AS_OF - timedelta(days=14), branches=["HAL", "RED"])
    b = synth.World(start=synth.AS_OF - timedelta(days=14), branches=["HAL", "RED"])
    assert [r.versions[-1].payload for r in a.stop_records()[:200]] == \
           [r.versions[-1].payload for r in b.stop_records()[:200]]


def test_tms_overstates_on_time_and_about_one_in_eight_entries_are_backfilled(full_world):
    stops = [s for s in full_world.stops if s.d <= full_world.as_of]
    on_geofence = sum(s.arrival <= s.window_end for s in stops) / len(stops)
    on_tms = sum(s.delivered_at <= s.window_end for s in stops) / len(stops)
    backfilled = sum(s.backfilled for s in stops) / len(stops)
    assert 0.84 <= on_geofence <= 0.88
    assert 0.92 <= on_tms <= 0.95
    assert 0.11 <= backfilled <= 0.15


def test_timestamps_follow_each_source_convention(full_world):
    stop = full_world.stop_records()[0].versions[1].payload
    visit = full_world.visit_records()[0].versions[0].payload
    assert not stop["window_start"].endswith("Z") and "+" not in stop["window_start"]  # TMS: branch local
    assert stop["delivered_recorded_at"].endswith("Z") and visit["entered_at"].endswith("Z")  # UTC


def test_credits_post_one_to_five_days_after_delivery(full_world):
    d1, d2 = synth.AS_OF - timedelta(days=40), synth.AS_OF
    _, lines = full_world.erp_documents(d1, d2)
    by_order = {s.order_number: s for s in full_world.stops}
    credits = [ln for ln in lines if ln[0].startswith("CR")]
    assert credits
    for ln in credits:
        lag = (ln[4] - by_order[ln[2]].d).days
        assert 1 <= lag <= 5 and ln[6] < 0 and ln[7] < 0


def test_customers_move_branches_on_their_effective_dates(full_world):
    moves = [h for h in full_world.customer_branch_history() if h[3].year == 2026]
    assert {(h[3].isoformat(), h[1]) for h in moves} == {("2026-03-02", "ASH"), ("2026-11-02", "MAR")}
