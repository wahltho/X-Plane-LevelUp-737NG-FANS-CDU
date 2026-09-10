# FANS CDU patch for the LevelUp 737NG Series

This unofficial patch enables LevelUp's existing A2/FANS CDU implementation in
the 3D cockpit. It adds the missing tablet selector and switchable 3D key
labels for both Captain and First Officer CDUs.

The repository does not contain complete LevelUp, Zibo or X-Plane aircraft
files. The installer applies small, integrity-checked deltas to files from a
supported local LevelUp installation.

Release `v0.1.5` accepts structurally compatible shared Tablet and cockpit
assets, verifies the affected content instead of unrelated whole-file bytes,
and removes only FANS-owned Tablet blocks during uninstall.

Release `v0.1.6` stops coupling the CPDLC protocol to the CDU type: the
tablet `CPDLC` option now cycles `NONE / ATN B1 / FANS` with either CDU, and
switching the CDU type never rewrites that choice. Installing `v0.1.6` over an
installed `v0.1.5` upgrades in place; the earlier owned blocks are recognised
and replaced.

## Supported baseline

- LevelUp 737NG Series V2.S1.50 aircraft assets for X-Plane 12
- All aircraft variants in those packages: 737-600, -700, -800, -900 and
  -900ER

The OBJ transform validates the exact affected geometry/index contract, DDS
deltas remain bound to exact supported assets, and the PNG normal map is
validated by decoded RGBA pixels rather than compression bytes.
`B738.tablet.lua` is not bound to a whole-file hash: the installer requires the
two exact, unmodified selector and type-switch blocks and preserves unrelated
changes elsewhere in the file. Other revisions are accepted only when these
owned contracts still match. The installer neither modifies nor validates
`B738.a_fms.lua` or `zibomod.xpl`.

## Behavior

The LevelUp FMS script already contains the alternate A2/FANS command routing,
Captain/First Officer handlers, FANS pages and CPDLC backend. This patch:

- exposes `MCDU / FANS MCDU` on the tablet FMS options page;
- switches `laminar/B738/fmc_type` immediately;
- leaves the CPDLC protocol (`NONE / ATN B1 / FANS`) to the user: the tablet
  `CPDLC` option cycles through all three with either CDU type while the CMU
  is enabled, and the CDU type switch never changes it;
- switches the visible 3D labels for `ATC`, `VNAV` and `FMC COMM` on both
  CDUs;
- preserves LevelUp's existing command names and click manipulators.

Changing CDU type during an active datalink session is not guarded. End or
stabilize the session before changing the type.

With the standard CDU and `FANS` selected, the ATC pages are reached through
`MENU`, `DLK`, `ATC` because that CDU has no `ATC` key. The LevelUp FMS
script does not draw an `ATC` prompt on the `DLNK-APPLICATION MENU` in that
combination; the left LSK 2 still opens the ATC index. Adding the prompt is
outside this patch, which does not modify `B738.a_fms.lua`.

This package does **not** add or modify a custom CDU pop-out window. It only
covers the LevelUp 3D cockpit and the upstream Lua tablet selector.

## Install

Close X-Plane, download or clone this repository, then run:

```bash
python3 z_Install.py check --aircraft-root "/path/to/737NG Series_v2.S1.50"
python3 z_Install.py install --aircraft-root "/path/to/737NG Series_v2.S1.50"
```

On Windows, use `py` or `python` if `python3` is not available. Restart X-Plane
after installation.

Running `install` with an earlier release of this patch already installed
upgrades it: the earlier release is removed first, then the current one is
installed. No manual uninstall is needed.

## Verify and uninstall

```bash
python3 z_Install.py verify --aircraft-root "/path/to/737NG Series_v2.S1.50"
python3 z_Install.py uninstall --aircraft-root "/path/to/737NG Series_v2.S1.50"
```

Installation creates an exact audit backup under
`.levelup-fans-cdu-patch/backups/` inside the selected aircraft root. Uninstall
removes only the FANS-owned Tablet blocks, preserving unrelated Lua changes.
Dedicated OBJ and texture assets are restored only after their installed state
has passed integrity verification.

## Package contract

`package-manifest.json` uses schema version 2 and declares every target,
operation and payload hash. Binary targets declare supported source hashes;
the Tablet and OBJ targets are structurally validated, and the PNG target uses
decoded source/result pixel hashes.
The allowed operations are:

- exact UTF-8 text replacement with line-ending preservation;
- a structural OBJ8 vertex/index/draw-command transform;
- sparse byte replacement for equal-size DDS files;
- one bounded RGBA pixel-region replacement for the PNG normal map.

The installer does not execute code from a downloaded content payload. This
operation set is intended to be implementable later by the X-Plane 737NG
Maintenance Toolkit as a declarative, multi-file transaction.

## Development

Patch payloads can be regenerated only from locally owned upstream and
reference aircraft files. The asset baseline is the public `v2.S1.50` release,
whose full-package manifest identifies LevelUp source commit
`6e9e40761bbd176cc5d27ffe8dc9a12ff6acc4fd`:

```bash
python3 tools/make_patch_payloads.py \
  --upstream-root "/path/to/clean/737NG Series_v2.S1.50" \
  --reference-root "/path/to/reference/FANS aircraft overlay"
```

The generator rejects unexpected OBJ structure and texture bounds. It also
removes the unrelated compass-dataref change from the generated OBJ result.

Run the integration test with local paths supplied through environment
variables:

```bash
LEVELUP_UPSTREAM_ROOT="/path/to/clean/737NG Series_v2.S1.50" \
LEVELUP_FANS_REFERENCE_ROOT="/path/to/reference/FANS aircraft overlay" \
python3 -m unittest -v
```

Build the deterministic release archive and checksum with:

```bash
python3 tools/build_release.py
```

## Disclaimer

This project is unofficial and is not supported by LevelUp, Zibo or Laminar
Research. Keep a separate aircraft backup and use the patch at your own risk.
