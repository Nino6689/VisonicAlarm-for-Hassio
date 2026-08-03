"""Shared entity base for the Visonic Alarm integration.

Deliberately does **not** define `device_info`. This integration is set up from
YAML via `discovery.load_platform`, so its entities have no config entry, and
`EntityPlatform._async_add_entity` only creates device registry entries under
`if self.config_entry:`. Returning `device_info` here is silently ignored.

Grouping the entities under one panel device requires migrating the integration
to a config entry first. That would also move the credentials out of
configuration.yaml, but it has to preserve the existing `unique_id` values or
every entity ID changes.
"""

from __future__ import annotations

from homeassistant.helpers.entity import Entity


def _hub():
    """Resolve the hub lazily.

    `from . import HUB` binds the value at import time, and HUB is still None
    until `setup()` runs. Reading the attribute on each access avoids depending
    on module import order.
    """
    from . import HUB  # noqa: PLC0415 - deliberate late binding

    return HUB


class VisonicEntity(Entity):
    """Common availability handling for all Visonic entities."""

    _attr_has_entity_name = False

    @property
    def available(self) -> bool:
        """Whether the last poll of the Visonic cloud API succeeded.

        This tracks the *cloud API*, not the panel's own link to the cloud. A
        panel that has gone offline still answers via cached data, which is what
        `binary_sensor.visonic_alarm_cloud_connection` reports.
        """
        return _hub().available
