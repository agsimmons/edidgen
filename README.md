# edidgen

Generate EDID binaries (128-byte base block + CTA-861 extension) from a TOML config.
The config is fully validated first, and every problem is reported with its location
(`modes[2].timing: must be one of ...`). The `.bin` is only written when there are no errors.

Built for faking a monitor on an unused GPU output (`drm.edid_firmware=` +
`video=<connector>:e`), e.g. a virtual display for Sunshine game streaming.

No runtime dependencies (Python ≥ 3.14 standard library only).

## Usage

```bash
uv run edidgen examples/virtual-display.toml            # validate, then write the .bin
uv run edidgen examples/virtual-display.toml --check    # validate only
uv run edidgen examples/virtual-display.toml --decode   # write, then run edid-decode on it
uv run edidgen config.toml -o out.bin                   # override the output path
```

Exit codes: `0` valid (and written), `1` config errors (nothing written), `2` file read/write failure.
Warnings (duplicate modes, modes outside the declared range limits, …) are printed but don't block output.

## Config

[`examples/virtual-display.toml`](examples/virtual-display.toml) documents every option. In short:

```toml
output = "virtual-display.bin"     # top-level keys go before the first [table]
vics = [97, 16, 63, 4, 1]          # standard CTA-861 modes by VIC

[display]                          # name, manufacturer, size, bit depth, interface, ...
name = "VirtDisplay"
bit_depth = 10
interface = "hdmi-a"

[hdmi]                             # HDMI VSDB + HDMI Forum VSDB
max_tmds_mhz = 600

[hdr]                              # HDR static metadata + BT.2020 colorimetry
enabled = true

[range]                            # display range limits (derived from the modes if omitted)
vrefresh_hz = [24, 120]

[[modes]]                          # first mode = preferred
width = 2560
height = 1440
refresh = 60                       # timing = "cvt-rb" (default) | "cvt-rb2" | "explicit"
```

Modes can use generated VESA CVT reduced-blanking timings (`cvt-rb`, `cvt-rb2`), whose
output matches `edid-decode --cvt`, or fully explicit timings.

How the display is named in desktop settings comes from `[display]`:

- `manufacturer` (default `XXX`) is looked up in hwdata's `pnp.ids`, and a registered code
  shows that company's name. Unregistered codes are shown as-is.
- `serial` defaults to `0` (none). KWin then adds the connector to the model name
  (`XXX HDMI-A-1-VirtDisplay`) and ties the display's saved settings to that port. Set any
  nonzero serial to get `XXX VirtDisplay`.

What gets checked includes types and ranges of every field, unknown keys (typos), the
field-width limits of an 18-byte detailed timing descriptor (pixel clock ≤ 655.35 MHz,
porch sizes), modes and VICs that need more than `hdmi.max_tmds_mhz`, and whether all
modes fit in the extension block.

## Development

```bash
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
uv run pre-commit install   # ruff check --fix + ruff format on every commit
uv run ty check
```

Tests that compare against `edid-decode` are skipped when it isn't installed.
