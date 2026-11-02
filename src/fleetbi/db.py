"""Thin SQL Server helpers: connections, GO-separated scripts, and fast multi-row inserts."""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

import pymssql

from .config import Settings

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
_GO = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)


def connect(s: Settings, database: str | None = None, retries: int = 30) -> pymssql.Connection:
    """Autocommit connection; retries while a fresh SQL Server container is still starting."""
    last: Exception | None = None
    for _ in range(retries):
        try:
            conn = pymssql.connect(server=s.sql_host, port=s.sql_port, user=s.sql_user, password=s.sql_password,
                                   database=database or s.dw_db, autocommit=True, login_timeout=10, timeout=600)
            return conn
        except pymssql.Error as exc:  # pragma: no cover - only hit while the server boots
            last = exc
            time.sleep(2)
    raise RuntimeError(f"could not connect to SQL Server at {s.sql_host}:{s.sql_port}: {last}")


def batches(sql: str) -> list[str]:
    return [b.strip() for b in _GO.split(sql) if b.strip()]


def run_script(conn: pymssql.Connection, path: Path) -> None:
    with conn.cursor() as cur:
        for batch in batches(path.read_text(encoding="utf-8")):
            cur.execute(batch)


def execute(conn: pymssql.Connection, sql: str, params: Sequence | dict | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)


def query(conn: pymssql.Connection, sql: str, params: Sequence | dict | None = None) -> list[dict]:
    with conn.cursor(as_dict=True) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def scalar(conn: pymssql.Connection, sql: str, params: Sequence | dict | None = None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return None if row is None else row[0]


def call(conn: pymssql.Connection, proc: str, *args) -> list[dict]:
    """EXEC a procedure; returns its last result set, if any."""
    placeholders = ", ".join(["%s"] * len(args))
    with conn.cursor(as_dict=True) as cur:
        cur.execute(f"EXEC {proc} {placeholders}", args)
        rows: list[dict] = []
        while True:
            if cur.description:
                rows = list(cur.fetchall())
            if not cur.nextset():
                break
        return rows


def literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, Decimal)):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, datetime):
        return "'" + v.strftime("%Y-%m-%dT%H:%M:%S") + "'"
    if isinstance(v, date):
        return "'" + v.isoformat() + "'"
    return "N'" + str(v).replace("'", "''") + "'"


def insert_rows(conn: pymssql.Connection, table: str, columns: Sequence[str], rows: Iterable[Sequence],
                batch: int = 1000) -> int:
    """Insert rows as multi-row VALUES statements (SQL Server allows 1,000 rows per statement)."""
    head = f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
    n = 0
    buf: list[str] = []
    with conn.cursor() as cur:
        for row in rows:
            buf.append("(" + ", ".join(literal(v) for v in row) + ")")
            if len(buf) == batch:
                cur.execute(head + ", ".join(buf))
                n += len(buf)
                buf = []
        if buf:
            cur.execute(head + ", ".join(buf))
            n += len(buf)
    return n
