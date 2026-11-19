"""CVT timing generators, checked against values from `edid-decode --cvt`."""

import pytest

from edidgen import Timing, cvt_rb, cvt_rb2


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
