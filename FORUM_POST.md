# Forum post — ready to paste

**Where:** https://community.home-assistant.io/ → **Custom Integrations** category → **+ New Topic**

**Title:**

```
Visonic / Bentel / Tyco alarm — maintained fork of the cloud integration (upstream archived)
```

**Tags:** `visonic` `alarm` `custom-integration`

---

## Body — paste everything below this line

The Visonic cloud integration most people were using, [And3rsL/VisonicAlarm-for-Hassio](https://github.com/And3rsL/VisonicAlarm-for-Hassio), was **archived in December 2025** — and so was the library it depends on, [And3rsL/VisonicAlarm2](https://github.com/And3rsL/VisonicAlarm2). Both are frozen and the open issues can't be answered. And3rsL did all the original work and deserves the credit for it.

I've been maintaining a fork, and it's now at a point where it's worth sharing:

**https://github.com/Nino6689/VisonicAlarm-for-Hassio**

### If yours stopped working, this is probably why

The most common failure is this one:

```
Connection failed: Rest API version 8.0, 9.0 or 10.0 is not supported by server.
Supported versions: 14.0
```

The old library had a hardcoded version list. This fork negotiates whatever the server advertises, so it works on REST 14.0 panels.

The other common one is an intermittent `'NoneType' object is not subscriptable` — often about once a day — that a Home Assistant restart clears. That's the cloud session expiring. The upstream code *tried* to reconnect, but `System.is_token_valid` was a `@property` returning the *bound method* `API.is_logged_in` without calling it, so `is_token_valid == False` was always False and the reconnect branch was unreachable. Sessions now re-authenticate on their own.

A third one worth knowing even if you don't use this fork: the upstream manifest pins `python-dateutil==2.7.3`, a 2018 release. That pin **wins inside the Home Assistant container** and downgrades dateutil for every other integration you have. This fork vendors the client and has **no external requirements at all**.

### What's changed

- **Set up in the UI** — config flow with reauth, reconfigure and options. Existing YAML is imported automatically and **entity IDs are preserved**, so dashboards and automations keep working.
- **Panel health** — the upstream fetched troubles, alerts and alarms and then discarded them. There's now a cloud-connection sensor (the important one: when it's off, everything else you're looking at is cached), active troubles named by room, per-transport connectivity, and the panel event log with the user who caused it.
- **Zone bypass** — a switch per zone. Worth knowing that a bypassed zone is **not** reported as a trouble by the panel, so the system says "armed" while that zone does nothing. There's a sensor for it now.
- **Every enrolled device gets an entity** — keypads, sirens, smoke detectors and the PowerLink previously got none, so a keypad reporting `LOW_BATTERY` was invisible. That's the complaint in upstream issues #32, #43, #48 and #57.
- **Siren actions** — panic and silence, as explicit actions rather than switches.
- The live session token is no longer published as an entity attribute. It used to reach the states API, the recorder database and any dashboard showing the panel.

### Two things it does *not* fix

**Motion detectors still don't report live motion.** The cloud only publishes whether a zone participates in the current arm mode. This is not something a different integration would solve either — on PowerMaster panels the sensors stop transmitting to the panel while it's disarmed, to save battery, so nothing downstream can know. The [Homey PowerMax app](https://github.com/nlrb/com.visonic.powermax), which reads the panel over a direct serial cable, documents the same constraint.

**Multiple partitions aren't supported** (upstream #41). It works against partition −1 only. If you need partitions, that's still open.

### Cloud or local?

**Correction, from the author himself below:** I originally described
[davesmeghead/visonic](https://github.com/davesmeghead/visonic) as the *local* option. It is no
longer local-only — it has **cloud capability too**, currently a pre-release on HACS, tested
against a PowerLink 3.1 on REST API 14.0, and **it supports multiple partitions**. It also does
image/video/audio from PIR camera sensors now, and `serial_proxy` via ESPHome makes the wired
route much easier than it used to be. There's a long-running thread for it
[here](https://community.home-assistant.io/t/visonic-powermax-and-powermaster-integration/316702).

So treat these as two mature options rather than a cloud one and a local one. If you want
partitions, or a wired connection, or camera media, go there. This one needs nothing but your
Visonic GO / Connect Alarm login and no hardware at all, and it's where I've put the work into
panel health, per-device faults and zone bypass. We're comparing notes.

### Installing

HACS → Custom repositories → `https://github.com/Nino6689/VisonicAlarm-for-Hassio`, category Integration. It's also submitted to the HACS default store, so eventually it'll be a plain search.

Issues and PRs welcome. I'm running it against a PowerMaster 360R on REST API 14.0; reports from other panel models are especially useful, since that's the one thing I can't test myself.
