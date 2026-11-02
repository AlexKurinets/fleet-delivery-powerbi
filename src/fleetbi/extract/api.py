"""Incremental pulls from the TMS and telematics APIs into landing.api_record.

Each entity keeps a watermark (the newest updated_at landed). A run asks for records updated since the
watermark minus an overlap window, pages on the API's (updated_at, id) cursor, and lands every record
exactly as the API returned it. Silver keeps the latest version of each record, so re-reading the
overlap costs a few duplicate landing rows and never a duplicate stop.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator

import httpx

from .. import db
from ..config import Settings

log = logging.getLogger(__name__)

ENTITIES = [
    ("tms_route_plan", "/tms/v1/route-plans"),
    ("tms_stop", "/tms/v1/stops"),
    ("tel_visit", "/telematics/v1/geofence-visits"),
    ("tel_trip", "/telematics/v1/trips"),
]


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class ApiClient:
    def __init__(self, base_url: str, page_size: int = 1000, max_retries: int = 6,
                 http: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep):
        self.http = http or httpx.Client(base_url=base_url, timeout=60)
        self.page_size = page_size
        self.max_retries = max_retries
        self.sleep = sleep
        self.retries = 0

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.http.get(path, params=params)
            except httpx.TransportError:
                if attempt == self.max_retries:
                    raise
                self.retries += 1
                self.sleep(min(2 ** attempt, 30))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    resp.raise_for_status()
                self.retries += 1
                wait = float(resp.headers.get("Retry-After", min(2 ** attempt, 30)))
                self.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("unreachable")

    def iter_records(self, path: str, updated_since: datetime | None) -> Iterator[dict]:
        params: dict = {"limit": self.page_size}
        if updated_since is not None:
            params["updated_since"] = updated_since.strftime("%Y-%m-%dT%H:%M:%SZ")
        while True:
            body = self._get(path, params)
            yield from body["data"]
            if not body.get("next_cursor"):
                return
            params["cursor"] = body["next_cursor"]


def get_watermark(conn, source: str) -> str | None:
    return db.scalar(conn, "SELECT value FROM meta.watermark WHERE source = %s", (source,))


def set_watermark(conn, source: str, value: str) -> None:
    db.execute(conn, "DELETE FROM meta.watermark WHERE source = %s; "
                     "INSERT meta.watermark (source, value, updated_utc) VALUES (%s, %s, SYSUTCDATETIME())",
               (source, source, value))


def extract_api(conn, s: Settings, run_id: int, client: ApiClient | None = None) -> dict[str, int]:
    client = client or ApiClient(s.sources_url, s.page_size)
    landed: dict[str, int] = {}
    for entity, path in ENTITIES:
        wm = get_watermark(conn, entity)
        since = parse_ts(wm) - timedelta(hours=s.overlap_hours) if wm else None
        newest = parse_ts(wm) if wm else None
        rows = []
        for rec in client.iter_records(path, since):
            upd = parse_ts(rec["updated_at"])
            newest = upd if newest is None or upd > newest else newest
            rows.append((entity, rec["id"], upd.replace(tzinfo=None), json.dumps(rec, separators=(",", ":")), run_id))
        n = db.insert_rows(conn, "landing.api_record", ["entity", "record_id", "updated_utc", "payload", "run_id"], rows)
        new_wm = newest.strftime("%Y-%m-%dT%H:%M:%SZ") if newest else None
        if new_wm:
            set_watermark(conn, entity, new_wm)
        db.execute(conn, "INSERT meta.source_load (run_id, source, rows_landed, watermark_from, watermark_to) "
                         "VALUES (%s, %s, %s, %s, %s)", (run_id, entity, n, wm, new_wm))
        landed[entity] = n
        log.info("%s: landed %d records since %s", entity, n, since)
    if client.retries:
        log.info("API retries after 429 or 5xx responses: %d", client.retries)
    return landed
