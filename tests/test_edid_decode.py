"""Cross-check against edid-decode (skipped when it isn't installed)."""

import math
import re
import shutil
import subprocess
from fractions import Fraction
from typing import TYPE_CHECKING

import pytest
from helpers import GOLDEN_BIN, build_text

from edidgen import cvt_rb, cvt_rb2


if TYPE_CHECKING:
    from pathlib import Path

EDID_DECODE = shutil.which("edid-decode")
pytestmark = pytest.mark.skipif(EDID_DECODE is None, reason="edid-decode not installed")

# Sizes cover every CVT aspect class (4:3, 16:9, 16:10, 5:4, 15:9) plus non-standard
# ones, and widths that aren't multiples of 8 (RB1 rounds those for the clock).
SIZES = [
    (640, 480), (800, 600), (1024, 768), (1280, 720), (1280, 768), (1280, 800),
    (1280, 1024), (1366, 768), (1440, 900), (1600, 900), (1680, 1050), (1920, 1080),
    (1920, 1200), (2048, 1536), (2400, 1080), (2560, 1080), (2560, 1440), (2560, 1600),
    (2736, 1824), (2880, 1800), (3024, 1964), (3440, 1440), (3840, 1600), (3840, 2160),
]  # fmt: skip
RATES = [23.976, 24, 25, 29.97, 30, 48, 50, 59.94, 60, 72, 75, 85, 90, 100, 110, 119.88,
         120, 144, 165, 170, 175, 180, 200, 240]  # fmt: skip
TIMING_RE = re.compile(
    r"([\d.]+) MHz.*?Hfront\s+(\d+) Hsync\s+(\d+) Hback\s+(\d+).*?"
    r"Vfront\s+(\d+) Vsync\s+(\d+) Vback\s+(\d+)",
    re.DOTALL,
)


def decode(*args: str) -> str:
    assert EDID_DECODE is not None
    return subprocess.run(
        [EDID_DECODE, *args], capture_output=True, text=True, check=False
    ).stdout


def reference(w: int, h: int, hz: float, rb: int) -> tuple[float, ...]:
    m = TIMING_RE.search(decode("--cvt", f"w={w},h={h},fps={hz},rb={rb}"))
    assert m, "unexpected edid-decode output"
    return (float(m[1]), *(int(g) for g in m.groups()[1:]))


def clock_matches(
    ours: float, expected: float, exact_mhz: Fraction, ref: float, ref_step: float
) -> bool:
    """Our clock equals the reference, or the reference lost a step to float error.

    edid-decode floors `rate * total_pixels / step` in double precision, so when the
    exact value is a whole number of steps it can come out one step low. edidgen
    uses exact fractions, so in that case it must equal the exact clock.
    """
    if math.isclose(ours, expected, abs_tol=1e-9):
        return True
    return Fraction(repr(ours)) == exact_mhz and math.isclose(
        ref, ours - ref_step, abs_tol=1e-9
    )


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_cvt_rb_matches_edid_decode(size: tuple[int, int]) -> None:
    w, h = size
    problems = []
    for hz in RATES:
        t = cvt_rb(w, h, hz)
        ref = reference(w, h, hz, rb=1)
        porches = (t.h_front, t.h_sync, t.h_back, t.v_front, t.v_sync, t.v_back)
        exact = Fraction(repr(hz)) * t.v_total * (w // 8 * 8 + 160) / 10**6
        if porches != ref[1:] or not clock_matches(
            t.pclk_mhz, ref[0], exact, ref[0], 0.25
        ):
            problems.append(f"@{hz}: {t.pclk_mhz} MHz {porches} vs {ref}")
    assert problems == []


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_cvt_rb2_matches_edid_decode(size: tuple[int, int]) -> None:
    w, h = size
    problems = []
    for hz in RATES:
        t = cvt_rb2(w, h, hz)
        ref = reference(w, h, hz, rb=2)
        # RB2 has 1 kHz steps; a DTD holds 10 kHz, so edidgen rounds down to that.
        expected = math.floor(ref[0] * 100 + 1e-6) / 100
        exact = Fraction(repr(hz)) * t.v_total * t.h_total / 10**6
        # The DTD front porch is 6 bits, so edidgen clamps it to 63 and keeps the total.
        same_porches = (t.h_front, t.h_sync, t.h_back, t.v_sync) == (
            ref[1],
            ref[2],
            ref[3],
            ref[5],
        ) and (t.v_front, t.v_front + t.v_back) == (min(ref[4], 63), ref[4] + ref[6])
        if not same_porches or not clock_matches(
            t.pclk_mhz, expected, exact, ref[0], 0.001
        ):
            problems.append(f"@{hz}: {t.pclk_mhz} MHz vs {ref}")
    assert problems == []


def failures(path: Path) -> str:
    out = decode("-c", str(path))
    return out.split("Failures:", 1)[1] if "Failures:" in out else ""


def test_golden_binary_has_only_the_known_conformance_note() -> None:
    # The HDMI VSDB technically wants EDID 1.3, but 10-bit color needs 1.4.
    lines = [ln.strip() for ln in failures(GOLDEN_BIN).splitlines() if ln.strip()]
    problems = [ln for ln in lines if not ln.startswith(("Block ", "EDID conformity"))]
    assert problems == [
        "Vendor-Specific Data Block (HDMI), OUI 00-0C-03: The HDMI Specification requires EDID 1.3 instead of 1.4."
    ]


def test_dp_edid_is_fully_conformant(tmp_path: Path) -> None:
    edid = build_text(
        'vics = []\n[display]\ninterface = "dp"\n[[modes]]\nwidth = 2560\nheight = 1440\nrefresh = 60\n'
    )
    path = tmp_path / "dp.bin"
    path.write_bytes(edid)
    assert "EDID conformity: PASS" in decode("-c", str(path))
