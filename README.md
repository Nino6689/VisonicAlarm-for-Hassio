> **Maintained fork.** The upstream repository
> [And3rsL/VisonicAlarm-for-Hassio](https://github.com/And3rsL/VisonicAlarm-for-Hassio)
> was archived in December 2025 (last release 3.3.6). This fork exists to keep the
> integration working against current Home Assistant releases. The `visonicalarm`
> domain and all entity IDs are unchanged, so it is a drop-in replacement.
>
## What this fork changes (3.4.0)

The `visonicalarm2` library is now **vendored** as `visonic_api.py`. Its upstream
repository was archived on the same day as this one, so depending on it meant
depending on two dead projects and it could not be fixed in place.

**Fixed**

- **Stale sessions now self-heal** (upstream [VisonicAlarm2#16][i16]). The old
  `System.is_token_valid` was a `@property` that returned the *bound method*
  `API.is_logged_in` without calling it, so `is_token_valid == False` was always
  False and the reconnect branch was dead code. Sessions could only be recovered
  with a full Home Assistant restart. Requests now retry once after
  re-authenticating.
- **Auth failures are actually detected.** The old request helper caught
  `HTTPError`, logged it and returned `None`, making a 401 indistinguishable from
  an empty response. Errors now propagate. Note PowerManage returns **400**, not
  401, for an unrecognised *session* token — that is handled explicitly.
- **`python-dateutil==2.7.3` pin removed.** That 2018 pin won inside the Home
  Assistant container and downgraded dateutil for every other integration.
  Timestamps now use `datetime.fromisoformat`. The integration has **no**
  external requirements at all.
- **The session token is no longer published as an entity attribute.** It was
  being written to the states API, the recorder database and any dashboard
  showing the panel.
- **Removed the leaking global event listener.** The panel registered an
  `EVENT_STATE_CHANGED` listener it never unregistered, which produced ~250
  errors on every shutdown. Arm-state changes are detected inside the entity's
  own update instead.

**Added** — the integration previously fetched troubles, alerts and alarms and
then discarded them. They are now surfaced, along with endpoints the library
never implemented (`/feature_set`, `/users`, `/panels`, `/cameras`,
`/smart_devices`):

| Entity | Why it matters |
| --- | --- |
| `binary_sensor.visonic_alarm_cloud_connection` | Whether the cloud can reach the panel. When off, every other Visonic entity is showing cached data. |
| `binary_sensor.visonic_alarm_problem` | Active troubles, with type/zone/location attributes. |
| `binary_sensor.visonic_alarm_triggered` | Active alarms. |
| `binary_sensor.visonic_alarm_ready_to_arm` | Whether arming would succeed. |
| `binary_sensor.visonic_alarm_broadband` / `_gprs` | Per-transport connectivity. |
| `binary_sensor.visonic_zone_*` | Zones with real device classes. |
| `sensor.visonic_alarm_trouble_count` | Numeric, so it graphs and alerts. |
| `sensor.visonic_alarm_last_event` | Last panel event with user and timestamp. |
| `sensor.visonic_alarm_panel` | Model, alias, features, users, REST version. |

**Not** grouped under a panel device: this integration is configured from YAML,
so its entities have no config entry, and Home Assistant only creates device
registry entries for entities that do. Grouping needs a config-entry migration,
which is tracked separately.

**Compatibility:** `alarm_control_panel.visonic_alarm` and the existing
`sensor.visonicalarm_*` zone entities keep their exact entity IDs — their
`unique_id` values are unchanged. The YAML configuration schema is unchanged.

> ⚠️ Motion zones: the cloud API never publishes live motion. It only reports
> whether a zone participates in the current arm mode, which is what the motion
> entities reflect. Use real PIRs if you need motion detection.

[i16]: https://github.com/And3rsL/VisonicAlarm2/issues/16

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
<br><a href="https://www.buymeacoffee.com/4nd3rs" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-black.png" width="150px" height="35px" alt="Buy Me A Coffee" style="height: 35px !important;width: 150px !important;" ></a>

## Visonic/Bentel/Tyco Alarm Sensor
This component interfaces with the API server hosted by your home alarm system company.

It is dependant on the Python module: https://github.com/And3rsL/VisonicAlarm2 which will automatically be installed when running the sensor component. This library has much more functionality than this component utilises, so feel free to check it out of you are into Python 3 programming.

This is unsupported by Visonic - they don't publish their REST API. It is also unsupported by me. I accept no liability for your use of the component or library nor for any loss or damage resulting from security breaches at your property.

### Introduction
This component will create one **alarm_control_panel** that let you show the current state of the alarm system and also to arm and disarm the system. It will also create one **sensor** for every door/window contact that let you see if the doors or windows are open or closed.

The Alarm Control Panel will be called **alarm_control_panel.visonic_alarm** and the contact sensors will be called **sensor.visonic_alarm_contact_ID** (where ID is the contact ID in the alarm system).

It polls the API server every 10 seconds, which is the same interval as the app does its updates. So there is up to a 10 second delay between updates.

### Requirements
The component has only been tested with a Visonic PowerMaster 10 with a PowerLink 3 ethernet module, so it might not work with (but should) other Visonic alarm systems.

### Configuration
Now to the configuration of Home Assistant.

Open the configuration file (`configuration.yaml`) and use the following code:
```yaml
visonicalarm:
  host: YOURALARMCOMPANY.tycomonitor.com
  panel_id: 123456
  user_code: 1234
  app_id: 00000000-0000-0000-0000-000000000000
  user_email: 'example@email.com'
  user_password: 'yourpassword'
  partition: -1
  no_pin_required: False
```

The **host**, **user_code**, **panel_id**, **user_email**, **user_password** are the same you are using when logging in to your system via the Visonic-GO/BW app,
and **user_id** is just a uniqe id generated from this site: https://www.uuidgenerator.net/ so make sure you replace 00000000-0000-0000-0000-000000000000 with an ID that you generate with that site. There is only support for the -1 partition.

Please be sure that the user is the MASTER USER and you alredy added your panel in your registered account

### Screenshots ###
![Alarm Panel dialog](https://github.com/And3rsL/VisonicAlarm-for-Hassio/blob/master/HomeAssistantArmDialog2.png)
