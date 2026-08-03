"""Data models for the Visonic Alarm integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .const import (
    SUBTYPE_CONTACT,
    SUBTYPE_KEYFOB,
)


class VisonicDevice:
    """One enrolled device, wrapping the raw ``/devices`` entry."""

    def __init__(self, raw: dict[str, Any]) -> None:
        """Store the raw payload; all accessors read through to it."""
        self._raw = raw

    @property
    def raw(self) -> dict[str, Any]:
        """The unmodified API payload, used by diagnostics."""
        return self._raw

    @property
    def id(self) -> int | None:
        """Stable device id. This is what pins entity IDs."""
        device_id = self._raw.get("id")
        return int(device_id) if device_id is not None else None

    @property
    def name(self) -> str | None:
        """Explicitly assigned device name, usually empty."""
        return self._raw.get("name") or None

    @property
    def zone_type(self) -> str:
        """Zone classification, e.g. ``INTERIOR`` or ``HOME_DELAY``."""
        return self._raw.get("zone_type") or ""

    @property
    def device_type(self) -> str | None:
        """Top-level type, e.g. ``ZONE`` or ``CONTROL_PANEL``."""
        return self._raw.get("device_type")

    @property
    def subtype(self) -> str:
        """Device subtype, e.g. ``MOTION`` or ``CONTACT_V``."""
        return self._raw.get("subtype") or ""

    @property
    def warnings(self) -> list[dict[str, Any]]:
        """Raw per-device warnings."""
        return self._raw.get("warnings") or []

    @property
    def partitions(self) -> list[int]:
        """Partitions this device belongs to."""
        return self._raw.get("partitions") or []

    @property
    def traits(self) -> dict[str, Any]:
        """Per-device metadata. Empty while the panel is offline."""
        return self._raw.get("traits") or {}

    @property
    def location(self) -> str | None:
        """Room label, e.g. ``Living room``.

        Lives under ``traits.location.name``, not at the top level. Most devices
        have an empty ``name``, so this is usually the only human-readable label
        available.
        """
        location = self.traits.get("location") or {}
        return location.get("name") or None

    @property
    def display_name(self) -> str:
        """Best available label for this device.

        An explicitly set name wins over the room label, because the panel
        abbreviates its own locations ("Master Bdrm" vs a device named
        "Master Bedroom").
        """
        return self.name or self.location or f"Zone {self.id}"

    @property
    def zone_number(self) -> int | None:
        """Panel zone number, as used by ``set_bypass_zone``.

        This is ``device_number``, which is only meaningful for zone devices —
        the panel, PowerLink, keypad and siren all report ``1``. Verified
        against the trouble list, where the same numbers appear as ``zone``.
        """
        if not self.is_zone:
            return None
        number = self._raw.get("device_number")
        return int(number) if number is not None else None

    @property
    def enrollment_id(self) -> str | None:
        """Enrollment code, e.g. ``120-0918``. The prefix encodes device type."""
        return self._raw.get("enrollment_id")

    @property
    def bypassed(self) -> bool | None:
        """Whether this zone is bypassed, i.e. excluded from arming."""
        bypass = self.traits.get("bypass")
        return bypass.get("enabled") if isinstance(bypass, dict) else None

    @property
    def soak(self) -> bool | None:
        """Whether the zone is in soak-test mode (reports but never alarms)."""
        soak = self.traits.get("soak")
        return soak.get("enabled") if isinstance(soak, dict) else None

    @property
    def rssi(self) -> dict[str, Any]:
        """Stored RF survey for this device.

        ``last_updated`` is the time of the last survey, **not** a live reading:
        every device on a panel reports the same enrollment-era timestamp. Treat
        signal as static metadata rather than telemetry.
        """
        return self.traits.get("rssi") or {}

    @property
    def fault_types(self) -> list[str]:
        """Active warning types, e.g. ``['INACTIVE', '1_WAY']``."""
        return [w["type"] for w in self.warnings if isinstance(w, dict) and "type" in w]

    @property
    def is_zone(self) -> bool:
        """Whether this device occupies an alarm zone."""
        return self.device_type == "ZONE"

    @property
    def is_contact(self) -> bool:
        """Whether this is a door or window contact."""
        return SUBTYPE_CONTACT in self.subtype

    @property
    def state(self) -> str | None:
        """Contact state derived from device warnings.

        Only contact-style devices report anything usable. Motion detectors
        expose nothing here, which is why their entities derive state from the
        arm mode instead.
        """
        if self.is_contact or SUBTYPE_KEYFOB in self.subtype:
            if any("OPENED" in str(w) for w in self.warnings):
                return "opened"
            return "closed"
        return None


@dataclass
class VisonicEvent:
    """One entry from the panel event log."""

    event_id: int | None = None
    type_id: int | None = None
    label: str | None = None
    description: str | None = None
    user: str | None = None
    timestamp: str | None = None
    zone: int | None = None
    zone_name: str | None = None
    device_type: str | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any], hour_offset: int = 0) -> VisonicEvent:
        """Build from an API payload, applying the configured hour offset.

        The API supplies ``label`` (``DISARM``, ``BURGLER``) and a
        human-readable ``description`` ("Disarm after alarm"). Both are used:
        ``label`` alone is misleading, since a panel tamper is labelled
        ``BURGLER``.
        """
        timestamp = raw.get("datetime")
        if timestamp:
            try:
                parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                parsed += timedelta(hours=hour_offset)
                timestamp = parsed.strftime("%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError):
                pass

        return cls(
            event_id=raw.get("event"),
            type_id=raw.get("type_id"),
            label=raw.get("label"),
            description=raw.get("description"),
            user=raw.get("appointment"),
            timestamp=timestamp,
            zone=raw.get("zone"),
            zone_name=raw.get("zone_name") or None,
            device_type=raw.get("device_type"),
        )


@dataclass
class VisonicData:
    """Everything one poll cycle knows about the alarm system."""

    state: str | None = None
    ready: bool | None = None
    connected: bool | None = None
    alarm_active: bool = False

    serial: str | None = None
    model: str | None = None
    alias: str | None = None
    rest_version: str | None = None

    devices: list[VisonicDevice] = field(default_factory=list)
    troubles: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    alarms: list[dict[str, Any]] = field(default_factory=list)
    events: list[VisonicEvent] = field(default_factory=list)

    status: dict[str, Any] = field(default_factory=dict)
    panel_info: dict[str, Any] = field(default_factory=dict)
    feature_set: dict[str, Any] = field(default_factory=dict)
    users: dict[str, Any] = field(default_factory=dict)
    cameras: list[dict[str, Any]] = field(default_factory=list)
    smart_devices: list[dict[str, Any]] = field(default_factory=list)
    home_automation_devices: list[dict[str, Any]] = field(default_factory=list)
    email_notifications: dict[str, Any] = field(default_factory=dict)

    @property
    def connection_detail(self) -> dict[str, dict[str, Any]]:
        """Per-transport connectivity, e.g. ``{'bba': {...}, 'gprs': {...}}``."""
        detail: dict[str, dict[str, Any]] = {}
        for name, info in (self.status.get("connected_status") or {}).items():
            if isinstance(info, dict):
                detail[name] = {
                    "is_connected": info.get("is_connected"),
                    "state": info.get("state"),
                }
        return detail

    @property
    def last_event(self) -> VisonicEvent | None:
        """Most recent panel event, if the log is not empty."""
        return self.events[-1] if self.events else None

    @property
    def zones(self) -> list[VisonicDevice]:
        """Devices that occupy an alarm zone."""
        return [d for d in self.devices if d.is_zone]

    @property
    def bypassed_zones(self) -> list[VisonicDevice]:
        """Zones currently excluded from arming."""
        return [d for d in self.devices if d.bypassed]

    @property
    def soak_zones(self) -> list[VisonicDevice]:
        """Zones in soak-test mode."""
        return [d for d in self.devices if d.soak]

    @property
    def faulty_devices(self) -> dict[str, list[str]]:
        """Faults keyed by room.

        Device-level warnings name the room; the panel-level trouble list does
        not always.
        """
        return {d.display_name: d.fault_types for d in self.devices if d.fault_types}

    def device_by_id(self, device_id: int) -> VisonicDevice | None:
        """Look up a device by its stable id."""
        return next((d for d in self.devices if d.id == device_id), None)
