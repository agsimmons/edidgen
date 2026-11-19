"""VESA CVT timing generators: standard CVT and reduced blanking v1, v2 and v3.

A port of edid-decode's `calc_cvt_mode` (v4l-utils, `utils/edid-decode/calc-gtf-cvt.cpp`)
done in exact rational arithmetic. CVT rounds the pixel clock to a fixed step, and
with floats a value landing exactly on a step can lose (or gain) a whole step;
edid-decode itself does this in `double`, so on exact boundaries it can be one
step off, and edidgen is not.

Pixel clocks are then rounded to the DTD's 10 kHz resolution in the same direction
CVT rounds: down, except RB3, which rounds up.
"""

import math
from dataclasses import dataclass
from enum import IntEnum
from fractions import Fraction

from edidgen.model import Timing


class ReducedBlanking(IntEnum):
    NONE = 0
    V1 = 1
    V2 = 2
    V3 = 3


@dataclass(frozen=True)
class CvtResult:
    timing: Timing
    exact_clock_mhz: Fraction
    """The pixel clock before rounding to any clock step (useful for tests)."""


CELL_GRAN = 8
MARGIN_PERCENT = Fraction("1.8")
MIN_VSYNC_BP = 550  # µs, standard CVT
MIN_V_PORCH = 3
MIN_V_BPORCH = 7  # standard CVT and RB1
FIXED_V_BPORCH = 6  # RB2 and RB3
C_PRIME = 30
M_PRIME = 300
RB_MIN_V_BLANK = 460  # µs
RB3_V_BLANK_RANGE = (300, 920)  # µs, after edid-decode's clamping
RB3_H_BLANK_RANGE = (80, 200)


def exact(value: float) -> Fraction:
    """Treat a rate like 59.94 as the decimal the user wrote, not its binary float."""
    return Fraction(repr(value))


def aspect_v_sync(width: int, height: int) -> int:
    """V-sync width from the aspect ratio, using exact integer matches like edid-decode."""
    if height * 4 // 3 == width:
        return 4
    if height * 16 // 9 == width:
        return 5
    if height * 16 // 10 == width:
        return 6
    if (height % 4 == 0 and height * 5 // 4 == width) or height * 15 // 9 == width:
        return 7
    return 10  # non-standard aspect ratio


def _rb3_v_blank(v_blank_us: int) -> int:
    lo, hi = RB3_V_BLANK_RANGE
    if v_blank_us < lo:
        return lo
    if lo + 140 < v_blank_us < RB_MIN_V_BLANK:
        return RB_MIN_V_BLANK
    return min(v_blank_us, hi)


def cvt_exact(
    width: int,
    height: int,
    refresh: float,
    rb: ReducedBlanking = ReducedBlanking.V1,
    *,
    interlaced: bool = False,
    margins: bool = False,
    video_optimized: bool = False,
    h_blank: int | None = None,
    v_blank_us: int | None = None,
    early_vsync: bool = False,
) -> CvtResult:
    """CVT timing for `width` x `height` at `refresh` Hz.

    `refresh` is the frame rate, or the field rate when `interlaced` (1080i60 → 60).
    `video_optimized` (RB2 only) multiplies the rate by 1000/1001 (60 → 59.94).
    `h_blank` (80-200), `v_blank_us` and `early_vsync` apply to RB3 only.
    """
    field_rate = exact(refresh)
    gran = 1 if rb is ReducedBlanking.V2 else CELL_GRAN
    h_pixels_rnd = width // gran * gran
    v_lines_rnd = height // 2 if interlaced else height
    h_margin = (
        math.floor(h_pixels_rnd * MARGIN_PERCENT / 100 / gran) * gran if margins else 0
    )
    v_margin = math.floor(MARGIN_PERCENT / 100 * v_lines_rnd) if margins else 0
    interlace = Fraction(1, 2) if interlaced else Fraction(0)
    total_active = h_pixels_rnd + 2 * h_margin

    v_sync = 8 if rb >= ReducedBlanking.V2 else aspect_v_sync(width, height)
    h_sync = 32

    if rb is ReducedBlanking.NONE:
        h_period_est = (
            (Fraction(1) / field_rate - Fraction(MIN_VSYNC_BP, 10**6))
            / (v_lines_rnd + 2 * v_margin + MIN_V_PORCH + interlace)
            * 10**6
        )  # µs
        v_sync_bp = max(
            math.floor(MIN_VSYNC_BP / h_period_est) + 1, v_sync + MIN_V_BPORCH
        )
        v_blank = v_sync_bp + MIN_V_PORCH
        duty = max(C_PRIME - M_PRIME * h_period_est / 1000, Fraction(20))
        blank = (
            math.floor(total_active * duty / (100 - duty) / (2 * CELL_GRAN))
            * 2
            * CELL_GRAN
        )
        total_pixels = total_active + blank
        h_sync = math.floor(total_pixels * Fraction(8, 100) / CELL_GRAN) * CELL_GRAN
        exact_clock = total_pixels / h_period_est
        step = Fraction(1, 4)
        pclk = math.floor(exact_clock / step) * step
        v_back = v_sync_bp - v_sync
    else:
        blank = 160 if rb is ReducedBlanking.V1 else 80
        if rb is ReducedBlanking.V3 and h_blank is not None:
            blank = min(max(h_blank & ~7, RB3_H_BLANK_RANGE[0]), RB3_H_BLANK_RANGE[1])
        min_v_blank_us = RB_MIN_V_BLANK
        if rb is ReducedBlanking.V3:
            min_v_blank_us = _rb3_v_blank(
                v_blank_us if v_blank_us is not None else RB_MIN_V_BLANK
            )
        v_front_min = 3 if rb is ReducedBlanking.V1 else 1
        h_period_est = (Fraction(10**6) / field_rate - min_v_blank_us) / (
            v_lines_rnd + 2 * v_margin
        )
        vbi_lines = math.floor(min_v_blank_us / h_period_est) + 1
        v_bporch = MIN_V_BPORCH if rb is ReducedBlanking.V1 else FIXED_V_BPORCH
        v_blank = max(vbi_lines, v_front_min + v_sync + v_bporch)
        total_v_lines = v_blank + v_lines_rnd + 2 * v_margin + interlace
        if rb is ReducedBlanking.V3 and early_vsync:
            v_bporch = vbi_lines // 2
            if v_blank - v_bporch - v_sync < v_front_min:
                v_bporch = v_blank - v_sync - v_front_min
        v_back = (
            v_blank - v_front_min - v_sync if rb is ReducedBlanking.V1 else v_bporch
        )
        multiplier = (
            Fraction(1000, 1001)
            if rb is ReducedBlanking.V2 and video_optimized
            else Fraction(1)
        )
        exact_clock = (
            field_rate * total_v_lines * (blank + total_active) * multiplier / 10**6
        )
        step = Fraction(1, 4) if rb is ReducedBlanking.V1 else Fraction(1, 100)
        if rb is ReducedBlanking.V3:
            pclk = math.ceil(exact_clock / step) * step
        else:
            pclk = math.floor(exact_clock / step) * step

    v_front = v_blank - v_back - v_sync
    h_front = 8 if rb >= ReducedBlanking.V2 else blank // 2 - h_sync
    if v_front > 63:
        # DTD front porch field is 6 bits; keep totals, move the rest to back porch.
        v_back += v_front - 63
        v_front = 63
    timing = Timing(
        float(pclk),
        width,
        h_front,
        h_sync,
        blank - h_front - h_sync,
        height,
        v_front,
        v_sync,
        v_back,
        h_sync_positive=rb is not ReducedBlanking.NONE,
        v_sync_positive=rb is ReducedBlanking.NONE,
        interlaced=interlaced,
        h_border=h_margin,
        v_border=v_margin,
    )
    return CvtResult(timing, exact_clock)


def cvt_rb(width: int, height: int, refresh: float) -> Timing:
    """VESA CVT reduced blanking, version 1."""
    return cvt_exact(width, height, refresh, ReducedBlanking.V1).timing


def cvt_rb2(width: int, height: int, refresh: float) -> Timing:
    """VESA CVT reduced blanking, version 2 (smaller blanking, lower pixel clock)."""
    return cvt_exact(width, height, refresh, ReducedBlanking.V2).timing
