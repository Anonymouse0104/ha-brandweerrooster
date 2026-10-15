"""A function profile (OvD West, TS Echt, ...): a subentry with its own sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CREW_MIN_SIZE,
    CONF_GROUP_IDS,
    CONF_LEGACY_IDS,
    CONF_TASK_IDS,
    CONF_TURNOUT_MODE,
    DEFAULT_CREW_MIN_SIZE,
    TURNOUT_MODE_RESPONSE,
)
from .incident import incident_groups, incident_tasks, int_set
from .statistics import PersonalIncidentStatistics


class Profile:
    """Settings, latest incident and statistics of one function."""

    def __init__(self, hass: HomeAssistant, entry_id: str, subentry: ConfigSubentry) -> None:
        data = subentry.data
        self.subentry_id = subentry.subentry_id
        self.name = subentry.title
        self.group_ids_ordered = [int(x) for x in data.get(CONF_GROUP_IDS, [])]
        self.group_ids = int_set(self.group_ids_ordered)
        self.task_ids = int_set(data.get(CONF_TASK_IDS, []))
        self.turnout_mode = str(data.get(CONF_TURNOUT_MODE) or TURNOUT_MODE_RESPONSE)
        self.crew_min_size = int(data.get(CONF_CREW_MIN_SIZE) or DEFAULT_CREW_MIN_SIZE)
        legacy = bool(data.get(CONF_LEGACY_IDS))
        # The profile migrated from a pre-1.5 entry keeps the old unique ids
        # (so entity ids, history and dashboards stay) and statistics storage.
        self.unique_prefix = entry_id if legacy else subentry.subentry_id
        self.storage_id = entry_id if legacy else subentry.subentry_id
        self.statistics = PersonalIncidentStatistics(hass, self.storage_id)
        self.latest_incident: dict[str, Any] | None = None
        # The incident shown before a FireServiceRota fallback was applied,
        # restored when the API shows the alarm wasn't for this profile.
        self.previous_incident: dict[str, Any] | None = None
        self.counts: dict[str, Any] = {}

    @property
    def station_group_id(self) -> int:
        """The first chosen group names the station in dispatch messages."""
        return self.group_ids_ordered[0] if self.group_ids_ordered else 0

    def is_relevant(self, incident: dict[str, Any]) -> bool:
        if not (self.group_ids or self.task_ids):
            return True
        if incident_groups(incident) & self.group_ids:
            return True
        return bool(incident_tasks(incident) & self.task_ids)
