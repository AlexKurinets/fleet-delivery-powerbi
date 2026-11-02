"""Mock TMS and telematics REST APIs over the synthetic world.

They behave like the real ones in the ways the pipeline has to handle: JSON pages, an `updated_since`
filter, cursor paging on (updated_at, id), the old offset paging that skips and repeats records when
something changes mid-pull, and 429 responses with Retry-After.
"""

from __future__ import annotations

import base64
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .. import clock, synth

ENTITIES = {
    "tms/v1/stops": "stop_records",
    "tms/v1/route-plans": "route_plan_records",
    "telematics/v1/geofence-visits": "visit_records",
    "telematics/v1/trips": "trip_records",
}


def encode_cursor(updated: datetime, rid: str) -> str:
    return base64.urlsafe_b64encode(f"{synth.iso_utc(updated)}|{rid}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        ts, rid = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(ts.replace("Z", "+00:00")), rid
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "bad cursor") from exc


def parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "updated_since must be ISO 8601") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=synth.UTC)


class Store:
    """Visible records per entity at the current clock, rebuilt when the clock or an override changes."""

    def __init__(self, world_factory: Callable[[], synth.World], now_fn: Callable[[], datetime]):
        self._world_factory = world_factory
        self._world: synth.World | None = None
        self._records: dict[str, list[synth.Record]] = {}
        self._cache: dict[str, tuple[tuple, list]] = {}
        self.now_fn = now_fn
        self.overrides: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def world(self) -> synth.World:
        with self._lock:
            if self._world is None:
                self._world = self._world_factory()
            return self._world

    def visible(self, path: str) -> list[tuple[datetime, str, dict]]:
        now = self.now_fn()
        key = (now, tuple(sorted(self.overrides.items())))
        hit = self._cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
        if path not in self._records:
            self._records[path] = getattr(self.world(), ENTITIES[path])()
        rows = synth.latest_visible(self._records[path], now, self.overrides)
        self._cache[path] = (key, rows)
        return rows


def create_app(world_factory: Callable[[], synth.World] | None = None,
               now_fn: Callable[[], datetime] | None = None,
               rate_limit_every: int | None = None, admin: bool | None = None) -> FastAPI:
    state_dir = Path(os.environ.get("FLEETBI_STATE_DIR", "./.state"))
    store = Store(world_factory or synth.World, now_fn or (lambda: clock.now(state_dir)))
    every = int(os.environ.get("FLEETBI_RATE_LIMIT_EVERY", "0")) if rate_limit_every is None else rate_limit_every
    admin = os.environ.get("FLEETBI_SOURCES_ADMIN", "0") == "1" if admin is None else admin
    app = FastAPI(title="Mock TMS and telematics APIs (synthetic)")
    app.state.store = store
    counter = {"n": 0}

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        if every and request.url.path.startswith(("/tms/", "/telematics/")):
            counter["n"] += 1
            if counter["n"] % every == 0:
                return JSONResponse({"error": "rate limited"}, status_code=429, headers={"Retry-After": "1"})
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok", "now_utc": synth.iso_utc(store.now_fn())}

    def page(path: str, updated_since: str | None, cursor: str | None, offset: int | None, limit: int):
        rows = store.visible(path)
        since = parse_since(updated_since)
        if since is not None:
            rows = [r for r in rows if r[0] > since]
        if offset is not None:  # legacy paging: positions shift when a record's updated_at changes mid-pull
            chunk = rows[offset:offset + limit]
            nxt = offset + limit if offset + limit < len(rows) else None
            return {"data": [r[2] for r in chunk], "next_offset": nxt}
        if cursor:
            after = decode_cursor(cursor)
            rows = [r for r in rows if (r[0], r[1]) > after]
        chunk = rows[:limit]
        nxt = encode_cursor(chunk[-1][0], chunk[-1][1]) if len(rows) > limit else None
        return {"data": [r[2] for r in chunk], "next_cursor": nxt}

    def make_handler(route: str):
        def handler(updated_since: str | None = None, cursor: str | None = None, offset: int | None = None,
                    limit: int = Query(500, ge=1, le=2000)):
            return page(route, updated_since, cursor, offset, limit)
        return handler

    for route in ENTITIES:
        app.add_api_route(f"/{route}", make_handler(route), methods=["GET"], name=route)

    if admin:
        @app.post("/admin/touch")
        def touch(record_id: str, minutes: int = 1):
            """Test hook: mark a record as edited now, the way a dispatcher edit would."""
            store.overrides[record_id] = store.now_fn() + timedelta(minutes=minutes)
            return {"touched": record_id}

    return app


app = create_app()
