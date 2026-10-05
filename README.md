# Observing Time Reservation

[![Tests](https://github.com/jan-tdy/ha-observing-time-reservation/actions/workflows/test.yml/badge.svg)](https://github.com/jan-tdy/ha-observing-time-reservation/actions/workflows/test.yml)
[![Validate](https://github.com/jan-tdy/ha-observing-time-reservation/actions/workflows/validate.yml/badge.svg)](https://github.com/jan-tdy/ha-observing-time-reservation/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A [Home Assistant](https://www.home-assistant.io/) **custom integration + a full
sidebar panel** that lets clients reserve observing time on a telescope, and then -
for the exact duration of their slot, nothing before or after - unlocks a
full-page telescope control view: goto, park/tracking, exposure/filter/focuser,
live preview and frame saving. It's a sidebar item (like Map or Energy), not a
small dashboard tile - the goal is something that actually replaces CCDciel for
the observing session itself, not a status widget.

Built for the **Bombol.Space** telescope hosting facility, part of the
**DevControl2** project. It is backend-agnostic: it talks to whatever entities
[`ha-indi-client`](https://github.com/jan-tdy/ha-indi-client) or
[`ha-seestar`](https://github.com/jaxzin/ha-seestar) already expose - it does not
replace either of them, it sits on top and adds reservations + access control.

## How it fits together

```
ha-indi-client / ha-seestar   -->  normal HA entities (number, select, button, camera, ...)
                                              |
                                              |  admin maps each capability to one
                                              |  of those entities (native HA entity
                                              |  picker, once, in the options flow)
                                              v
            observing_time_reservation (this integration)
    - availability windows (admin opens them, e.g. "tomorrow 20:00-23:00")
    - reservations (clients book inside an open window, first-come-first-served)
    - access control (commands are only forwarded while the caller holds
      the *currently active* reservation for that telescope)
    - periodic frame saving to a configurable folder while a session records
    - usage log per client, for the admin to invoice manually elsewhere
                                              |
                                              v
                 "Observing Time" sidebar panel (full page, ships inside this
                 integration, discovers every telescope itself over websocket -
                 nothing to configure)
    - tabs across the top if you have more than one telescope
    - booking view: availability + "reserve a slot"
    - control view: unlocks automatically for whoever currently holds the slot
    - admin view: set the next availability window, see usage per client
```

A small Lovelace card (`observing-time-reservation-card`) ships alongside the
panel too, for a compact status/booking tile on a regular dashboard - but the
panel is the primary interface and needs no per-card configuration.

One config entry = one telescope. Add as many as you have (today: one, with more
coming) - each gets its own calendar/sensor/binary_sensor entities and capability
mapping.

## Installation

### Via HACS (custom repository)

1. HACS -> Integrations -> the `⋮` menu (top right) -> **Custom repositories**.
2. URL: `https://github.com/jan-tdy/ha-observing-time-reservation`, category:
   **Integration**.
3. Install **Observing Time Reservation**, then restart Home Assistant.

The card is bundled inside the integration and registers itself automatically
(via `add_extra_js_url`) - there is no separate Lovelace resource to add by hand.

### Manual

Copy `custom_components/observing_time_reservation` into your Home Assistant
`config/custom_components/` directory, then restart Home Assistant.

## Setting up a telescope

1. **Settings -> Devices & services -> Add integration -> Observing Time
   Reservation**.
2. Give it a name (e.g. `Bombol 1`) and pick its backend (`ha-indi-client`,
   `ha-seestar`, or `manual`).
3. Pick every HA device that belongs to this telescope. A telescope is rarely
   one HA device - INDI gives the mount, CCD/camera, focuser and filter wheel
   each their own device - so this step takes a *list*, not a single device
   (optional either way; you can still map entities freely afterwards, and
   change the list later from **Configure**).
4. Open the integration entry's **Configure** (options flow):
   - reservation rules: min/max duration, start-time granularity, image folder,
     auto-save interval while recording, admin HA user IDs, and the same
     device list from step 3 (editable here too);
   - capability mapping: for each abstract action (goto RA/Dec, park, tracking,
     start/stop capture, exposure, filter, focuser, CCD temperature, the
     controls-enabled gate, allow-power-actions, startup sequence, shutdown,
     dew heater, live/preview camera, status sensor) pick the existing entity
     it should drive. This uses HA's own entity selector, so it's the same
     dropdown you already know from every other integration - there is
     nothing to type or get wrong - and, when step 3 named at least one
     device, the dropdown only lists entities from those devices instead of
     every entity in the house. Leave a capability blank if your backend has
     no matching entity (e.g. `ha-seestar` has no "Unpark"); the UI simply
     hides that control instead of showing a dead button.

The service -> entity mapping is inferred automatically from the entity's
domain (`button.press`, `number.set_value`, `select.select_option`,
`text.set_value`, `switch.turn_on`/`turn_off`), so the admin never has to name a
service by hand. For a `select`-domain target (e.g. `ha-indi-client`'s Park,
which is one dropdown with "Park"/"Unpark" options, not two buttons) the UI
reads the entity's *actual* current `options` at click time and matches the
one that looks right, rather than guessing driver-specific label text.

If you map `controls_enabled` (`ha-seestar`'s "Controls enabled" switch,
without which it silently refuses every command), the integration arms it
automatically the moment a reservation becomes active and disarms it the
moment the session ends - you never have to remember to flip it yourself.
`allow_power_actions` is the opposite: a manual switch in the control panel,
left to the client to arm deliberately right before Park/Startup/Shutdown,
per `ha-seestar`'s own safety guidance.

## The "Observing Time" panel (primary interface)

After installing and setting up at least one telescope, an **"Observing Time"**
item appears in the HA sidebar automatically - nothing to add to a dashboard,
no entity ids to type anywhere. It covers every telescope you've configured
(with tabs across the top if you have more than one), discovering each one's
entities itself over a small websocket API the integration registers
(`observing_time_reservation/list_telescopes`).

### What a client sees

- **Free / someone else's slot:** the open availability windows and a start/end
  picker to reserve a slot inside one of them.
- **Their own active slot:** the booking form is replaced by the control panel -
  park/unpark, tracking, goto (RA/Dec + execute/stop), exposure/filter/focuser/CCD
  temperature, start/stop capture, a live preview image, a "save every frame"
  switch and a manual "save frame now" button, plus the session log if the
  backend exposes one. Every button is just a thin wrapper around the
  `observing_time_reservation.send_command` service, which the integration
  *re-checks server-side* against the active reservation before touching any
  entity - so this isn't just a UI lock, a client cannot drive the scope
  outside their booked slot even by calling the service directly.

### What an admin additionally sees

A panel to open the next availability window (start/end), and a per-client
usage table (sessions + total minutes) to invoice manually outside this system -
billing itself is intentionally out of scope for now.

## Adding the card (optional, compact dashboard tile)

A small Lovelace card ships alongside the panel for a quick status/booking
widget on a regular dashboard - the panel above is the full interface and
needs none of this configuration.

```yaml
type: custom:observing-time-reservation-card
title: Bombol 1
config_entry_id: <the telescope's config entry id - see the integration page URL>
in_use_entity: binary_sensor.bombol_1_in_use
availability_entity: sensor.bombol_1_availability
usage_entity: sensor.bombol_1_usage        # optional, only rendered for admins
live_camera_entity: camera.bombol_1_live   # optional, used for the control-panel preview
preview_camera_entity: camera.bombol_1_ccd # optional, same entity you mapped for frame saving
```

The card ships with a graphical editor too (native `ha-form`), so you can add it
through **Edit dashboard -> Add card -> Observing Time Reservation** instead of
hand-writing YAML. It behaves the same way as the panel (booking view /
control view / admin view), just scaled down to card size.

## Services

| Service | Purpose |
|---|---|
| `observing_time_reservation.reserve` | Book `start`-`end` on a telescope for the calling user. |
| `observing_time_reservation.cancel_reservation` | Cancel your own reservation (or any, as an admin). |
| `observing_time_reservation.set_availability` | Admin-only: replace the list of open windows. |
| `observing_time_reservation.send_command` | Dispatch an abstract capability (`goto`, `park`, `set_exposure`, ...) - only works while you hold the active reservation. |
| `observing_time_reservation.set_recording` | Arm/disarm periodic frame saving for your session. |
| `observing_time_reservation.save_frame` | Save one frame immediately. |

See [`services.yaml`](custom_components/observing_time_reservation/services.yaml)
for full field definitions - they also show up in **Developer tools -> Actions**
with proper selectors.

## Known limitations / next steps

- **Billing is out of scope for now.** The usage sensor gives the admin exactly
  what's needed to invoice manually; no payment flow exists yet.
- **One capability = one entity.** This is enough for every INDI/Seestar control
  surfaced today (a goto needs two text/number entities for RA/Dec plus one
  button to execute - modelled as three separate capabilities, and the
  execute step is simply skipped when a backend has none, since
  `ha-indi-client` itself has no separate "goto" trigger - writing the RA/Dec
  number elements directly *is* the goto), but a property that genuinely
  needs several simultaneous values in one call isn't supported; use
  `ha-indi-client`'s `indi_client.set_property` service directly for that
  rare case.
- **Exposure units differ by backend and aren't converted.** `ha-seestar`'s
  stacking exposure is milliseconds; `ha-indi-client`'s `CCD_EXPOSURE` is
  typically seconds. The control panel shows whatever
  `unit_of_measurement` the mapped number entity itself reports, so the
  field is always labelled correctly - but it sends the raw number through
  unchanged, so read the label.
- **Frame storage is local disk only.** `image_base_path` currently has to be a
  path the HA process can write to directly; moving it to a mounted USB drive
  once storage grows is just a matter of changing that option (no code change).
  The directory must also be listed in HA's `allowlist_external_dirs`
  (`camera.snapshot` refuses to write outside it), e.g.:
  ```yaml
  homeassistant:
    allowlist_external_dirs:
      - /config/observing_sessions
  ```
- **No conflict/weather awareness beyond overlap checking.** Availability
  windows and reservations are purely time-based; cloud-cover/weather-based
  auto-cancellation is not implemented.
- **HA accounts for clients are created manually by the admin** (Settings ->
  People); there is no self-service signup flow.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

`reservation.py` (availability/overlap/validation logic) has zero Home Assistant
imports on purpose, mirroring `ha-indi-client`'s protocol-core split, so it is
fully unit tested without a running HA instance.

## License

[MIT](LICENSE)
