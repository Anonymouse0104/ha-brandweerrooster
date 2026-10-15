"""Constants for the Brandweerrooster API integration."""

from __future__ import annotations

DOMAIN = "brandweerrooster"

API_BASE_URL = "https://www.brandweerrooster.nl/api/v2"
OAUTH_TOKEN_URL = "https://www.brandweerrooster.nl/oauth/token"
API_TIMEOUT = 20

CONF_STATION_GROUP_ID = "station_group_id"
CONF_MONITORED_GROUP_IDS = "monitored_group_ids"
CONF_MONITORED_TASK_IDS = "monitored_task_ids"
CONF_PERSON_NAME = "person_name"
CONF_INCIDENT_ENTITY = "incident_entity"
CONF_CREW_MIN_SIZE = "crew_min_size"
CONF_FACEBOOK_TEMPLATE = "facebook_template"
CONF_VEHICLE_NAMES = "vehicle_names"
CONF_INSTALL_BLUEPRINTS = "install_blueprints"

CONF_TURNOUT_MODE = "turnout_mode"
# How a turnout is determined for the personal statistics:
# - response: you confirmed your turnout in the app (crew members)
# - duty: every alarm you received while on duty (OvD and other standby duties,
#   who don't confirm their turnout in the app)
TURNOUT_MODE_RESPONSE = "response"
TURNOUT_MODE_DUTY = "duty"
TURNOUT_MODES = [TURNOUT_MODE_RESPONSE, TURNOUT_MODE_DUTY]

DEFAULT_INCIDENT_ENTITY = "sensor.incidents"
DEFAULT_CREW_MIN_SIZE = 6

PLATFORMS = ["binary_sensor", "button", "event", "geo_location", "sensor"]

# Throttling for the one-time history synchronisation.
HISTORY_PAGE_SIZE = 50  # the API returns at most 50 incidents per page
HISTORY_PAGE_DELAY = 2.0
HISTORY_DETAIL_DELAY = 0.5
HISTORY_MAX_PAGES = 1000
# Retry a paused history sync after this many seconds when the API does not
# send a Retry-After header.
RATE_LIMIT_DEFAULT_RETRY = 900

# Bounded retry schedule (seconds between attempts) used after a new incident
# to pick up crew assignments and responses that are added later.
ENRICHMENT_DELAYS = (15, 30, 60, 120, 300, 600, 1200)

# How long to wait for the FireServiceRota entity after start-up before
# raising a repair issue.
INCIDENT_ENTITY_GRACE_PERIOD = 120

# Statistics data schema. Bumping this triggers a one-time re-sync of history
# so new per-incident fields are filled for older incidents as well.
STATISTICS_SCHEMA = 3

SERVICE_GENERATE_MESSAGE = "generate_message"
SERVICE_REFRESH_INCIDENT = "refresh_incident"
SERVICE_RESYNC_STATISTICS = "resync_statistics"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_TEMPLATE = "template"
