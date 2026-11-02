"""Fuel card CSV files from the SFTP drop folder. A file is loaded once per content hash."""

from __future__ import annotations

import csv
import hashlib
import logging

from .. import db
from ..config import Settings

log = logging.getLogger(__name__)
COLUMNS = ["card_number", "truck_code", "txn_time_local", "site_name", "gallons", "price_per_gallon", "amount"]


def extract_fuel(conn, s: Settings, run_id: int) -> dict[str, int]:
    seen = {r["file_name"]: r["sha256"] for r in db.query(conn, "SELECT file_name, sha256 FROM meta.file_log")}
    files = rows_total = 0
    for path in sorted(s.sftp_dir.glob("fuel_*.csv")) if s.sftp_dir.exists() else []:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if seen.get(path.name) == digest:
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            rows = [(path.name, i, *[r[c] for c in COLUMNS], run_id)
                    for i, r in enumerate(csv.DictReader(fh), start=1)]
        n = db.insert_rows(conn, "landing.fuel_txn", ["file_name", "line_no", *COLUMNS, "run_id"], rows)
        db.execute(conn, "DELETE FROM meta.file_log WHERE file_name = %s; "
                         "INSERT meta.file_log (file_name, sha256, rows_landed, run_id) VALUES (%s, %s, %s, %s)",
                   (path.name, path.name, digest, n, run_id))
        files += 1
        rows_total += n
    db.execute(conn, "INSERT meta.source_load (run_id, source, rows_landed) VALUES (%s, 'fuel_files', %s)",
               (run_id, rows_total))
    log.info("fuel files loaded: %d (%d rows)", files, rows_total)
    return {"fuel_files": files, "fuel_rows": rows_total}
