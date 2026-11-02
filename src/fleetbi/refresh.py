"""The semantic model refresh, the last step of every run.

In production this was the Fabric pipeline's semantic model refresh activity. Here it is an adapter:
`LogRefresher` (the default) records that a refresh would be triggered, and `PowerBIRefresher` calls
the Power BI REST API's enhanced refresh with the incremental refresh policy applied. The REST call
is covered by a test against a mock transport; it has not been run against a live workspace here.
"""

from __future__ import annotations

import logging
import os

import httpx

from .config import Settings

log = logging.getLogger(__name__)
API = "https://api.powerbi.com/v1.0/myorg"


class LogRefresher:
    name = "log"

    def refresh(self, run_id: int) -> str:
        log.info("run %d: semantic model refresh would be triggered here (FLEETBI_REFRESH_MODE=log)", run_id)
        return "not configured"


class PowerBIRefresher:
    name = "powerbi"

    def __init__(self, workspace_id: str, dataset_id: str, token: str, http: httpx.Client | None = None):
        if not (workspace_id and dataset_id and token):
            raise ValueError("Power BI refresh needs a workspace id, a dataset id and an access token")
        self.url = f"{API}/groups/{workspace_id}/datasets/{dataset_id}/refreshes"
        self.http = http or httpx.Client(timeout=30)
        self.token = token

    def refresh(self, run_id: int) -> str:
        body = {"type": "full", "commitMode": "transactional", "applyRefreshPolicy": True, "retryCount": 1}
        resp = self.http.post(self.url, json=body, headers={"Authorization": f"Bearer {self.token}"})
        if resp.status_code != 202:
            raise RuntimeError(f"refresh request failed: {resp.status_code} {resp.text[:200]}")
        log.info("run %d: refresh accepted, request id %s", run_id, resp.headers.get("RequestId", "?"))
        return "triggered"


def from_settings(s: Settings):
    if s.refresh_mode == "powerbi":
        return PowerBIRefresher(s.pbi_workspace_id, s.pbi_dataset_id, os.environ.get("FLEETBI_PBI_TOKEN", ""))
    return LogRefresher()
