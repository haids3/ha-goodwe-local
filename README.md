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

- Zeroconf discovery of GoodWe WiFi/LAN dongles (`_goodwe._tcp`).
- Work mode 3.0 firmware gets one switch per work mode (backup, TOU, smart
  charge, peak shaving) instead of the operation-mode select.

## Credits

Based on the GoodWe integration in
[home-assistant/core](https://github.com/home-assistant/core) by its code
owners, licensed under the Apache License 2.0, as is this repository.
