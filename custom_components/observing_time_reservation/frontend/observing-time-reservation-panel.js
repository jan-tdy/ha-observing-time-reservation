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
        "live_camera_entity",
        "preview_camera_entity",
        "status_sensor_entity",
      ].forEach((key) => t[key] && ids.push(t[key]));
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

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <div class="page">
        <div class="header">
          <h1><ha-icon icon="mdi:telescope"></ha-icon> Observing Time Reservation</h1>
          ${this._telescopes.length > 1 ? this._renderTabs() : ""}
        </div>
        ${this._error ? `<ha-alert alert-type="error">${this._escape(this._error)}</ha-alert>` : ""}
        ${this._renderStatus(holder, amIHolder)}
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
    return `
      <div class="section">
        <h2><ha-icon icon="mdi:axis-arrow"></ha-icon> Mount</h2>
        <div class="row buttons">
          <ha-button id="park-btn">Park</ha-button>
          <ha-button id="unpark-btn">Unpark</ha-button>
          <div class="switch-row">
            <span>Tracking</span>
            <ha-switch id="tracking-switch"></ha-switch>
          </div>
        </div>
      </div>

      <div class="section">
        <h2><ha-icon icon="mdi:crosshairs-gps"></ha-icon> Goto</h2>
        <div class="row">
          <ha-input id="ra-input" label="RA"></ha-input>
          <ha-input id="dec-input" label="Dec"></ha-input>
        </div>
        <div class="row buttons">
          <ha-button id="goto-btn" appearance="accent">Goto</ha-button>
          <ha-button id="stop-goto-btn">Stop</ha-button>
        </div>
      </div>

      <div class="section">
        <h2><ha-icon icon="mdi:camera-iris"></ha-icon> Imaging</h2>
        <div class="row">
          <ha-input id="exposure-input" label="Exposure (s)" type="number"></ha-input>
          <ha-input id="filter-input" label="Filter"></ha-input>
          <ha-input id="focus-input" label="Focus"></ha-input>
          <ha-input id="temp-input" label="CCD temp (C)" type="number"></ha-input>
        </div>
        <div class="row buttons">
          <ha-button id="start-capture-btn" appearance="accent">Start capture</ha-button>
          <ha-button id="stop-capture-btn">Stop capture</ha-button>
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

    on("park-btn", "click", () => this._sendCommand("park"));
    on("unpark-btn", "click", () => this._sendCommand("unpark"));
    on("tracking-switch", "change", (e) => this._sendCommand("set_tracking", e.target.checked));

    on("goto-btn", "click", async () => {
      await this._sendCommand("set_goto_ra", val("ra-input"));
      await this._sendCommand("set_goto_dec", val("dec-input"));
      await this._sendCommand("goto");
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
      await this._sendCommand("start_capture");
    });
    on("stop-capture-btn", "click", () => this._sendCommand("stop_capture"));
    on("recording-switch", "change", (e) => this._call("set_recording", { enabled: e.target.checked }));
    on("save-frame-btn", "click", () => this._call("save_frame", {}));

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
    `;
  }
}

if (!customElements.get("observing-time-reservation-panel")) {
  customElements.define("observing-time-reservation-panel", ObservingTimeReservationPanel);
}
