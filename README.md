# GoodWe Local for Home Assistant

A Home Assistant integration that talks to GoodWe inverters directly over the
local network (Modbus over UDP 8899 or TCP 502), without the cloud. It is a
custom-component fork of Home Assistant's built-in
[GoodWe integration](https://www.home-assistant.io/integrations/goodwe), using
the domain `goodwe_local` so it can run side by side with the built-in one.

It runs on [haids3/goodwe](https://github.com/haids3/goodwe), a fork of
[marcelblijleven/goodwe](https://github.com/marcelblijleven/goodwe) carrying
fixes for work mode 3.0 firmware (per-mode switches), the TOU export-limit
bit and NUL-padded model names.

## Differences from the built-in integration

- **Controls are off by default.** Settings (export limit, depth of
  discharge, operation mode or work modes) are shown read-only. Turning on
  *Allow controls* in the integration's options adds the entities that write
  to the inverter, and the read-only ones stay, so nothing is removed when
  controls are switched on or off.
- Settings are read every 5 minutes, so changes made in the GoodWe apps show
  up in Home Assistant.
- **Devices like the GoodWe apps.** The inverter carries power flow, status,
  grid connection and PV strings; the battery, smart meter and work modes are
  devices of their own, connected via the inverter.
- **Names from the apps, not the register map.** ET-family inverters (ET,
  EH, BT, BH, EHA and the other hybrids) get curated names, such as
  "Grid power" for "Active Power" and "Status" for "Work Mode code". About 60
  sensors are shown by default; the remaining register readings exist but are
  disabled. Other families keep the library's names, with the main sensors
  shown.
- **Signs as Home Assistant expects.** Grid power is positive while
  importing, and battery power positive while discharging.
- Zeroconf discovery of GoodWe WiFi/LAN dongles (`_goodwe._tcp`).
- Work mode 3.0 firmware gets one switch per work mode (backup, TOU, smart
  charge, peak shaving) instead of the operation-mode select.

## Credits

Based on the GoodWe integration in
[home-assistant/core](https://github.com/home-assistant/core) by its code
owners, licensed under the Apache License 2.0, as is this repository.
