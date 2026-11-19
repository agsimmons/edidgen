"""Command-line interface."""

import argparse
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from edidgen.config import parse_config
from edidgen.encode import build_edid
from edidgen.reader import Diagnostics
from edidgen.tables import VICS


if TYPE_CHECKING:
    from collections.abc import Sequence

    from edidgen.model import Config


def summarize(cfg: Config) -> list[str]:
    lines = [
        f"  {'*' if i == 0 else ' '} DTD  {t.label():>18}  {t.pclk_mhz:8.2f} MHz  "
        f"{t.hfreq_khz:6.1f} kHz"
        for i, t in enumerate(cfg.modes)
    ]
    lines += [
        f"    VIC {v:<3}{VICS[v].width}x{VICS[v].height}@{VICS[v].refresh:g}"
        f"{'i' if VICS[v].interlaced else ''}{'  (native)' if v == cfg.native_vic else ''}"
        for v in cfg.vics
    ]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate an EDID binary from a TOML config."
    )
    ap.add_argument("config", type=Path, help="TOML config file")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output .bin (default: `output` in the config, else the config name with .bin)",
    )
    ap.add_argument(
        "--check", action="store_true", help="validate only; don't write anything"
    )
    ap.add_argument(
        "--decode", action="store_true", help="run edid-decode on the result"
    )
    ap.add_argument(
        "--allow-invalid",
        action="store_true",
        help="write the EDID even if it breaks the spec (e.g. modes above the HDMI "
        "TMDS limit); values that can't be encoded at all are still errors",
    )
    args = ap.parse_args(argv)

    try:
        with args.config.open("rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        print(f"error: cannot read {args.config}: {e.strerror}", file=sys.stderr)
        return 2
    except tomllib.TOMLDecodeError as e:
        print(f"{args.config}: TOML syntax error: {e}", file=sys.stderr)
        return 1

    diag = Diagnostics(allow_invalid=args.allow_invalid)
    cfg = parse_config(data, diag)
    for w in diag.warnings:
        print(f"{args.config}: warning: {w}", file=sys.stderr)
    for v in diag.allowed_violations:
        print(f"{args.config}: invalid (allowed): {v}", file=sys.stderr)
    if cfg is None:
        for err in diag.errors:
            print(f"{args.config}: error: {err}", file=sys.stderr)
        n = len(diag.errors)
        print(f"{n} error{'s' * (n != 1)}; no file written.", file=sys.stderr)
        k = diag.blocking_violations
        if k == n:
            hint = "--allow-invalid would write the EDID anyway (these are spec violations)."
        elif k:
            are = "is a spec violation" if k == 1 else "are spec violations"
            hint = f"{k} of these {are} that --allow-invalid accepts; the rest must be fixed."
        if k:
            print(hint, file=sys.stderr)
        return 1

    edid = build_edid(cfg)
    n_bad = len(diag.allowed_violations)
    status = (
        f"INVALID ({n_bad} allowed violation{'s' * (n_bad != 1)})" if n_bad else "valid"
    )
    print(
        f"{args.config}: {status} ({len(cfg.modes)} detailed modes, {len(cfg.vics)} VICs)"
    )
    for line in summarize(cfg):
        print(line)
    if args.check:
        return 0

    out: Path = args.output or (
        args.config.parent / cfg.output
        if cfg.output
        else args.config.with_suffix(".bin")
    )
    try:
        out.write_bytes(edid)
    except OSError as e:
        print(f"error: cannot write {out}: {e.strerror}", file=sys.stderr)
        return 2
    print(f"wrote {out} ({len(edid)} bytes)")

    if args.decode:
        if shutil.which("edid-decode") is None:
            print("edid-decode not installed; skipping", file=sys.stderr)
        else:
            subprocess.run(["edid-decode", "-c", str(out)], check=False)
    return 0
