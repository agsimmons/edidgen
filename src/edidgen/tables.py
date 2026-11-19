"""Lookup tables: EDID field encodings and CTA-861 VICs."""

from dataclasses import dataclass
from typing import Final


DTD_MAX_PCLK_MHZ: Final = 655.35
# Decoders (edid-decode, the kernel) treat a DTD below 10 MHz as invalid data.
DTD_MIN_PCLK_MHZ: Final = 10.0
INTERFACES: Final[dict[str, int]] = {
    "none": 0,
    "dvi": 1,
    "hdmi-a": 2,
    "hdmi-b": 3,
    "mddi": 4,
    "dp": 5,
}
BIT_DEPTHS: Final[dict[int, int]] = {6: 1, 8: 2, 10: 3, 12: 4, 14: 5, 16: 6}
DEEP_COLOR_BITS: Final[dict[int, int]] = {30: 0x10, 36: 0x20, 48: 0x40}


@dataclass(frozen=True)
class Vic:
    width: int
    height: int
    refresh: float
    pclk_mhz: float
    h_total: int
    interlaced: bool = False

    @property
    def hfreq_khz(self) -> float:
        return self.pclk_mhz * 1e3 / self.h_total


# The established timing edidgen always includes (and HDMI requires): 640x480@60.
ESTABLISHED_640X480: Final = Vic(640, 480, 59.94, 25.175, 800)

# CTA-861 Video Identification Codes that are accepted in `vics`.
VICS: Final[dict[int, Vic]] = {
    1: Vic(640, 480, 59.94, 25.175, 800),
    2: Vic(720, 480, 59.94, 27.0, 858),
    3: Vic(720, 480, 59.94, 27.0, 858),
    4: Vic(1280, 720, 60, 74.25, 1650),
    5: Vic(1920, 1080, 60, 74.25, 2200, interlaced=True),
    16: Vic(1920, 1080, 60, 148.5, 2200),
    17: Vic(720, 576, 50, 27.0, 864),
    18: Vic(720, 576, 50, 27.0, 864),
    19: Vic(1280, 720, 50, 74.25, 1980),
    20: Vic(1920, 1080, 50, 74.25, 2640, interlaced=True),
    31: Vic(1920, 1080, 50, 148.5, 2640),
    32: Vic(1920, 1080, 24, 74.25, 2750),
    33: Vic(1920, 1080, 25, 74.25, 2640),
    34: Vic(1920, 1080, 30, 74.25, 2200),
    47: Vic(1280, 720, 120, 148.5, 1650),
    63: Vic(1920, 1080, 120, 297.0, 2200),
    64: Vic(1920, 1080, 100, 297.0, 2640),
    93: Vic(3840, 2160, 24, 297.0, 5500),
    94: Vic(3840, 2160, 25, 297.0, 5280),
    95: Vic(3840, 2160, 30, 297.0, 4400),
    96: Vic(3840, 2160, 50, 594.0, 5280),
    97: Vic(3840, 2160, 60, 594.0, 4400),
    98: Vic(4096, 2160, 24, 297.0, 5500),
    99: Vic(4096, 2160, 25, 297.0, 5280),
    100: Vic(4096, 2160, 30, 297.0, 4400),
    101: Vic(4096, 2160, 50, 594.0, 5280),
    102: Vic(4096, 2160, 60, 594.0, 4400),
    117: Vic(3840, 2160, 100, 1188.0, 5280),
    118: Vic(3840, 2160, 120, 1188.0, 4400),
}

# Top-level config keys, used to explain keys swallowed by a preceding [table].
ROOT_KEYS: Final = frozenset(
    {"output", "vics", "native_vic", "display", "hdmi", "hdr", "range", "modes"}
)
