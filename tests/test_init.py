"""End-to-end tests with a running Home Assistant instance."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA as BLUEPRINT_SCHEMA
from homeassistant.components.blueprint import models as blueprint_models
from homeassistant.setup import async_setup_component
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.brandweerrooster.api import (
    BrandweerRoosterAuthenticationError,
    BrandweerRoosterRateLimitError,
)
from custom_components.brandweerrooster.const import (
    CONF_FACEBOOK_TEMPLATE,
    CONF_INCIDENT_ENTITY,
    CONF_VEHICLE_NAMES,
    DOMAIN,
)
from custom_components.brandweerrooster.diagnostics import async_get_config_entry_diagnostics

from .conftest import make_incident

BLUEPRINTS = Path(__file__).parent.parent / "custom_components" / DOMAIN / "blueprints"


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = next(
        entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == DOMAIN and entry.domain == platform and entry.unique_id.endswith(f"_{key}")
    )
    return entity_id


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_new_incident(hass: HomeAssistant, mock_api, config_entry) -> None:
    hass.states.async_set("sensor.incidents", "geen", {})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    # Old YAML template absent -> default stored in options.
    assert CONF_FACEBOOK_TEMPLATE in config_entry.options

    latest = _entity_id(hass, "sensor", "latest_incident")
    assert hass.states.get(latest).state == "Geen incident"
    assert hass.states.get(_entity_id(hass, "binary_sensor", "api_online")).state == "on"

    hass.states.async_set("sensor.incidents", "P 1 BR woning", {"id": 3010161})
    await hass.async_block_till_done()

    state = hass.states.get(latest)
    assert state.state == "Incident 3010161"
    assert state.attributes["voertuigen"] == ["TS Echt", "HV Echt"]
    assert state.attributes["classificatie"] == "Woningbrand"

    event_state = hass.states.get(_entity_id(hass, "event", "new_incident"))
    assert event_state.attributes["event_type"] == "p1_incident"
    assert "Echt" in event_state.attributes["bericht"]
    assert event_state.attributes["afstand_km"] is not None

    assert hass.states.get(_entity_id(hass, "sensor", "crew")).state == "2"
    assert hass.states.get(_entity_id(hass, "binary_sensor", "crew_complete")).state == "off"
    assert hass.states.get(_entity_id(hass, "sensor", "uitrukken_totaal")).state == "1"
    assert hass.states.get(_entity_id(hass, "sensor", "my_response")).state == "acknowledged"
    geo = hass.states.get(_entity_id(hass, "geo_location", "incident_location"))
    assert geo.attributes["latitude"] == 51.1

    user_state = hass.states.get(_entity_id(hass, "sensor", "current_user"))
    assert "email" not in user_state.attributes

    # Same incident again does not refetch.
    calls = mock_api["incident"].await_count
    hass.states.async_set("sensor.incidents", "P 1 BR woning", {"id": 3010161, "x": 1})
    await hass.async_block_till_done()
    assert mock_api["incident"].await_count == calls

    # Blueprints were installed.
    installed = Path(hass.config.path("blueprints", "automation", DOMAIN))
    assert (installed / "brandweerrooster_melding.yaml").exists()

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"

    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_rate_limit_keeps_statistics(hass: HomeAssistant, mock_api, config_entry) -> None:
    hass.states.async_set("sensor.incidents", "geen", {})
    await _setup(hass, config_entry)
    mock_api["incident"].return_value = make_incident(1)
    hass.states.async_set("sensor.incidents", "P 1 BR woning", {"id": 1})
    await hass.async_block_till_done()
    total = _entity_id(hass, "sensor", "uitrukken_totaal")
    assert hass.states.get(total).state == "1"

    coordinator = config_entry.runtime_data.coordinator
    mock_api["incident"].side_effect = BrandweerRoosterRateLimitError("slow down", 30)
    await coordinator.async_process_incident(1, force=True)
    await hass.async_block_till_done()
    assert hass.states.get(total).state == "1"
    assert "1" in coordinator.statistics.events

    # A new incident during the rate-limit is still shown from FireServiceRota.
    hass.states.async_set("sensor.incidents", "P 2 BR buiten Kraanbergweg Herkenbosch", {"id": 2, "prio": 2})
    await hass.async_block_till_done()
    state = hass.states.get(_entity_id(hass, "sensor", "latest_incident"))
    assert state.state == "Incident 2"
    assert state.attributes["bron"] == "FireServiceRota"
    assert hass.states.get(_entity_id(hass, "binary_sensor", "api_online")).state in ("on", "off")
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_month_rollover(hass: HomeAssistant, mock_api, config_entry, freezer) -> None:
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-04-30T21:00:00+00:00")
    hass.states.async_set("sensor.incidents", "geen", {})
    await _setup(hass, config_entry)
    mock_api["incident"].return_value = {**make_incident(5), "created_at": "2026-04-30T10:00:00Z", "start_time": "2026-04-30T10:00:00Z"}
    hass.states.async_set("sensor.incidents", "P 1 BR woning", {"id": 5})
    await hass.async_block_till_done()
    month = _entity_id(hass, "sensor", "uitrukken_maand")
    assert hass.states.get(month).state == "1"

    freezer.move_to("2026-04-30T22:00:10+00:00")  # 1 May 00:00:10 local
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(month).state == "0"
    assert hass.states.get(_entity_id(hass, "sensor", "uitrukken_vorige_maand")).state == "1"
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_auth_failure_starts_reauth(hass: HomeAssistant, mock_api, config_entry) -> None:
    mock_api["auth"].side_effect = BrandweerRoosterAuthenticationError("nope")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flows and flows[0]["context"]["source"] == "reauth"

    mock_api["auth"].side_effect = None
    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"password": "nieuw"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["password"] == "nieuw"
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_reauth_while_loaded(hass: HomeAssistant, mock_api, config_entry, caplog) -> None:
    hass.states.async_set("sensor.incidents", "geen", {})
    await _setup(hass, config_entry)
    config_entry.async_start_reauth(hass)
    await hass.async_block_till_done()
    flow = hass.config_entries.flow.async_progress_by_handler(DOMAIN)[0]
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"password": "nieuw2"})
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert "update listener" not in caplog.text
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_config_and_options_flow(hass: HomeAssistant, mock_api) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "jan@example.com", "password": "geheim"}
    )
    assert result["step_id"] == "scope"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "person_name": "Jan Jansen",
            "station_group_id": "100",
            "monitored_group_ids": [],
            "monitored_task_ids": [],
            "incident_entity": "sensor.incidents",
            "crew_min_size": 6,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.title == "Brandweer Echt TS (100)"
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    base = {
        "person_name": "Jan Jansen",
        "station_group_id": "100",
        "monitored_group_ids": ["300"],
        "monitored_task_ids": [],
        "incident_entity": "sensor.fsr_incidents",
        "crew_min_size": 4,
        "turnout_mode": "duty",
        "install_blueprints": False,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, "facebook_template": "Hallo {foo}", "vehicle_names": "onzin"}
    )
    assert result["errors"] == {"facebook_template": "template_unknown_placeholder", "vehicle_names": "vehicle_invalid"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, "facebook_template": "Alarm {kazerne}", "vehicle_names": "235331 = Tankautospuit"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_INCIDENT_ENTITY] == "sensor.fsr_incidents"
    assert entry.options[CONF_VEHICLE_NAMES] == "235331 = Tankautospuit"
    coordinator = entry.runtime_data.coordinator
    assert coordinator.monitored_group_ids == {100, 300}
    assert coordinator.crew_min_size == 4
    assert coordinator.turnout_mode == "duty"
    assert coordinator.statistics.mode == "duty"
    assert coordinator.vehicle_names == {"235331": "Tankautospuit"}


async def test_services_and_buttons(hass: HomeAssistant, mock_api, config_entry) -> None:
    hass.states.async_set("sensor.incidents", "P 1 BR woning", {"id": 3010161})
    await _setup(hass, config_entry)
    response = await hass.services.async_call(DOMAIN, "generate_message", {}, blocking=True, return_response=True)
    assert response["incident_id"] == 3010161
    assert response["bericht"].startswith("🚒 Brandweer Echt uitgerukt – Woningbrand")

    response = await hass.services.async_call(
        DOMAIN, "generate_message", {"template": "{voertuigen}"}, blocking=True, return_response=True
    )
    assert response["bericht"] == "TS Echt, HV Echt"

    calls = mock_api["incident"].await_count
    await hass.services.async_call(
        "button", "press", {"entity_id": _entity_id(hass, "button", "refresh_incident")}, blocking=True
    )
    assert mock_api["incident"].await_count == calls + 1

    mock_api["incidents"].return_value = [make_incident(9, group=300), make_incident(10)]
    await hass.services.async_call(DOMAIN, "resync_statistics", {}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = config_entry.runtime_data.coordinator
    assert "10" in coordinator.statistics.events
    assert "9" not in coordinator.statistics.events
    assert coordinator.statistics.initialized
    report = coordinator.history_report
    assert report["status"] == "klaar"
    assert report["incidenten"] == 2
    assert report["relevant"] == 1
    assert report["met_jouw_reactie"] == 1
    assert report["jouw_statussen"] == {"acknowledged / unknown / dienst=None": 1}
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diagnostics["statistics"]["recorded_by_status"]["acknowledged"] >= 1
    assert report["voorbeelden_niet_relevant"] == [{"incident_id": 9, "groups": [300], "task_ids": [11]}]
    total = hass.states.get(_entity_id(hass, "sensor", "uitrukken_totaal"))
    assert total.attributes["historie_samenvatting"]["status"] == "klaar"

    # Pages with fewer items than requested are not the end; only an empty page is.
    other = [make_incident(1000 + n, group=300) for n in range(20)]
    mock_api["incidents"].side_effect = [other, [make_incident(12)], []]
    with patch("custom_components.brandweerrooster.coordinator.HISTORY_PAGE_DELAY", 0):
        await hass.services.async_call(DOMAIN, "resync_statistics", {}, blocking=True)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert "12" in coordinator.statistics.events
    assert coordinator.history_report["paginas"] == 2
    assert coordinator.history_report["incidenten"] == 21
    mock_api["incidents"].side_effect = None

    # List items without responses or scope fields are fetched in detail.
    bare = {"id": 11, "body": "P 1 BR woning"}
    mock_api["incidents"].return_value = [bare]
    mock_api["incident"].return_value = make_incident(11)
    with patch("custom_components.brandweerrooster.coordinator.HISTORY_DETAIL_DELAY", 0):
        await hass.services.async_call(DOMAIN, "resync_statistics", {}, blocking=True)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert "11" in coordinator.statistics.events
    assert coordinator.history_report["details_opgehaald"] == 1
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_missing_incident_entity_raises_issue(hass: HomeAssistant, mock_api, config_entry) -> None:
    with patch("custom_components.brandweerrooster.coordinator.STARTUP_POLL_INTERVAL", 0):
        await _setup(hass, config_entry)
        await hass.async_block_till_done(wait_background_tasks=True)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"incident_entity_missing_{config_entry.entry_id}")
    hass.states.async_set("sensor.incidents", "geen", {})
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, f"incident_entity_missing_{config_entry.entry_id}") is None
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_legacy_template_is_imported(hass: HomeAssistant, mock_api, config_entry) -> None:
    path = Path(hass.config.path("brandweerrooster", "facebook_template.yaml"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("facebook_template: |\n  Eigen tekst {kazerne}\n", encoding="utf-8")
    try:
        hass.states.async_set("sensor.incidents", "geen", {})
        await _setup(hass, config_entry)
    finally:
        path.unlink()
    assert config_entry.options[CONF_FACEBOOK_TEMPLATE] == "Eigen tekst {kazerne}"
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_blueprints_are_valid(hass: HomeAssistant, mock_api, config_entry) -> None:
    paths = sorted(BLUEPRINTS.glob("*.yaml"))
    assert len(paths) == 3
    for path in paths:
        blueprint = blueprint_models.Blueprint(
            load_yaml(path), expected_domain="automation", schema=BLUEPRINT_SCHEMA
        )
        assert blueprint.metadata["source_url"].endswith(path.name)

    # Instantiate the night alarm blueprint (no external devices needed).
    hass.states.async_set("sensor.incidents", "geen", {})
    await _setup(hass, config_entry)
    event_entity = _entity_id(hass, "event", "new_incident")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "nacht",
                "use_blueprint": {
                    "path": "brandweerrooster/brandweerrooster_nachtalarm.yaml",
                    "input": {"incident_event": event_entity, "lights": {"entity_id": "light.gang"}},
                },
            }
        },
    )
    await hass.async_block_till_done()
    automations = hass.states.async_all("automation")
    assert len(automations) == 1
    assert automations[0].state == "on", automations[0]
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_enrichment_updates_crew(hass: HomeAssistant, mock_api, config_entry) -> None:
    hass.states.async_set("sensor.incidents", "geen", {})
    await _setup(hass, config_entry)
    mock_api["incident"].return_value = make_incident(20, assigned=False)
    with patch("custom_components.brandweerrooster.coordinator.ENRICHMENT_DELAYS", (0.2, 0.01, 0.01)):
        hass.states.async_set("sensor.incidents", "P 1 BR woning", {"id": 20})
        await hass.async_block_till_done()
        crew = _entity_id(hass, "sensor", "crew")
        assert hass.states.get(crew).state == "0"

        mock_api["incident"].return_value = make_incident(20, assigned=True)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(crew).state == "2"
    assert await hass.config_entries.async_unload(config_entry.entry_id)
