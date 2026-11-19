"""Generate EDID binaries from a validated TOML config."""

from edidgen.config import parse_config
from edidgen.encode import build_edid
from edidgen.model import Config, Display, Hdmi, Hdr, RangeLimits, Timing, TimingKind
from edidgen.reader import Diagnostics
from edidgen.timing import cvt_rb, cvt_rb2


__all__ = [
    "Config",
    "Diagnostics",
    "Display",
    "Hdmi",
    "Hdr",
    "RangeLimits",
    "Timing",
    "TimingKind",
    "build_edid",
    "cvt_rb",
    "cvt_rb2",
    "parse_config",
]
