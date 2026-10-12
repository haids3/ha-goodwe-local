# Development

## Setup

```sh
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest -q -p no:logging
uvx ruff check . && uvx ruff format --check .
```

To work on unpushed library changes, install the clone editable:
`uv pip install --python .venv/bin/python -e /path/to/goodwe`.

## Library

The manifest pins a commit of the `ha-local` branch of
[haids3/goodwe](https://github.com/haids3/goodwe), which merges the fix
branches offered upstream. A library change is pushed there first, then
repinned in both `manifest.json` and `requirements_test.txt`.

The library is imported as `goodwe`, like the PyPI release the built-in
integration requires. Running both integrations in one Home Assistant means
one of them gets the other's library version; start a development instance
with `--skip-pip-packages goodwe` to keep an editable install.

## Origin

Ported from `homeassistant/components/goodwe` in home-assistant/core
(`dev`, 2026.11.0.dev0) plus the unmerged work-mode switch and zeroconf
branches of haids3/HASScore. Unique IDs are `{serial}-{key}` throughout; the
built-in integration's legacy formats were not carried over.

## Sensors

`catalog.py` decides, for each ET runtime sensor ID, its translation key,
device, entity category and whether it is enabled by default; `strings.json`
holds the names. A sensor the table doesn't know falls back to the library's
name, hidden. When the library gains ET sensors, compare the table with
`ET.sensors()` so none of them fall back by accident.

Codes become enum states in the table (work mode 35187 → Status, grid mode
35136 → Grid, battery mode 35184 → battery Status). The mappings are ET
codes; DT and ES reuse some sensor IDs with other meanings, which is why
the table applies to ET only.

## Options

The settings and controls options are off by default, so a new entry shows
readings only. *Show stored settings* adds the read-only settings and TOU
slot sensors and the work mode binary sensors; *Allow controls* adds the
switches, after a warning that points to SEMS+. The settings area is read only while one of
them is on. The inverter's stored settings sync with the cloud only now and
then, so they are not a source of truth; SEMS+ is the place to see and change
settings. Turning an option off removes its entities from the registry.

*Check for firmware updates* is on by default. Once a day it posts the
inverter's serial and DSP/ARM versions to
`https://solargo.sems.com.cn/api/Solargo/CheckUpgradePlus_v3`, as the SEMS+
app does before sign-in, with the token built into the app (`firmware.py`).
The versions are the middle part of the firmware strings (7 from
`04082-07-S08`), because the library's `dsp1_version`/`arm_version` read 1 on
the EHA; inverters whose strings have another form aren't checked. An empty
answer means up to date; asking with an older ARM version returned the
installed ARM firmware, so the check does report releases. The endpoint is
undocumented and may change; a failed check leaves the entity unavailable.
Nothing is ever installed from here.

## Writes

The integration only turns things on or off, by design: the work mode
enables and the on/off byte of an existing TOU slot (`eco_mode_N_switch`,
the high byte of the group's third register). Anything with a value is
read-only here. Don't add numbers, selects, times or schedule writes; SEMS+
or the app validate those before they reach the inverter, a Modbus write
does not.

Work mode 3.0 has 8 TOU slots, other firmware 4. Following the SEMS web
portal, slots 1-7 are the groups at 47547 + 6 * (n - 1) and slot 8 is at
47840, after the two groups peak shaving and smart charge share (47589 and
47834). Slots 5-8 are read live, but have never held a schedule on the test
inverter. A group with no days, or on/off byte 85 (not set), counts as empty.

Verified on a work mode 3.0 EHA (2026-10-12): TOU slot on/off, TOU mode and
backup mode; each acts at once. Smart charge on and off, with its schedule in
the second shared group (47834), switched the inverter at once and reached
SEMS+ with the usual sync lag. The inverter can read a backup write back a
moment late, so a switch shows what it wrote until a read agrees, or until a
read 30 seconds later.

Slots 5-8 were set up in the portal (2026-10-12) and read back at 47571,
47577, 47583 and 47840, confirming the layout above.

Peak shaving is untested and its switch doesn't work yet. Set up in the
portal but left off (2026-10-12), it landed in 47589 as `0c00 0f00 007f 0005
000a 0000`: 12:00-15:00, every day, on/off byte **0**, max import power 5
(whole kW, not the library's 10 W steps) and reserve SOC 10 %. The portal
code writes 252 (-4) for on, so off is 0 rather than the type (3), unlike
smart charge (off 5). The library looks for 3 or -4, so it can't find an off
peak shaving group: turning the switch on raises an error and writes
nothing.

## CI

Lint and Test run on every push to `main`. Validate (manual) runs HACS,
which passes, and hassfest, which fails: it rejects the git requirement
(`goodwe @ git+https://…`, "contains a space"). Only a PyPI release of the
library would fix that.
