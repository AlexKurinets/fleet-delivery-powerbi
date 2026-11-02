"""The refresh adapter sends the request the Power BI REST API expects (against a mock transport)."""

import json

import httpx
import pytest

from fleetbi.refresh import LogRefresher, PowerBIRefresher


def test_power_bi_refresh_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(202, headers={"RequestId": "req-1"})

    r = PowerBIRefresher("ws-1", "ds-1", "token-1", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert r.refresh(7) == "triggered"
    assert seen["url"] == "https://api.powerbi.com/v1.0/myorg/groups/ws-1/datasets/ds-1/refreshes"
    assert seen["auth"] == "Bearer token-1"
    assert seen["body"]["applyRefreshPolicy"] is True and seen["body"]["commitMode"] == "transactional"


def test_power_bi_refresh_failure_raises():
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(400, text="bad dataset")))
    with pytest.raises(RuntimeError, match="400"):
        PowerBIRefresher("ws", "ds", "t", http=client).refresh(1)


def test_power_bi_refresh_needs_ids():
    with pytest.raises(ValueError):
        PowerBIRefresher("", "ds", "t")


def test_log_refresher_is_the_default():
    assert LogRefresher().refresh(1) == "not configured"
