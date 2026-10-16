"""End-to-end tests with a running Home Assistant instance."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA as BLUEPRINT_SCHEMA
from homeassistant.components.blueprint import models as blueprint_models
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.brandweerrooster import brandbase
from custom_components.brandweerrooster.api import (
    BrandweerRoosterAuthenticationError,
    BrandweerRoosterRateLimitError,
)
from custom_components.brandweerrooster.const import CONF_FACEBOOK_TEMPLATE, DOMAIN, SUBENTRY_PROFILE
from custom_components.brandweerrooster.diagnostics import async_get_config_entry_diagnostics
from custom_components.brandweerrooster.profile import Profile

from .conftest import make_incident, profile_subentry

BLUEPRINTS = Path(__file__).parent.parent / "custom_components" / DOMAIN / "blueprints"


def _entity_id(hass: HomeAssistant, platform: str, key: str, prefix: str | None = None) -> str:
    registry = er.async_get(hass)
    return next(
        entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == DOMAIN
        and entry.domain == platform
        and entry.unique_id.endswith(f"_{key}")
        and (prefix is None or entry.unique_id.startswith(prefix))
    )


def _profile(entry: MockConfigEntry, name: str | None = None) -> Profile:
    profiles = entry.runtime_data.coordinator.profiles.values()
    return next(p for p in profiles if name is None or p.name == name)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_new_incident(hass: HomeAssistant, mock_api, config_entry) -> None:
    hass.states.async_set("sensor.incidents", "geen", {})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert CONF_FACEBOOK_TEMPLATE in config_entry.options

    latest = _entity_id(hass, "sensor", "latest_incident")
    assert hass.states.get(latest).state == "Geen incident"
    assert hass.states.get(_entity_id(hass, "binary_sensor", "api_online")).state == "on"

    # Before the first alarm nothing is "unknown" or "unavailable".
    platforms = ("sensor", "binary_sensor", "number", "button", "switch")
    for state in hass.states.async_all(platforms):
        if state.entity_id.startswith(platforms) and "button." not in state.entity_id:
            assert state.state not in ("unknown", "unavailable"), state
    assert hass.states.get(_entity_id(hass, "sensor", "last_alarm")).state == "Nog geen alarmering"
    assert hass.states.get(_entity_id(hass, "sensor", "last_turnout")).state == "Nog geen uitruk"
    assert hass.states.get(_entity_id(hass, "sensor", "incident_distance")).state == "Geen incident"
    assert hass.states.get(_entity_id(hass, "sensor", "response_rate_year")).state == "0.0"
    crew_complete = hass.states.get(_entity_id(hass, "binary_sensor", "crew_complete"))
    assert crew_complete.state == "off"
    assert crew_complete.attributes["status"] == "Geen incident"

    hass.states.async_set("sensor.incidents", "P 1 BR woning", {"id": 3010161})
    await hass.async_block_till_done()

    state = hass.states.get(latest)
    assert state.state == "Incident 3010161"
    # No Brandbase and no own names in this entry: vehicles stay unknown.
    assert state.attributes["voertuigen"] == []
    assert state.attributes["onbekende_voertuignummers"] == ["235331", "235371"]
    assert state.attributes["classificatie"] == "Woningbrand"

    event_state = hass.states.get(_entity_id(hass, "event", "new_incident"))
    assert event_state.attributes["event_type"] == "p1_incident"
    assert event_state.attributes["functie"] == "TS Echt"
    assert "Echt" in event_state.attributes["bericht"]
    assert event_state.attributes["afstand_km"] is not None

    assert hass.states.get(_entity_id(hass, "sensor", "crew")).state == "2"
    assert hass.states.get(_entity_id(hass, "binary_sensor", "crew_complete")).state == "off"
    assert hass.states.get(_entity_id(hass, "sensor", "uitrukken_totaal")).state == "1"
    assert hass.states.get(_entity_id(hass, "sensor", "uitrukken_totaal_alle")).state == "1"
    assert hass.states.get(_entity_id(hass, "sensor", "my_response")).state == "acknowledged"
    assert state.attributes["latitude"] == 51.1
    distance = hass.states.get(_entity_id(hass, "sensor", "incident_distance"))
    assert distance.state.endswith(" km")
    assert isinstance(distance.attributes["km"], float)
    last_alarm = hass.states.get(_entity_id(hass, "sensor", "last_alarm"))
    assert last_alarm.state == dt_util.as_local(dt_util.parse_datetime("2026-03-31T22:30:00Z")).strftime("%d-%m-%Y %H:%M")
    assert last_alarm.attributes["tijdstip"].startswith("20")
    assert hass.states.get(_entity_id(hass, "sensor", "last_turnout")).state != "Nog geen uitruk"
    assert hass.states.get(_entity_id(hass, "binary_sensor", "crew_complete")).attributes["status"] == "Niet compleet"
    assert "email" not in hass.states.get(_entity_id(hass, "sensor", "current_user")).attributes

    # Same incident again does not refetch.
    calls = mock_api["incident"].await_count
    hass.states.async_set("sensor.incidents", "P 1 BR woning", {"id": 3010161, "x": 1})
    await hass.async_block_till_done()
    assert mock_api["incident"].await_count == calls

    # Profile entities hang under the profile device, account entities under the account device.
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    profile_device = dev_reg.async_get(ent_reg.async_get(latest).device_id)
    account_device = dev_reg.async_get(ent_reg.async_get(_entity_id(hass, "binary_sensor", "api_online")).device_id)
    assert profile_device.name == "TS Echt"
    assert account_device.name == "Brandweerrooster (Jan Jansen)"

    installed = Path(hass.config.path("blueprints", "automation", DOMAIN))
    assert (installed / "brandweerrooster_melding.yaml").exists()

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"
    assert diagnostics["profiles"]["TS Echt"]["statistics"]["recorded_incidents"] == 1

    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_two_profiles(hass: HomeAssistant, mock_api) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Brandweerrooster",
        unique_id="jan@example.com",
        data={"username": "jan@example.com", "password": "geheim"},
        options={"person_name": "Jan Jansen", "incident_entity": "sensor.incidents", "brandbase": False},
        subentries_data=[
            profile_subentry("TS Echt", [100]),
            profile_subentry("OvD West", [5588], [7121], mode="duty"),
        ],
    )
    hass.states.async_set("sensor.incidents", "geen", {})
    await _setup(hass, entry)
    ts, ovd = _profile(entry, "TS Echt"), _profile(entry, "OvD West")

    ts_latest = _entity_id(hass, "sensor", "latest_incident", ts.unique_prefix)
    ovd_latest = _entity_id(hass, "sensor", "latest_incident", ovd.unique_prefix)

    # Only the standby function has a "Piketdienst" switch.
    duty_switch = _entity_id(hass, "switch", "standby_duty", ovd.unique_prefix)
    assert not [
        e for e in er.async_get(hass).entities.values()
        if e.domain == "switch" and e.unique_id.startswith(ts.unique_prefix)
    ]
    assert hass.states.get(duty_switch).state == "off"

    def ovd_incident(number: int) -> dict:
        incident = make_incident(number, group=6101)
        incident["created_at"] = incident["start_time"] = dt_util.utcnow().isoformat()
        incident["task_ids"] = [7121]
        incident["incident_responses"][0].update({"status": "expired", "on_duty": False})
        return incident

    # An OvD alarm (task 7121) only reaches the OvD profile; switch off -> not counted.
    mock_api["incident"].return_value = ovd_incident(49)
    hass.states.async_set("sensor.incidents", "OvD", {"id": 49})
    await hass.async_block_till_done()
    assert hass.states.get(ovd_latest).state == "Incident 49"
    assert hass.states.get(ts_latest).state == "Geen incident"
    assert "49" not in ovd.statistics.events
    ovd_event = hass.states.get(_entity_id(hass, "event", "new_incident", ovd.unique_prefix))
    assert ovd_event.attributes["functie"] == "OvD West"
    assert ovd_event.attributes["piketdienst"] is False

    # Switch on -> the next OvD alarm counts, whatever Brandweerrooster says about on_duty.
    await hass.services.async_call("switch", "turn_on", {"entity_id": duty_switch}, blocking=True)
    assert hass.states.get(duty_switch).state == "on"
    mock_api["incident"].return_value = ovd_incident(50)
    hass.states.async_set("sensor.incidents", "OvD", {"id": 50})
    await hass.async_block_till_done()
    assert ovd.statistics.events["50"]["type"] == "opgekomen_ingedeeld"
    assert hass.states.get(_entity_id(hass, "event", "new_incident", ovd.unique_prefix)).attributes["piketdienst"] is True

    # An incident for both profiles counts once in the combined total.
    both = make_incident(51, group=100)
    both["created_at"] = both["start_time"] = dt_util.utcnow().isoformat()
    both["task_ids"] = [7121]
    mock_api["incident"].return_value = both
    hass.states.async_set("sensor.incidents", "Beide", {"id": 51})
    await hass.async_block_till_done()
    assert hass.states.get(ts_latest).state == "Incident 51"
    assert hass.states.get(ovd_latest).state == "Incident 51"
    assert hass.states.get(_entity_id(hass, "sensor", "uitrukken_totaal", ts.unique_prefix)).state == "1"
    assert hass.states.get(_entity_id(hass, "sensor", "uitrukken_totaal", ovd.unique_prefix)).state == "2"
    combined = hass.states.get(_entity_id(hass, "sensor", "uitrukken_totaal_alle"))
    assert combined.state == "2"
    assert combined.attributes["per_functieprofiel"] == {"TS Echt": 1, "OvD West": 2}

    # Own corrections, e.g. turnouts from another system.
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": _entity_id(hass, "number", "correction_total", ts.unique_prefix), "value": 100},
        blocking=True,
    )
    ts_total = hass.states.get(_entity_id(hass, "sensor", "uitrukken_totaal", ts.unique_prefix))
    assert ts_total.state == "101"
    assert ts_total.attributes["geteld"] == 1
    assert ts_total.attributes["correctie"] == 100
    assert hass.states.get(_entity_id(hass, "sensor", "uitrukken_totaal_alle")).state == "102"

    # The duty periods and corrections survive a reload.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(duty_switch).state == "on"
    assert hass.states.get(_entity_id(hass, "number", "correction_total", ts.unique_prefix)).state == "100"

    response = await hass.services.async_call(
        DOMAIN, "generate_message", {"functie": "ovd west"}, blocking=True, return_response=True
    )
    assert response["functie"] == "OvD West"
    assert response["incident_id"] == 51
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_migration_from_single_entry(hass: HomeAssistant, mock_api, legacy_entry) -> None:
    legacy_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=legacy_entry.entry_id, identifiers={(DOMAIN, legacy_entry.entry_id)}, name="Brandweer Echt TS (100)"
    )
    old_latest = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{legacy_entry.entry_id}_latest_incident",
        config_entry=legacy_entry, device_id=device.id, suggested_object_id="echt_laatste_incident",
    )
    old_api = ent_reg.async_get_or_create(
        "binary_sensor", DOMAIN, f"{legacy_entry.entry_id}_api_online",
        config_entry=legacy_entry, device_id=device.id, suggested_object_id="echt_api_beschikbaar",
    )
    retired = [
        ent_reg.async_get_or_create(
            "geo_location", DOMAIN, f"{legacy_entry.entry_id}_incident_location", config_entry=legacy_entry
        ),
        ent_reg.async_get_or_create("sensor", DOMAIN, f"{legacy_entry.entry_id}_api_diagnostic", config_entry=legacy_entry),
    ]

    hass.states.async_set("sensor.incidents", "P 1 BR woning", {"id": 3010161})
    assert await hass.config_entries.async_setup(legacy_entry.entry_id)
    await hass.async_block_till_done()

    assert legacy_entry.version == 2
    assert legacy_entry.title == "Brandweerrooster"
    assert set(legacy_entry.data) == {"username", "password"}
    assert legacy_entry.options["facebook_template"] == "Eigen {kazerne}"
    assert legacy_entry.options["vehicle_names"] == ""
    subentry = next(iter(legacy_entry.subentries.values()))
    assert subentry.subentry_type == SUBENTRY_PROFILE
    assert subentry.title == "Brandweer Echt TS"
    assert subentry.data["group_ids"] == [100]
    assert subentry.data["turnout_mode"] == "duty"
    assert subentry.data["crew_min_size"] == 4

    # Same entity ids; profile entities moved to the profile.
    assert ent_reg.async_get(old_latest.entity_id).config_subentry_id == subentry.subentry_id
    assert ent_reg.async_get(old_api.entity_id).config_subentry_id is None
    assert hass.states.get(old_latest.entity_id).state == "Incident 3010161"
    assert hass.states.get(old_api.entity_id).state == "on"
    # Entities of earlier versions that no longer exist are cleaned up.
    assert all(ent_reg.async_get(entity.entity_id) is None for entity in retired)
    assert _profile(legacy_entry).unique_prefix == legacy_entry.entry_id
    assert await hass.config_entries.async_unload(legacy_entry.entry_id)


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
    assert "1" in _profile(config_entry).statistics.events

    # A new incident during the rate-limit is still shown from FireServiceRota.
    hass.states.async_set("sensor.incidents", "P 2 BR buiten Kraanbergweg Herkenbosch", {"id": 2, "prio": 2})
    await hass.async_block_till_done()
    state = hass.states.get(_entity_id(hass, "sensor", "latest_incident"))
    assert state.state == "Incident 2"
    assert state.attributes["bron"] == "FireServiceRota"
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_month_rollover(hass: HomeAssistant, mock_api, config_entry, freezer) -> None:
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-04-30T21:00:00+00:00")
    hass.states.async_set("sensor.incidents", "geen", {})
    await _setup(hass, config_entry)
    mock_api["incident"].return_value = {
        **make_incident(5), "created_at": "2026-04-30T10:00:00Z", "start_time": "2026-04-30T10:00:00Z"
    }
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
    assert config_entry.data["password"] == "nieuw2"
    assert config_entry.state is ConfigEntryState.LOADED
    assert "update listener" not in caplog.text
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_config_flow_options_and_profiles(hass: HomeAssistant, mock_api) -> None:
    hass.states.async_set("sensor.incidents", "geen", {"id": None})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "jan@example.com", "password": "geheim"}
    )
    assert result["step_id"] == "profile"
    base = {
        "person_name": "Jan Jansen",
        "incident_entity": "sensor.incidents",
        "name": "OvD West",
        "turnout_mode": "duty",
        "crew_min_size": 1,
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**base, "group_ids": [], "task_ids": []})
    assert result["errors"] == {"base": "no_scope"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**base, "group_ids": ["300"], "task_ids": []}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.title == "Brandweerrooster (Jan Jansen)"
    await hass.async_block_till_done()
    assert [p.name for p in entry.runtime_data.coordinator.profiles.values()] == ["OvD West"]

    # Account options.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    options = {
        "person_name": "Jan Jansen",
        "incident_entity": "sensor.fsr_incidents",
        "brandbase": False,
        "install_blueprints": False,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**options, "facebook_template": "Hallo {foo}", "vehicle_names": "onzin"}
    )
    assert result["errors"] == {"facebook_template": "template_unknown_placeholder", "vehicle_names": "vehicle_invalid"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**options, "facebook_template": "Alarm {kazerne}", "vehicle_names": "235331 = Tankautospuit"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    assert coordinator.incident_entity == "sensor.fsr_incidents"
    assert coordinator.vehicle_names == {"235331": "Tankautospuit"}
    assert coordinator.brandbase is None

    # Add a second function.
    result = await hass.config_entries.subentries.async_init((entry.entry_id, SUBENTRY_PROFILE), context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    profile_input = {"name": "TS Echt", "group_ids": ["100"], "task_ids": [], "turnout_mode": "response", "crew_min_size": 6}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {**profile_input, "name": "ovd west"})
    assert result["errors"] == {"name": "name_exists"}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], profile_input)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    assert sorted(p.name for p in coordinator.profiles.values()) == ["OvD West", "TS Echt"]
    ts = _profile(entry, "TS Echt")
    assert hass.states.get(_entity_id(hass, "sensor", "latest_incident", ts.unique_prefix)) is not None

    # Reconfigure it.
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PROFILE), context={"source": "reconfigure", "subentry_id": ts.subentry_id}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**profile_input, "name": "TS Echt 1", "crew_min_size": 4}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    ts = _profile(entry, "TS Echt 1")
    assert ts.crew_min_size == 4

    # Remove it: its entities and statistics go.
    hass.config_entries.async_remove_subentry(entry, ts.subentry_id)
    await hass.async_block_till_done()
    assert [p.name for p in entry.runtime_data.coordinator.profiles.values()] == ["OvD West"]
    assert not [
        e for e in er.async_get(hass).entities.values() if e.unique_id.startswith(ts.unique_prefix)
    ]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_services_and_buttons(hass: HomeAssistant, mock_api, config_entry) -> None:
    hass.states.async_set("sensor.incidents", "P 1 BR woning", {"id": 3010161})
    await _setup(hass, config_entry)
    response = await hass.services.async_call(DOMAIN, "generate_message", {}, blocking=True, return_response=True)
    assert response["incident_id"] == 3010161
    assert response["bericht"].startswith("🚒 Brandweer Echt uitgerukt – Woningbrand")

    calls = mock_api["incident"].await_count
    await hass.services.async_call(
        "button", "press", {"entity_id": _entity_id(hass, "button", "refresh_incident")}, blocking=True
    )
    assert mock_api["incident"].await_count == calls + 1

    mock_api["incidents"].return_value = [make_incident(9, group=300), make_incident(10)]
    await hass.services.async_call(DOMAIN, "resync_statistics", {}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    profile = _profile(config_entry)
    coordinator = config_entry.runtime_data.coordinator
    assert "10" in profile.statistics.events
    assert "9" not in profile.statistics.events
    assert profile.statistics.initialized
    report = coordinator.history_report
    assert report["status"] == "klaar"
    assert report["incidenten"] == 2
    assert report["relevant"] == 1
    assert report["met_jouw_reactie"] == 1
    assert report["jouw_statussen"] == {"acknowledged / unknown / dienst=None": 1}
    assert report["per_functie"]["TS Echt"]["relevant"] == 1
    assert report["voorbeelden_niet_relevant"] == [{"incident_id": 9, "groups": [300], "task_ids": [11]}]
    total = hass.states.get(_entity_id(hass, "sensor", "uitrukken_totaal"))
    assert total.attributes["historie_samenvatting"]["status"] == "klaar"

    # Pages with fewer items than requested are not the end; only an empty page is.
    other = [make_incident(1000 + n, group=300) for n in range(20)]
    mock_api["incidents"].side_effect = [other, [make_incident(12)], []]
    with patch("custom_components.brandweerrooster.coordinator.HISTORY_PAGE_DELAY", 0):
        await hass.services.async_call(DOMAIN, "resync_statistics", {}, blocking=True)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert "12" in profile.statistics.events
    assert coordinator.history_report["paginas"] == 2
    assert coordinator.history_report["incidenten"] == 21
    mock_api["incidents"].side_effect = None

    # List items without responses or scope fields are fetched in detail.
    mock_api["incidents"].return_value = [{"id": 11, "body": "P 1 BR woning"}]
    mock_api["incident"].return_value = make_incident(11)
    with patch("custom_components.brandweerrooster.coordinator.HISTORY_DETAIL_DELAY", 0):
        await hass.services.async_call(DOMAIN, "resync_statistics", {}, blocking=True)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert "11" in profile.statistics.events
    assert coordinator.history_report["details_opgehaald"] == 1
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_brandbase_vehicle_names(hass: HomeAssistant, mock_api, config_entry, aioclient_mock) -> None:
    aioclient_mock.get(
        brandbase.INDEX_URL,
        text='<a href="https://brandbase.hetbrandweerforum.nl/voertuigen/regio/23-brandweer-limburg-noord/">VRLN</a>',
    )
    aioclient_mock.get(
        "https://brandbase.hetbrandweerforum.nl/voertuigen/regio/23-brandweer-limburg-noord/",
        text=(
            "<h3>23-53 Echt</h3><ul>"
            '<li><a href="https://brandbase.hetbrandweerforum.nl/voertuigen/23-5331-x/">23-5331 Tankautospuit Terreinvaardig</a></li>'
            '<li><a href="https://brandbase.hetbrandweerforum.nl/voertuigen/23-5371-x/">23-5371 Hulpverleningsvoertuig Terreinvaardig</a></li>'
            "</ul>"
        ),
    )
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, "brandbase": True, "vehicle_names": "235371 = Redding Echt"}
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    with patch.object(brandbase, "_sleep", no_sleep):
        hass.states.async_set("sensor.incidents", "P 1 BR woning", {"id": 3010161})
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    state = hass.states.get(_entity_id(hass, "sensor", "latest_incident"))
    # Own name wins; Brandbase provides the rest.
    assert state.attributes["voertuigen"] == ["TST Echt", "Redding Echt"]
    assert state.attributes["onbekende_voertuignummers"] == []
    assert aioclient_mock.call_count == 2
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
        blueprint = blueprint_models.Blueprint(load_yaml(path), expected_domain="automation", schema=BLUEPRINT_SCHEMA)
        assert blueprint.metadata["source_url"].endswith(path.name)

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
