"""Shared test helpers (importable because tests/ is on pytest's pythonpath)."""

import tomllib
from pathlib import Path

from edidgen import Config, Diagnostics, build_edid, parse_config


REPO = Path(__file__).resolve().parent.parent
EXAMPLE_TOML = REPO / "examples" / "virtual-display.toml"
GOLDEN_BIN = Path(__file__).resolve().parent / "data" / "virtual-display.bin"

MODE = """
[[modes]]
width = 1920
height = 1080
refresh = 60
"""

MINIMAL = "vics = [16]\n" + MODE


def with_tables(tables: str, top: str = "vics = [16]") -> str:
    """Top-level keys, then extra tables, then one 1080p60 mode (TOML order matters)."""
    return f"{top}\n{tables}\n{MODE}"


def parse_text(
    text: str, *, allow_invalid: bool = False
) -> tuple[Config | None, Diagnostics]:
    diag = Diagnostics(allow_invalid=allow_invalid)
    return parse_config(tomllib.loads(text), diag), diag


def build_text(text: str) -> bytes:
    cfg, diag = parse_text(text)
    assert cfg is not None, diag.errors
    return build_edid(cfg)


def errors_of(text: str) -> list[str]:
    cfg, diag = parse_text(text)
    assert cfg is None, "expected the config to be rejected"
    return diag.errors
