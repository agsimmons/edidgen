# edidgen

Generates EDID binaries (base block + CTA-861 extension) from a TOML config, validating
everything first. Typical use: faking a monitor on an unused GPU output (`drm.edid_firmware=`)
for a virtual display, e.g. Sunshine streaming.

## Commands

```bash
uv run pytest                                   # tests (edid-decode ones skip if it's missing)
uv run ruff check && uv run ruff format --check   # also run by pre-commit
uv run ty check
uv run edidgen examples/virtual-display.toml --decode
```

Run all three checks before committing. `uv run --with mypy mypy --strict src tests` should
also stay clean.

## Layout

- `src/edidgen/tables.py`: field encodings, the `VICS` table, and `ROOT_KEYS`
- `src/edidgen/model.py`: frozen dataclasses (`Config`, `Timing`, ...)
- `src/edidgen/reader.py`: `Diagnostics` and `Reader` (typed TOML access that records errors)
- `src/edidgen/timing.py`: CVT generators (`cvt_exact`: standard CVT and RB1/RB2/RB3 with
  interlace, margins and the RB2/RB3 options; `cvt_rb` / `cvt_rb2` wrappers)
- `src/edidgen/config.py`: `parse_config` (per-field checks) and `cross_check` (multi-field checks)
- `src/edidgen/encode.py`: `build_edid` and the byte encoders
- `src/edidgen/cli.py`: argparse entry point (`edidgen` script, `python -m edidgen`)
- `tests/helpers.py`: shared helpers, imported as `from helpers import ...` (works because `tests/`
  has no `__init__.py`, so pytest's default import mode puts it on `sys.path`)

## Conventions

- Runtime is stdlib only, Python >= 3.14. Annotations are lazily evaluated (PEP 649), so don't add
  `from __future__ import annotations`.
- Fully typed: no `Any` past the TOML boundary (`Table = Mapping[str, object]`).
- Validation never stops at the first problem. Readers return the default on error and record
  `path: message` in `Diagnostics`, and `parse_config` returns `None` if there were any errors.
  Messages name the exact key (`modes[2].timing`) and say what is allowed.
- Every key must be read via a `Reader` method (or added to `seen`). `finish()` reports the
  rest as "unknown option".
- Errors are things the driver or format would reject. Warnings are inconsistencies that
  still produce a usable EDID.
- `tests/data/virtual-display.bin` is a golden file: `test_example_config_matches_golden_binary`
  checks that `examples/virtual-display.toml` still builds it byte-for-byte. If an encoding
  change is intentional, regenerate it
  (`uv run edidgen examples/virtual-display.toml -o tests/data/virtual-display.bin`) and say
  so in the commit.
- Timing math is a port of edid-decode's `calc_cvt_mode` (in v4l-utils,
  `utils/edid-decode/calc-gtf-cvt.cpp`). `tests/test_edid_decode.py` checks it against
  `edid-decode --cvt` for every variant, round-trips encoded DTDs through edid-decode, and runs
  `edid-decode -c` on a set of configs. Verify new timing or encoding code there and don't
  trust memory of the spec. Details that matter:
  - Pixel-clock math uses exact `Fraction`s: CVT floors to a clock step, and floats lose a step
    when the exact value lands on a boundary. edid-decode itself does this in `double`, so on
    those boundaries it reports one step low; the sweep test allows exactly that case.
  - RB1: minimum vertical back porch 7; v-sync width from exact integer aspect matches
    (else 10); the clock uses the active width rounded down to 8 pixels.
  - RB2: 1 kHz clock steps, rounded down to the DTD's 10 kHz. CVT-RB2 puts the computed lines
    in the *front* porch; we clamp it to 63 for the 6-bit DTD field and move the excess to the
    back porch. RB3 rounds the clock up instead.
  - `edid-decode --cvt` needs `interlaced=1` / `alt=1`: a bare flag sets them to 0. It also
    raises RB3 `vblank` below 460 µs to 460, so the config accepts only 460-920.
  - DTD conventions (edid-decode's reading): interlaced DTDs store lines per field with flag
    bit 7, and each field has an extra half line; borders are included in the blanking fields
    (twice) but not in the front porch. A DTD clock below 10 MHz is treated as invalid.
  - edid-decode's refresh for interlaced modes ignores vertical borders, so interlaced +
    margins fails its range check; that's its inconsistency, and the conformance test skips
    that combination.
- `edid-decode -c` on HDMI configs reports one known failure ("requires EDID 1.3 instead of
  1.4"). This is intentional: 10-bit color needs EDID 1.4.
