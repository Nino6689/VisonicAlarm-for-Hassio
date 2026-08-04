<h1 align="center">
  <img src="custom_components/visonicalarm/brand/icon.png" width="96" alt=""><br>
  Visonic Alarm for Home Assistant
</h1>

<p align="center">
  Arm, disarm and monitor a <b>Visonic</b>, <b>Bentel</b> or <b>Tyco</b> alarm —<br>
  plus the panel-health data your alarm has always reported and nothing ever showed you.
</p>

<p align="center">
  <a href="https://github.com/Nino6689/VisonicAlarm-for-Hassio/releases/latest"><img src="https://img.shields.io/github/v/release/Nino6689/VisonicAlarm-for-Hassio?style=for-the-badge&color=41BDF5" alt="Release"></a>
  <a href="https://github.com/Nino6689/VisonicAlarm-for-Hassio/actions/workflows/tests.yaml"><img src="https://img.shields.io/github/actions/workflow/status/Nino6689/VisonicAlarm-for-Hassio/tests.yaml?style=for-the-badge&label=tests" alt="Tests"></a>
  <a href="custom_components/visonicalarm/quality_scale.yaml"><img src="https://img.shields.io/badge/quality_scale-platinum-e5e4e2?style=for-the-badge" alt="Quality scale: platinum"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-MIT-blue?style=for-the-badge" alt="Licence"></a>
  <a href="https://buymeacoffee.com/nino6689"><img src="https://img.shields.io/badge/buy_me_a_coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black" alt="Buy Me A Coffee"></a>
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=Nino6689&repository=VisonicAlarm-for-Hassio&category=integration"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open in HACS"></a>
  &nbsp;
  <a href="https://my.home-assistant.io/redirect/config_flow_start/?domain=visonicalarm"><img src="https://my.home-assistant.io/badges/config_flow_start.svg" alt="Add integration to Home Assistant"></a>
</p>

---

## What you get

|  |  |
|---|---|
| 🛡️ **Arm & disarm** | Home, away and disarm — and the arm modes come from the panel's own capability list, so it never offers one your panel cannot do |
| ☁️ **Cloud connection** | The one that matters. When your panel stops reporting, everything else silently goes stale — this is what tells you |
| ⚠️ **Faults by room** | Active troubles named by room, not zone number, so "Kitchen: low battery" instead of "zone 5" |
| 🚫 **Zone bypass** | A switch per zone. A bypassed zone is excluded from arming but is **not** reported as a trouble — the system says "armed" while that door does nothing |
| 🚨 **Panic & silence** | Sound or silence the siren as explicit actions |
| 📋 **Event log** | Last panel event with the user who caused it and a plain-English description |
| 📶 **Per-zone detail** | Room, zone type, bypass, soak test, faults, RF signal and channel |
| 🔌 **Transports** | Broadband and GPRS connectivity, separately |
| 🏠 **Proper devices** | One device for the panel, one per zone, linked together |
| 🔐 **No secrets leaked** | The old version published your live session token as an entity attribute — into the states API, the recorder database and every dashboard showing it. Not any more. |

Around **30 entities** for a nine-zone panel, with no extra hardware.

---

## Before you start

This talks to the **Visonic cloud** — the same service behind the *Visonic GO*
and *Connect Alarm* apps. It does **not** connect to your panel over your local
network.

Three consequences worth knowing up front:

> **1. You need a working app login.**
> If you cannot sign in to the mobile app, this cannot sign in either. Get the
> app working first.
>
> **2. Your panel must be reporting to the cloud.**
> A panel that has lost its broadband or GPRS link still *looks* fine here,
> because the cloud keeps serving its last known state. See
> [When the panel stops reporting](#when-the-panel-stops-reporting).
>
> **3. Motion detectors do not report live motion.**
> This is the panel's own behaviour, not something a different integration would
> fix. See [Known limitations](#known-limitations).

### Supported panels

Anything that reports to a PowerManage server:

| Family | Models |
| --- | --- |
| **PowerMaster** | 360R, 33, 30, 10 |
| **PowerMax** | Complete, Complete Pro, Express, Pro |
| **Rebadges** | Bentel and Tyco versions of the above |

Built against **REST API 14.0**.

---

## Install

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nino6689&repository=VisonicAlarm-for-Hassio&category=integration)

Click the button, or add it by hand:

1. HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/Nino6689/VisonicAlarm-for-Hassio`, category
   **Integration**
3. Install **Visonic Alarm**, then **restart Home Assistant**

Then add it:

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=visonicalarm)

<details>
<summary>Manual install without HACS</summary>

Copy `custom_components/visonicalarm` into your Home Assistant
`config/custom_components/` directory and restart.

</details>

---

## What setup asks for

Two separate things, and confusing them is far and away the most common reason
setup fails.

|  | Field | What it actually is |
|---|---|---|
| 👤 | **App account email** | The email you sign in to the mobile app with |
| 🔑 | **App account password** | That account's password — ⚠️ **not** your keypad PIN |
| 🏷️ | **Panel serial number** | Identifies the alarm. A short code, usually 6 characters. In the app under panel settings, on the sticker inside the panel, or in your welcome email. Sometimes called *panel ID*. |
| 🔢 | **Keypad PIN** | The code you type to disarm — ⚠️ use **your own user code**, not the installer or engineer one. The integration acts as that user, so it is the name that shows in the event log. |
| 🌐 | **Monitoring server** | Leave the default unless your provider uses a different one. It is shown in the app's *About* or *Server* screen. |
| 🆔 | **App ID** | **Leave blank.** One is generated for you. |

Every field has help text in the form itself, so you do not need this page open
while setting up.

### Options

Via ⚙ on the integration card. Both are Home Assistant-side only — neither
writes anything to the panel.

- **Arm and disarm without entering the code** — skips the Home Assistant code
  prompt so dashboard buttons and automations can act directly. Your PIN still
  reaches the panel either way; this only controls whether Home Assistant asks
  you to type it first. **Leave it off** if anyone who can reach your dashboard
  should not be able to disarm the alarm.
- **Event timestamp offset** — only needed if *Last event* times look wrong,
  which happens when the panel clock is in another time zone.

<details>
<summary>Upgrading from a YAML setup</summary>

Delete nothing first. On restart your existing `visonicalarm:` block is imported
into a config entry automatically, and a repair notice tells you to remove it.
Do that, restart again, and the notice clears itself.

**Your entity IDs are preserved.** They are pinned by `unique_id` and every
historical value is kept, so dashboards and automations referencing
`alarm_control_panel.visonic_alarm` or `sensor.visonicalarm_*` keep working
untouched.

</details>

---

## Entities

<details open>
<summary><b>Panel</b></summary>

| Entity | |
| --- | --- |
| `alarm_control_panel` | Arm home, arm away, disarm |
| `binary_sensor.*_cloud_connection` | **The important one** — off means you are looking at cached data |
| `binary_sensor.*_problem` | Active troubles, with type, zone and room |
| `binary_sensor.*_triggered` | An alarm is active |
| `binary_sensor.*_ready_to_arm` | Whether arming would succeed right now |
| `binary_sensor.*_zones_bypassed` | Any zone excluded from arming |
| `binary_sensor.*_broadband` / `*_gprs` | Per-transport connectivity |
| `sensor.*_trouble_count` | Numeric, so it graphs and alerts |
| `sensor.*_last_event` | Last event, with user and description |
| `sensor.*_panel` | Model, features, users, REST version |

</details>

<details open>
<summary><b>Per zone</b></summary>

Each enrolled zone becomes its own device under the panel:

| Entity | |
| --- | --- |
| `binary_sensor.<room>` | Contacts use the `door` class and report real open/closed |
| `switch.<room>_bypass` | Bypass or unbypass the zone |

Attributes: room, zone type, enrollment ID, bypass, soak test, faults, RF signal
and channel.

</details>

<details>
<summary><b>Actions</b></summary>

| Action | |
| --- | --- |
| `visonicalarm.refresh` | Poll the panel immediately |
| `visonicalarm.sound_siren` | Sound the siren — a panic alarm |
| `visonicalarm.silence_siren` | Silence a sounding siren |
| `visonicalarm.set_zone_name` | Rename a zone on the panel itself |

Sirens are **actions rather than switches** on purpose. Sounding a house alarm
should take a deliberate call, not one stray toggle on a dashboard.

</details>

### How often it updates

| Every | What |
| --- | --- |
| **10 seconds** | Arm state, readiness, device state — matching what the mobile app does |
| **5 minutes** | Troubles, alerts, event log, capabilities — these move rarely and the API is rate sensitive |

Arming, disarming and bypassing refresh immediately rather than waiting.

---

## Known limitations

Properties of the panel and the cloud API, not bugs:

- **Motion detectors never report live motion.** The cloud only publishes whether
  a zone *participates* in the current arm mode — "is this detector armed", not
  "is someone moving". Use real PIR sensors for motion.

  You cannot work around this by going local. On PowerMaster panels the
  **sensors stop transmitting to the panel while it is disarmed**, to save
  battery, so nothing downstream can know. The
  [Homey PowerMax app](https://github.com/nlrb/com.visonic.powermax), which
  reads the panel over a direct serial cable, documents the same constraint.

- **Signal strength is a stored survey, not telemetry.** Every device reports the
  same enrollment-era timestamp, so it is exposed as `signal_surveyed` rather
  than dressed up as a live reading.

- **Room names need the panel online.** While a panel is not reporting, the
  device `traits` object comes back empty — so room labels, bypass state and
  signal are all unavailable.

- **A disconnected panel does not make entities unavailable.** See below.

---

## Troubleshooting

### When the panel stops reporting

**This is the failure mode worth understanding.** If the panel loses its link to
the cloud, the cloud keeps serving its **last known arm state**. Nothing goes
unavailable, nothing errors — the alarm entity quietly freezes, and every
automation that trusts it carries on believing stale data.

That is what `binary_sensor.*_cloud_connection` is for, and why this integration
raises a repair notice when it happens.

If it is off:

1. Check the panel's broadband or GPRS connection.
2. If the panel **has** an IP address and still will not connect, check which
   server address it is configured to report to. A panel provisioned for a
   monitoring service that has since been shut down looks perfectly healthy on
   the network while never connecting to anything. Re-pointing it is done in the
   panel's installer menu.

<details>
<summary><b>Setup keeps failing</b></summary>

In order of likelihood: the keypad PIN was entered as the account password; the
panel serial has a typo; an installer code was used instead of a user code.
Confirm the exact same details sign in to the mobile app.

</details>

<details>
<summary><b>Credentials rejected after months of working</b></summary>

The cloud session expires. This fork detects that and re-authenticates on its
own — the original could not, which is why it used to need a full restart. If it
persists, use the reauth prompt; usually the app password or keypad PIN changed.

</details>

<details>
<summary><b>Lots of INACTIVE troubles right after a reconnect</b></summary>

Expected. The cloud has no recent report from any device yet, so everything looks
inactive at once. They clear as each sensor checks in over the following hours.
Anything **still** inactive the next day is a real fault, usually a battery.

</details>

<details>
<summary><b>Getting logs and diagnostics</b></summary>

```yaml
logger:
  logs:
    custom_components.visonicalarm: debug
```

Diagnostics download from the integration card. Credentials, serials and
identifying details are redacted automatically, so it is safe to attach to an
issue.

</details>

---

## Automation ideas

<details open>
<summary><b>Tell me when the alarm stops reporting</b> — the failure you would otherwise never notice</summary>

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

</details>

<details>
<summary><b>Warn if armed with a zone bypassed</b></summary>

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

</details>

<details>
<summary><b>Flag a sensor that has genuinely dropped off</b></summary>

The six-hour delay skips the post-reconnect noise, so this only fires for real
faults.

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

</details>

---

## Project status

**This is the maintained continuation of Visonic Alarm for Home Assistant.**

Upstream [And3rsL/VisonicAlarm-for-Hassio](https://github.com/And3rsL/VisonicAlarm-for-Hassio)
was archived in December 2025 — and so was the library it depended on,
[And3rsL/VisonicAlarm2](https://github.com/And3rsL/VisonicAlarm2). Both are
frozen, and the open issues on them will never be answered. And3rsL did all the
original work and deserves the credit for it.

Vendoring that client is what made the rest possible:

| Fixed | |
| --- | --- |
| **Stale sessions self-heal** | `is_token_valid` was a property returning the *bound method* `is_logged_in` without calling it, so `== False` was always False and the reconnect branch was dead code. Recovery used to need a full Home Assistant restart. |
| **Auth failures are detected** | The old request helper caught `HTTPError`, logged it and returned `None`, so a 401 was indistinguishable from an empty response |
| **`python-dateutil==2.7.3` pin removed** | That 2018 pin won inside the container and downgraded dateutil for *every other integration*. There are now **no external requirements at all**. |
| **Session token no longer published** | It was reaching the states API, the recorder database and any dashboard showing the panel |
| **Shutdown error flood** | A global event listener was registered and never unregistered, producing ~250 errors on every shutdown |

Quality scale: **platinum** — async on aiohttp with an injected session, strict
typing, device registry, diagnostics, repair issues, reauth and reconfigure
flows, entity and icon translations. The
[self-assessment](custom_components/visonicalarm/quality_scale.yaml) records how
each rule is met and says so honestly where one is exempt.

---

## Related projects

Two fundamentally different ways to reach a Visonic panel. Which is right depends
on whether you can get a cable to it.

**Cloud** — no extra hardware, works from anywhere, but needs internet and
depends on the panel keeping its own link up.

| | |
| --- | --- |
| **This fork** | UI setup, zone bypass, siren actions, panel health |
| [nitaybz/visonic-cloud](https://github.com/nitaybz/visonic-cloud) | Similar architecture |
| [msp1974/VisonicAlarm-for-Hassio](https://github.com/msp1974/VisonicAlarm-for-Hassio) | Uses [pyvisonicalarm](https://github.com/msp1974/pyvisonicalarm) |

**Local serial / TTL** — real time, no internet needed, and can read settings the
cloud never exposes. Needs an RS-232 or TTL interface plus a serial-to-Ethernet
adapter wired to the panel.

| | |
| --- | --- |
| [davesmeghead/visonic](https://github.com/davesmeghead/visonic) | Home Assistant — the mature local option |
| [nlrb/com.visonic.powermax](https://github.com/nlrb/com.visonic.powermax) | Homey |

> Not related: **Homely** is a separate Norwegian alarm company with its own
> hardware and API. If that is what you were looking for, see
> [ludvikroed/homely-integration](https://github.com/ludvikroed/homely-integration).

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

CI enforces all four, with coverage held above 95%.

Test fixtures are real API payloads with identifying details replaced. Using real
response *shapes* rather than hand-written stubs is what surfaced several of the
quirks documented above — including one where legacy zone sensors were registered
with integer `unique_id`s while everything else used strings.

---

## Credits

- [**And3rsL**](https://github.com/And3rsL) — the original integration and
  library this builds on
- [**msp1974**](https://github.com/msp1974) — whose
  [pyvisonicalarm](https://github.com/msp1974/pyvisonicalarm) documents the
  bypass, siren and rename endpoints that are published nowhere else
- [**nlrb**](https://github.com/nlrb) — whose Homey app explained *why*
  PowerMaster sensors go quiet when disarmed

<p align="center">
  <br>
  <a href="https://buymeacoffee.com/nino6689"><img src="https://img.shields.io/badge/buy_me_a_coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black" alt="Buy Me A Coffee"></a>
  <br><br>
  <sub>MIT licensed — see <a href="LICENSE">LICENSE</a></sub>
</p>
