# Observing Time Reservation

[![Tests](https://github.com/jan-tdy/ha-observing-time-reservation/actions/workflows/test.yml/badge.svg)](https://github.com/jan-tdy/ha-observing-time-reservation/actions/workflows/test.yml)
[![Validate](https://github.com/jan-tdy/ha-observing-time-reservation/actions/workflows/validate.yml/badge.svg)](https://github.com/jan-tdy/ha-observing-time-reservation/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A [Home Assistant](https://www.home-assistant.io/) **custom integration + Lovelace
card** that lets clients reserve observing time on a telescope, and then - for the
exact duration of their slot, nothing before or after - unlocks a full telescope
control panel right in the same card: goto, park/tracking, exposure/filter/focuser,
live preview and frame saving.

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
                 observing-time-reservation-card (Lovelace card, ships inside
                 this integration, no manual resource/build step needed)
    - booking view: availability + "reserve a slot" + "my reservations"
    - control view: unlocks automatically for whoever currently holds the slot
    - admin view: set the next availability window, see usage per client
```

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
     start/stop capture, exposure, filter, focuser, CCD temperature, live/preview
     camera, status sensor) pick the existing entity it should drive. This uses
     HA's own entity selector, so it's the same dropdown you already know from
     every other integration - there is nothing to type or get wrong - and,
     when step 3 named at least one device, the dropdown only lists entities
     from those devices instead of every entity in the house.

The service -> entity mapping is inferred automatically from the entity's
domain (`button.press`, `number.set_value`, `select.select_option`,
`text.set_value`, `switch.turn_on`/`turn_off`), so the admin never has to name a
service by hand.

## Adding the card

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
hand-writing YAML.

### What a client sees

- **Free / someone else's slot:** the open availability windows, a start/end
  picker to reserve a slot inside one of them, and their own upcoming
  reservations.
- **Their own active slot:** the booking form is replaced by the control panel -
  park/unpark, tracking, goto (RA/Dec + execute/stop), exposure/filter/focuser/CCD
  temperature, start/stop capture, a live preview image, a "save every frame"
  switch and a manual "save frame now" button. Every button is just a thin
  wrapper around the `observing_time_reservation.send_command` service, which the
  integration *re-checks server-side* against the active reservation before
  touching any entity - so this isn't just a UI lock, a client cannot drive the
  scope outside their paid/booked slot even by calling the service directly.

### What an admin additionally sees

A small panel to open the next availability window (start/end), and a per-client
usage table (sessions + total minutes) to invoice manually outside this system -
billing itself is intentionally out of scope for now.

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
  button to execute - modelled as three separate capabilities), but a property
  that genuinely needs several simultaneous values in one call isn't supported;
  use `ha-indi-client`'s `indi_client.set_property` service directly for that
  rare case.
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
