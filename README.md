<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.png">
    <img src="docs/logo.png" width="380" alt="PowerTech Security &amp; Communications">
  </picture>
</p>

# PT Alarm

[![Marketplace](https://img.shields.io/badge/Home%20Assistant-Marketplace-41BDF5.svg)](https://contributors.home-assistant.io/marketplace/)
[![Validate](https://github.com/YOUR_GITHUB_USERNAME/pt-alarm/actions/workflows/validate.yaml/badge.svg)](https://github.com/YOUR_GITHUB_USERNAME/pt-alarm/actions/workflows/validate.yaml)

**PT Alarm** by PowerTech Security & Communications turns the sensors you already have in Home Assistant into a full alarm system. It runs entirely locally, needs no cloud and no extra hardware, and **comes with its own dashboard card**.

## Features

- **Five arm modes**: Away, Home, Night, Vacation and Custom. Each mode has its own exit delay, entry delay and trigger time.
- **Sensor types with sensible defaults**: door, window, motion, tamper, environmental (smoke, water, gas) and other. You can fine-tune each sensor:
  - which modes it is active in
  - trigger immediately or after the entry delay
  - always on (24 hours, even when disarmed)
  - allow it to be open when arming (for example motion sensors)
  - trigger when it becomes unavailable
- **User codes**: each user has their own code with separate arm and disarm permissions. Codes are stored as salted PBKDF2 hashes, never in plain text.
- **Lockout** after too many wrong codes.
- **Open-sensor protection**: arming is refused while a door or window is open. You can force-arm or enable auto-bypass to skip the open sensors.
- **Sirens**: turn on any siren, switch, light or script when the alarm triggers, and turn them off when it is disarmed.
- **Notifications** to any `notify` service for the events you choose.
- **Events** (`pt_alarm_event`) for your own automations.
- **Survives restarts**: an armed panel stays armed after a reboot, without restarting countdowns or sirens.
- **Multiple panels**: add the integration again to create another panel (for example *House* and *Garage*).
- **Dashboard card** with a keypad, arm buttons, live countdown, open and bypassed sensors, and "Arm anyway". The card is loaded automatically, so you don't need to add a resource.

## Installation

### Home Assistant Marketplace (2026.11 and newer)

1. Go to **Settings → Marketplace**.
2. Search for **PT Alarm**. If it isn't in the catalog yet, choose **Add from link** and paste `https://github.com/YOUR_GITHUB_USERNAME/pt-alarm`. Adding from a link requires a one-time GitHub connection.
3. Install it. Because PT Alarm is set up from the UI, it loads without a restart.

### HACS (Home Assistant 2026.10 and older)

In HACS, open the menu ⋮ → **Custom repositories**, add `https://github.com/YOUR_GITHUB_USERNAME/pt-alarm` with the category **Integration**, install it, and restart Home Assistant.

### Manual

Copy `custom_components/pt_alarm` into your Home Assistant `config/custom_components/` folder and restart.

## Setup

1. Go to **Settings → Devices & services → Add integration → PT Alarm**.
2. Name the panel and, optionally, set a first user code.
3. Open the integration and click **Configure**. From the menu you can:
   - **General settings**: code requirements, auto-bypass, lockout
   - **Arm modes and delays**: enable modes and set exit, entry and trigger times
   - **Add / Edit / Remove sensors**
   - **Add / Remove user codes**
   - **Sirens and notifications**
4. Choose **Save and close**. The panel reloads with the new settings.

### Sensor defaults

| Type          | Active in modes              | Behaviour                         |
|---------------|------------------------------|-----------------------------------|
| Door          | Away, Home, Night, Vacation  | Entry delay                       |
| Window        | Away, Home, Night, Vacation  | Immediate                         |
| Motion        | Away, Vacation               | Entry delay, may be open when arming |
| Tamper        | –                            | Always on, immediate              |
| Environmental | –                            | Always on, immediate              |
| Other         | Away                         | Entry delay                       |

A sensor counts as **open** when its state is `on`, `open`, `opening`, `unlocked`, `detected`, `true` or `not_home`.

## Dashboard card

The card appears in the card picker as **PT Alarm Card** and has a visual editor. In YAML:

```yaml
type: custom:pt-alarm-card
entity: alarm_control_panel.pt_alarm
name: House            # optional
modes:                 # optional: buttons to show (default: all enabled modes)
  - armed_away
  - armed_home
  - armed_night
show_keypad: true      # optional
show_sensors: true     # optional
show_logo: true        # optional: PowerTech logo header (follows light/dark theme)
```

The keypad only appears when a code is needed for the next action. If arming fails because a sensor is open, the card offers **Arm anyway**, which bypasses the open sensors.

You can also use Home Assistant's built-in *Alarm panel* card with PT Alarm entities.

## Services

PT Alarm supports all standard `alarm_control_panel` actions (`alarm_arm_away`, `alarm_disarm`, `alarm_trigger`, and so on), plus:

### `pt_alarm.arm`

| Field        | Description                                              |
|--------------|----------------------------------------------------------|
| `mode`       | `away`, `home`, `night`, `vacation` or `custom_bypass`   |
| `code`       | User code (if required)                                  |
| `force`      | Arm even if sensors are open (they are bypassed)         |
| `skip_delay` | Arm right away, without the exit delay                   |

```yaml
action: pt_alarm.arm
target:
  entity_id: alarm_control_panel.pt_alarm
data:
  mode: night
  force: true
```

## Events

Every state change fires `pt_alarm_event`:

```yaml
event_type: pt_alarm_event
data:
  entity_id: alarm_control_panel.pt_alarm
  name: PT Alarm
  event: triggered        # arming, armed, disarmed, pending, triggered,
                          # failed_to_arm, invalid_code, locked_out
  state: triggered
  user: null
  mode: armed_away
  sensor: binary_sensor.front_door
  sensor_name: Front door
```

Example automation, which flashes the lights when the alarm triggers:

```yaml
automation:
  - alias: Alarm - flash lights
    triggers:
      - trigger: event
        event_type: pt_alarm_event
        event_data:
          event: triggered
    actions:
      - action: light.turn_on
        target:
          area_id: living_room
        data:
          flash: long
```

## Entity attributes

| Attribute              | Meaning                                       |
|------------------------|-----------------------------------------------|
| `arm_mode`             | Current or target armed mode                  |
| `supported_modes`      | Enabled arm modes                             |
| `delay` / `expiration` | Running exit or entry countdown               |
| `open_sensors`         | Sensors that are currently open               |
| `bypassed_sensors`     | Sensors ignored for this arming               |
| `triggered_by`         | Sensor that caused the trigger or entry delay |
| `locked_until`         | End of the keypad lockout                     |
| `changed_by`           | User who last armed or disarmed               |

## How it works

```
disarmed ──arm──▶ arming ──exit delay──▶ armed_* ──sensor (delayed)──▶ pending ──entry delay──▶ triggered
    ▲                                       │                                                  │
    │                                       └──────sensor (immediate)─────────────────────────▶│
    └──────────────────────disarm (from any state)─────────────────────────────────────────────┘
                     triggered ──trigger time──▶ back to armed (or disarmed, if configured)
```

Always-on sensors trigger from any state.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

## Credits

Inspired by the excellent [Alarmo](https://github.com/nielsfaber/alarmo) by Niels Faber. PT Alarm is an independent implementation.

## License

MIT
