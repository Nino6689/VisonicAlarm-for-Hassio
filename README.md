# Visonic Alarm for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Tests](https://github.com/Nino6689/VisonicAlarm-for-Hassio/actions/workflows/tests.yaml/badge.svg)](https://github.com/Nino6689/VisonicAlarm-for-Hassio/actions/workflows/tests.yaml)
[![Quality scale](https://img.shields.io/badge/quality%20scale-platinum-e5e4e2.svg)](custom_components/visonicalarm/quality_scale.yaml)

Arm, disarm and monitor a **Visonic**, **Bentel** or **Tyco** alarm from Home
Assistant — plus the panel-health data the alarm has always reported but nothing
ever showed you.

> **Maintained fork.** Upstream
> [And3rsL/VisonicAlarm-for-Hassio](https://github.com/And3rsL/VisonicAlarm-for-Hassio)
> was archived in December 2025, and so was the library it depended on,
> [And3rsL/VisonicAlarm2](https://github.com/And3rsL/VisonicAlarm2). This fork
> vendors that client so it can be fixed, moves setup into the UI, and meets the
> Home Assistant quality scale up to **platinum**.

---

## How this works, before you start

This talks to the **Visonic cloud**, the same service behind the *Visonic GO*
and *Connect Alarm* mobile apps. It does **not** connect to your panel over your
local network.

That has three consequences worth knowing up front:

1. **You need a working app login.** If you cannot sign in to the mobile app,
   this integration cannot sign in either. Set the app up first.
2. **Your panel must be reporting to the cloud.** A panel that has lost its
   broadband or GPRS link will still appear to work here, because the cloud
   serves its last known state. See
   [When the panel stops reporting](#when-the-panel-stops-reporting).
3. **Motion detectors do not report live motion.** This is a limitation of the
   cloud API, not of this integration. See
   [Known limitations](#known-limitations).

## Supported panels

Any panel that reports to a PowerManage server, including:

| Family | Examples |
| --- | --- |
| PowerMaster | 360R, 33, 30, 10 |
| PowerMax | Complete, Complete Pro, Express, Pro |
| Rebadges | Bentel and Tyco versions of the above |

Developed and tested against a **PowerMaster 360R** on REST API **14.0**.

---

## Installation

### HACS

1. HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/Nino6689/VisonicAlarm-for-Hassio`, category
   **Integration**
3. Search for **Visonic Alarm**, install it, then **restart Home Assistant**
4. **Settings → Devices & Services → Add Integration → Visonic Alarm**

### Manual

Copy `custom_components/visonicalarm` into your Home Assistant
`config/custom_components/` directory and restart.

---

## What you will be asked for

The setup form needs two separate things, and mixing them up is by far the most
common reason setup fails.

| Field | What it actually is | Where to find it |
| --- | --- | --- |
| **Monitoring server** | The server your alarm reports to | Default `visonic.tycomonitor.com` suits most UK and EU panels. If you are professionally monitored, check the app's *About* or *Server* screen, or ask your provider. |
| **App account email** | The email you log in to the mobile app with | You chose it when you registered the app |
| **App account password** | The password for that account | ⚠️ **Not** your keypad PIN |
| **Panel serial number** | Identifies the alarm itself | App → panel settings; the sticker inside the panel; or your welcome email. A short code such as `1D0B0A`, usually 6 characters. Sometimes called *panel ID*. |
| **Keypad PIN** | The code you type to disarm | ⚠️ Use **your own user code**, not the installer or engineer code. The integration arms and disarms as that user, so it is the name that appears in the event log. |
| **App ID** | A client identifier | **Leave blank.** One is generated for you. |

### Options

Available afterwards via ⚙ on the integration card. Both are Home Assistant-side
only; neither writes anything to the panel.

- **Arm and disarm without entering the code** — skips the Home Assistant code
  prompt so dashboard buttons and automations can act directly. Your PIN is
  still sent to the panel either way. Leave it **off** if anyone who can reach
  your dashboard should not be able to disarm the alarm.
- **Event timestamp offset** — only needed if *Last event* times look wrong,
  which happens when the panel clock is in a different time zone.

### Upgrading from a YAML setup

Delete nothing first. On restart your existing `visonicalarm:` block is imported
automatically, and a repair notice tells you to remove it. Do that, restart
again, and the notice clears itself.

> **Entity IDs are preserved.** They are pinned by `unique_id`, and every
> historical value is kept — so dashboards and automations referencing
> `alarm_control_panel.visonic_alarm` or `sensor.visonicalarm_*` keep working
> untouched.

---

## What you get

### The alarm

`alarm_control_panel` — arm home, arm away, disarm. Arm modes are read from the
panel's own capability list, so a panel that cannot arm home will not offer it.

### Panel health

The upstream integration fetched all of this and threw it away.

| Entity | Why you want it |
| --- | --- |
| `binary_sensor.*_cloud_connection` | **The important one.** Off means the panel is not reporting and everything else you see is cached. |
| `binary_sensor.*_problem` | Active troubles, with type, zone and room |
| `binary_sensor.*_triggered` | An alarm is currently active |
| `binary_sensor.*_ready_to_arm` | Whether arming would succeed right now |
| `binary_sensor.*_zones_bypassed` | Any zone excluded from arming |
| `binary_sensor.*_broadband` / `*_gprs` | Per-transport connectivity |
| `sensor.*_trouble_count` | Numeric, so it graphs and alerts |
| `sensor.*_last_event` | Last panel event, with user and plain-English description |
| `sensor.*_panel` | Model, features, users, REST version |

### Per zone

Each enrolled zone becomes its own device, linked under the panel:

- `binary_sensor.<room>` — contacts use the `door` device class and report real
  open/closed
- `switch.<room>_bypass` — bypass or unbypass the zone
- Attributes: room, zone type, enrollment ID, bypass, soak test, faults, RF
  signal and channel

### Actions

| Action | Description |
| --- | --- |
| `visonicalarm.refresh` | Poll the panel immediately |
| `visonicalarm.sound_siren` | Sound the siren — a panic alarm |
| `visonicalarm.silence_siren` | Silence a sounding siren |
| `visonicalarm.set_zone_name` | Rename a zone on the panel itself |

Sirens are **actions rather than switches** on purpose. Sounding a house alarm
should take a deliberate call, not one stray toggle on a dashboard.

---

## How data is updated

Cloud polling on two cadences:

| Every | What |
| --- | --- |
| **10 seconds** | Arm state, partition readiness, device state — matching what the mobile app does |
| **5 minutes** | Troubles, alerts, event log, capabilities — these move rarely and the API is rate sensitive |

Arming, disarming and bypassing trigger an immediate refresh rather than waiting
for the next poll.

---

## Known limitations

All properties of the cloud API, not bugs:

- **Motion detectors never report live motion.** The cloud only publishes
  whether a zone *participates* in the current arm mode, which is what the
  motion entities reflect — "is this detector currently armed", not "is someone
  moving". Use real PIR sensors if you need motion detection.
- **Signal strength is a stored survey, not telemetry.** Every device reports the
  same enrollment-era `last_updated`, so it is exposed as `signal_surveyed`
  rather than dressed up as a live reading.
- **Room names need the panel online.** While a panel is not reporting, the
  device `traits` object comes back empty, so room labels, bypass state and
  signal are all unavailable.
- **A disconnected panel does not make entities unavailable.** See below.

---

## Troubleshooting

### When the panel stops reporting

**This is the failure mode worth understanding.** If the panel loses its link to
the cloud, the cloud keeps serving its **last known arm state**. Nothing goes
unavailable, nothing errors — the alarm entity just quietly freezes, and any
automation that trusts it carries on believing stale data.

That is exactly what `binary_sensor.*_cloud_connection` is for, and why this
integration raises a repair notice when it happens.

If it is off:

1. Check the panel's broadband or GPRS connection.
2. If the panel has an IP address but still will not connect, check **which
   server address it is configured to report to**. A panel provisioned for a
   monitoring service that has since been decommissioned looks perfectly healthy
   on the network while never connecting to anything. Re-pointing it is done in
   the panel's installer menu.

### Credentials rejected after working for months

The cloud session expires. This fork detects that and re-authenticates on its
own. If it persists, use the reauth prompt — usually the app password or the
keypad PIN was changed.

### `INACTIVE` troubles right after a reconnect

Expected. The cloud has no recent report from any device yet, so everything
looks inactive at once. They clear as each sensor checks in over the following
hours. Anything **still** inactive the next day is a real fault, usually a
battery.

### Setup keeps failing

In order of likelihood: the keypad PIN was entered as the account password; the
panel serial has a typo; an installer code was used instead of a user code.
Confirm the exact same details sign in to the mobile app.

### Getting logs

```yaml
logger:
  logs:
    custom_components.visonicalarm: debug
```

Diagnostics can be downloaded from the integration card. Credentials, serials
and identifying details are redacted automatically, so it is safe to attach to
an issue.

---

## Example automations

Tell me when the alarm stops reporting — the failure you would otherwise never
notice:

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
            The panel has stopped reporting. The alarm state shown in Home
            Assistant is no longer live.
```

Warn if the alarm is armed while a zone is bypassed:

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

Flag a sensor that has genuinely dropped off, ignoring post-reconnect noise:

```yaml
automation:
  - alias: "Alarm sensor fault"
    triggers:
      - trigger: state
        entity_id: binary_sensor.visonic_alarm_problem
        to: "on"
        for: "06:00:00"
    actions:
      - action: notify.mobile_app
        data:
          message: >-
            Alarm faults persisting:
            {{ state_attr('binary_sensor.visonic_alarm_problem',
                          'faulty_devices') }}
```

---

## Removal

**Settings → Devices & Services → Visonic Alarm → ⋮ → Delete**, then remove the
repository from HACS. If you previously used YAML, delete the `visonicalarm:`
block from `configuration.yaml` too.

---

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt

.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
.venv/bin/mypy custom_components/visonicalarm
.venv/bin/pytest tests --cov=custom_components.visonicalarm
```

CI enforces all four, with coverage held above 95%. The test fixtures are real
payloads captured from a live PowerMaster 360R — using real shapes rather than
hand-written stubs is what surfaced several of the quirks documented above.

The [quality scale self-assessment](custom_components/visonicalarm/quality_scale.yaml)
records how each rule is met, and says so honestly where a rule is exempt.

---

## Credits

- [And3rsL](https://github.com/And3rsL) — the original integration and library,
  which this builds on
- [msp1974](https://github.com/msp1974) — whose
  [pyvisonicalarm](https://github.com/msp1974/pyvisonicalarm) documents the
  bypass, siren and rename endpoints that are not published anywhere else

## Licence

MIT. See [LICENSE](LICENSE).
