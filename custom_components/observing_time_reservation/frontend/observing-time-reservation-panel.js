/**
 * Observing Time Reservation panel.
 *
 * Registered as a full-page HA sidebar panel (via panel_custom), not a
 * Lovelace card - this is the primary, CCDciel-style interface: it covers
 * every telescope by itself (discovered over websocket, see
 * websocket_api.py's `observing_time_reservation/list_telescopes`), so
 * nothing needs to be typed into a card config. A compact Lovelace card
 * (observing-time-reservation-card.js) still exists separately for a small
 * dashboard tile.
 *
 * Plain custom element, no bundler/dependencies - same approach as the
 * card, using only native ha-* components so it matches stock HA styling.
 *
 * HA sets these properties on the element directly (see
 * ha-panel-custom.ts / setCustomPanelProperties upstream): hass, panel,
 * narrow, route.
 */

const DOMAIN = "observing_time_reservation";

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toLocalInputValue(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

class ObservingTimeReservationPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._telescopes = null;
    this._selectedEntryId = null;
    this._pending = false;
    this._error = null;
    this._lastSignature = undefined;
    // Draft rows for the sequence builder (see _renderSequence). Each row
    // only carries a stable `key` (never reused positionally) so removing
    // a row in the middle doesn't shift other rows' element ids - field
    // values are read straight off the DOM at submit time, same as every
    // other form in this panel.
    this._sequenceKeySeq = 1;
    this._sequenceDraft = [{ key: 0 }];
  }

  set hass(hass) {
    this._hass = hass;
    this._maybeLoadTelescopes();
    const signature = this._relevantSignature();
    if (signature !== this._lastSignature) {
      this._lastSignature = signature;
      this._render();
    }
  }

  get hass() {
    return this._hass;
  }

  // The following are set by ha-panel-custom; we don't need their values,
  // but must accept them without throwing.
  set panel(panel) {
    this._panel = panel;
  }

  set narrow(narrow) {
    this._narrow = narrow;
    this._render();
  }

  set route(route) {
    this._route = route;
  }

  // -- data loading -----------------------------------------------------

  _maybeLoadTelescopes() {
    if (this._telescopesPromise || !this._hass) return;
    this._telescopesPromise = this._hass
      .callWS({ type: `${DOMAIN}/list_telescopes` })
      .then((data) => {
        this._telescopes = data.telescopes;
        this._isAdmin = data.is_admin;
        this._userId = data.user_id;
        if (!this._selectedEntryId && this._telescopes.length) {
          this._selectedEntryId = this._telescopes[0].entry_id;
        }
        this._render();
      })
      .catch((err) => {
        this._error = (err && err.message) || String(err);
        this._render();
      });
  }

  _selectedTelescope() {
    if (!this._telescopes) return null;
    return this._telescopes.find((t) => t.entry_id === this._selectedEntryId) || null;
  }

  // Target-name catalog (Messier + other named deep-sky objects) for the
  // goto search box - fetched once, lazily, from the static file this
  // integration serves (see CATALOG_URL_PATH in __init__.py). Non-critical:
  // if it fails to load, the search box just has nothing to suggest, and
  // the raw RA/Dec fields next to it still work as always.
  _maybeLoadCatalog() {
    if (this._catalogPromise) return;
    this._catalogPromise = fetch(`/${DOMAIN}/catalog.json`)
      .then((r) => r.json())
      .then((data) => {
        this._catalogIndex = new Map();
        const addEntry = (label, ra, dec) => this._catalogIndex.set(label, { ra, dec });
        (data.messier || []).forEach((o) => {
          const extra = (o.common_names && o.common_names[0]) || o.type || "";
          addEntry(`${o.messier}${extra ? " — " + extra : ""}`, o.ra, o.dec);
        });
        (data.named || []).forEach((o) => {
          const name = (o.common_names && o.common_names[0]) || o.id;
          addEntry(`${name} (${o.id})`, o.ra, o.dec);
        });
        this._render();
      })
      .catch(() => {
        this._catalogIndex = null;
      });
  }


  // -- service helpers ------------------------------------------------

  async _call(service, data) {
    this._pending = true;
    this._error = null;
    this._render();
    try {
      await this._hass.callService(DOMAIN, service, {
        config_entry_id: this._selectedEntryId,
        ...data,
      });
    } catch (err) {
      this._error = (err && err.message) || String(err);
    } finally {
      this._pending = false;
      this._render();
    }
  }

  _sendCommand(capability, value) {
    return this._call("send_command", { capability, value });
  }

  // -- state helpers ----------------------------------------------------

  _inUseState(telescope) {
    return telescope.in_use_entity ? this._hass.states[telescope.in_use_entity] : undefined;
  }

  _availabilityState(telescope) {
    return telescope.availability_entity ? this._hass.states[telescope.availability_entity] : undefined;
  }

  _usageState(telescope) {
    return telescope.usage_entity ? this._hass.states[telescope.usage_entity] : undefined;
  }

  _currentHolder(telescope) {
    const st = this._inUseState(telescope);
    if (!st || st.state !== "on") return null;
    return st.attributes;
  }

  _amIHolder(telescope) {
    const holder = this._currentHolder(telescope);
    return !!(holder && this._userId && holder.client_user_id === this._userId);
  }

  _windows(telescope) {
    const st = this._availabilityState(telescope);
    return (st && st.attributes && st.attributes.windows) || [];
  }

  // -- capability helpers ------------------------------------------------
  // The backend only ever tells us WHICH entity a capability is mapped to
  // (capability_map); everything backend-specific (an entity's current
  // .attributes.options, its unit_of_measurement, whether it exists at
  // all) is read from that entity's live state here, at the moment of the
  // click - never hardcoded, since it differs by backend (e.g.
  // ha-indi-client's Park is a `select` whose two option labels come from
  // the INDI driver; ha-seestar's is a `button` with no options at all,
  // and has no "Unpark" to speak of).

  _capabilityEntity(telescope, cap) {
    return (telescope.capability_map && telescope.capability_map[cap]) || null;
  }

  _hasCapability(telescope, cap) {
    return !!this._capabilityEntity(telescope, cap);
  }

  _resolveCapabilityValue(telescope, cap, hint, fallback) {
    const entityId = this._capabilityEntity(telescope, cap);
    if (!entityId) return fallback;
    if (entityId.split(".")[0] !== "select") return fallback;
    const state = this._hass.states[entityId];
    const options = (state && state.attributes && state.attributes.options) || [];
    const lower = hint.toLowerCase();
    const match = options.find((o) => o.toLowerCase().includes(lower));
    return match || fallback;
  }

  _unitFor(telescope, cap) {
    const entityId = this._capabilityEntity(telescope, cap);
    const state = entityId ? this._hass.states[entityId] : null;
    return (state && state.attributes && state.attributes.unit_of_measurement) || "";
  }

  // Every entity id across every telescope, used to decide whether a hass
  // update is relevant enough to re-render (and not blow away whatever the
  // viewer is mid-typing in an input field for an unrelated reason).
  _relevantSignature() {
    if (!this._hass) return null;
    const ids = [];
    (this._telescopes || []).forEach((t) => {
      [
        "in_use_entity",
        "availability_entity",
        "usage_entity",
        "sequence_entity",
        "live_camera_entity",
        "preview_camera_entity",
        "status_sensor_entity",
      ].forEach((key) => t[key] && ids.push(t[key]));
      // Every mapped action AND reference capability - this is what makes
      // the telemetry grid (current temperature, RA/Dec, stack state, ...)
      // actually update live instead of only ever showing the value from
      // the moment the panel first loaded.
      if (t.capability_map) {
        Object.values(t.capability_map).forEach((id) => id && ids.push(id));
      }
    });
    const states = ids.map((id) => this._hass.states[id] && this._hass.states[id].last_updated);
    return JSON.stringify([states, this._selectedEntryId, this._pending, this._error, this._narrow]);
  }

  // -- render -------------------------------------------------------------

  _render() {
    if (!this.shadowRoot) return;

    if (!this._hass) return;

    if (this._error && !this._telescopes) {
      this.shadowRoot.innerHTML = `<style>${this._styles()}</style>
        <div class="page"><ha-alert alert-type="error">${this._escape(this._error)}</ha-alert></div>`;
      return;
    }

    if (!this._telescopes) {
      this.shadowRoot.innerHTML = `<style>${this._styles()}</style>
        <div class="page loading"><ha-spinner></ha-spinner></div>`;
      return;
    }

    if (this._telescopes.length === 0) {
      this.shadowRoot.innerHTML = `<style>${this._styles()}</style>
        <div class="page">
          <ha-alert alert-type="info">No telescope is configured yet. Add one under
            Settings &rarr; Devices &amp; services &rarr; Add integration &rarr; Observing Time Reservation.</ha-alert>
        </div>`;
      return;
    }

    const telescope = this._selectedTelescope() || this._telescopes[0];
    const holder = this._currentHolder(telescope);
    const amIHolder = this._amIHolder(telescope);

    // Telemetry (and now the sequence sensor) is watched for live updates,
    // which means a re-render can fire mid-keystroke, e.g. while typing a
    // goto RA/Dec or building a sequence step - without this, whatever the
    // viewer just typed would be wiped the moment any sensor ticks.
    const inputSnapshot = this._snapshotInputValues();

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <div class="page">
        <div class="header">
          <h1><ha-icon icon="mdi:telescope"></ha-icon> Observing Time Reservation</h1>
          ${this._telescopes.length > 1 ? this._renderTabs() : ""}
        </div>
        ${this._error ? `<ha-alert alert-type="error">${this._escape(this._error)}</ha-alert>` : ""}
        ${this._renderStatus(holder, amIHolder)}
        ${this._renderTelemetry(telescope)}
        <div class="columns">
          <div class="column">
            ${amIHolder ? this._renderControlPanel(telescope, holder) : this._renderBooking(telescope)}
          </div>
          <div class="column">
            ${this._renderPreview(telescope)}
            ${this._renderStatusLog(telescope)}
          </div>
        </div>
        ${this._isAdmin ? this._renderAdmin(telescope) : ""}
      </div>
    `;
    this._attachListeners(telescope);
    this._restoreInputValues(inputSnapshot);
  }

  // Full-innerHTML re-render is simple but destroys live DOM state, so any
  // text a viewer is mid-typing has to be saved beforehand and reapplied
  // after - otherwise a telemetry tick could wipe a half-typed RA/Dec or
  // sequence step out from under them.
  _snapshotInputValues() {
    const root = this.shadowRoot;
    if (!root) return {};
    const snapshot = {};
    root.querySelectorAll("ha-input, input.target-search").forEach((el) => {
      if (el.id && el.value) snapshot[el.id] = el.value;
    });
    return snapshot;
  }

  _restoreInputValues(snapshot) {
    const root = this.shadowRoot;
    Object.entries(snapshot).forEach(([id, value]) => {
      const el = root.getElementById(id);
      if (el) el.value = value;
    });
  }

  _renderTabs() {
    return `
      <div class="tabs" role="tablist">
        ${this._telescopes
          .map(
            (t) => `
          <button class="tab ${t.entry_id === this._selectedEntryId ? "active" : ""}"
                  data-entry-id="${t.entry_id}">${this._escape(t.name)}</button>
        `
          )
          .join("")}
      </div>
    `;
  }

  _renderStatus(holder, amIHolder) {
    if (!holder) {
      return `<div class="status status-free"><ha-icon icon="mdi:telescope"></ha-icon> Free</div>`;
    }
    if (amIHolder) {
      return `<div class="status status-mine"><ha-icon icon="mdi:account-check"></ha-icon>
        Your session until ${fmtTime(holder.end)}</div>`;
    }
    return `<div class="status status-busy"><ha-icon icon="mdi:account-clock"></ha-icon>
      In use by ${this._escape(holder.client_name)} until ${fmtTime(holder.end)}</div>`;
  }

  // At-a-glance telemetry: what the telescope is actually doing right now
  // (temperature, where it's really pointing, stacking progress, ...) as
  // opposed to the write-only setpoints in the control panel below. Shown
  // to every viewer, not just the current holder.
  _renderTelemetry(telescope) {
    const has = (ref) => this._hasCapability(telescope, ref);
    const stateOf = (ref) => {
      const id = this._capabilityEntity(telescope, ref);
      return id ? this._hass.states[id] : null;
    };
    const display = (ref) => {
      const st = stateOf(ref);
      if (!st) return "";
      const unit = (st.attributes && st.attributes.unit_of_measurement) || "";
      return `${this._escape(st.state)}${unit ? ` ${this._escape(unit)}` : ""}`;
    };

    const items = [
      ["mdi:thermometer", "Temperature", "temperature_sensor_entity"],
      ["mdi:battery-medium", "Battery", "battery_sensor_entity"],
      ["mdi:crosshairs-gps", "Current RA", "current_ra_sensor_entity"],
      ["mdi:crosshairs-gps", "Current Dec", "current_dec_sensor_entity"],
      ["mdi:angle-acute", "Altitude", "altitude_sensor_entity"],
      ["mdi:compass-outline", "Azimuth", "azimuth_sensor_entity"],
      ["mdi:sync", "Tracking", "tracking_state_sensor_entity"],
      ["mdi:rotate-3d-variant", "Slewing", "slewing_state_sensor_entity"],
      ["mdi:parking", "Parked", "at_park_sensor_entity"],
      ["mdi:layers-triple", "Stack state", "stack_state_sensor_entity"],
      ["mdi:image-multiple", "Stacked frames", "stacked_frames_sensor_entity"],
      ["mdi:image-off", "Dropped frames", "dropped_frames_sensor_entity"],
      ["mdi:counter", "Total frames", "total_frames_sensor_entity"],
      ["mdi:timer-sand", "Integration time", "integration_time_sensor_entity"],
      ["mdi:focus-field", "Focuser position", "focuser_position_sensor_entity"],
      ["mdi:filter-variant", "Filter position", "filter_position_sensor_entity"],
    ].filter(([, , ref]) => has(ref));

    if (!items.length) return "";

    return `
      <div class="section telemetry">
        <h2><ha-icon icon="mdi:gauge"></ha-icon> Telemetry</h2>
        <div class="telemetry-grid">
          ${items
            .map(
              ([icon, label, ref]) => `
            <div class="telemetry-item">
              <ha-icon icon="${icon}"></ha-icon>
              <span class="t-label">${label}</span>
              <span class="t-value">${display(ref) || "–"}</span>
            </div>
          `
            )
            .join("")}
        </div>
      </div>
    `;
  }

  _renderBooking(telescope) {
    const windows = this._windows(telescope);
    const now = new Date();
    const defaultStart = toLocalInputValue(new Date(now.getTime() + 5 * 60000));
    const defaultEnd = toLocalInputValue(new Date(now.getTime() + 65 * 60000));

    const windowsHtml = windows.length
      ? `<ul class="windows">${windows
          .map((w) => `<li>${fmtTime(w.start)} &ndash; ${fmtTime(w.end)}</li>`)
          .join("")}</ul>`
      : `<p class="hint">No availability window is open yet - ask the admin.</p>`;

    return `
      <div class="section">
        <h2>Availability</h2>
        ${windowsHtml}
      </div>
      <div class="section">
        <h2>Book a slot</h2>
        <div class="row">
          <ha-input id="start-input" label="Start" type="datetime-local" value="${defaultStart}"></ha-input>
          <ha-input id="end-input" label="End" type="datetime-local" value="${defaultEnd}"></ha-input>
        </div>
        <ha-button id="reserve-btn" appearance="accent" ${this._pending ? "disabled" : ""}>Reserve</ha-button>
      </div>
    `;
  }

  _renderControlPanel(telescope, holder) {
    this._maybeLoadCatalog();

    const has = (cap) => this._hasCapability(telescope, cap);
    const exposureUnit = this._unitFor(telescope, "set_exposure");

    const mountRow = [
      has("park") ? `<ha-button id="park-btn">Park</ha-button>` : "",
      has("unpark") ? `<ha-button id="unpark-btn">Unpark</ha-button>` : "",
      has("set_tracking")
        ? `<div class="switch-row"><span>Tracking</span><ha-switch id="tracking-switch"></ha-switch></div>`
        : "",
    ]
      .filter(Boolean)
      .join("");

    const powerRow = [
      has("allow_power_actions")
        ? `<div class="switch-row"><span>Allow power actions</span><ha-switch id="allow-power-switch"></ha-switch></div>`
        : "",
      has("startup_sequence") ? `<ha-button id="startup-btn">Startup sequence</ha-button>` : "",
      has("shutdown") ? `<ha-button id="shutdown-btn">Shutdown</ha-button>` : "",
    ]
      .filter(Boolean)
      .join("");

    const dewRow = has("set_dew_heater")
      ? `<div class="switch-row"><span>Dew heater</span><ha-switch id="dew-heater-switch"></ha-switch></div>`
      : "";

    return `
      ${
        mountRow || powerRow || dewRow
          ? `<div class="section">
        <h2><ha-icon icon="mdi:axis-arrow"></ha-icon> Mount</h2>
        ${mountRow ? `<div class="row buttons">${mountRow}</div>` : ""}
        ${powerRow ? `<div class="row buttons">${powerRow}</div>` : ""}
        ${dewRow ? `<div class="row buttons">${dewRow}</div>` : ""}
      </div>`
          : ""
      }

      <div class="section">
        <h2><ha-icon icon="mdi:crosshairs-gps"></ha-icon> Goto</h2>
        <div class="row">
          <input id="target-search" class="target-search" list="target-catalog"
                 placeholder="Search target by name (e.g. M31, Andromeda)" autocomplete="off" />
          <datalist id="target-catalog">
            ${this._catalogIndex ? Array.from(this._catalogIndex.keys()).map((label) => `<option value="${this._escape(label)}"></option>`).join("") : ""}
          </datalist>
        </div>
        <div class="row">
          <ha-input id="ra-input" label="RA"></ha-input>
          <ha-input id="dec-input" label="Dec"></ha-input>
        </div>
        <div class="row buttons">
          <ha-button id="goto-btn" appearance="accent">Goto</ha-button>
          ${has("stop_goto") ? `<ha-button id="stop-goto-btn">Stop</ha-button>` : ""}
        </div>
      </div>

      <div class="section">
        <h2><ha-icon icon="mdi:camera-iris"></ha-icon> Imaging</h2>
        <div class="row">
          <ha-input id="exposure-input" label="Exposure${exposureUnit ? ` (${exposureUnit})` : ""}" type="number"></ha-input>
          <ha-input id="filter-input" label="Filter"></ha-input>
          <ha-input id="focus-input" label="Focus"></ha-input>
          <ha-input id="temp-input" label="CCD temp (C)" type="number"></ha-input>
        </div>
        <div class="row buttons">
          <ha-button id="start-capture-btn" appearance="accent">Start capture</ha-button>
          ${has("stop_capture") ? `<ha-button id="stop-capture-btn">Stop capture</ha-button>` : ""}
        </div>
        <div class="row buttons">
          <div class="switch-row">
            <span>Save every frame</span>
            <ha-switch id="recording-switch" ${
              holder.recording === true || holder.recording === "true" ? "checked" : ""
            }></ha-switch>
          </div>
          <ha-button id="save-frame-btn">Save frame now</ha-button>
        </div>
      </div>

      ${this._renderSequence(telescope)}
    `;
  }

  // Multi-exposure sequences: an ordered plan of capture steps
  // (filter/exposure/count, optional autofocus every N subs), modeled on
  // CCDciel's own plan/step engine - run server-side by the coordinator so
  // it keeps going exactly as described even if this tab is closed.
  _renderSequence(telescope) {
    const has = (cap) => this._hasCapability(telescope, cap);
    if (!has("set_exposure")) return "";
    const exposureUnit = this._unitFor(telescope, "set_exposure");

    const seqState = telescope.sequence_entity ? this._hass.states[telescope.sequence_entity] : null;
    const state = seqState ? seqState.state : "idle";

    if (state === "running" || state === "paused") {
      const steps = (seqState.attributes && seqState.attributes.steps) || [];
      const currentStep = (seqState.attributes && seqState.attributes.current_step) || 0;
      const totalSubs = steps.reduce((sum, s) => sum + (s.count || 0), 0);
      const doneSubs = steps.reduce((sum, s) => sum + (s.done_count || 0), 0);
      return `
        <div class="section sequence">
          <h2><ha-icon icon="mdi:camera-burst"></ha-icon> Sequence</h2>
          <p>${state === "running" ? "Running" : "Paused"} &ndash; step ${currentStep + 1} of
            ${steps.length}, ${doneSubs}/${totalSubs} subs</p>
          <ul class="log sequence-steps">
            ${steps
              .map(
                (s, i) => `
              <li class="${i === currentStep ? "current" : ""}">
                ${this._escape(s.filter || "–")} &middot; ${this._escape(String(s.exposure))}${exposureUnit}
                &times; ${s.done_count}/${s.count}
              </li>
            `
              )
              .join("")}
          </ul>
          <div class="row buttons">
            ${
              state === "running"
                ? `<ha-button id="sequence-pause-btn">Pause</ha-button>`
                : `<ha-button id="sequence-resume-btn" appearance="accent">Resume</ha-button>`
            }
            <ha-button id="sequence-cancel-btn">Cancel</ha-button>
          </div>
        </div>
      `;
    }

    const statusHint =
      state === "done"
        ? `<p class="hint">Last sequence finished.</p>`
        : state === "cancelled"
          ? `<p class="hint">Last sequence was cancelled.</p>`
          : "";

    // Each row's inputs are keyed by a stable per-row key (never reused
    // positionally), not by array index - removing a row in the middle
    // must not shift any other row's element ids, or the generic
    // snapshot/restore in _render() (see _snapshotInputValues) would
    // reapply values by id onto what is now a *different* row.
    const rows = this._sequenceDraft
      .map(
        (step) => `
      <div class="row sequence-step">
        <ha-input id="seq-filter-${step.key}" label="Filter"></ha-input>
        <ha-input id="seq-exposure-${step.key}" label="Exposure${exposureUnit ? ` (${exposureUnit})` : ""}" type="number"></ha-input>
        <ha-input id="seq-count-${step.key}" label="Count" type="number"></ha-input>
        ${
          has("auto_focus")
            ? `<ha-input id="seq-autofocus-${step.key}" label="Autofocus every"></ha-input>`
            : ""
        }
        ${
          this._sequenceDraft.length > 1
            ? `<ha-button data-remove-step="${step.key}" title="Remove step">&times;</ha-button>`
            : ""
        }
      </div>
    `
      )
      .join("");

    return `
      <div class="section sequence">
        <h2><ha-icon icon="mdi:camera-burst"></ha-icon> Sequence</h2>
        ${statusHint}
        ${rows}
        <div class="row buttons">
          <ha-button id="sequence-add-step-btn">Add step</ha-button>
          <ha-button id="sequence-start-btn" appearance="accent">Start sequence</ha-button>
        </div>
      </div>
    `;
  }

  _renderPreview(telescope) {
    const cameraEntity = telescope.live_camera_entity || telescope.preview_camera_entity;
    const cameraState = cameraEntity ? this._hass.states[cameraEntity] : null;
    const imgSrc =
      cameraState && cameraState.attributes && cameraState.attributes.entity_picture
        ? `${cameraState.attributes.entity_picture}&t=${Date.now()}`
        : null;

    return `
      <div class="section preview-section">
        <h2><ha-icon icon="mdi:image"></ha-icon> Live preview</h2>
        ${
          imgSrc
            ? `<img class="preview" src="${imgSrc}" alt="Live preview" />`
            : `<p class="hint">No live preview available yet.</p>`
        }
      </div>
    `;
  }

  _renderStatusLog(telescope) {
    const st = telescope.status_sensor_entity ? this._hass.states[telescope.status_sensor_entity] : null;
    if (!st) return "";
    const history = (st.attributes && st.attributes.history) || [];
    return `
      <div class="section">
        <h2><ha-icon icon="mdi:text-box-outline"></ha-icon> Session log</h2>
        <p>${this._escape(st.state)}</p>
        ${
          history.length
            ? `<ul class="log">${history
                .slice(-10)
                .reverse()
                .map((line) => `<li>${this._escape(line)}</li>`)
                .join("")}</ul>`
            : ""
        }
      </div>
    `;
  }

  _renderAdmin(telescope) {
    const usage = this._usageState(telescope);
    const perClient = (usage && usage.attributes && usage.attributes.per_client) || {};
    const rows = Object.entries(perClient)
      .map(
        ([, u]) =>
          `<tr><td>${this._escape(u.client_name)}</td><td>${u.sessions}</td><td>${u.total_minutes} min</td></tr>`
      )
      .join("");

    return `
      <div class="section admin">
        <h2><ha-icon icon="mdi:shield-account"></ha-icon> Admin</h2>
        <p class="hint">Set the next availability window for this telescope.</p>
        <div class="row">
          <ha-input id="admin-start-input" label="Open from" type="datetime-local"></ha-input>
          <ha-input id="admin-end-input" label="Open until" type="datetime-local"></ha-input>
        </div>
        <ha-button id="set-availability-btn">Set availability</ha-button>

        ${
          rows
            ? `<h3>Usage (for manual invoicing)</h3>
          <table class="usage"><thead><tr><th>Client</th><th>Sessions</th><th>Total</th></tr></thead>
          <tbody>${rows}</tbody></table>`
            : ""
        }
      </div>
    `;
  }

  // -- DOM wiring -----------------------------------------------------------

  _attachListeners(telescope) {
    const root = this.shadowRoot;
    const on = (id, event, handler) => {
      const el = root.getElementById(id);
      if (el) el.addEventListener(event, handler);
    };
    const val = (id) => {
      const el = root.getElementById(id);
      return el ? el.value : undefined;
    };

    root.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        this._selectedEntryId = tab.getAttribute("data-entry-id");
        this._render();
      });
    });

    on("reserve-btn", "click", () => {
      const start = val("start-input");
      const end = val("end-input");
      if (!start || !end) {
        this._error = "pick a start and end time";
        this._render();
        return;
      }
      this._call("reserve", { start: new Date(start).toISOString(), end: new Date(end).toISOString() });
    });

    on("park-btn", "click", () =>
      this._sendCommand("park", this._resolveCapabilityValue(telescope, "park", "park"))
    );
    on("unpark-btn", "click", () =>
      this._sendCommand("unpark", this._resolveCapabilityValue(telescope, "unpark", "unpark"))
    );
    on("tracking-switch", "change", (e) => {
      const hint = e.target.checked ? "on" : "off";
      this._sendCommand(
        "set_tracking",
        this._resolveCapabilityValue(telescope, "set_tracking", hint, e.target.checked)
      );
    });
    on("allow-power-switch", "change", (e) => this._sendCommand("allow_power_actions", e.target.checked));
    on("startup-btn", "click", () => this._sendCommand("startup_sequence"));
    on("shutdown-btn", "click", () => this._sendCommand("shutdown"));
    on("dew-heater-switch", "change", (e) => this._sendCommand("set_dew_heater", e.target.checked));

    on("target-search", "change", (e) => {
      const entry = this._catalogIndex && this._catalogIndex.get(e.target.value);
      if (!entry) return;
      const raEl = root.getElementById("ra-input");
      const decEl = root.getElementById("dec-input");
      if (raEl) raEl.value = String(entry.ra);
      if (decEl) decEl.value = String(entry.dec);
    });

    on("goto-btn", "click", async () => {
      await this._sendCommand("set_goto_ra", val("ra-input"));
      await this._sendCommand("set_goto_dec", val("dec-input"));
      // Some backends (e.g. ha-indi-client) have no separate "execute"
      // entity at all - setting the RA/Dec number elements above already
      // IS the goto. Only call a dedicated execute step when one is mapped.
      if (this._hasCapability(telescope, "goto")) {
        await this._sendCommand("goto");
      }
    });
    on("stop-goto-btn", "click", () => this._sendCommand("stop_goto"));

    on("start-capture-btn", "click", async () => {
      const exposure = val("exposure-input");
      const filter = val("filter-input");
      const focus = val("focus-input");
      const temp = val("temp-input");
      if (exposure) await this._sendCommand("set_exposure", Number(exposure));
      if (filter) await this._sendCommand("set_filter", filter);
      if (focus) await this._sendCommand("set_focus", Number(focus));
      if (temp) await this._sendCommand("set_ccd_temperature", Number(temp));
      // As with goto: some backends start the exposure merely by writing
      // the exposure value itself, with no separate trigger entity.
      if (this._hasCapability(telescope, "start_capture")) {
        await this._sendCommand("start_capture");
      }
    });
    on("stop-capture-btn", "click", () => this._sendCommand("stop_capture"));
    on("recording-switch", "change", (e) => this._call("set_recording", { enabled: e.target.checked }));
    on("save-frame-btn", "click", () => this._call("save_frame", {}));

    root.querySelectorAll("[data-remove-step]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = Number(btn.getAttribute("data-remove-step"));
        this._sequenceDraft = this._sequenceDraft.filter((s) => s.key !== key);
        this._render();
      });
    });
    on("sequence-add-step-btn", "click", () => {
      this._sequenceDraft.push({ key: this._sequenceKeySeq++ });
      this._render();
    });
    on("sequence-start-btn", "click", () => {
      const steps = this._sequenceDraft.map((draftStep) => {
        const k = draftStep.key;
        const step = {
          exposure: Number(val(`seq-exposure-${k}`)),
          count: Number(val(`seq-count-${k}`)),
        };
        const filter = val(`seq-filter-${k}`);
        const autofocusEvery = val(`seq-autofocus-${k}`);
        if (filter) step.filter = filter;
        if (autofocusEvery) step.autofocus_every = Number(autofocusEvery);
        return step;
      });
      if (steps.some((s) => !s.exposure || !s.count)) {
        this._error = "every sequence step needs an exposure and a count";
        this._render();
        return;
      }
      this._call("start_sequence", { steps });
    });
    on("sequence-pause-btn", "click", () => this._call("pause_sequence", {}));
    on("sequence-resume-btn", "click", () => this._call("resume_sequence", {}));
    on("sequence-cancel-btn", "click", () => this._call("cancel_sequence", {}));

    on("set-availability-btn", "click", () => {
      const start = val("admin-start-input");
      const end = val("admin-end-input");
      if (!start || !end) {
        this._error = "pick a start and end time";
        this._render();
        return;
      }
      this._call("set_availability", {
        windows: [{ start: new Date(start).toISOString(), end: new Date(end).toISOString() }],
      });
    });
  }

  _escape(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  _styles() {
    return `
      :host { display: block; height: 100%; background: var(--primary-background-color); }
      .page { max-width: 1400px; margin: 0 auto; padding: 16px 24px 48px; box-sizing: border-box; }
      .page.loading { display: flex; justify-content: center; align-items: center; min-height: 60vh; }
      .header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
      h1 { display: flex; align-items: center; gap: 10px; font-size: 1.4em; color: var(--primary-text-color); margin: 0; }
      .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--divider-color); }
      .tab { background: none; border: none; padding: 10px 16px; font-size: 0.95em; color: var(--secondary-text-color); cursor: pointer; border-bottom: 2px solid transparent; }
      .tab.active { color: var(--primary-color); border-bottom-color: var(--primary-color); font-weight: 500; }
      .status { display: flex; align-items: center; gap: 8px; font-weight: 500; padding: 10px 0; font-size: 1.05em; }
      .status-free { color: var(--success-color, #4caf50); }
      .status-busy { color: var(--warning-color, #ff9800); }
      .status-mine { color: var(--primary-color); }
      .columns { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
      @media (max-width: 900px) { .columns { grid-template-columns: 1fr; } }
      .column { display: flex; flex-direction: column; gap: 16px; }
      .section { background: var(--card-background-color, #fff); border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,0.12)); padding: 16px; }
      .section h2 { margin: 0 0 12px; font-size: 1.05em; color: var(--primary-text-color); display: flex; align-items: center; gap: 8px; }
      .section h3 { margin: 16px 0 8px; font-size: 0.95em; color: var(--secondary-text-color); }
      .row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
      .row.buttons { align-items: center; }
      .switch-row { display: flex; align-items: center; gap: 8px; }
      ha-input { flex: 1 1 140px; }
      ul.windows, ul.log { margin: 0; padding-left: 20px; }
      ul.log { font-family: var(--code-font-family, monospace); font-size: 0.85em; color: var(--secondary-text-color); }
      p.hint { color: var(--secondary-text-color); font-size: 0.9em; margin: 4px 0; }
      img.preview { width: 100%; border-radius: 8px; display: block; background: #000; }
      .preview-section { min-height: 160px; }
      table.usage { width: 100%; border-collapse: collapse; margin-top: 8px; }
      table.usage th, table.usage td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--divider-color); }
      .admin { margin-top: 24px; background: var(--card-background-color, #fff); border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,0.12)); padding: 16px; }
      .telemetry-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
      .telemetry-item { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border-radius: 8px;
        background: var(--secondary-background-color, rgba(0,0,0,0.03)); }
      .telemetry-item ha-icon { color: var(--primary-color); width: 18px; height: 18px; }
      .t-label { font-size: 0.75em; color: var(--secondary-text-color); }
      .t-value { font-size: 1.05em; font-weight: 500; color: var(--primary-text-color); }
      input.target-search { flex: 1 1 220px; padding: 10px 12px; border: 1px solid var(--divider-color);
        border-radius: 8px; font-size: 14px; font-family: inherit; background: var(--card-background-color, #fff);
        color: var(--primary-text-color); box-sizing: border-box; }
      .sequence-step { align-items: center; }
      .sequence-step ha-input { flex: 1 1 110px; }
      .sequence-step ha-button { flex: 0 0 auto; padding: 0 12px; }
      ul.sequence-steps { list-style: none; margin: 8px 0; padding: 0; font-family: var(--code-font-family, monospace); font-size: 0.9em; }
      ul.sequence-steps li { padding: 4px 8px; border-radius: 6px; color: var(--secondary-text-color); }
      ul.sequence-steps li.current { background: var(--primary-color); color: #fff; font-weight: 500; }
    `;
  }
}

if (!customElements.get("observing-time-reservation-panel")) {
  customElements.define("observing-time-reservation-panel", ObservingTimeReservationPanel);
}
