"""Constants for the Visonic Alarm integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "visonicalarm"

PLATFORMS: Final = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Configuration keys. These match the historical YAML schema so that imported
# entries carry the same names and nothing has to be translated at read time.
CONF_USER_CODE: Final = "user_code"
CONF_APP_ID: Final = "app_id"
CONF_USER_EMAIL: Final = "user_email"
CONF_USER_PASSWORD: Final = "user_password"
CONF_PANEL_ID: Final = "panel_id"
CONF_PARTITION: Final = "partition"
CONF_NO_PIN_REQUIRED: Final = "no_pin_required"
CONF_EVENT_HOUR_OFFSET: Final = "event_hour_offset"

DEFAULT_HOST: Final = "visonic.tycomonitor.com"
DEFAULT_PARTITION: Final = "ALL"
DEFAULT_NAME: Final = "Visonic Alarm"

# The cloud reflects panel state within a few seconds; polling faster than this
# gains nothing and the API is rate sensitive.
SCAN_INTERVAL: Final = timedelta(seconds=10)
# Troubles, events and the capability endpoints change rarely.
SLOW_SCAN_INTERVAL: Final = timedelta(minutes=5)

# Panel arm states as reported by the API.
STATE_AWAY: Final = "AWAY"
STATE_HOME: Final = "HOME"
STATE_DISARM: Final = "DISARM"
STATE_ARMING: Final = "ARMING"
STATE_ENTRY_DELAY: Final = "ENTRYDELAY"
STATE_ALARM: Final = "ALARM"

# Zone types that are only live while the system is armed away.
ZONE_INTERIOR: Final = "INTERIOR"
ZONE_24H: Final = "24H"

# Device subtype fragments used to classify enrolled devices.
SUBTYPE_CONTACT: Final = "CONTACT"
SUBTYPE_MOTION: Final = "MOTION"
SUBTYPE_CURTAIN: Final = "CURTAIN"
SUBTYPE_SMOKE: Final = "SMOKE"
SUBTYPE_KEYFOB: Final = "KEYFOB"

ATTR_LOCATION: Final = "location"
ATTR_ZONE_TYPE: Final = "zone_type"
ATTR_SUBTYPE: Final = "subtype"
ATTR_DEVICE_TYPE: Final = "device_type"
ATTR_ENROLLMENT_ID: Final = "enrollment_id"
ATTR_BYPASSED: Final = "bypassed"
ATTR_SOAK_TEST: Final = "soak_test"
ATTR_FAULTS: Final = "faults"
ATTR_SIGNAL: Final = "signal"
ATTR_SIGNAL_AVERAGE: Final = "signal_average"
ATTR_RF_CHANNEL: Final = "rf_channel"
ATTR_REPEATER: Final = "repeater"
ATTR_SIGNAL_SURVEYED: Final = "signal_surveyed"

SERVICE_REFRESH: Final = "refresh"
SERVICE_WAKE_PANEL: Final = "wake_panel"

ISSUE_YAML_DEPRECATED: Final = "yaml_deprecated"
ISSUE_PANEL_OFFLINE: Final = "panel_offline"
