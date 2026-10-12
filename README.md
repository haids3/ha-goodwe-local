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

- **Only on/off over Modbus, and only when allowed.** Settings (export
  limit, depth of discharge, operation mode, work modes and TOU slots) are
  shown read-only. Turning on *Allow controls* in the integration's options
  adds switches for the work modes and for TOU slots already set up, and
  nothing else: a raw register write has no validation, so values such as
  limits, powers and times are left to the GoodWe app or SEMS+, which check
  them. A slot switch writes only the slot's on/off byte, after reading the
  slot again. The read-only entities stay whether controls are on or off.
- **Changes act at once; stored settings sync slowly.** A switch here, in the
  GoodWe app or in SEMS+ takes effect on the inverter straight away. The
  stored settings sync between the inverter and the cloud only now and then,
  with delays from a few minutes to over an hour. Settings are read every 5
  minutes, but after a change in the app or SEMS+ they can show the old
  values for a while, and SEMS+ can lag changes made here the same way. A
  switch shows the state it wrote for up to 30 seconds, since the inverter
  can take a moment to read it back.
- **Devices like the GoodWe apps.** The inverter carries power flow, status,
  grid connection and PV strings; the battery, smart meter and work modes are
  devices of their own, connected via the inverter.
- **Names from the apps, not the register map.** ET-family inverters (ET,
  EH, BT, BH, EHA and the other hybrids) get curated names, such as
  "Grid power" for "Active Power" and "Status" for "Work Mode code". About 60
  sensors are shown by default; the remaining register readings exist but are
  disabled. Other families keep the library's names, with the main sensors
  shown.
- **Battery racks.** Batteries built from racks (BMS clusters), such as the
  All-in-One, get a device per rack with its state of charge, power,
  current, voltage, temperatures, cell voltages, current limits, fault code
  and state of health, read every minute.
- **Firmware versions** as diagnostic sensors: the DSP and ARM internal
  versions and beta numbers, and the BMS software version. Checking for
  and installing updates is left to the GoodWe app or SEMS+.
- **Signs as Home Assistant expects.** Grid power is positive while
  importing, and battery power positive while discharging.
- Zeroconf discovery of GoodWe WiFi/LAN dongles (`_goodwe._tcp`).
- Work mode 3.0 firmware gets one switch per work mode (backup, TOU, smart
  charge, peak shaving) instead of the operation-mode select.

## Credits

Based on the GoodWe integration in
[home-assistant/core](https://github.com/home-assistant/core) by its code
owners, licensed under the Apache License 2.0, as is this repository.
