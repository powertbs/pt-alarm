# Changelog

## 0.0.3

### Zones
- Alarm-industry zone types: Entry/Exit 1 and 2, Perimeter, Interior follower, Interior, Fire/CO, 24-hour panic, Supervisory and Tamper.
- Two entry delays per partition (Entry delay 1 and 2).
- Each zone gets its own name, device type, location and door chime.
- A zone status sensor for every zone: Closed/Open, Clear/Motion, Bypassed or Alarm, with its location.
- Existing sensors are converted to zone types automatically.

### Arming
- "Stay" replaces "Home" everywhere.
- Ready to arm / Not ready to arm.
- Bypass open zones with a PIN. Only users with bypass permission can do it.
- Bypassed zones are always shown while armed, and every disarm clears them.

### Fire and troubles
- Fire/CO zones sound a FIRE alarm in every state, and always need a PIN to reset.
- Supervisory and Tamper zones report a trouble only and never sound the siren.

### Partitions and users
- Partitions: add a partition with **Add hub**. Users can be assigned to one or more partitions.
- Users: edit users; can arm, can disarm and can bypass permissions; allowed days and hours (overnight works); valid from/until dates; "not allowed while" holiday entities; access IDs.
- Settings are saved right away. Clicking Submit without changes goes back to the menu.

### Automations and access control
- `pt_alarm.arm` and `pt_alarm.disarm` take `user` (PT user or access ID) and `source`.
- Setup questions: allow automations, what to do with open zones (refuse or bypass, then notify), and trust access control.
- Automations can never disarm during an alarm.
- The activity log names the user and the automation or system that armed or disarmed.

### Notifications
- Email and push/SMS channels, each with its own on/off list of events.
- Branded HTML email whose color, icon and details change with the event. Your own `pt_alarm_email.html` in the config folder replaces the built-in design.
- Notifiers set up from the UI (notify entities) are supported with plain text.
- **Send a test notification** in the menu.

### Dashboard card
- Big centered status bar, partition tabs with an All tab, and an automatic jump to a partition in alarm or entry delay.
- Square keypad (round keys optional), countdown ring with the PT shield, beeps and door chime.
- Trouble banner, FIRE state with **Reset fire alarm**, and a bypass panel.
- Optional whole-card coloring, real icons and capitalized labels.

## 0.0.2 and 0.0.1
- See the [GitHub releases](https://github.com/powertbs/pt-alarm/releases).
