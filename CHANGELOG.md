# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `edidgen` command that builds a 256-byte EDID (base block + CTA-861 extension) from a
  TOML config, with `--check` (validate only), `-o` (output path), `--decode` (run
  edid-decode on the result) and `--allow-invalid` (write it despite spec violations).
- Validation that reports every problem at once, each with its key path
  (`modes[2].timing: …`), and writes nothing when there are errors. Unknown keys are errors,
  so typos don't go unnoticed.
- Display identity, size, gamma, bit depth and interface; HDMI and HDMI Forum vendor blocks
  with deep color and SCDC; HDR static metadata with BT.2020 colorimetry; display range
  limits, derived from all advertised timings when not given.
- Standard CTA-861 modes by VIC, with an optional native VIC.
- Detailed modes from VESA CVT (standard blanking and reduced blanking v1, v2 and v3, with
  interlacing, margins, RB2 video-optimized rates and the RB3 blanking options) or from
  explicit timings. CVT timings match `edid-decode --cvt`, computed in exact arithmetic.
- Each detailed mode reports the display's image size fitted to its aspect ratio.
- Example config for a virtual 1440p/4K HDMI display.

[Unreleased]: https://github.com/agsimmons/edidgen/commits/main
