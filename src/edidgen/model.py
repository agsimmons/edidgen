"""Typed, validated configuration model."""

from dataclasses import dataclass
from enum import Enum


class TimingKind(Enum):
    CVT_RB = "cvt-rb"
    CVT_RB2 = "cvt-rb2"
    EXPLICIT = "explicit"


@dataclass(frozen=True)
class Timing:
    """A fully resolved detailed timing."""

    pclk_mhz: float
    h_active: int
    h_front: int
    h_sync: int
    h_back: int
    v_active: int
    v_front: int
    v_sync: int
    v_back: int
    h_sync_positive: bool
    v_sync_positive: bool

    @property
    def h_total(self) -> int:
        return self.h_active + self.h_front + self.h_sync + self.h_back

    @property
    def v_total(self) -> int:
        return self.v_active + self.v_front + self.v_sync + self.v_back

    @property
    def refresh(self) -> float:
        return self.pclk_mhz * 1e6 / (self.h_total * self.v_total)

    @property
    def hfreq_khz(self) -> float:
        return self.pclk_mhz * 1e3 / self.h_total

    def label(self) -> str:
        return f"{self.h_active}x{self.v_active}@{self.refresh:.2f}"


@dataclass(frozen=True)
class Display:
    name: str = "VirtDisplay"
    manufacturer: str = "XXX"
    product_code: int = 0
    serial: int = 0
    week: int = 1
    year: int = 2026
    size_cm: tuple[int, int] = (60, 34)
    gamma: float = 2.2
    bit_depth: int = 8
    interface: str = "hdmi-a"


@dataclass(frozen=True)
class RangeLimits:
    vrefresh_hz: tuple[int, int] | None = None  # None = derive from modes
    hfreq_khz: tuple[int, int] | None = None
    max_pixel_clock_mhz: int | None = None


@dataclass(frozen=True)
class Hdmi:
    enabled: bool = True
    max_tmds_mhz: int = 340
    deep_color: tuple[int, ...] = ()
    y444_deep_color: bool = True
    scdc: bool = True


@dataclass(frozen=True)
class Hdr:
    enabled: bool = False
    bt2020: bool = True
    max_luminance_nits: float = 0.0  # 0 = not specified
    max_frame_avg_nits: float = 0.0


@dataclass(frozen=True)
class Config:
    output: str | None
    display: Display
    range_limits: RangeLimits
    hdmi: Hdmi
    hdr: Hdr
    modes: tuple[Timing, ...]
    vics: tuple[int, ...]
    native_vic: int | None
