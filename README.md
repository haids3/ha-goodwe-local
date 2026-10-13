# GoodWe Local for Home Assistant

A Home Assistant integration that talks to GoodWe inverters directly over the
local network (Modbus over UDP 8899 or TCP 502), without the cloud (apart
from an optional daily firmware update check). It is a
custom-component fork of Home Assistant's built-in
[GoodWe integration](https://www.home-assistant.io/integrations/goodwe), using
its own domain, `goodwe_local`. Use it instead of the built-in one, not
alongside it (see [Requirements](#requirements)).

It runs on [haids3/goodwe](https://github.com/haids3/goodwe), a fork of
[marcelblijleven/goodwe](https://github.com/marcelblijleven/goodwe) carrying
fixes for work mode 3.0 firmware (per-mode switches), the TOU export-limit
bit and NUL-padded model names.

## Requirements

- Home Assistant 2026.8 or later.
- A GoodWe inverter with a WiFi or LAN dongle on your local network. WiFi
  dongles usually answer on UDP port 8899, LAN dongles on TCP port 502; the
  integration tries both.
- A fixed IP address for the dongle (a DHCP reservation in your router), so
  Home Assistant can keep finding it.
- **Don't run the built-in GoodWe integration on the same Home Assistant.**
  Both use the `goodwe` Python package, but in different versions, so
  Home Assistant can replace one with the other at startup and break
  GoodWe Local. The dongle may also allow only a few connections at once.
  Remove (or disable) the built-in GoodWe integration before installing
  this one.

## Installation

### HACS (recommended)

1. In HACS, open the menu (⋮) and choose **Custom repositories**.
2. Add `https://github.com/haids3/ha-goodwe-local` with the type
   **Integration**.
3. Search HACS for **GoodWe Local**, open it and select **Download**.
4. Restart Home Assistant.

### Manual

1. Download the latest
   [release](https://github.com/haids3/ha-goodwe-local/releases).
2. Copy `custom_components/goodwe_local` into the `custom_components`
   folder of your Home Assistant configuration.
3. Restart Home Assistant.

## Setup

GoodWe dongles announce themselves on the network, so Home Assistant may
show a discovered **GoodWe inverter** under **Settings → Devices &
services**. Select **Add** to set it up.

To add it by hand:

1. Go to **Settings → Devices & services → Add integration** and search for
   **GoodWe Local**.
2. Enter the dongle's IP address.

The integration finds the port and the inverter family on its own. If the
inverter's address changes and it is discovered again, the entry is updated
to the new address.

## Options

Open the integration and select **Configure**:

| Option | Default | What it does |
|---|---|---|
| **Show stored settings** | Off | Adds read-only sensors for the inverter's settings: export limit, depth of discharge, operation mode, work modes and TOU slots. They lag changes made in the GoodWe app or SEMS portal by up to an hour, so don't use them in automations. |
| **Check for firmware updates** | On | Once a day, asks GoodWe whether newer inverter firmware exists. Turn it off to keep everything local. |
| **Allow controls** | Off | Adds switches that turn the work modes and existing TOU slots on or off. Shows a warning first; using SEMS+ for control is recommended. |

Turning an option off removes its entities.

## Using it

- **Devices:** the inverter, plus **Battery**, **Smart meter**, a device per
  battery rack (on rack batteries such as the All-in-One), and **Work mode**
  (only with stored settings or controls on).
- **Readings** update every 10 seconds; battery racks every minute; stored
  settings every 5 minutes.
- **Energy dashboard:**
  - *Grid consumption:* Smart meter **Import total**
  - *Return to grid:* Smart meter **Export total**
  - *Solar production:* inverter **PV energy total**
  - *Home battery storage:* Battery **Charge total** and **Discharge total**

  Use the smart meter totals for the grid: the inverter's own energy
  counters measure its AC port, not the grid connection.
- **Firmware updates** show under **Settings → Updates**. Install them with
  the GoodWe app or ask your installer.
- More sensors exist than are shown: open a device's entity list and enable
  the disabled ones you want.

## Removing

Go to **Settings → Devices & services → GoodWe Local**, open the entry's
menu (⋮) and select **Delete**. If you installed through HACS, also remove
the integration in HACS and restart Home Assistant.

## Differences from the built-in integration

- **Fast readings; settings and control through SEMS+.** GoodWe Local is
  meant for quickly updated readings, and by default shows nothing else. To
  see or change settings, use the
  [SEMS+ integration](https://github.com/haids3/ha-sems-plus), which keeps
  the GoodWe app, the SEMS portal and Home Assistant in sync. The inverter's
  own copy of its settings syncs with the cloud only about hourly (see
  below), so it is no source of truth for automations.
- **Stored settings, read-only, when asked for.** Turning on *Show stored
  settings* in the integration's options adds read-only sensors for the
  export limit, depth of discharge, operation mode, work modes and TOU
  slots. They are read every 5 minutes, and only while this option or
  controls are on.
- **Only on/off over Modbus, and only when allowed.** Turning on *Allow
  controls* in the integration's options, after a warning, adds switches
  for the work modes and for TOU slots already set up, and nothing else: a
  raw register write has no validation, so values such as limits, powers
  and times are left to the GoodWe app or SEMS+, which check them. A slot
  switch writes only the slot's on/off byte, after reading the slot again.
  Turning either option off removes its entities.
- **Changes act at once; stored settings sync slowly.** A switch here, in the
  GoodWe app or in SEMS+ takes effect on the inverter straight away. The
  stored settings sync between the inverter and the cloud in one batch,
  both ways, roughly once an hour, so a change can take anything from a few
  minutes to about an hour to show on the other side. Until
  then the stored settings and switches here can show the old values after
  a change in the app or SEMS+, and SEMS+ can lag changes made here the
  same way. A switch shows the state it wrote for up to 30 seconds, since
  the inverter can take a moment to read it back.
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
  All-in-One, get a device per rack with its status (as the GoodWe app
  shows it: running, standby, sleeping, fault and so on), state of charge,
  power, current, voltage, temperatures, cell voltages, current limits,
  fault code and state of health, read every minute.
- **Firmware versions** as diagnostic sensors: the DSP and ARM internal
  versions and beta numbers, and the BMS software version.
- **Firmware update check.** Once a day, a *Firmware* update entity asks
  GoodWe whether newer DSP or ARM firmware exists, sending the inverter's
  serial number and firmware versions as the GoodWe app does. It only
  checks: install updates with the GoodWe app or ask your installer. This
  is the only feature that contacts GoodWe; it uses the app's undocumented
  service, which may stop working. Turn off *Check for firmware updates* in
  the integration's options to keep everything local.
- **Signs as Home Assistant expects.** Grid power is positive while
  importing, and battery power positive while discharging.
- Zeroconf discovery of GoodWe WiFi/LAN dongles (`_goodwe._tcp`).
- Work mode 3.0 firmware gets one switch per work mode (backup, TOU, smart
  charge, peak shaving) instead of the operation-mode select.

## Credits

Based on the GoodWe integration in
[home-assistant/core](https://github.com/home-assistant/core) by its code
owners, licensed under the Apache License 2.0, as is this repository.
