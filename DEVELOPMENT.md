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
