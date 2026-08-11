"""Constants for the Brandweerrooster API integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "brandweerrooster"
VERSION = "1.1.8"

API_BASE_URL = "https://www.brandweerrooster.nl/api/v2"
OAUTH_TOKEN_URL = "https://www.brandweerrooster.nl/oauth/token"
API_TIMEOUT = 20

CONF_STATION_GROUP_ID = "station_group_id"
CONF_MONITORED_GROUP_IDS = "monitored_group_ids"
CONF_MONITORED_TASK_IDS = "monitored_task_ids"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_PERSON_NAME = "person_name"

DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 300
HISTORY_PAGE_DELAY = 1.0
FIRESERVICEROTA_INCIDENT_ENTITY = "sensor.incidents"
DEFAULT_HISTORY_SIZE = 10

PLATFORMS = ["sensor", "binary_sensor"]
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

ATTR_INCIDENT_ID = "incident_id"
ATTR_INCIDENT = "incident"
ATTR_PERSONNEL = "personnel"
ATTR_RESPONSES = "responses"
ATTR_CURRENT_USER = "current_user"
