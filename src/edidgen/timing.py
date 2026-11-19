"""VESA CVT reduced-blanking timing generators."""

import math

from edidgen.model import Timing


def cvt_rb(width: int, height: int, refresh: float) -> Timing:
    """VESA CVT reduced blanking, version 1."""
    h_blank, h_sync, h_front = 160, 32, 48
    v_front, min_v_back = 3, 6
    aspect = width / height
    v_sync = next(
        (
            s
            for a, s in ((4 / 3, 4), (16 / 9, 5), (16 / 10, 6), (5 / 4, 7), (15 / 9, 7))
            if abs(aspect - a) < 0.01
        ),
        10,
    )
    h_period_est = (1e6 / refresh - 460) / height
    vbi = max(int(460 / h_period_est) + 1, v_front + v_sync + min_v_back)
    h_total = width + h_blank
    pclk = math.floor(refresh * (height + vbi) * h_total / 1e6 / 0.25) * 0.25
    return Timing(
        pclk,
        width,
        h_front,
        h_sync,
        h_blank - h_front - h_sync,
        height,
        v_front,
        v_sync,
        vbi - v_front - v_sync,
        h_sync_positive=True,
        v_sync_positive=False,
    )


def cvt_rb2(width: int, height: int, refresh: float) -> Timing:
    """VESA CVT reduced blanking, version 2 (smaller blanking, lower pixel clock)."""
    h_blank, h_sync, h_front = 80, 32, 8
    v_sync, v_back = 8, 6
    h_period_est = (1e6 / refresh - 460) / height
    vbi = max(int(460 / h_period_est) + 1, 1 + v_sync + v_back)
    h_total = width + h_blank
    pclk = (
        math.floor(refresh * (height + vbi) * h_total / 1e4) / 100
    )  # DTD has 10 kHz units
    v_front = vbi - v_sync - v_back
    if (
        v_front > 63
    ):  # DTD front porch field is 6 bits; keep totals, move the rest to back porch
        v_back += v_front - 63
        v_front = 63
    return Timing(
        pclk,
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
