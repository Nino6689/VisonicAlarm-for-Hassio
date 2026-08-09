"""Data-model tests, including the traits behaviour that only shows up online."""

from __future__ import annotations

from custom_components.visonicalarm.models import (
    VisonicData,
    VisonicDevice,
    VisonicEvent,
)


def _device(**overrides) -> VisonicDevice:
    raw = {
        "id": 6148586,
        "device_number": 5,
        "device_type": "ZONE",
        "zone_type": "HOME_DELAY",
        "subtype": "MOTION",
        "enrollment_id": "120-0001",
        "name": "",
        "warnings": None,
        "partitions": [1],
        "traits": {
            "location": {"name": "Kitchen"},
            "bypass": {"enabled": False},
            "soak": {"enabled": False},
            "rssi": {"current": "strong", "channel": 8},
        },
    }
    raw.update(overrides)
    return VisonicDevice(raw)


def test_traits_are_empty_when_the_panel_is_offline() -> None:
    """⚠️ traits is {} while the panel is not reporting.

    Every accessor must cope, because this is the state a freshly installed
    integration sees if the panel has lost its cloud connection.
    """
    device = _device(traits={})
    assert device.location is None
    assert device.bypassed is None
    assert device.soak is None
    assert device.rssi == {}
    assert device.display_name == "Zone 6148586"


def test_display_name_prefers_explicit_name() -> None:
    """The panel abbreviates locations, so a real name wins."""
    assert _device().display_name == "Kitchen"
    assert _device(name="Master Bedroom").display_name == "Master Bedroom"


def test_zone_number_only_applies_to_zones() -> None:
    """Non-zone devices all report device_number 1, which is meaningless."""
    assert _device().zone_number == 5
    assert _device(device_type="CONTROL_PANEL").zone_number is None
    assert _device(device_number=None).zone_number is None


def test_contact_state_from_warnings() -> None:
    """Contacts are the only devices that report a usable state."""
    contact = _device(subtype="CONTACT_V")
    assert contact.state == "closed"

    opened = _device(
        subtype="CONTACT_V",
        warnings=[{"type": "OPENED", "severity": "TROUBLE"}],
    )
    assert opened.state == "opened"

    # Motion detectors expose nothing here.
    assert _device().state is None


def test_fault_types_ignores_malformed_warnings() -> None:
    """Warnings from the panel are not always well formed."""
    device = _device(warnings=[{"type": "INACTIVE"}, "junk", {"nope": 1}])
    assert device.fault_types == ["INACTIVE"]


def test_missing_id() -> None:
    """A device without an id is tolerated."""
    assert VisonicDevice({}).id is None


def test_event_uses_label_over_type_id() -> None:
    """type_id 173 is absent from the legacy map; label must win."""
    event = VisonicEvent.from_raw(
        {
            "event": 1,
            "type_id": 173,
            "label": "DISARM",
            "description": "Disarm after alarm",
            "appointment": "Control Panel",
            "datetime": "2026-08-03 20:14:31",
        }
    )
    assert event.label == "DISARM"
    assert event.description == "Disarm after alarm"
    assert event.timestamp == "2026-08-03 20:14:31"


def test_event_hour_offset_is_applied() -> None:
    """The configured offset shifts event timestamps."""
    event = VisonicEvent.from_raw({"datetime": "2026-08-03 20:00:00"}, hour_offset=2)
    assert event.timestamp == "2026-08-03 22:00:00"


def test_event_with_unparseable_timestamp() -> None:
    """A malformed timestamp is passed through rather than crashing."""
    event = VisonicEvent.from_raw({"datetime": "not a date"})
    assert event.timestamp == "not a date"
    assert VisonicEvent.from_raw({}).timestamp is None


def test_data_aggregates() -> None:
    """The snapshot's derived views."""
    kitchen = _device(warnings=[{"type": "INACTIVE"}])
    bypassed = _device(id=1, name="Hall")
    bypassed._raw["traits"]["bypass"]["enabled"] = True  # noqa: SLF001

    data = VisonicData(devices=[kitchen, bypassed])
    assert data.zones == [kitchen, bypassed]
    assert data.faulty_devices == {"Kitchen": ["INACTIVE"]}
    assert [d.display_name for d in data.bypassed_zones] == ["Hall"]
    assert data.soak_zones == []
    assert data.device_by_id(6148586) is kitchen
    assert data.device_by_id(999) is None
    assert data.last_event is None


def test_connection_detail_ignores_malformed_entries() -> None:
    """The status payload is not always shaped as expected."""
    data = VisonicData(status={"connected_status": {"bba": {"is_connected": True}, "gprs": None}})
    assert data.connection_detail == {"bba": {"is_connected": True, "state": None}}


def test_non_zone_device_label_is_not_called_a_zone() -> None:
    """Keypads, sirens and the PowerLink occupy no zone.

    Regression: a proximity keypad with a LOW_BATTERY warning surfaced as
    "Zone 828779", which reads as an alarm zone that does not exist.
    """
    keypad = VisonicDevice(
        {
            "id": 828779,
            "subtype": "PROXIMITY_KEYPAD",
            "device_type": "WIRELESS_COMMANDER",
            "traits": {},
        }
    )
    assert keypad.is_zone is False
    assert keypad.display_name == "Proximity Keypad 828779"

    zone = VisonicDevice({"id": 6148586, "subtype": "MOTION", "device_type": "ZONE", "traits": {}})
    assert zone.display_name == "Zone 6148586"


def _data_with(bba: dict, connected: bool) -> VisonicData:
    d = VisonicData()
    d.connected = connected
    d.status = {"connected_status": {"bba": bba}}
    return d


def test_check_in_gap_is_not_reported_as_an_outage() -> None:
    """A PowerMaster on broadband checks in periodically.

    Between check-ins the cloud reports connected=False with the transport
    still "online". Measured 444 such transitions in three days on a live
    panel, none of them a real outage.
    """
    blip = _data_with({"is_connected": False, "state": "online"}, connected=False)
    assert blip.is_cloud_connected is True


def test_genuine_outage_is_still_reported() -> None:
    """When the transport itself reports offline, that is a real outage."""
    outage = _data_with({"is_connected": False, "state": "offline"}, connected=False)
    assert outage.is_cloud_connected is False


def test_connected_panel_reads_connected() -> None:
    ok = _data_with({"is_connected": True, "state": "online"}, connected=True)
    assert ok.is_cloud_connected is True


def test_falls_back_to_the_flag_without_transport_info() -> None:
    d = VisonicData()
    d.connected = True
    d.status = {}
    assert d.is_cloud_connected is True
    d.connected = False
    assert d.is_cloud_connected is False
