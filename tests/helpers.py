"""Shared test helpers. Database tests need a SQL Server (FLEETBI_TEST_SQL_HOST/PORT/PASSWORD); CI runs one
as a service container. Each loaded fixture uses its own pair of databases, so tests never touch the
Compose stack's databases."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fleetbi import clock, config, db, pipeline, seed, synth
from fleetbi.extract.api import ApiClient
from fleetbi.sources.app import create_app

ROOT = Path(__file__).resolve().parents[1]
# A smaller world than the Compose stack: three branches (one on Mountain time, one with the faulty
# telematics unit) and seven weeks, ending on the same AS_OF date.
TEST_START = date(2026, 9, 14)
TEST_BRANCHES = ["COR", "MAR", "RED"]


def make_settings(tmp: Path, suffix: str) -> config.Settings:
    base = config.load()
    return replace(
        base,
        sql_host=os.environ.get("FLEETBI_TEST_SQL_HOST", "localhost"),
        sql_port=int(os.environ.get("FLEETBI_TEST_SQL_PORT", "14331")),
        sql_password=os.environ.get("FLEETBI_TEST_SQL_PASSWORD", base.sql_password),
        dw_db=f"fleetdw_{suffix}", erp_db=f"erp_{suffix}", state_dir=tmp / "state", sftp_dir=tmp / "sftp",
        page_size=500, overlap_hours=48, refresh_mode="log")


def drop_databases(s: config.Settings) -> None:
    master = db.connect(s, "master", retries=5)
    for name in (s.dw_db, s.erp_db):
        db.execute(master, f"IF DB_ID('{name}') IS NOT NULL BEGIN "
                           f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{name}]; END")
    master.close()


@dataclass
class Loaded:
    s: config.Settings
    world: synth.World
    app: object
    api: TestClient
    first_run: pipeline.RunResult

    def client(self) -> ApiClient:
        return ApiClient("", page_size=self.s.page_size, http=self.api, sleep=lambda _: None)

    def conn(self):
        return db.connect(self.s, self.s.dw_db)

    def run(self, refresher=None) -> pipeline.RunResult:
        return pipeline.run(self.s, client=self.client(), refresher=refresher)


def load(tmp: Path, suffix: str) -> Loaded:
    s = make_settings(tmp, suffix)
    try:
        drop_databases(s)
    except RuntimeError as exc:
        pytest.skip(f"SQL Server not reachable for database tests: {exc}")
    world = synth.World(start=TEST_START, branches=TEST_BRANCHES)
    app = create_app(world_factory=lambda: world, now_fn=lambda: clock.now(s.state_dir), rate_limit_every=0,
                     admin=True)
    api = TestClient(app)
    seed.init_databases(s)
    seed.seed(s, world)
    loaded = Loaded(s, world, app, api, None)  # type: ignore[arg-type]
    loaded.first_run = loaded.run()
    return loaded


def visible_stops(loaded) -> dict[str, dict]:
    now = clock.now(loaded.s.state_dir)
    return {rid: p for _, rid, p in synth.latest_visible(loaded.world.stop_records(), now)}


def truth(loaded) -> dict[str, synth.Stop]:
    return {s.id: s for s in loaded.world.stops}


def trunc(dt: datetime) -> datetime:
    return dt.replace(microsecond=0)


def minute_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def expected_arrival(world, s: synth.Stop, visits: dict) -> tuple[str, datetime]:
    """What the warehouse should score: the geofence entry (as telematics sent it), else the TMS time."""
    v = visits.get(synth.guid("visit", s.id))
    if v is None:
        return "TMS", trunc(s.delivered_at)
    entered = datetime.fromisoformat(v["entered_at"].replace("Z", "+00:00"))
    return "Geofence", entered.astimezone(synth.BRANCH_BY_CODE[s.branch].tz)


def visit_map(world) -> dict:
    return {r.id: r.versions[0].payload for r in world.visit_records()}


def check_stop_rows(world, rows, stops) -> list[str]:
    """Compare gold rows with what really happened; returns a list of mismatches."""
    visits = visit_map(world)
    bad = []
    for r in rows:
        s = stops[r["stop_id"]]
        exp_source, arrival = expected_arrival(world, s, visits)
        if s.geofence and not s.glitch:
            assert arrival == trunc(s.arrival)  # telematics saw the real arrival
        if r["arrival_source"] != exp_source:
            bad.append(f"{s.id} source {r['arrival_source']} != {exp_source}")
        if r["arrival_minute"] != minute_of_day(arrival):
            bad.append(f"{s.id} {s.branch} {s.d} arrival minute {r['arrival_minute']} != {minute_of_day(arrival)}")
        if r["window_end_minute"] != minute_of_day(s.window_end):
            bad.append(f"{s.id} window end {r['window_end_minute']}")
        if bool(r["is_on_time"]) != (arrival <= s.window_end):
            bad.append(f"{s.id} on-time {r['is_on_time']}")
        if bool(r["is_on_time_tms"]) != (trunc(s.delivered_at) <= s.window_end):
            bad.append(f"{s.id} tms on-time {r['is_on_time_tms']}")
    return bad
