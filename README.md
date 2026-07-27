# FANS CDU patch for the LevelUp 737NG Series

This unofficial patch enables LevelUp's existing A2/FANS CDU implementation in
the 3D cockpit. It adds the missing tablet selector and switchable 3D key
labels for both Captain and First Officer CDUs.

The repository does not contain complete LevelUp, Zibo or X-Plane aircraft
files. The installer applies small, integrity-checked deltas to files from a
supported local LevelUp installation.

## Supported baseline

- LevelUp 737NG Series V2.S1.50A for X-Plane 12
- All aircraft variants in those packages: 737-600, -700, -800, -900 and
  -900ER

Modified or unknown upstream files are rejected instead of overwritten.

## Behavior

The LevelUp FMS script already contains the alternate A2/FANS command routing,
Captain/First Officer handlers, FANS pages and CPDLC backend. This patch:

- exposes `MCDU / FANS MCDU` on the tablet FMS options page;
- switches `laminar/B738/fmc_type` immediately;
- selects CPDLC `FANS` with the FANS CDU and `ATN B1` with the standard CDU
  while the CMU is enabled;
- switches the visible 3D labels for `ATC`, `VNAV` and `FMC COMM` on both
  CDUs;
- preserves LevelUp's existing command names and click manipulators.

Changing CDU type during an active datalink session is not guarded. End or
stabilize the session before changing the type.

This package does **not** add or modify a custom CDU pop-out window. It only
covers the LevelUp 3D cockpit and the upstream Lua tablet selector.

## Install

Close X-Plane, download or clone this repository, then run:

```bash
python3 z_Install.py check --aircraft-root "/path/to/737NG Series_V2.S1.50A"
python3 z_Install.py install --aircraft-root "/path/to/737NG Series_V2.S1.50A"
```

On Windows, use `py` or `python` if `python3` is not available. Restart X-Plane
after installation.

## Verify and uninstall

```bash
python3 z_Install.py verify --aircraft-root "/path/to/737NG Series_V2.S1.50A"
python3 z_Install.py uninstall --aircraft-root "/path/to/737NG Series_V2.S1.50A"
```

Installation creates a complete backup under
`.levelup-fans-cdu-patch/backups/` inside the selected aircraft root. An
uninstall is refused if any installed target was changed after installation.

## Package contract

`package-manifest.json` uses schema version 2 and declares every target,
supported source hash, operation and payload hash. The allowed operations are:

- exact UTF-8 text replacement with line-ending preservation;
- a structural OBJ8 vertex/index/draw-command transform;
- sparse byte replacement for equal-size DDS files;
- one bounded RGBA pixel-region replacement for the PNG normal map.

The installer does not execute code from a downloaded content payload. This
operation set is intended to be implementable later by the X-Plane 737NG
Maintenance Toolkit as a declarative, multi-file transaction.

## Development

Patch payloads can be regenerated only from locally owned upstream and
reference aircraft files:

```bash
python3 tools/make_patch_payloads.py \
  --upstream-root "/path/to/original/737NG Series_V2.S1.50A" \
  --reference-root "/path/to/reference/FANS aircraft overlay"
```

The generator rejects unexpected OBJ structure and texture bounds. It also
removes the unrelated compass-dataref change from the generated OBJ result.

Run the integration test with local paths supplied through environment
variables:

```bash
LEVELUP_UPSTREAM_ROOT="/path/to/original/737NG Series_V2.S1.50A" \
LEVELUP_FANS_REFERENCE_ROOT="/path/to/reference/FANS aircraft overlay" \
python3 -m unittest -v
```

## Disclaimer

This project is unofficial and is not supported by LevelUp, Zibo or Laminar
Research. Keep a separate aircraft backup and use the patch at your own risk.
