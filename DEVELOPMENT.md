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

## Writes

The integration only turns things on or off, by design: the work mode
enables and the on/off byte of an existing TOU slot (`eco_mode_N_switch`,
the high byte of the group's third register). Anything with a value is
read-only here. Don't add numbers, selects, times or schedule writes; SEMS+
or the app validate those before they reach the inverter, a Modbus write
does not.

Verified on a work mode 3.0 EHA (2026-10-12): TOU slot on/off, TOU mode and
backup mode; each acts at once. Smart charge and peak shaving are untested,
because the shared group (47589) must already hold their schedule. The
inverter can read a backup write back a moment late, so a switch shows what
it wrote until a read agrees, or until a read 30 seconds later.

## CI

Lint and Test run on every push to `main`. Validate (manual) runs HACS,
which passes, and hassfest, which fails: it rejects the git requirement
(`goodwe @ git+https://…`, "contains a space"). Only a PyPI release of the
library would fix that.
