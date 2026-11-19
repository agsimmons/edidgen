"""CVT timing generators, checked against values from `edid-decode --cvt`."""

import pytest

from edidgen import Timing, cvt_rb, cvt_rb2
from edidgen.timing import ReducedBlanking, cvt_exact


# (w, h, hz) -> (pclk MHz, h_front, h_sync, h_back, v_front, v_sync, v_back)
CVT_RB_REFERENCE = {
    (2560, 1440, 60): (241.5, 48, 32, 80, 3, 5, 33),
    (2560, 1440, 120): (497.75, 48, 32, 80, 3, 5, 77),
    (1280, 800, 90): (108.0, 48, 32, 80, 3, 6, 26),
    (1920, 1200, 60): (154.0, 48, 32, 80, 3, 6, 26),
    (3440, 1440, 60): (319.75, 48, 32, 80, 3, 10, 28),
}


def porches(t: Timing) -> tuple[float, int, int, int, int, int, int]:
    return (t.pclk_mhz, t.h_front, t.h_sync, t.h_back, t.v_front, t.v_sync, t.v_back)


@pytest.mark.parametrize(("mode", "expected"), CVT_RB_REFERENCE.items())
def test_cvt_rb_matches_reference(
    mode: tuple[int, int, int], expected: tuple[float, ...]
) -> None:
    t = cvt_rb(*mode)
    assert porches(t) == expected
    assert (t.h_active, t.v_active) == mode[:2]
    assert t.h_sync_positive
    assert not t.v_sync_positive


def test_cvt_rb2_matches_reference_when_it_fits() -> None:
    t = cvt_rb2(2560, 1440, 60)
    assert porches(t) == (234.59, 8, 32, 40, 27, 8, 6)


@pytest.mark.parametrize(
    ("hz", "pclk", "spec_v_front"),
    [(120, 483.12, 71), (144, 586.58, 89)],
)
def test_cvt_rb2_clamps_front_porch_but_keeps_totals(
    hz: int, pclk: float, spec_v_front: int
) -> None:
    """The DTD front-porch field is 6 bits, so the excess moves to the back porch."""
    t = cvt_rb2(2560, 1440, hz)
    assert t.pclk_mhz == pclk
    assert t.v_front == 63
    assert t.v_sync == 8
    assert t.v_total == 1440 + spec_v_front + 8 + 6


def test_timing_derived_properties() -> None:
    t = Timing(
        594.0,
        3840,
        176,
        88,
        296,
        2160,
        8,
        10,
        72,
        h_sync_positive=True,
        v_sync_positive=True,
    )
    assert t.h_total == 4400
    assert t.v_total == 2250
    assert t.refresh == pytest.approx(60.0)
    assert t.hfreq_khz == pytest.approx(135.0)
    assert t.label() == "3840x2160@60.00"


@pytest.mark.parametrize(
    ("mode", "pclk"),
    [
        (
            (640, 480, 50),
            19.75,
        ),  # floats gave 19.5: the exact value is on a step boundary
        ((1024, 768, 30), 27.75),
        ((2560, 1080, 30), 89.75),
    ],
)
def test_cvt_rb_exact_step_boundaries(mode: tuple[int, int, int], pclk: float) -> None:
    assert cvt_rb(*mode).pclk_mhz == pclk


def test_cvt_rb_min_back_porch_is_7() -> None:
    t = cvt_rb(1280, 720, 30)  # low rate: the minimum vertical blank applies
    assert (t.v_front, t.v_sync, t.v_back) == (3, 5, 7)
    assert t.pclk_mhz == 31.75


def test_cvt_rb_non_standard_aspect_uses_10_line_vsync() -> None:
    # 1366x768 is close to 16:9 but not exactly, so CVT treats it as custom.
    t = cvt_rb(1366, 768, 60)
    assert t.v_sync == 10
    assert t.pclk_mhz == 72.0  # clock uses the width rounded down to 1360


@pytest.mark.parametrize(
    ("size", "v_sync"),
    [
        ((1024, 768), 4),
        ((1920, 1080), 5),
        ((1920, 1200), 6),
        ((1280, 1024), 7),
        ((1280, 768), 7),
    ],
)
def test_cvt_rb_aspect_v_sync(size: tuple[int, int], v_sync: int) -> None:
    assert cvt_rb(*size, 60).v_sync == v_sync


def test_cvt_rb2_exact_step_boundary() -> None:
    # Exactly 13.53 MHz; double arithmetic (and edid-decode) lands on 13.529.
    assert cvt_rb2(800, 600, 25).pclk_mhz == 13.53


# Reference values below come from `edid-decode --cvt` (see test_edid_decode for the sweep).


def test_cvt_standard_blanking() -> None:
    t = cvt_exact(1920, 1080, 60, ReducedBlanking.NONE).timing
    assert (t.pclk_mhz, t.h_front, t.h_sync, t.h_back) == (173.0, 128, 200, 328)
    assert (t.v_front, t.v_sync, t.v_back) == (3, 5, 32)
    assert (t.h_sync_positive, t.v_sync_positive) == (False, True)


def test_cvt_interlaced_with_margins() -> None:
    t = cvt_exact(
        1920, 1080, 60, ReducedBlanking.NONE, interlaced=True, margins=True
    ).timing
    assert t.interlaced
    assert (t.pclk_mhz, t.h_front, t.h_sync, t.h_back, t.h_border) == (
        87.5,
        64,
        200,
        264,
        32,
    )
    assert (t.v_front, t.v_sync, t.v_back, t.v_border) == (3, 5, 15, 9)
    assert t.v_active == 1080
    assert t.v_active_field == 540
    assert t.v_total == 540 + 3 + 5 + 15 + 18 + 0.5
    assert t.label() == "1920x1080i@59.90"


def test_cvt_rb2_video_optimized() -> None:
    result = cvt_exact(1920, 1080, 60, ReducedBlanking.V2, video_optimized=True)
    assert result.exact_clock_mhz * 1000 // 1 == 133186  # edid-decode: 133.186 MHz
    assert result.timing.pclk_mhz == 133.18  # rounded down to the DTD's 10 kHz


def test_cvt_rb3_options() -> None:
    t = cvt_exact(
        1920,
        1080,
        60,
        ReducedBlanking.V3,
        h_blank=120,
        v_blank_us=500,
        early_vsync=True,
    ).timing
    assert t.pclk_mhz == 136.36  # edid-decode: 136.354, RB3 rounds up
    assert (t.h_front, t.h_sync, t.h_back) == (8, 32, 80)
    assert (t.v_front, t.v_sync, t.v_back) == (9, 8, 17)


@pytest.mark.parametrize(
    ("asked", "used"), [(200, 300), (300, 300), (450, 460), (2000, 920)]
)
def test_cvt_rb3_v_blank_is_clamped_like_edid_decode(asked: int, used: int) -> None:
    def t(v: int) -> Timing:
        return cvt_exact(2560, 1440, 60, ReducedBlanking.V3, v_blank_us=v).timing

    assert t(asked) == t(used)


def test_cvt_rb3_h_blank_is_clamped_to_80_200_in_steps_of_8() -> None:
    def t(h: int) -> Timing:
        return cvt_exact(2560, 1440, 60, ReducedBlanking.V3, h_blank=h).timing

    assert t(70) == t(80)
    assert t(250) == t(200)
    assert t(127) == t(120)


def test_cvt_rb3_early_vsync_keeps_a_front_porch() -> None:
    # Short blanking: half the blanking lines as back porch would leave no front porch.
    t = cvt_exact(640, 480, 60, ReducedBlanking.V3, early_vsync=True).timing
    assert (t.v_front, t.v_sync, t.v_back) == (1, 8, 6)  # edid-decode agrees
