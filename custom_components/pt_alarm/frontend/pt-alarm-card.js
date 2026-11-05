/*
 * PT Alarm Card - dashboard card for the PT Alarm integration.
 * Served and auto-registered by the integration; no manual resource needed.
 */
const CARD_VERSION = "1.0.0";
const ASSET_BASE = "/pt_alarm_static";

const MODES = {
  armed_away: { label: "Away", icon: "mdi:shield-lock" },
  armed_home: { label: "Home", icon: "mdi:shield-home" },
  armed_night: { label: "Night", icon: "mdi:shield-moon" },
  armed_vacation: { label: "Vacation", icon: "mdi:shield-airplane" },
  armed_custom_bypass: { label: "Custom", icon: "mdi:shield-star" },
};

const STATES = {
  disarmed: { label: "Disarmed", icon: "mdi:shield-off-outline", color: "var(--success-color, #43a047)" },
  arming: { label: "Arming", icon: "mdi:shield-sync", color: "var(--warning-color, #ffa600)" },
  pending: { label: "Entry delay", icon: "mdi:shield-alert", color: "var(--warning-color, #ffa600)" },
  triggered: { label: "TRIGGERED", icon: "mdi:bell-ring", color: "var(--error-color, #db4437)" },
  armed_away: { label: "Armed away", icon: "mdi:shield-lock", color: "var(--error-color, #db4437)" },
  armed_home: { label: "Armed home", icon: "mdi:shield-home", color: "var(--error-color, #db4437)" },
  armed_night: { label: "Armed night", icon: "mdi:shield-moon", color: "var(--error-color, #db4437)" },
  armed_vacation: { label: "Armed vacation", icon: "mdi:shield-airplane", color: "var(--error-color, #db4437)" },
  armed_custom_bypass: { label: "Armed custom", icon: "mdi:shield-star", color: "var(--error-color, #db4437)" },
  unavailable: { label: "Unavailable", icon: "mdi:shield-off", color: "var(--disabled-text-color, #999)" },
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

class PTAlarmCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._code = "";
    this._error = "";
    this._forceMode = null;
    this._busy = false;
    this._stateObj = null;
    this._timer = null;
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: "alarm_control_panel", integration: "pt_alarm" } } },
        { name: "name", selector: { text: {} } },
        {
          name: "modes",
          selector: {
            select: {
              multiple: true,
              options: Object.entries(MODES).map(([value, m]) => ({ value, label: m.label })),
            },
          },
        },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "show_keypad", selector: { boolean: {} } },
            { name: "show_sensors", selector: { boolean: {} } },
            { name: "show_logo", selector: { boolean: {} } },
          ],
        },
      ],
      computeLabel: (s) =>
        ({
          entity: "Alarm panel",
          name: "Name (optional)",
          modes: "Arm buttons to show (empty = all enabled modes)",
          show_keypad: "Show keypad",
          show_sensors: "Show open sensors",
          show_logo: "Show PowerTech logo",
        }[s.name]),
    };
  }

  static getStubConfig(hass) {
    const entity =
      Object.keys(hass.states).find(
        (e) => e.startsWith("alarm_control_panel.") && "supported_modes" in hass.states[e].attributes
      ) || Object.keys(hass.states).find((e) => e.startsWith("alarm_control_panel.")) || "";
    return { entity, show_keypad: true, show_sensors: true, show_logo: true };
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error("Please choose an alarm panel entity");
    this._config = { show_keypad: true, show_sensors: true, show_logo: true, ...config };
    this._stateObj = null;
    if (this._hass) this.hass = this._hass;
  }

  set hass(hass) {
    this._hass = hass;
    const stateObj = hass.states[this._config?.entity];
    const dark = !!hass.themes?.darkMode;
    if (stateObj !== this._stateObj || dark !== this._dark) {
      this._dark = dark;
      const prev = this._stateObj?.state;
      this._stateObj = stateObj;
      if (prev && stateObj && prev !== stateObj.state) {
        this._code = "";
        this._forceMode = null;
        this._error = "";
      }
      this._render();
    }
  }

  getCardSize() {
    return this._config?.show_keypad ? 7 : 3;
  }

  getGridOptions() {
    return { columns: 6, min_columns: 4, rows: "auto" };
  }

  connectedCallback() {
    this._startTimer();
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._timer = null;
  }

  _startTimer() {
    if (this._timer) return;
    this._timer = setInterval(() => this._tick(), 1000);
  }

  _tick() {
    const el = this.shadowRoot.querySelector(".countdown");
    if (!el || !this._stateObj) return;
    const { expiration, delay } = this._stateObj.attributes;
    if (!expiration) return;
    const remaining = Math.max(0, Math.round((new Date(expiration) - Date.now()) / 1000));
    el.querySelector(".secs").textContent = remaining;
    const bar = el.querySelector(".bar > div");
    if (bar && delay) bar.style.width = `${Math.min(100, (remaining / delay) * 100)}%`;
  }

  // ------------------------------------------------------------------ helpers
  get _attrs() {
    return this._stateObj?.attributes || {};
  }

  get _isDisarmed() {
    return this._stateObj?.state === "disarmed";
  }

  get _codeNeeded() {
    if (!this._attrs.code_format) return false;
    return this._isDisarmed ? !!this._attrs.code_arm_required : this._attrs.code_disarm_required !== false;
  }

  get _modes() {
    const supported = this._attrs.supported_modes || Object.keys(MODES);
    const wanted = this._config.modes?.length ? this._config.modes : supported;
    return wanted.filter((m) => supported.includes(m) && MODES[m]);
  }

  _friendly(entityId) {
    return this._hass.states[entityId]?.attributes.friendly_name || entityId;
  }

  // ------------------------------------------------------------------ actions
  async _call(domain, service, data) {
    this._busy = true;
    this._error = "";
    this._render();
    try {
      await this._hass.callService(domain, service, { entity_id: this._config.entity, ...data });
      this._code = "";
      this._forceMode = null;
    } catch (err) {
      this._error = err?.message || String(err);
      this._code = "";
    }
    this._busy = false;
    this._render();
  }

  _arm(mode, force = false) {
    const data = { mode: mode.replace("armed_", ""), force };
    if (this._code) data.code = this._code;
    this._call("pt_alarm", "arm", data).then(() => {
      if (this._error && /open/i.test(this._error)) {
        this._forceMode = mode;
        this._render();
      }
    });
  }

  _disarm() {
    const data = {};
    if (this._code) data.code = this._code;
    this._call("alarm_control_panel", "alarm_disarm", data);
  }

  _key(k) {
    if (k === "clear") this._code = "";
    else if (k === "back") this._code = this._code.slice(0, -1);
    else if (this._code.length < 12) this._code += k;
    this._error = "";
    this._updateCode();
  }

  _updateCode() {
    const el = this.shadowRoot.querySelector(".code-display");
    if (el) el.textContent = this._code ? "●".repeat(this._code.length) : "Enter code";
    el?.classList.toggle("empty", !this._code);
  }

  // ------------------------------------------------------------------ render
  _render() {
    if (!this._config || !this._hass) return;
    const stateObj = this._stateObj;
    if (!stateObj) {
      this.shadowRoot.innerHTML = `<ha-card><div class="warn">Entity not found: ${esc(this._config.entity)}</div></ha-card>`;
      return;
    }
    const state = stateObj.state;
    const info = STATES[state] || STATES.unavailable;
    const a = this._attrs;
    const name = this._config.name || a.friendly_name || "Alarm";
    const open = Object.keys(a.open_sensors || {});
    const bypassed = a.bypassed_sensors || [];
    const showKeypad = this._config.show_keypad && a.code_format && this._codeNeeded;
    const numeric = a.code_format === "number";
    const hasTimer = (state === "arming" || state === "pending") && a.expiration;
    const remaining = hasTimer ? Math.max(0, Math.round((new Date(a.expiration) - Date.now()) / 1000)) : 0;
    const pct = hasTimer && a.delay ? Math.min(100, (remaining / a.delay) * 100) : 0;
    const locked = a.locked_until && new Date(a.locked_until) > Date.now();

    let buttons = "";
    if (state === "unavailable") {
      buttons = "";
    } else if (this._isDisarmed) {
      buttons = this._modes
        .map(
          (m) => `<button class="action arm" data-mode="${m}" ${this._busy ? "disabled" : ""}>
            <ha-icon icon="${MODES[m].icon}"></ha-icon><span>${MODES[m].label}</span></button>`
        )
        .join("");
    } else {
      buttons = `<button class="action disarm" ${this._busy ? "disabled" : ""}>
        <ha-icon icon="mdi:shield-off"></ha-icon><span>Disarm</span></button>`;
    }

    const keypad = !showKeypad
      ? ""
      : numeric
      ? `<div class="code-display ${this._code ? "" : "empty"}">${this._code ? "●".repeat(this._code.length) : "Enter code"}</div>
         <div class="keypad">
           ${["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"]
             .map((k) => {
               const label = k === "clear" ? '<ha-icon icon="mdi:close"></ha-icon>' : k === "back" ? '<ha-icon icon="mdi:backspace-outline"></ha-icon>' : k;
               return `<button class="key ${k.length > 1 ? "fn" : ""}" data-key="${k}">${label}</button>`;
             })
             .join("")}
         </div>`
      : `<input class="code-input" type="password" autocomplete="off" placeholder="Enter code" value="${esc(this._code)}">`;

    const sensorList =
      this._config.show_sensors && (open.length || bypassed.length)
        ? `<div class="sensors">
            ${open
              .map(
                (e) => `<div class="sensor ${bypassed.includes(e) ? "bypassed" : ""}">
                  <ha-icon icon="${bypassed.includes(e) ? "mdi:eye-off" : "mdi:alert-circle-outline"}"></ha-icon>
                  <span>${esc(this._friendly(e))}</span><em>${bypassed.includes(e) ? "bypassed" : "open"}</em></div>`
              )
              .join("")}
          </div>`
        : "";

    this.shadowRoot.innerHTML = `
      <style>${PTAlarmCard.styles}</style>
      <ha-card style="--state-color:${info.color}">
        ${
          this._config.show_logo
            ? `<div class="brand"><img src="${ASSET_BASE}/${this._dark ? "logo-dark" : "logo"}.png?v=${CARD_VERSION}" alt="PowerTech Security &amp; Communications"></div>`
            : ""
        }
        <div class="header ${state === "triggered" ? "pulse" : ""}">
          <div class="badge"><ha-icon icon="${info.icon}"></ha-icon></div>
          <div class="titles">
            <div class="name">${esc(name)}</div>
            <div class="state">${info.label}${a.changed_by && state !== "triggered" ? ` <span class="by">by ${esc(a.changed_by)}</span>` : ""}</div>
            ${state === "triggered" && a.triggered_by ? `<div class="by">by ${esc(this._friendly(a.triggered_by))}</div>` : ""}
          </div>
        </div>
        ${
          hasTimer
            ? `<div class="countdown"><div class="secs">${remaining}</div><div class="label">${
                state === "arming" ? "seconds to leave" : "seconds to disarm"
              }</div><div class="bar"><div style="width:${pct}%"></div></div></div>`
            : ""
        }
        ${sensorList}
        ${locked ? `<div class="error">Keypad locked, try again later</div>` : ""}
        ${this._error ? `<div class="error">${esc(this._error)}</div>` : ""}
        ${
          this._forceMode
            ? `<button class="action force" data-force="${this._forceMode}"><ha-icon icon="mdi:shield-alert-outline"></ha-icon><span>Arm anyway (bypass open sensors)</span></button>`
            : ""
        }
        ${keypad}
        <div class="actions">${buttons}</div>
      </ha-card>`;

    this.shadowRoot.querySelectorAll("button.arm").forEach((b) => b.addEventListener("click", () => this._arm(b.dataset.mode)));
    this.shadowRoot.querySelector("button.disarm")?.addEventListener("click", () => this._disarm());
    this.shadowRoot.querySelector("button.force")?.addEventListener("click", (ev) => this._arm(ev.currentTarget.dataset.force, true));
    this.shadowRoot.querySelectorAll("button.key").forEach((b) => b.addEventListener("click", () => this._key(b.dataset.key)));
    const input = this.shadowRoot.querySelector(".code-input");
    if (input) {
      input.addEventListener("input", (ev) => (this._code = ev.target.value));
      input.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter") return;
        if (this._isDisarmed && this._modes.length) this._arm(this._modes[0]);
        else if (!this._isDisarmed) this._disarm();
      });
    }
    this._startTimer();
  }

  static get styles() {
    return `
      ha-card { padding: 16px; display: flex; flex-direction: column; gap: 14px; }
      .brand { display: flex; justify-content: center; padding-bottom: 10px; border-bottom: 1px solid var(--divider-color, #e0e0e0); }
      .brand img { height: 30px; max-width: 100%; object-fit: contain; }
      .header { display: flex; align-items: center; gap: 14px; }
      .badge { width: 52px; height: 52px; border-radius: 50%; display: grid; place-items: center; flex: none;
        background: color-mix(in srgb, var(--state-color) 18%, transparent); color: var(--state-color); }
      .badge ha-icon { --mdc-icon-size: 30px; }
      .pulse .badge { animation: pulse 1s ease-in-out infinite; }
      @keyframes pulse { 50% { transform: scale(1.12); background: color-mix(in srgb, var(--state-color) 40%, transparent); } }
      .titles { min-width: 0; }
      .name { font-size: 1.1em; font-weight: 500; color: var(--primary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .state { font-size: 1.35em; font-weight: 600; color: var(--state-color); }
      .by { font-size: 0.7em; font-weight: 400; color: var(--secondary-text-color); }
      .countdown { text-align: center; }
      .countdown .secs { font-size: 2.6em; font-weight: 600; color: var(--state-color); line-height: 1; font-variant-numeric: tabular-nums; }
      .countdown .label { color: var(--secondary-text-color); font-size: 0.9em; margin: 4px 0 8px; }
      .bar { height: 6px; border-radius: 3px; background: var(--divider-color, #e0e0e0); overflow: hidden; }
      .bar > div { height: 100%; background: var(--state-color); transition: width 1s linear; }
      .sensors { display: flex; flex-direction: column; gap: 4px; }
      .sensor { display: flex; align-items: center; gap: 8px; font-size: 0.95em; color: var(--warning-color, #ffa600); }
      .sensor span { flex: 1; color: var(--primary-text-color); }
      .sensor em { font-style: normal; font-size: 0.85em; }
      .sensor.bypassed { color: var(--secondary-text-color); }
      .sensor ha-icon { --mdc-icon-size: 18px; }
      .error, .warn { color: var(--error-color, #db4437); font-size: 0.95em; padding: 8px 12px; border-radius: 8px;
        background: color-mix(in srgb, var(--error-color, #db4437) 10%, transparent); }
      .code-display { text-align: center; font-size: 1.6em; letter-spacing: 6px; min-height: 1.5em; color: var(--primary-text-color); }
      .code-display.empty { font-size: 1em; letter-spacing: normal; color: var(--secondary-text-color); line-height: 2.4em; }
      .code-input { font: inherit; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--divider-color, #ccc);
        background: var(--card-background-color); color: var(--primary-text-color); text-align: center; }
      .keypad { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; max-width: 280px; margin: 0 auto; width: 100%; }
      button { font: inherit; cursor: pointer; border: none; border-radius: 12px; color: var(--primary-text-color);
        background: var(--secondary-background-color, #f2f2f2); transition: filter .15s, transform .05s; }
      button:hover { filter: brightness(0.95); }
      button:active { transform: scale(0.97); }
      button:disabled { opacity: 0.5; cursor: default; }
      .key { height: 52px; font-size: 1.3em; font-weight: 500; }
      .key.fn { color: var(--secondary-text-color); }
      .actions { display: flex; flex-wrap: wrap; gap: 8px; }
      .action { flex: 1 1 90px; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 12px 8px; font-weight: 500; }
      .action.disarm { flex-direction: row; justify-content: center; background: var(--success-color, #43a047); color: #fff; }
      .action.force { flex-direction: row; justify-content: center; background: color-mix(in srgb, var(--warning-color, #ffa600) 20%, transparent); }
      .action.arm ha-icon { color: var(--primary-color); }
    `;
  }
}

if (!customElements.get("pt-alarm-card")) {
  customElements.define("pt-alarm-card", PTAlarmCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "pt-alarm-card",
    name: "PT Alarm Card",
    description: "Keypad, arm modes, countdowns and open sensors for PT Alarm.",
    preview: true,
    documentationURL: "https://github.com/YOUR_GITHUB_USERNAME/pt-alarm",
  });
  console.info(`%c PT-ALARM-CARD %c v${CARD_VERSION} `, "color:#fff;background:#db4437;font-weight:700", "color:#db4437");
}
