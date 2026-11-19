"""Cross-check against edid-decode (skipped when it isn't installed)."""

import re
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from helpers import GOLDEN_BIN, build_text

from edidgen import cvt_rb, cvt_rb2


if TYPE_CHECKING:
    from pathlib import Path

EDID_DECODE = shutil.which("edid-decode")
pytestmark = pytest.mark.skipif(EDID_DECODE is None, reason="edid-decode not installed")

MODES = [
    (1280, 720, 60),
    (1280, 800, 90),
    (1920, 1080, 120),
    (2560, 1440, 60),
    (3440, 1440, 100),
]
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


def reference(w: int, h: int, hz: int, rb: int) -> tuple[float, ...]:
    m = TIMING_RE.search(decode("--cvt", f"w={w},h={h},fps={hz},rb={rb}"))
    assert m, "unexpected edid-decode output"
    return (float(m[1]), *(int(g) for g in m.groups()[1:]))


@pytest.mark.parametrize("mode", MODES)
def test_cvt_rb_matches_edid_decode(mode: tuple[int, int, int]) -> None:
    t = cvt_rb(*mode)
    ref = reference(*mode, rb=1)
    assert t.pclk_mhz == pytest.approx(ref[0], abs=0.01)
    assert (t.h_front, t.h_sync, t.h_back, t.v_front, t.v_sync, t.v_back) == ref[1:]


@pytest.mark.parametrize("mode", MODES)
def test_cvt_rb2_totals_match_edid_decode(mode: tuple[int, int, int]) -> None:
    t = cvt_rb2(*mode)
    ref = reference(*mode, rb=2)
    assert t.pclk_mhz == pytest.approx(
        ref[0], abs=0.01
    )  # RB2 has 1 kHz steps, DTD has 10 kHz
    assert (t.h_front, t.h_sync, t.h_back, t.v_sync) == (ref[1], ref[2], ref[3], ref[5])
    assert t.v_front + t.v_back == ref[4] + ref[6]


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
