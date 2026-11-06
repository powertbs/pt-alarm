/*
 * PT Alarm Card - dashboard card for the PT Alarm integration.
 * Served and auto-registered by the integration; no manual resource needed.
 */
const CARD_VERSION = "0.0.3";
const ASSET_BASE = "/pt_alarm_static";
const COMPANY_URL = "https://powertbs.com/";
const RING_R = 52;
const RING_C = 2 * Math.PI * RING_R;
const ALL = "__all__";

const GREEN = "#2e7d32";
const RED = "#c62828";
const AMBER = "#ef8f00";
const GREY = "#616161";
const FIRE = "#d84315";
const TROUBLE = "#ef6c00";

const MODES = {
  armed_away: { label: "Away", icon: "mdi:shield-lock" },
  armed_home: { label: "Stay", icon: "mdi:shield-home" },
  armed_night: { label: "Night", icon: "mdi:shield-moon" },
  armed_vacation: { label: "Vacation", icon: "mdi:shield-airplane" },
  armed_custom_bypass: { label: "Custom", icon: "mdi:shield-star" },
};

const STATES = {
  disarmed: { label: "Disarmed", icon: "mdi:shield-off-outline", color: GREEN },
  arming: { label: "Arming", icon: "mdi:shield-sync", color: AMBER },
  pending: { label: "Entry delay", icon: "mdi:shield-alert", color: AMBER },
  triggered: { label: "Alarm", icon: "mdi:alarm-light", color: RED },
  armed_away: { label: "Armed away", icon: "mdi:shield-lock", color: RED },
  armed_home: { label: "Armed stay", icon: "mdi:shield-home", color: RED },
  armed_night: { label: "Armed night", icon: "mdi:shield-moon", color: RED },
  armed_vacation: { label: "Armed vacation", icon: "mdi:shield-airplane", color: RED },
  armed_custom_bypass: { label: "Armed custom", icon: "mdi:shield-star", color: RED },
  partial: { label: "Partially armed", icon: "mdi:shield-half-full", color: RED },
  fire: { label: "Fire", icon: "mdi:fire", color: FIRE },
  panic: { label: "Panic", icon: "mdi:alarm-light", color: RED },
  unavailable: { label: "Unavailable", icon: "mdi:shield-off", color: "#757575" },
};

const ARMED = Object.keys(MODES);
const URGENT = ["triggered", "pending"];

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

class PTAlarmCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._code = "";
    this._error = "";
    this._bypass = false;
    this._showBypassed = false;
    this._showTroubles = false;
    this._chimes = {};
    this._busy = false;
    this._selected = null;
    this._snapshot = "";
    this._prevStates = {};
    this._timer = null;
    this._audio = null;
    this._lastBeep = null;
    // Browsers only allow sound after the user has touched the page.
    this.shadowRoot.addEventListener("pointerdown", () => this._unlockAudio(), { capture: true });
  }

  // ------------------------------------------------------------------ config
  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: "alarm_control_panel", integration: "pt_alarm" } } },
        {
          name: "entities",
          selector: { entity: { domain: "alarm_control_panel", integration: "pt_alarm", multiple: true } },
        },
        { name: "name", selector: { text: {} } },
        {
          name: "modes",
          selector: {
            select: { multiple: true, options: Object.entries(MODES).map(([value, m]) => ({ value, label: m.label })) },
          },
        },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "show_keypad", selector: { boolean: {} } },
            { name: "show_sensors", selector: { boolean: {} } },
            { name: "show_logo", selector: { boolean: {} } },
            { name: "sound", selector: { boolean: {} } },
            { name: "show_all", selector: { boolean: {} } },
          ],
        },
        {
          name: "status_style",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "bar", label: "Colored status bar" },
                { value: "card", label: "Whole card colored" },
              ],
            },
          },
        },
        {
          name: "keypad_style",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "modern", label: "Modern (square keys)" },
                { value: "round", label: "Round keys" },
              ],
            },
          },
        },
      ],
      computeLabel: (s) =>
        ({
          entity: "Default partition",
          entities: "Other partitions to include (optional)",
          name: "Name (optional, single partition only)",
          modes: "Arm buttons to show (empty = all enabled modes)",
          show_keypad: "Show keypad",
          show_sensors: "Show open zones",
          show_logo: "Show PowerTech logo",
          sound: "Beep during exit and entry delay",
          show_all: "Show 'All' tab",
          status_style: "Status color",
          keypad_style: "Keypad style",
        }[s.name]),
    };
  }

  static getStubConfig(hass) {
    const panels = Object.keys(hass.states).filter(
      (e) => e.startsWith("alarm_control_panel.") && "supported_modes" in hass.states[e].attributes
    );
    const entity = panels[0] || Object.keys(hass.states).find((e) => e.startsWith("alarm_control_panel.")) || "";
    return { entity, entities: panels.slice(1), show_keypad: true, show_sensors: true, show_logo: true, sound: true };
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error("Please choose an alarm panel (partition)");
    this._config = {
      show_keypad: true,
      show_sensors: true,
      show_logo: true,
      sound: true,
      show_all: true,
      keypad_style: "modern",
      status_style: "bar",
      ...config,
    };
    this._selected = this._config.entity;
    this._snapshot = "";
    if (this._hass) this.hass = this._hass;
  }

  get _partitions() {
    const list = [this._config.entity, ...(this._config.entities || [])];
    return [...new Set(list)].filter(Boolean);
  }

  get _multi() {
    return this._partitions.length > 1;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const dark = !!hass.themes?.darkMode;
    const snapshot =
      this._partitions
        .map((e) => (hass.states[e]?.last_updated || "") + JSON.stringify(hass.states[e]?.attributes || {}))
        .join("|") + dark;
    if (snapshot === this._snapshot) return;
    this._snapshot = snapshot;
    this._dark = dark;

    // Door chime: play once per new chime on any shown partition.
    for (const entityId of this._partitions) {
      const chime = hass.states[entityId]?.attributes.last_chime;
      const seen = this._chimes[entityId];
      if (chime?.time && seen !== undefined && chime.time !== seen && Date.now() - new Date(chime.time) < 10000) {
        this._playChime();
      }
      this._chimes[entityId] = chime?.time || null;
    }

    // Jump to a partition that just went into alarm or entry delay.
    for (const entityId of this._partitions) {
      const state = hass.states[entityId]?.state;
      const prev = this._prevStates[entityId];
      const changed = state && state !== prev;
      // Also on first load: open on a partition that is already in alarm / entry delay.
      if (changed && URGENT.includes(state) && this._selected !== entityId) this._select(entityId, false);
      if (changed && prev !== undefined && (entityId === this._selected || this._selected === ALL)) this._resetEntry();
      this._prevStates[entityId] = state;
    }
    this._render();
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

  // ------------------------------------------------------------------ helpers
  _resetEntry() {
    this._code = "";
    this._error = "";
    this._bypass = false;
  }

  _select(entityId, render = true) {
    this._selected = entityId;
    this._resetEntry();
    this._lastBeep = null;
    if (render) this._render();
  }

  get _isAll() {
    return this._multi && this._selected === ALL;
  }

  get _stateObj() {
    if (this._isAll) return null;
    const id = this._partitions.includes(this._selected) ? this._selected : this._config.entity;
    return this._hass?.states[id] || null;
  }

  get _attrs() {
    return this._stateObj?.attributes || {};
  }

  _states() {
    return this._partitions.map((e) => this._hass.states[e]).filter(Boolean);
  }

  _name(stateObj) {
    if (!this._multi && this._config.name) return this._config.name;
    return stateObj?.attributes.friendly_name || stateObj?.entity_id || "Alarm";
  }

  _friendly(entityId, attrs = this._attrs) {
    const zone = attrs.zones?.[entityId];
    if (zone?.name) return zone.location ? `${zone.name} (${zone.location})` : zone.name;
    return this._hass.states[entityId]?.attributes.friendly_name || entityId;
  }

  _activeWord(entityId, attrs = this._attrs) {
    const type = attrs.zones?.[entityId]?.type;
    return { motion: "Motion", tamper: "Tampered", environmental: "Detected" }[type] || "Open";
  }

  _notReady(attrs = this._attrs) {
    if (Array.isArray(attrs.not_ready_sensors)) return attrs.not_ready_sensors;
    return Object.keys(attrs.open_sensors || {});
  }

  _combinedState() {
    const states = this._states().map((s) => s.state);
    if (!states.length) return "unavailable";
    for (const s of ["triggered", "pending", "arming"]) if (states.includes(s)) return s;
    if (states.every((s) => s === "disarmed")) return "disarmed";
    const armed = states.filter((s) => ARMED.includes(s));
    if (armed.length === states.length) return new Set(armed).size === 1 ? armed[0] : "partial";
    return armed.length ? "partial" : "unavailable";
  }

  _codeNeeded(attrs, disarmed) {
    if (!attrs.code_format) return false;
    if (this._bypass) return true; // bypassing open zones needs an authorized code
    return disarmed ? !!attrs.code_arm_required : attrs.code_disarm_required !== false;
  }

  _modesFor(attrs) {
    const supported = attrs.supported_modes || Object.keys(MODES);
    const wanted = this._config.modes?.length ? this._config.modes : supported;
    return wanted.filter((m) => supported.includes(m) && MODES[m]);
  }

  _remaining(attrs = this._attrs) {
    if (!attrs.expiration) return 0;
    return Math.max(0, Math.ceil((new Date(attrs.expiration) - Date.now()) / 1000));
  }

  _ringOffset(remaining, attrs = this._attrs) {
    const delay = attrs.delay || 0;
    const fraction = delay ? Math.min(1, remaining / delay) : 0;
    return RING_C * (1 - fraction);
  }

  // ------------------------------------------------------------------ timer & sound
  _startTimer() {
    if (this._timer) return;
    this._timer = setInterval(() => this._tick(), 1000);
  }

  _tick() {
    const state = this._stateObj?.state;
    const counting = (state === "arming" || state === "pending") && this._attrs.expiration;
    if (!counting) {
      this._lastBeep = null;
      return;
    }
    const remaining = this._remaining();
    const el = this.shadowRoot.querySelector(".countdown");
    if (el) {
      el.querySelector(".secs").textContent = remaining;
      el.querySelector(".ring-progress")?.setAttribute("stroke-dashoffset", this._ringOffset(remaining));
    }
    if (remaining > 0 && remaining !== this._lastBeep) {
      this._lastBeep = remaining;
      this._countdownBeep(state, remaining);
    }
  }

  _unlockAudio() {
    if (!this._config?.sound) return;
    try {
      if (!this._audio) this._audio = new (window.AudioContext || window.webkitAudioContext)();
      if (this._audio.state === "suspended") this._audio.resume();
    } catch (err) {
      this._audio = null;
    }
  }

  _beep(freq, at = 0, length = 0.12) {
    const ctx = this._audio;
    if (!ctx || ctx.state !== "running") return;
    const start = ctx.currentTime + at;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "square";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.15, start + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + length);
    osc.connect(gain).connect(ctx.destination);
    osc.start(start);
    osc.stop(start + length + 0.02);
  }

  _playChime() {
    if (!this._config.sound) return;
    this._unlockAudio();
    const ctx = this._audio;
    if (!ctx || ctx.state !== "running") return;
    [[1046, 0], [784, 0.28]].forEach(([freq, at]) => {
      const start = ctx.currentTime + at;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.25, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.9);
      osc.connect(gain).connect(ctx.destination);
      osc.start(start);
      osc.stop(start + 1);
    });
  }

  _countdownBeep(state, remaining) {
    if (!this._config.sound) return;
    this._unlockAudio();
    if (state === "pending") {
      this._beep(1400, 0);
      this._beep(1400, 0.18);
    } else if (remaining <= 10) {
      this._beep(1000, 0);
      this._beep(1000, 0.18);
    } else {
      this._beep(880, 0);
    }
  }

  // ------------------------------------------------------------------ actions
  async _run(calls) {
    this._busy = true;
    this._error = "";
    this._render();
    const errors = [];
    for (const [domain, service, data, label] of calls) {
      try {
        await this._hass.callService(domain, service, data);
      } catch (err) {
        errors.push((label ? `${label}: ` : "") + (err?.message || String(err)));
      }
    }
    this._busy = false;
    this._code = "";
    if (errors.length) {
      this._error = errors.join("\n");
      if (!this._bypass && /open/i.test(this._error)) this._bypass = true;
    } else {
      this._bypass = false;
    }
    this._render();
  }

  _armData(entityId, mode) {
    const data = { entity_id: entityId, mode: mode.replace("armed_", ""), force: this._bypass };
    if (this._code) data.code = this._code;
    return data;
  }

  _arm(mode) {
    if (this._isAll) {
      const calls = this._states()
        .filter((s) => s.state === "disarmed")
        .map((s) => ["pt_alarm", "arm", this._armData(s.entity_id, mode), this._name(s)]);
      this._run(calls);
    } else {
      this._run([["pt_alarm", "arm", this._armData(this._stateObj.entity_id, mode)]]);
    }
  }

  _disarm() {
    const targets = this._isAll ? this._states().filter((s) => s.state !== "disarmed") : [this._stateObj];
    const calls = targets.map((s) => {
      const data = { entity_id: s.entity_id };
      if (this._code) data.code = this._code;
      return ["alarm_control_panel", "alarm_disarm", data, this._isAll ? this._name(s) : ""];
    });
    this._run(calls);
  }

  _key(k) {
    if (k === "clear") this._code = "";
    else if (k === "back") this._code = this._code.slice(0, -1);
    else if (this._code.length < 12) this._code += k;
    this._error = "";
    const el = this.shadowRoot.querySelector(".code-display");
    if (el) {
      el.textContent = this._code ? "●".repeat(this._code.length) : this._prompt;
      el.classList.toggle("empty", !this._code);
    }
  }

  // ------------------------------------------------------------------ render pieces
  _tabs() {
    if (!this._multi) return "";
    const tab = (id, label, state) => {
      const info = STATES[state] || STATES.unavailable;
      const notReady = state === "disarmed" && id !== ALL && this._notReady(this._hass.states[id]?.attributes || {}).length;
      return `<button class="tab ${this._selected === id ? "active" : ""} ${URGENT.includes(state) ? "urgent" : ""}" data-tab="${id}">
        <span class="dot" style="background:${notReady ? GREY : info.color}"></span>${esc(label)}</button>`;
    };
    const tabs = this._states().map((s) => tab(s.entity_id, this._name(s), s.state));
    if (this._config.show_all) tabs.push(tab(ALL, "All", this._combinedState()));
    return `<div class="tabs">${tabs.join("")}</div>`;
  }

  get _prompt() {
    return this._bypass ? "Enter your PIN to bypass" : "Enter code";
  }

  _keypad(numeric) {
    if (!numeric) {
      return `<input class="code-input" type="password" autocomplete="off" placeholder="${this._prompt}" value="${esc(this._code)}">`;
    }
    const style = this._config.keypad_style === "round" ? "round" : "modern";
    const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"]
      .map((k) => {
        const label =
          k === "clear" ? '<ha-icon icon="mdi:close"></ha-icon>' : k === "back" ? '<ha-icon icon="mdi:backspace-outline"></ha-icon>' : k;
        return `<button class="key ${k.length > 1 ? "fn" : ""}" data-key="${k}">${label}</button>`;
      })
      .join("");
    return `<div class="code-display ${this._code ? "" : "empty"} ${this._bypass ? "bypassing" : ""}">${this._code ? "●".repeat(this._code.length) : this._prompt}</div>
      <div class="keypad ${style}">${keys}</div>`;
  }

  _statusBar(state, sub, color) {
    const info = STATES[state] || STATES.unavailable;
    return `<div class="status" style="--bar:${color || info.color}">
      <ha-icon icon="${info.icon}"></ha-icon>
      <div class="status-text">
        <div class="status-label ${info.label.length > 12 ? "long" : ""}">${esc(info.label)}</div>
        ${sub ? `<div class="status-sub">${sub}</div>` : ""}
      </div>
    </div>`;
  }

  _bypassedText(count) {
    return `${count} zone${count > 1 ? "s" : ""} bypassed`;
  }

  _readyText(count) {
    return count ? "Not ready to arm" : "Ready to arm";
  }

  _singleBody(stateObj) {
    const a = stateObj.attributes;
    const state = stateObj.state;
    const disarmed = state === "disarmed";
    const notReady = disarmed ? this._notReady(a) : [];
    const bypassed = a.bypassed_sensors || [];
    const name = esc(this._name(stateObj));

    // Status bar: DISARMED with "Ready to arm" / "Not ready to arm" underneath
    let sub = name;
    let barColor = null;
    if (disarmed) {
      sub = this._readyText(notReady.length);
      if (notReady.length) barColor = GREY;
      if (this._multi) sub = `${name} · ${sub}`;
    } else if (state === "arming" && MODES[a.arm_mode]) {
      sub = `${name} · ${MODES[a.arm_mode].label}`;
    } else if (state === "triggered" && a.triggered_by) {
      sub = `${name} · ${esc(this._friendly(a.triggered_by, a))}`;
    }
    const shown = state === "triggered" && STATES[a.alarm_type] && a.alarm_type !== "burglary" ? a.alarm_type : state;
    const status = this._statusBar(shown, sub, barColor);

    const counting = (state === "arming" || state === "pending") && a.expiration;
    const remaining = counting ? this._remaining(a) : 0;
    const countdown = counting
      ? `<div class="countdown ${state}">
          <div class="ring">
            <svg viewBox="0 0 120 120" aria-hidden="true">
              <circle class="ring-track" cx="60" cy="60" r="${RING_R}"></circle>
              <circle class="ring-progress" cx="60" cy="60" r="${RING_R}"
                stroke-dasharray="${RING_C}" stroke-dashoffset="${this._ringOffset(remaining, a)}"></circle>
            </svg>
            <img src="${ASSET_BASE}/${this._dark ? "icon-dark" : "icon"}.png?v=${CARD_VERSION}" alt="">
          </div>
          <div class="secs">${remaining}</div>
          <div class="label">${state === "arming" ? "seconds to leave" : "seconds to disarm"}</div>
        </div>`
      : "";

    // Zones: open (not ready) while disarmed, bypassed while armed
    const zoneRows = [];
    if (this._config.show_sensors && disarmed) {
      for (const e of notReady) {
        zoneRows.push(`<div class="zone">
          <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
          <span>${esc(this._friendly(e, a))}</span><em>${this._activeWord(e, a)}</em></div>`);
      }
    }
    let zones = zoneRows.length ? `<div class="zones">${zoneRows.join("")}</div>` : "";
    if (!disarmed && bypassed.length) {
      const list = this._showBypassed
        ? `<div class="zones bypassed-list">${bypassed
            .map(
              (e) => `<div class="zone bypassed"><ha-icon icon="mdi:shield-off-outline"></ha-icon>
                <span>${esc(this._friendly(e, a))}</span><em>Bypassed</em></div>`
            )
            .join("")}</div>`
        : "";
      zones = `<button class="bypassed-toggle"><ha-icon icon="mdi:shield-off-outline"></ha-icon>
          <span>${this._bypassedText(bypassed.length)}</span>
          <ha-icon icon="${this._showBypassed ? "mdi:chevron-up" : "mdi:chevron-down"}"></ha-icon></button>${list}`;
    }

    let bypassBlock = "";
    if (disarmed && notReady.length) {
      bypassBlock = this._bypass
        ? a.code_format
          ? ""
          : `<div class="hint">Choose Away or Stay to bypass</div>`
        : `<button class="bypass"><ha-icon icon="mdi:shield-off-outline"></ha-icon><span>Bypass open zones</span></button>`;
    }

    const troubles = Object.entries(a.troubles || {});
    let troubleBlock = "";
    if (troubles.length) {
      const label = (t) => `${esc(t.name)}${t.location ? ` (${esc(t.location)})` : ""}`;
      const title =
        troubles.length === 1 ? `Trouble · ${label(troubles[0][1])}` : `${troubles.length} troubles`;
      const list =
        troubles.length > 1 && this._showTroubles
          ? `<div class="zones">${troubles
              .map(
                ([, t]) => `<div class="zone trouble"><ha-icon icon="mdi:alert"></ha-icon>
                  <span>${label(t)}</span><em>${t.zone_type === "tamper" ? "Tamper" : "Supervisory"}</em></div>`
              )
              .join("")}</div>`
          : "";
      troubleBlock = `<button class="trouble-toggle ${troubles.length > 1 ? "multi" : ""}">
          <ha-icon icon="mdi:alert"></ha-icon><span>${title}</span>
          ${troubles.length > 1 ? `<ha-icon icon="${this._showTroubles ? "mdi:chevron-up" : "mdi:chevron-down"}"></ha-icon>` : ""}
        </button>${list}`;
    }

    const showKeypad = this._config.show_keypad && a.code_format && this._codeNeeded(a, disarmed);
    const keypad = showKeypad ? this._keypad(a.code_format === "number") : "";
    const buttons = this._buttons(
      state === "unavailable" ? null : disarmed,
      this._modesFor(a),
      false,
      a.alarm_type === "fire" ? "Reset fire alarm" : null
    );
    const cancel = disarmed && this._bypass ? `<button class="link cancel-bypass">Cancel</button>` : "";
    return { status, body: `${troubleBlock}${countdown}${zones}${bypassBlock}${keypad}`, buttons, footer: cancel };
  }

  _allBody() {
    const states = this._states();
    const combined = this._combinedState();
    const allDisarmed = combined === "disarmed";
    const notReadyCount = states.reduce((n, s) => n + (s.state === "disarmed" ? this._notReady(s.attributes).length : 0), 0);
    let sub = `${states.length} partitions`;
    let color = null;
    if (allDisarmed) {
      sub = this._readyText(notReadyCount);
      if (notReadyCount) color = GREY;
    }
    const status = this._statusBar(combined, sub, color);

    const rows = states
      .map((s) => {
        const info = STATES[s.state] || STATES.unavailable;
        const nr = s.state === "disarmed" && this._notReady(s.attributes).length;
        const nBypassed = s.state !== "disarmed" ? (s.attributes.bypassed_sensors || []).length : 0;
        const label =
          s.state === "disarmed" ? (nr ? "Not ready" : "Ready") : nBypassed ? `${info.label} · ${nBypassed} byp.` : info.label;
        const color = nr ? GREY : info.color;
        return `<button class="part-row" data-tab="${s.entity_id}">
          <span class="dot" style="background:${color}"></span>
          <span class="part-name">${esc(this._name(s))}</span>
          <span class="part-state" style="color:${color}">${esc(label)}</span>
          <ha-icon icon="mdi:chevron-right"></ha-icon></button>`;
      })
      .join("");

    const anyCode = states.some((s) => this._codeNeeded(s.attributes, allDisarmed));
    const numeric = states.every((s) => !s.attributes.code_format || s.attributes.code_format === "number");
    const keypad = this._config.show_keypad && anyCode ? this._keypad(numeric) : "";
    const modes = [...new Set(states.flatMap((s) => this._modesFor(s.attributes)))].filter((m) => MODES[m]);
    const buttons = this._buttons(allDisarmed, modes, true);
    return { status, body: `<div class="parts">${rows}</div>${keypad}`, buttons };
  }

  _buttons(disarmed, modes, all = false, disarmLabel = null) {
    if (disarmed === null) return "";
    const off = this._busy ? "disabled" : "";
    if (disarmed) {
      return modes
        .map(
          (m) => `<button class="action arm" data-mode="${m}" ${off}>
            <ha-icon icon="${MODES[m].icon}"></ha-icon><span>${all ? "All " : ""}${MODES[m].label}</span></button>`
        )
        .join("");
    }
    return `<button class="action disarm" ${off}><ha-icon icon="mdi:shield-off"></ha-icon><span>${disarmLabel || (all ? "Disarm all" : "Disarm")}</span></button>`;
  }

  // ------------------------------------------------------------------ render
  _render() {
    if (!this._config || !this._hass) return;
    if (!this._hass.states[this._config.entity]) {
      this.shadowRoot.innerHTML = `<style>${PTAlarmCard.styles}</style><ha-card><div class="error">Entity not found: ${esc(this._config.entity)}</div></ha-card>`;
      return;
    }
    if (this._selected === ALL && !(this._multi && this._config.show_all)) this._selected = this._config.entity;

    const view = this._isAll ? this._allBody() : this._singleBody(this._stateObj);
    const state = this._isAll ? this._combinedState() : this._stateObj.state;
    const anyAlarm = this._states().some((s) => s.state === "triggered");
    const anyFire = this._states().some((s) => s.state === "triggered" && s.attributes.alarm_type === "fire");
    const info = STATES[state] || STATES.unavailable;
    const tint = anyAlarm || state === "triggered" ? "alarm tinted" : this._config.status_style === "card" ? "tinted" : "";
    const locked = !this._isAll && this._attrs.locked_until && new Date(this._attrs.locked_until) > Date.now();

    this.shadowRoot.innerHTML = `
      <style>${PTAlarmCard.styles}</style>
      <ha-card class="${tint}" style="--state-color:${anyFire ? FIRE : anyAlarm ? RED : info.color}">
        ${
          this._config.show_logo
            ? `<a class="brand" href="${COMPANY_URL}" target="_blank" rel="noopener noreferrer" title="PowerTech Security &amp; Communications"><img src="${ASSET_BASE}/${this._dark ? "logo-dark" : "logo"}.png?v=${CARD_VERSION}" alt="PowerTech Security &amp; Communications"></a>`
            : ""
        }
        ${this._tabs()}
        ${view.status}
        ${locked ? `<div class="error">Keypad locked, try again later</div>` : ""}
        ${this._error ? `<div class="error">${esc(this._error).replace(/\n/g, "<br>")}</div>` : ""}
        ${view.body}
        <div class="actions">${view.buttons}</div>
        ${view.footer || ""}
      </ha-card>`;

    const root = this.shadowRoot;
    root.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => this._select(b.dataset.tab)));
    root.querySelectorAll("button.arm").forEach((b) => b.addEventListener("click", () => this._arm(b.dataset.mode)));
    root.querySelector("button.disarm")?.addEventListener("click", () => this._disarm());
    root.querySelector("button.bypass")?.addEventListener("click", () => {
      this._bypass = true;
      this._error = "";
      this._render();
    });
    root.querySelector("button.trouble-toggle.multi")?.addEventListener("click", () => {
      this._showTroubles = !this._showTroubles;
      this._render();
    });
    root.querySelector("button.bypassed-toggle")?.addEventListener("click", () => {
      this._showBypassed = !this._showBypassed;
      this._render();
    });
    root.querySelector("button.cancel-bypass")?.addEventListener("click", () => {
      this._bypass = false;
      this._code = "";
      this._render();
    });
    root.querySelectorAll("button.key").forEach((b) => b.addEventListener("click", () => this._key(b.dataset.key)));
    const input = root.querySelector(".code-input");
    if (input) {
      input.addEventListener("input", (ev) => (this._code = ev.target.value));
      input.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter") return;
        root.querySelector("button.disarm, button.arm")?.click();
      });
    }
    this._startTimer();
  }

  static get styles() {
    return `
      ha-card { padding: 16px; display: flex; flex-direction: column; gap: 14px; }
      .brand { display: flex; justify-content: center; padding-bottom: 10px; border-bottom: 1px solid var(--divider-color, #e0e0e0); }
      .brand img { height: 30px; max-width: 100%; object-fit: contain; }

      .tabs { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; }
      .tab { display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px; border-radius: 999px; white-space: nowrap;
        font-size: 0.9em; font-weight: 500; background: var(--secondary-background-color, #f2f2f2); }
      .tab.active { background: var(--primary-text-color); color: var(--card-background-color, #fff); }
      .tab.urgent { background: ${RED}; color: #fff; animation: tab-flash 1s steps(1, end) infinite; }
      .tab.urgent .dot { background: #fff !important; }
      .tab.urgent.active { box-shadow: 0 0 0 2px var(--primary-text-color); }
      @keyframes tab-flash { 50% { background: #8e0000; } }
      .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }

      .status { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 16px 18px;
        border-radius: 12px; background: var(--bar); color: #fff; text-align: center; }
      .status ha-icon { --mdc-icon-size: 40px; flex: none; }
      .status-text { min-width: 0; display: flex; flex-direction: column; align-items: center; }
      .status-label { font-size: 1.6em; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase; line-height: 1.1;
        white-space: nowrap; }
      .status-label.long { font-size: 1.25em; }
      .status-sub { font-size: 0.95em; opacity: 0.92; margin-top: 3px; }

      ha-card.tinted { --pt-tint: color-mix(in srgb, var(--state-color) 14%, var(--card-background-color, #fff));
        --ha-card-background: var(--pt-tint); background: var(--pt-tint);
        box-shadow: inset 0 0 0 3px var(--state-color); }
      ha-card.alarm { animation: alarm-flash 1s steps(1, end) infinite; }
      ha-card.alarm .status { animation: alarm-bar 1s steps(1, end) infinite; }
      @keyframes alarm-flash { 50% { --ha-card-background: color-mix(in srgb, var(--state-color) 45%, var(--card-background-color, #fff));
        background: color-mix(in srgb, var(--state-color) 45%, var(--card-background-color, #fff)); } }
      @keyframes alarm-bar { 50% { background: #8e0000; } }
      @media (prefers-reduced-motion: reduce) { ha-card.alarm, ha-card.alarm .status, .tab.urgent { animation: none; } }

      .countdown { text-align: center; --ring-color: #1e88e5; }
      .countdown.pending { --ring-color: var(--warning-color, #ffa600); }
      .ring { position: relative; width: 150px; height: 150px; margin: 0 auto; }
      .ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
      .ring-track { fill: none; stroke: var(--divider-color, #e0e0e0); stroke-width: 7; }
      .ring-progress { fill: none; stroke: var(--ring-color); stroke-width: 7; stroke-linecap: round; transition: stroke-dashoffset 1s linear; }
      .ring img { position: absolute; inset: 0; margin: auto; width: 58%; height: 58%; object-fit: contain; }
      .countdown .secs { font-size: 2.4em; font-weight: 600; color: var(--ring-color); line-height: 1.1; margin-top: 6px; font-variant-numeric: tabular-nums; }
      .countdown .label { color: var(--secondary-text-color); font-size: 0.9em; }

      .zones { display: flex; flex-direction: column; gap: 6px; }
      .zone { display: flex; align-items: center; gap: 8px; font-size: 0.95em; color: var(--warning-color, #ffa600); }
      .zone span { flex: 1; color: var(--primary-text-color); }
      .zone em { font-style: normal; font-size: 0.85em; }
      .zone.bypassed { color: var(--secondary-text-color); }
      .bypassed-toggle { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 9px 14px;
        border-radius: 10px; font-weight: 600; background: transparent; border: 2px solid var(--state-color);
        color: var(--primary-text-color); }
      .bypassed-toggle ha-icon { --mdc-icon-size: 20px; color: var(--state-color); }
      .bypassed-list { padding: 0 6px; }
      .trouble-toggle { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 9px 14px;
        border-radius: 10px; font-weight: 600; cursor: default;
        background: color-mix(in srgb, ${TROUBLE} 12%, transparent); border: 2px solid ${TROUBLE};
        color: var(--primary-text-color); }
      .trouble-toggle.multi { cursor: pointer; }
      .trouble-toggle ha-icon { --mdc-icon-size: 20px; color: ${TROUBLE}; }
      .zone.trouble { color: ${TROUBLE}; }
      .zone ha-icon { --mdc-icon-size: 18px; }

      .hint { text-align: center; font-size: 1.05em; font-weight: 500; color: var(--primary-text-color); }
      .bypass { align-self: center; display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px;
        border-radius: 999px; font-size: 0.92em; font-weight: 500; background: transparent;
        border: 1px solid var(--divider-color, #cfcfcf); color: var(--primary-text-color); }
      .bypass ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); }
      .link { align-self: center; background: none; padding: 6px 12px; color: var(--secondary-text-color);
        font-weight: 500; text-decoration: underline; text-underline-offset: 3px; }

      .parts { display: flex; flex-direction: column; gap: 6px; }
      .part-row { display: flex; align-items: center; gap: 10px; padding: 12px; text-align: left; border-radius: 8px;
        background: var(--secondary-background-color, #f2f2f2); }
      .part-name { flex: 1; min-width: 0; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .part-state { font-size: 0.85em; font-weight: 500; white-space: nowrap; }
      .part-row ha-icon { color: var(--secondary-text-color); --mdc-icon-size: 20px; }

      .error { color: var(--error-color, #db4437); font-size: 0.95em; padding: 8px 12px; border-radius: 8px;
        background: color-mix(in srgb, var(--error-color, #db4437) 10%, transparent); }
      .code-display { text-align: center; font-size: 1.6em; letter-spacing: 6px; min-height: 1.5em; color: var(--primary-text-color); }
      .code-display.empty { font-size: 1em; letter-spacing: normal; color: var(--secondary-text-color); line-height: 2.4em; }
      .code-display.empty.bypassing { color: var(--primary-text-color); font-weight: 500; font-size: 1.05em; }
      .code-input { font: inherit; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--divider-color, #ccc);
        background: var(--card-background-color); color: var(--primary-text-color); text-align: center; }

      button { font: inherit; cursor: pointer; border: none; border-radius: 12px; color: var(--primary-text-color);
        background: var(--secondary-background-color, #f2f2f2); transition: filter .15s, transform .05s; }
      button:hover { filter: brightness(0.95); }
      button:active { transform: scale(0.97); }
      button:disabled { opacity: 0.5; cursor: default; }

      .keypad { display: grid; grid-template-columns: repeat(3, 1fr); max-width: 280px; margin: 0 auto; width: 100%; }
      .key { height: 52px; font-size: 1.3em; font-weight: 500; font-variant-numeric: tabular-nums; }
      .key.fn { color: var(--secondary-text-color); }
      .keypad.modern { gap: 6px; }
      .keypad.modern .key { height: 56px; border-radius: 6px; background: var(--card-background-color, #fff);
        border: 1px solid var(--divider-color, #e0e0e0); box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06); }
      .keypad.modern .key:active { background: var(--secondary-background-color, #f2f2f2); }
      .keypad.round { gap: 10px 0; justify-items: center; }
      .keypad.round .key { width: 64px; height: 64px; border-radius: 50%; }

      .actions { display: flex; flex-wrap: wrap; gap: 8px; }
      .action { flex: 1 1 90px; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 12px 8px; font-weight: 500; }
      .action.arm { padding: 14px 8px; gap: 6px; }
      .action.arm ha-icon { color: var(--primary-color); --mdc-icon-size: 32px; }
      .action.disarm { flex-direction: row; justify-content: center; background: var(--success-color, #43a047); color: #fff; }
    `;
  }
}

if (!customElements.get("pt-alarm-card")) {
  customElements.define("pt-alarm-card", PTAlarmCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "pt-alarm-card",
    name: "PT Alarm Card",
    description: "Keypad, partitions, arm modes, countdowns and open zones for PT Alarm.",
    preview: true,
    documentationURL: "https://github.com/powertbs/pt-alarm",
  });
  console.info(`%c PT-ALARM-CARD %c v${CARD_VERSION} `, "color:#fff;background:#db4437;font-weight:700", "color:#db4437");
}
