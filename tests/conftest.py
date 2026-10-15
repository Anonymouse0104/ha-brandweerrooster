"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.brandweerrooster.const import (
    CONF_MONITORED_GROUP_IDS,
    CONF_MONITORED_TASK_IDS,
    CONF_PERSON_NAME,
    CONF_STATION_GROUP_ID,
    DOMAIN,
    SUBENTRY_PROFILE,
)

USER = {"id": 7, "name": "Jan Jansen", "email": "jan@example.com", "phone": "0612345678"}
GROUPS = [{"id": 100, "name": "Brandweer Echt TS"}, {"id": 200, "name": "Ploeg 2"}, {"id": 300, "name": "Venlo"}]
TASKS = [{"id": 11, "name": "TS Echt"}]
SKILLS = [{"id": 1, "name": "Bevelvoerder"}, {"id": 2, "name": "Chauffeur"}, {"id": 3, "name": "Manschap"}]


def make_incident(incident_id: int = 3010161, *, assigned: bool = True, group: int = 100) -> dict[str, Any]:
    incident: dict[str, Any] = {
        "id": incident_id,
        "body": "P 1 BDH-01 BR woning Kerkstraat Echt 235331 235371",
        # Field names and values as documented in the Brandweerrooster API v2.
        "prio": "prio1",
        "state": "alerted",
        "type": "incident_alert",
        "created_at": "2026-03-31T22:30:00Z",
        "start_time": "2026-03-31T22:30:00Z",
        "groups": [group],
        "task_ids": [11],
        "address": {"latitude": 51.1, "longitude": 5.87, "formatted_address": "Kerkstraat 1, Echt"},
        "incident_responses": [
            {"id": 1, "user_id": 7, "user_name": "Jan Jansen", "status": "acknowledged", "reported_status": "unknown"},
            {"id": 2, "user_id": 8, "user_name": "Piet", "status": "acknowledged", "reported_status": "dispatched"},
            {"id": 3, "user_id": 9, "user_name": "Klaas", "status": "rejected", "reported_status": "unknown"},
        ],
        "incident_skill_assignments": [],
    }
    if assigned:
        incident["incident_skill_assignments"] = [
            {"user_id": 7, "skill_ids": [1]},
            {"user_id": 8, "skill_ids": [2]},
        ]
    return incident


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Enable loading the custom integration."""


@pytest.fixture
def mock_api() -> Generator[dict[str, AsyncMock]]:
    """Patch the API client methods."""
    base = "custom_components.brandweerrooster.api.BrandweerRoosterApi"
    with (
        patch(f"{base}.async_authenticate", new=AsyncMock()) as auth,
        patch(f"{base}.async_test_connection", new=AsyncMock(return_value=USER)) as test_connection,
        patch(f"{base}.async_get_current_user", new=AsyncMock(return_value=USER)) as current_user,
        patch(f"{base}.async_get_groups", new=AsyncMock(return_value=GROUPS)) as groups,
        patch(f"{base}.async_get_tasks", new=AsyncMock(return_value=TASKS)) as tasks,
        patch(f"{base}.async_get_skills", new=AsyncMock(return_value=SKILLS)) as skills,
        patch(f"{base}.async_get_incidents", new=AsyncMock(return_value=[])) as incidents,
        patch(f"{base}.async_get_incident", new=AsyncMock(return_value=make_incident())) as incident,
    ):
        yield {
            "auth": auth,
            "test_connection": test_connection,
            "current_user": current_user,
            "groups": groups,
            "tasks": tasks,
            "skills": skills,
            "incidents": incidents,
            "incident": incident,
        }


def profile_subentry(name: str, groups: list[int], tasks: list[int] | None = None, mode: str = "response") -> dict:
    return {
        "subentry_type": SUBENTRY_PROFILE,
        "title": name,
        "unique_id": None,
        "data": {"group_ids": groups, "task_ids": tasks or [], "turnout_mode": mode, "crew_min_size": 6},
    }


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """An account with one function profile, as created by version 1.5."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Brandweerrooster (Jan Jansen)",
        unique_id="jan@example.com",
        data={"username": "jan@example.com", "password": "geheim"},
        options={
            CONF_PERSON_NAME: "Jan Jansen",
            "incident_entity": "sensor.incidents",
            "brandbase": False,
            "vehicle_names": "",
        },
        subentries_data=[profile_subentry("TS Echt", [100])],
    )


@pytest.fixture
def legacy_entry() -> MockConfigEntry:
    """A pre-1.5 entry: one function in the entry itself."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=1,
        title="Brandweer Echt TS (100)",
        unique_id="jan@example.com",
        data={
            "username": "jan@example.com",
            "password": "geheim",
            CONF_STATION_GROUP_ID: 100,
            CONF_MONITORED_GROUP_IDS: [100],
            CONF_MONITORED_TASK_IDS: [],
            CONF_PERSON_NAME: "Jan Jansen",
        },
        options={"crew_min_size": 4, "turnout_mode": "duty", "facebook_template": "Eigen {kazerne}"},
    )
