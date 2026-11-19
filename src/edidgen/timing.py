"""VESA CVT reduced-blanking timing generators.

Follows the same rules as edid-decode's `calc_cvt_mode`, but in exact rational
arithmetic: CVT rounds the pixel clock *down* to a fixed step, and with floats a
value landing exactly on a step can come out just below it and lose a whole step.
"""

import math
from fractions import Fraction

from edidgen.model import Timing


RB_MIN_V_BLANK = Fraction(460)  # µs
CELL_GRAN = 8  # RB1 rounds the active width down to this for the clock calculation


def _exact(value: float) -> Fraction:
    """Treat a refresh rate like 59.94 as the decimal the user wrote, not its binary float."""
    return Fraction(repr(value))


def _aspect_v_sync(width: int, height: int) -> int:
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


def _vbi_lines(height: int, refresh: Fraction) -> int:
    h_period_est = (Fraction(10**6) / refresh - RB_MIN_V_BLANK) / height
    return math.floor(RB_MIN_V_BLANK / h_period_est) + 1


def cvt_rb(width: int, height: int, refresh: float) -> Timing:
    """VESA CVT reduced blanking, version 1."""
    h_blank, h_sync, h_front = 160, 32, 48
    v_front, min_v_back = 3, 7
    v_sync = _aspect_v_sync(width, height)
    rate = _exact(refresh)
    v_blank = max(_vbi_lines(height, rate), v_front + v_sync + min_v_back)
    # The clock uses the active width rounded down to the 8-pixel cell size.
    clock_pixels = width // CELL_GRAN * CELL_GRAN + h_blank
    step = Fraction(1, 4)  # 0.25 MHz
    pclk = math.floor(rate * (height + v_blank) * clock_pixels / 10**6 / step) * step
    return Timing(
        float(pclk),
        width,
        h_front,
        h_sync,
        h_blank - h_front - h_sync,
        height,
        v_front,
        v_sync,
        v_blank - v_front - v_sync,
        h_sync_positive=True,
        v_sync_positive=False,
    )


def cvt_rb2(width: int, height: int, refresh: float) -> Timing:
    """VESA CVT reduced blanking, version 2 (smaller blanking, lower pixel clock)."""
    h_blank, h_sync, h_front = 80, 32, 8
    v_sync, v_back = 8, 6
    rate = _exact(refresh)
    v_blank = max(_vbi_lines(height, rate), 1 + v_sync + v_back)
    # RB2 specifies 1 kHz clock steps; a DTD stores 10 kHz, so round down to that.
    step = Fraction(1, 100)
    pclk = (
        math.floor(rate * (height + v_blank) * (width + h_blank) / 10**6 / step) * step
    )
    v_front = v_blank - v_sync - v_back
    if v_front > 63:
        # DTD front porch field is 6 bits; keep totals, move the rest to back porch.
        v_back += v_front - 63
        v_front = 63
    return Timing(
        float(pclk),
        width,
        h_front,
        h_sync,
        h_blank - h_front - h_sync,
        height,
        v_front,
        v_sync,
        v_back,
        h_sync_positive=True,
        v_sync_positive=False,
    )
