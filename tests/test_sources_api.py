"""The mock APIs and the extract client: cursor paging, the offset paging failure, clock, retries."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from fleetbi import synth
from fleetbi.extract.api import ApiClient
from fleetbi.sources.app import create_app

NOW = synth.default_clock()


@pytest.fixture(scope="module")
def world():
    return synth.World(start=date(2026, 10, 12), branches=["HAL", "RED"])


def make(world, now=NOW, every=0):
    clock = {"now": now}
    app = create_app(world_factory=lambda: world, now_fn=lambda: clock["now"], rate_limit_every=every, admin=True)
    return TestClient(app), clock


def test_cursor_paging_returns_each_record_once_in_order(world):
    api, _ = make(world)
    client = ApiClient("", page_size=97, http=api)
    recs = list(client.iter_records("/tms/v1/stops", None))
    ids = [r["id"] for r in recs]
    assert len(ids) == len(set(ids)) == len(synth.latest_visible(world.stop_records(), NOW))
    keys = [(r["updated_at"], r["id"]) for r in recs]
    assert keys == sorted(keys)


def test_offset_paging_skips_and_repeats_when_a_stop_changes_mid_pull(world):
    """Why the extract pages on a cursor: an edit moves a record to the end and shifts every offset."""
    api, _ = make(world)
    first = api.get("/tms/v1/stops", params={"offset": 0, "limit": 100}).json()["data"]
    api.post("/admin/touch", params={"record_id": first[10]["id"]})  # a dispatcher edits a stop we already have
    rest, offset = [], 100
    while offset is not None:
        body = api.get("/tms/v1/stops", params={"offset": offset, "limit": 100}).json()
        rest += body["data"]
        offset = body["next_offset"]
    ids = [r["id"] for r in first + rest]
    total = len(synth.latest_visible(world.stop_records(), NOW))
    assert len(ids) - len(set(ids)) == 1  # the edited stop comes back a second time
    assert len(set(ids)) == total - 1  # and the record that shifted into position 99 is never seen

    api2, _ = make(world)
    client = ApiClient("", page_size=100, http=api2)
    pages = client.iter_records("/tms/v1/stops", None)
    got = [next(pages) for _ in range(100)]
    api2.post("/admin/touch", params={"record_id": got[10]["id"]})
    got += list(pages)
    assert len({r["id"] for r in got}) == total  # cursor paging misses nothing; silver dedupes the repeat


def test_updated_since_and_the_clock(world):
    api, clock = make(world)
    since = NOW - timedelta(hours=30)
    recent = api.get("/tms/v1/stops", params={"updated_since": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                              "limit": 2000}).json()["data"]
    assert recent and all(datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00")) > since for r in recent)
    day = NOW.date().isoformat()  # Saturday: planned the afternoon before, not delivered yet at 06:00 UTC
    before = [r for r in ApiClient("", 2000, http=api).iter_records("/tms/v1/stops", None)
              if r["route_date"] == day]
    assert before and all(r["status"] == "planned" for r in before)
    clock["now"] = NOW + timedelta(days=1)
    after = [r for r in ApiClient("", 2000, http=api).iter_records("/tms/v1/stops", None) if r["route_date"] == day]
    assert after and all(r["status"] == "completed" for r in after)


def test_client_waits_out_429_responses(world):
    api, _ = make(world, every=3)
    waits = []
    client = ApiClient("", page_size=10, http=api, sleep=waits.append)
    recs = list(client.iter_records("/telematics/v1/trips", None))
    assert recs and client.retries > 0 and set(waits) == {1.0}


def test_bad_cursor_is_rejected(world):
    api, _ = make(world)
    assert api.get("/tms/v1/stops", params={"cursor": "not-a-cursor"}).status_code == 400


def test_health_reports_the_clock(world):
    api, _ = make(world, now=datetime(2026, 11, 1, 6, tzinfo=timezone.utc))
    assert api.get("/health").json()["now_utc"] == "2026-11-01T06:00:00Z"
