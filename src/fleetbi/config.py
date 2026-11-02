"""Settings from FLEETBI_* environment variables, with defaults that match docker-compose.yml."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    sql_host: str
    sql_port: int
    sql_user: str
    sql_password: str
    dw_db: str
    erp_db: str
    sources_url: str
    state_dir: Path
    sftp_dir: Path
    page_size: int
    overlap_hours: int
    refresh_mode: str  # "log" (default) or "powerbi"
    pbi_workspace_id: str
    pbi_dataset_id: str


def load() -> Settings:
    env = os.environ.get
    state = Path(env("FLEETBI_STATE_DIR", "./.state"))
    return Settings(
        sql_host=env("FLEETBI_SQL_HOST", "localhost"),
        sql_port=int(env("FLEETBI_SQL_PORT", "14330")),
        sql_user=env("FLEETBI_SQL_USER", "sa"),
        sql_password=env("FLEETBI_SQL_PASSWORD", "Fleet_Dev_2026!"),
        dw_db=env("FLEETBI_DW_DB", "fleetdw"),
        erp_db=env("FLEETBI_ERP_DB", "erp_demo"),
        sources_url=env("FLEETBI_SOURCES_URL", "http://localhost:8230"),
        state_dir=state,
        sftp_dir=Path(env("FLEETBI_SFTP_DIR", str(state / "sftp"))),
        page_size=int(env("FLEETBI_PAGE_SIZE", "1000")),
        overlap_hours=int(env("FLEETBI_OVERLAP_HOURS", "48")),
        refresh_mode=env("FLEETBI_REFRESH_MODE", "log"),
        pbi_workspace_id=env("FLEETBI_PBI_WORKSPACE_ID", ""),
        pbi_dataset_id=env("FLEETBI_PBI_DATASET_ID", ""),
    )
