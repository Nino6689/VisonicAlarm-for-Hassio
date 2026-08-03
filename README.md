# Visonic Alarm for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Tests](https://github.com/Nino6689/VisonicAlarm-for-Hassio/actions/workflows/tests.yaml/badge.svg)](https://github.com/Nino6689/VisonicAlarm-for-Hassio/actions/workflows/tests.yaml)

Control and monitor a Visonic, Bentel or Tyco alarm panel from Home Assistant,
through the same PowerManage cloud service the Visonic GO and Connect Alarm apps
use.

> **Maintained fork.** Upstream
> [And3rsL/VisonicAlarm-for-Hassio](https://github.com/And3rsL/VisonicAlarm-for-Hassio)
> was archived in December 2025, as was the library it depended on,
> [And3rsL/VisonicAlarm2](https://github.com/And3rsL/VisonicAlarm2). This fork
> keeps the integration alive: the API client is vendored so it can be fixed,
> setup has moved to the UI, and the integration now meets the Home Assistant
> quality scale up to platinum.

## Supported devices

Any panel reachable through a PowerManage server, including:

- PowerMaster 360R, 30, 33, 10
- PowerMax Complete / Express / Pro
- Bentel and Tyco rebadges of the above

Developed against a **PowerMaster 360R** on REST API 14.0.

## What you get

**Alarm**

- `alarm_control_panel` — arm home, arm away, disarm. Arm modes are read from
  the panel's own capability list, so a panel that cannot arm home will not
  offer it.

**Panel health** — the upstream integration fetched this data and discarded it.

| Entity | Purpose |
| --- | --- |
| `binary_sensor.*_cloud_connection` | Whether the cloud can reach the panel at all |
| `binary_sensor.*_problem` | Active troubles, with type, zone and room |
| `binary_sensor.*_triggered` | An alarm is currently active |
| `binary_sensor.*_ready_to_arm` | Arming would succeed right now |
| `binary_sensor.*_zones_bypassed` | Any zone excluded from arming |
| `binary_sensor.*_broadband` / `_gprs` | Per-transport connectivity |
| `sensor.*_trouble_count` | Numeric, so it graphs and alerts |
| `sensor.*_last_event` | Last panel event, with user and description |
| `sensor.*_panel` | Model, features, users, REST version |

**Per zone**

- `binary_sensor.visonic_<room>` — contacts use the `door` device class and
  report real open/closed
- `switch.visonic_<room>_bypass` — bypass a zone
- Attributes: room, zone type, enrollment id, bypass, soak test, faults, RF
  signal and channel

**Actions**

| Action | Description |
| --- | --- |
| `visonicalarm.refresh` | Poll the panel immediately |
| `visonicalarm.sound_siren` | Sound the siren as a panic alarm |
| `visonicalarm.silence_siren` | Silence a sounding siren |
| `visonicalarm.set_zone_name` | Rename a zone on the panel itself |

Sirens are actions rather than switches on purpose: sounding a house alarm
should take a deliberate call, not one stray toggle on a dashboard.

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Add `https://github.com/Nino6689/VisonicAlarm-for-Hassio`, category
   **Integration**
3. Install **Visonic Alarm**, then restart Home Assistant
4. Settings → Devices & Services → **Add Integration** → *Visonic Alarm*

### Manual

Copy `custom_components/visonicalarm` into your `config/custom_components/`
directory and restart.

## Configuration

Everything is configured in the UI.

| Field | Notes |
| --- | --- |
| Server | Your monitoring server, e.g. `visonic.tycomonitor.com`. Leave the default unless told otherwise. |
| Email / password | The same account you use in the app |
| Panel serial | Shown in the app, on the panel label, or in your welcome email |
| User code | The PIN you use to disarm at the keypad |
| App ID | Leave blank and one is generated |

Options (⚙ on the integration card):

- **Arm and disarm without entering the code** — skips the Home Assistant code
  prompt. The panel still receives your user code.
- **Event timestamp offset** — shifts event log timestamps if the panel clock is
  in a different time zone.

### Upgrading from YAML

Existing `visonicalarm:` configuration is imported automatically on restart and
a repair notice tells you to delete the block. **Entity IDs are preserved** —
they are pinned by `unique_id`, which is unchanged.

## How data is updated

Cloud polling, on two cadences:

- **Every 10 seconds** — arm state, partition readiness, device state. This
  matches what the vendor app does.
- **Every 5 minutes** — troubles, alerts, event log, capabilities. These move
  rarely and the API is rate sensitive.

Arming, disarming and bypassing trigger an immediate refresh.

## Known limitations

These are properties of the cloud API, not bugs:

- **Motion detectors never report live motion.** The cloud only publishes
  whether a zone *participates* in the current arm mode, which is what the
  motion entities reflect. Use real PIR sensors if you need motion detection.
- **Signal strength is a stored survey, not telemetry.** Every device reports
  the same enrollment-era `last_updated`, so it is exposed as
  `signal_surveyed` rather than dressed up as a live reading.
- **The panel must be online for device traits.** While a panel is not
  reporting, `traits` comes back empty, so room names, bypass state and signal
  are all unavailable.
- **A disconnected panel does not make entities unavailable.** The cloud keeps
  serving the last known arm state. That is what
  `binary_sensor.*_cloud_connection` and the repair issue are for.

## Troubleshooting

**Everything looks fine but the state never changes.** Check
`binary_sensor.*_cloud_connection`. If it is off, the panel has stopped
reporting and you are looking at a cached value. Verify the panel's broadband or
GPRS connection, and — if it has an IP address but still will not connect —
which server address it is configured to report to. A panel provisioned for a
decommissioned monitoring service will look perfectly healthy on the network
while never connecting.

**Credentials rejected after working for months.** The cloud session expires.
This fork detects that and re-authenticates automatically; if it persists, use
the reauth prompt.

**`INACTIVE` troubles right after a reconnect.** Expected — the cloud has no
recent report from any device yet. They clear as each sensor checks in. Anything
still inactive hours later is a real fault, usually a battery.

**Getting logs**

```yaml
logger:
  logs:
    custom_components.visonicalarm: debug
```

Download diagnostics from the integration card; credentials, serials and
identifying details are redacted automatically.

## Example automations

Alert when the panel stops reporting:

```yaml
automation:
  - alias: "Alarm lost cloud connection"
    triggers:
      - trigger: state
        entity_id: binary_sensor.visonic_alarm_cloud_connection
        to: "off"
        for: "00:15:00"
    actions:
      - action: notify.mobile_app
        data:
          title: "Alarm offline"
          message: >-
            The panel has stopped reporting. Alarm state shown in Home
            Assistant is no longer live.
```

Warn if the alarm is armed with a zone bypassed:

```yaml
automation:
  - alias: "Armed with a bypassed zone"
    triggers:
      - trigger: state
        entity_id: alarm_control_panel.visonic_alarm
        to: ["armed_away", "armed_home"]
    conditions:
      - condition: state
        entity_id: binary_sensor.visonic_alarm_zones_bypassed
        state: "on"
    actions:
      - action: notify.mobile_app
        data:
          message: >-
            Armed, but these zones are bypassed:
            {{ state_attr('binary_sensor.visonic_alarm_zones_bypassed',
                          'bypassed_zones') | join(', ') }}
```

## Removal

Settings → Devices & Services → Visonic Alarm → ⋮ → **Delete**. Then remove the
repository from HACS. If you previously used YAML, delete the `visonicalarm:`
block from `configuration.yaml`.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check custom_components tests
.venv/bin/mypy custom_components/visonicalarm
.venv/bin/pytest tests --cov=custom_components.visonicalarm
```

CI enforces lint, formatting, strict typing and 95% coverage.

## Credits

- [And3rsL](https://github.com/And3rsL) for the original integration and library
- [msp1974](https://github.com/msp1974) — whose
  [pyvisonicalarm](https://github.com/msp1974/pyvisonicalarm) documents the
  bypass, siren and rename endpoints that are not published anywhere else

## Licence

MIT. See [LICENSE](LICENSE).
