"""Tests for the pure helper modules."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.util import dt as dt_util

from custom_components.brandweerrooster import facebook_template
from custom_components.brandweerrooster.incident import (
    category,
    classification,
    crew_status,
    format_priority,
    incident_coordinates,
    incident_vehicles,
    personnel,
    response_is_negative,
    response_is_positive,
    response_status,
    response_summary,
    split_p2000,
    station_name,
)
from custom_components.brandweerrooster.statistics import (
    TYPE_ASSIGNED,
    TYPE_NO_TURNOUT,
    PersonalIncidentStatistics,
)
from custom_components.brandweerrooster.vehicles import (
    DEFAULT_VEHICLE_TEXT,
    invalid_vehicle_lines,
    parse_vehicle_names,
)

from .conftest import USER, make_incident

SKILLS = {1: "Bevelvoerder", 2: "Chauffeur", 3: "Manschap"}


def test_split_p2000_dashes() -> None:
    parsed = split_p2000("P 1 BR woning - Kerkstraat - Echt 235331")
    assert parsed == {"melding": "P 1 BR woning", "straat": "Kerkstraat", "plaats": "Echt", "locatie": "Kerkstraat - Echt"}


def test_split_p2000_street_suffix() -> None:
    parsed = split_p2000("P 2 BR buiten Kraanbergweg Herkenbosch 235331")
    assert parsed["locatie"] == "Kraanbergweg Herkenbosch"
    assert parsed["plaats"] == "Herkenbosch"


def test_classification_and_category() -> None:
    assert classification("BR woning") == "Woningbrand"
    assert category("BR woning") == "Brand"
    assert category("OMS automatische brandmelding") == "OMS / automatische melding"
    assert category("HV beknelling") == "Hulpverlening"
    assert category("iets anders") == "Overig"


def test_priority() -> None:
    assert format_priority(1) == "P1"
    assert format_priority("Prio 2") == "P2"
    assert format_priority(None) == ""


def test_coordinates_reject_zero() -> None:
    assert incident_coordinates({"latitude": 0, "longitude": 0}) == (None, None)
    assert incident_coordinates({"location": {"lat": "51.1", "lng": "5.8"}}) == (51.1, 5.8)


def test_vehicles_from_custom_mapping() -> None:
    incident = make_incident()
    assert incident_vehicles(incident) == ["TS Echt", "HV Echt"]
    assert incident_vehicles(incident, {"235331": "Tankspuit"}) == ["Tankspuit"]
    assert incident_vehicles(incident, {}) == []


def test_parse_vehicle_text() -> None:
    mapping = parse_vehicle_names("235331 = TS Echt\n# comment\n23-5371: HV Echt\n\n")
    assert mapping == {"235331": "TS Echt", "235371": "HV Echt"}
    assert invalid_vehicle_lines("235331 = TS\nonzin") == ["onzin"]
    assert parse_vehicle_names(DEFAULT_VEHICLE_TEXT)["235331"] == "TS Echt"


def test_personnel_and_crew_status() -> None:
    crew = personnel(make_incident(), SKILLS)
    assert [person["functie"] for person in crew] == ["Bevelvoerder", "Chauffeur"]
    assert crew[0]["naam"] == "Jan Jansen"
    status = crew_status(crew, 2)
    assert status["compleet"] is True
    status = crew_status(crew, 6)
    assert status["compleet"] is False
    assert "4 persoon/personen" in status["ontbreekt"]
    assert crew_status([], 1)["compleet"] is False


def test_response_summary() -> None:
    assert response_summary(make_incident()) == {"opgekomen": 2, "afgewezen": 1, "overig": 0}


def test_response_status_uses_alarm_response_until_attendance_is_known() -> None:
    assert response_status({"status": "acknowledged", "reported_status": "unknown"}) == "acknowledged"
    assert response_status({"status": "acknowledged", "reported_status": "no_show"}) == "no_show"
    assert response_status({"status": "pending", "reported_status": None}) == "pending"
    assert response_is_positive({"status": "acknowledged", "reported_status": "unknown"})
    assert not response_is_positive({"status": "acknowledged", "reported_status": "no_show"})
    assert response_is_negative({"status": "expired", "reported_status": "unknown"})
    assert not response_is_positive({"status": "pending", "reported_status": "unknown"})
    assert not response_is_negative({"status": "pending", "reported_status": "unknown"})


def test_station_name_skips_crew_groups() -> None:
    groups = {100: "Brandweer Echt TS", 200: "Ploeg 2"}
    assert station_name({"group_ids": [200, 100]}, groups, 100, "Ploeg 2 (200)") == "Echt"
    assert station_name(None, {}, 0, "Ploeg 2 (200)") == "Brandweer"


def test_template_render_drops_empty_lines() -> None:
    text = facebook_template.render(
        "Titel {kazerne}\n🚒 Voertuigen: {voertuigen}\n\n#Brandweer {onbekend}",
        {"kazerne": "Echt", "voertuigen": ""},
    )
    assert text == "Titel Echt\n\n#Brandweer"
    assert facebook_template.unknown_placeholders("{kazerne} {foo}") == ["foo"]
    default = facebook_template.render("", {"kazerne": "Echt", "classificatie": "Woningbrand", "locatie": "Echt"})
    assert default.startswith("🚒 Brandweer Echt uitgerukt – Woningbrand\n\n📍 Echt\n\nMeer informatie")


async def test_statistics_counts_and_timezone(hass) -> None:
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    stats = PersonalIncidentStatistics(hass, "test")
    # 31-03 22:30 UTC is 1 April 00:30 in Amsterdam.
    assert stats.record_incident(make_incident(1), USER, "Jan Jansen", SKILLS)
    declined = make_incident(2)
    declined["incident_responses"][0]["status"] = "rejected"
    declined["created_at"] = declined["start_time"] = "2026-02-10T10:00:00Z"
    assert stats.record_incident(declined, USER, "Jan Jansen", SKILLS)

    assert stats.events["1"]["type"] == TYPE_ASSIGNED
    assert stats.events["1"]["functies"] == ["Bevelvoerder"]
    assert stats.events["2"]["type"] == TYPE_NO_TURNOUT

    now = datetime(2026, 4, 15, 12, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
    counts = stats.counts(now)
    assert counts["month"] == 1
    assert counts["year"] == 1
    assert counts["total"] == 1
    assert counts["response_rate_year"] == 50.0
    assert counts["functions_year"] == {"Bevelvoerder": 1}
    assert counts["dayparts_year"]["nacht"] == 1
    assert dt_util.as_local(counts["last_turnout"]).day == 1

    may = datetime(2026, 5, 1, 0, 1, tzinfo=ZoneInfo("Europe/Amsterdam"))
    assert stats.counts(may)["month"] == 0
    assert stats.counts(may)["previous_month"] == 1


async def test_duty_mode_counts_alarms_while_on_duty(hass) -> None:
    stats = PersonalIncidentStatistics(hass, "test")
    stats.initialized = True
    stats.set_mode("duty")
    assert not stats.initialized  # switching mode re-syncs history

    def ovd_incident(incident_id: int, on_duty: bool | None, status: str = "pending") -> dict:
        incident = make_incident(incident_id, assigned=False)
        incident["incident_responses"] = [
            {"id": 1, "user_id": 7, "status": status, "reported_status": "unknown", "on_duty": on_duty, "assigned_skill_ids": [1]}
        ]
        return incident

    stats.record_incident(ovd_incident(1, True), USER, "", SKILLS)
    stats.record_incident(ovd_incident(2, False), USER, "", SKILLS)
    stats.record_incident(ovd_incident(3, None), USER, "", SKILLS)
    stats.record_incident(ovd_incident(4, True, "rejected"), USER, "", SKILLS)
    assert stats.events["1"]["type"] == TYPE_ASSIGNED
    assert stats.events["1"]["functies"] == ["Bevelvoerder"]
    assert stats.events["2"]["type"] == TYPE_NO_TURNOUT
    assert stats.events["3"]["type"] == TYPE_ASSIGNED
    assert stats.events["4"]["type"] == TYPE_NO_TURNOUT

    # The same data in the default mode: nothing was confirmed in the app.
    stats.set_mode("response")
    stats.record_incident(ovd_incident(1, True), USER, "", SKILLS)
    assert stats.events["1"]["type"] == TYPE_NO_TURNOUT


async def test_fallback_incident_never_deletes(hass) -> None:
    stats = PersonalIncidentStatistics(hass, "test")
    stats.record_incident(make_incident(1), USER, "Jan Jansen", SKILLS)
    assert not stats.record_incident({"id": 1, "_fallback": True, "body": "x"}, USER, "Jan Jansen", SKILLS)
    assert not stats.record_incident({"id": 1, "incident_responses": []}, USER, "Jan Jansen", SKILLS)
    assert "1" in stats.events
