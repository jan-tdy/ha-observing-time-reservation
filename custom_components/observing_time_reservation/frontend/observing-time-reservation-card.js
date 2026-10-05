/**
 * Observing Time Reservation card.
 *
 * Plain custom element (no bundler, no external deps) so it ships straight
 * from the integration with nothing to build. It only ever uses the native
 * elements the Home Assistant frontend itself registers globally
 * (ha-card, ha-textfield, ha-select, ha-switch, ha-alert, ha-button, ...)
 * so dropdowns/inputs look and behave exactly like the rest of HA.
 *
 * Config:
 *   type: custom:observing-time-reservation-card
 *   config_entry_id: <the telescope's config entry id>
 *   in_use_entity: binary_sensor.xxx_in_use
 *   availability_entity: sensor.xxx_availability
 *   usage_entity: sensor.xxx_usage            # optional, admin-only view
 *   live_camera_entity: camera.xxx            # optional, control panel preview
 *   preview_camera_entity: camera.xxx         # optional, same as mapped in options flow
 *   title: "Bombol 1"                         # optional
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

class ObservingTimeReservationCard extends HTMLElement {
  setConfig(config) {
    if (!config.config_entry_id) {
      throw new Error("config_entry_id is required");
    }
    if (!config.in_use_entity || !config.availability_entity) {
      throw new Error("in_use_entity and availability_entity are required");
    }
    this._config = config;
    this._error = null;
    this._pending = false;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const signature = this._relevantSignature();
    if (signature !== this._lastSignature) {
      this._lastSignature = signature;
      this._render();
    }
  }

  // Avoid tearing down input fields (and losing whatever the client is
  // mid-typing) on every unrelated hass update - only the entities this
  // card actually reads are allowed to trigger a re-render.
  _relevantSignature() {
    if (!this._hass || !this._config) return null;
    const ids = [
      this._config.in_use_entity,
      this._config.availability_entity,
      this._config.usage_entity,
      this._config.live_camera_entity,
      this._config.preview_camera_entity,
    ].filter(Boolean);
    return JSON.stringify(ids.map((id) => this._hass.states[id] && this._hass.states[id].last_updated));
  }

  getCardSize() {
    return 6;
  }

  static getConfigElement() {
    return document.createElement("observing-time-reservation-card-editor");
  }

  static getStubConfig(hass, entities) {
    const inUse = entities.find((e) => e.startsWith("binary_sensor.") && e.endsWith("_in_use"));
    return {
      config_entry_id: "",
      in_use_entity: inUse || "",
      availability_entity: "",
    };
  }

  // -- service helpers ------------------------------------------------

  async _call(service, data) {
    this._pending = true;
    this._error = null;
    this._render();
    try {
      await this._hass.callService(DOMAIN, service, {
        config_entry_id: this._config.config_entry_id,
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

  _inUseState() {
    return this._hass.states[this._config.in_use_entity];
  }

  _availabilityState() {
    return this._hass.states[this._config.availability_entity];
  }

  _usageState() {
    return this._config.usage_entity ? this._hass.states[this._config.usage_entity] : undefined;
  }

  _isAdmin() {
    return !!(this._hass.user && this._hass.user.is_admin);
  }

  _currentHolder() {
    const st = this._inUseState();
    if (!st || st.state !== "on") return null;
    return st.attributes;
  }

  _amIHolder() {
    const holder = this._currentHolder();
    return !!(holder && this._hass.user && holder.client_user_id === this._hass.user.id);
  }

  _windows() {
    const st = this._availabilityState();
    return (st && st.attributes && st.attributes.windows) || [];
  }

  // -- render -------------------------------------------------------------

  _render() {
    if (!this._hass || !this._config || !this.shadowRoot) return;

    const title = this._config.title || "Observing time";
    const holder = this._currentHolder();
    const amIHolder = this._amIHolder();

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <ha-card header="${this._escape(title)}">
        <div class="card-content">
          ${this._error ? `<ha-alert alert-type="error">${this._escape(this._error)}</ha-alert>` : ""}
          ${this._renderStatus(holder, amIHolder)}
          ${amIHolder ? this._renderControlPanel(holder) : this._renderBooking()}
          ${this._isAdmin() ? this._renderAdmin() : ""}
        </div>
      </ha-card>
    `;
    this._attachListeners();
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

  _renderBooking() {
    const windows = this._windows();
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
        <h3>Availability</h3>
        ${windowsHtml}
      </div>
      <div class="section">
        <h3>Book a slot</h3>
        <div class="row">
          <ha-textfield id="start-input" label="Start" type="datetime-local" value="${defaultStart}"></ha-textfield>
          <ha-textfield id="end-input" label="End" type="datetime-local" value="${defaultEnd}"></ha-textfield>
        </div>
        <ha-button id="reserve-btn" raised ${this._pending ? "disabled" : ""}>Reserve</ha-button>
      </div>
    `;
  }

  _renderControlPanel(holder) {
    const cameraEntity = this._config.live_camera_entity || this._config.preview_camera_entity;
    const cameraState = cameraEntity ? this._hass.states[cameraEntity] : null;
    const imgSrc =
      cameraState && cameraState.attributes && cameraState.attributes.entity_picture
        ? `${cameraState.attributes.entity_picture}&t=${Date.now()}`
        : null;

    return `
      <div class="section">
        ${imgSrc ? `<img class="preview" src="${imgSrc}" alt="Live preview" />` : ""}
      </div>

      <div class="section">
        <h3>Mount</h3>
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
        <h3>Goto</h3>
        <div class="row">
          <ha-textfield id="ra-input" label="RA"></ha-textfield>
          <ha-textfield id="dec-input" label="Dec"></ha-textfield>
        </div>
        <div class="row buttons">
          <ha-button id="goto-btn" raised>Goto</ha-button>
          <ha-button id="stop-goto-btn">Stop</ha-button>
        </div>
      </div>

      <div class="section">
        <h3>Imaging</h3>
        <div class="row">
          <ha-textfield id="exposure-input" label="Exposure (s)" type="number"></ha-textfield>
          <ha-textfield id="filter-input" label="Filter"></ha-textfield>
          <ha-textfield id="focus-input" label="Focus"></ha-textfield>
          <ha-textfield id="temp-input" label="CCD temp (C)" type="number"></ha-textfield>
        </div>
        <div class="row buttons">
          <ha-button id="start-capture-btn" raised>Start capture</ha-button>
          <ha-button id="stop-capture-btn">Stop capture</ha-button>
        </div>
        <div class="row buttons">
          <div class="switch-row">
            <span>Save every frame</span>
            <ha-switch id="recording-switch" ${holder.recording === true || holder.recording === "true" ? "checked" : ""}></ha-switch>
          </div>
          <ha-button id="save-frame-btn">Save frame now</ha-button>
        </div>
      </div>
    `;
  }

  _renderAdmin() {
    const usage = this._usageState();
    const perClient = (usage && usage.attributes && usage.attributes.per_client) || {};
    const rows = Object.entries(perClient)
      .map(
        ([userId, u]) =>
          `<tr><td>${this._escape(u.client_name)}</td><td>${u.sessions}</td><td>${u.total_minutes} min</td></tr>`
      )
      .join("");

    return `
      <div class="section admin">
        <h3><ha-icon icon="mdi:shield-account"></ha-icon> Admin</h3>
        <p class="hint">Set the next availability window for this telescope.</p>
        <div class="row">
          <ha-textfield id="admin-start-input" label="Open from" type="datetime-local"></ha-textfield>
          <ha-textfield id="admin-end-input" label="Open until" type="datetime-local"></ha-textfield>
        </div>
        <ha-button id="set-availability-btn">Set availability</ha-button>

        ${
          rows
            ? `<h4>Usage (for manual invoicing)</h4>
          <table class="usage"><thead><tr><th>Client</th><th>Sessions</th><th>Total</th></tr></thead>
          <tbody>${rows}</tbody></table>`
            : ""
        }
      </div>
    `;
  }

  // -- DOM wiring -----------------------------------------------------------

  _attachListeners() {
    const root = this.shadowRoot;
    const on = (id, event, handler) => {
      const el = root.getElementById(id);
      if (el) el.addEventListener(event, handler);
    };
    const val = (id) => {
      const el = root.getElementById(id);
      return el ? el.value : undefined;
    };

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
      .card-content { display: flex; flex-direction: column; gap: 16px; padding: 0 16px 16px; }
      .status { display: flex; align-items: center; gap: 8px; font-weight: 500; padding: 8px 0; }
      .status-free { color: var(--success-color, #4caf50); }
      .status-busy { color: var(--warning-color, #ff9800); }
      .status-mine { color: var(--primary-color); }
      .section { border-top: 1px solid var(--divider-color); padding-top: 12px; }
      .section:first-of-type { border-top: none; padding-top: 0; }
      .section h3 { margin: 0 0 8px; font-size: 1em; color: var(--secondary-text-color); display: flex; align-items: center; gap: 6px; }
      .row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
      .row.buttons { align-items: center; }
      .switch-row { display: flex; align-items: center; gap: 8px; }
      ha-textfield { flex: 1 1 140px; }
      ul.windows { margin: 0; padding-left: 20px; }
      p.hint { color: var(--secondary-text-color); font-size: 0.9em; margin: 4px 0; }
      img.preview { width: 100%; border-radius: var(--ha-card-border-radius, 12px); display: block; }
      table.usage { width: 100%; border-collapse: collapse; margin-top: 8px; }
      table.usage th, table.usage td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--divider-color); }
      .admin { opacity: 0.95; }
    `;
  }
}

class ObservingTimeReservationCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _schema() {
    return [
      { name: "title", selector: { text: {} } },
      { name: "config_entry_id", selector: { config_entry: { integration: DOMAIN } } },
      { name: "in_use_entity", selector: { entity: { domain: "binary_sensor" } } },
      { name: "availability_entity", selector: { entity: { domain: "sensor" } } },
      { name: "usage_entity", selector: { entity: { domain: "sensor" } } },
      { name: "live_camera_entity", selector: { entity: { domain: "camera" } } },
      { name: "preview_camera_entity", selector: { entity: { domain: "camera" } } },
    ];
  }

  _render() {
    if (!this._hass || !this.shadowRoot && !this.attachShadow) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = "";
    const form = document.createElement("ha-form");
    form.hass = this._hass;
    form.data = this._config || {};
    form.schema = this._schema();
    form.computeLabel = (s) => s.name.replace(/_/g, " ");
    form.addEventListener("value-changed", (ev) => {
      this._config = ev.detail.value;
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config } }));
    });
    this.shadowRoot.appendChild(form);
  }
}

if (!customElements.get("observing-time-reservation-card-editor")) {
  customElements.define("observing-time-reservation-card-editor", ObservingTimeReservationCardEditor);
}

if (!customElements.get("observing-time-reservation-card")) {
  customElements.define("observing-time-reservation-card", ObservingTimeReservationCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "observing-time-reservation-card",
  name: "Observing Time Reservation",
  description: "Reserve and control an observing-time-reservation telescope.",
});
