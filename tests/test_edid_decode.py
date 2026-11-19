"""Cross-check against edid-decode (skipped when it isn't installed).

- CVT: every generator variant against `edid-decode --cvt`.
- DTD round trip: timings encoded by edidgen decode back to the same values.
- Conformance: `edid-decode -c` on EDIDs built from a range of configs.
"""

import dataclasses
import itertools
import math
import re
import shutil
import subprocess
from fractions import Fraction
from typing import TYPE_CHECKING, TypedDict

import pytest
from helpers import GOLDEN_BIN, MINIMAL, build_text, parse_text

from edidgen import Timing, build_edid
from edidgen.encode import dtd_limit_errors
from edidgen.timing import ReducedBlanking, cvt_exact


if TYPE_CHECKING:
    from pathlib import Path

EDID_DECODE = shutil.which("edid-decode")
pytestmark = pytest.mark.skipif(EDID_DECODE is None, reason="edid-decode not installed")

# Sizes cover every CVT aspect class (4:3, 16:9, 16:10, 5:4, 15:9) plus non-standard
# ones, and widths that aren't multiples of 8 (CVT rounds those for the clock).
SIZES = [
    (640, 480), (800, 600), (1024, 768), (1280, 720), (1280, 768), (1280, 800),
    (1280, 1024), (1366, 768), (1440, 900), (1680, 1050), (1920, 1080), (1920, 1200),
    (2560, 1080), (2560, 1440), (2736, 1824), (3440, 1440), (3840, 2160),
]  # fmt: skip
RATES = [24, 25, 29.97, 30, 50, 59.94, 60, 75, 100, 119.88, 120, 144, 165, 240]


class Options(TypedDict, total=False):
    interlaced: bool
    margins: bool
    video_optimized: bool
    h_blank: int
    v_blank_us: int
    early_vsync: bool


COMMON: list[Options] = [
    {},
    {"interlaced": True},
    {"margins": True},
    {"interlaced": True, "margins": True},
]
VARIANTS: list[tuple[ReducedBlanking, Options]] = [
    *((rb, o) for rb in ReducedBlanking for o in COMMON),
    (ReducedBlanking.V2, {"video_optimized": True}),
    (ReducedBlanking.V2, {"video_optimized": True, "interlaced": True}),
    (ReducedBlanking.V3, {"h_blank": 160}),
    (ReducedBlanking.V3, {"h_blank": 120}),
    (ReducedBlanking.V3, {"v_blank_us": 600}),
    (ReducedBlanking.V3, {"early_vsync": True}),
    (ReducedBlanking.V3, {"h_blank": 200, "v_blank_us": 700, "early_vsync": True}),
]

CVT_RE = re.compile(r"CVT:\s+\d+x\d+(i?)\s.*?([\d.]+) MHz")
H_RE = re.compile(
    r"Hfront\s+(\d+) Hsync\s+(\d+) Hback\s+(-?\d+) Hpol ([PN])(?: Hborder (\d+))?"
)
V_RE = re.compile(
    r"Vfront\s+(\d+) Vsync\s+(\d+) Vback\s+(-?\d+) Vpol ([PN])(?: Vborder (\d+))?"
)
DTD_RE = re.compile(r"DTD\s+\d+:\s+(\d+)x(\d+)(i?)\s.*?([\d.]+) MHz")


def decode(*args: str) -> str:
    assert EDID_DECODE is not None
    return subprocess.run(
        [EDID_DECODE, *args], capture_output=True, text=True, check=False
    ).stdout


def cvt_args(w: int, h: int, hz: float, rb: ReducedBlanking, opts: Options) -> str:
    args = [f"w={w}", f"h={h}", f"fps={hz}", f"rb={int(rb)}"]
    # edid-decode takes interlaced/alt as `name=1`; a bare flag sets them to 0.
    if opts.get("interlaced"):
        args.append("interlaced=1")
    if opts.get("margins"):
        args.append("overscan")
    if opts.get("video_optimized"):
        args.append("alt=1")
    if "h_blank" in opts:
        args.append(f"hblank={opts['h_blank']}")
    if "v_blank_us" in opts:
        args.append(f"vblank={opts['v_blank_us']}")
    if opts.get("early_vsync"):
        args.append("early-vsync")
    return ",".join(args)


def timing_from_text(text: str, w: int, h: int, interlaced: bool, mhz: float) -> Timing:
    """Build a Timing from edid-decode's Hfront/Vfront lines (first ones in `text`)."""
    hl, vl = H_RE.search(text), V_RE.search(text)
    assert hl, text
    assert vl, text
    return Timing(
        mhz,
        w,
        int(hl[1]),
        int(hl[2]),
        int(hl[3]),
        h,
        int(vl[1]),
        int(vl[2]),
        int(vl[3]),
        h_sync_positive=hl[4] == "P",
        v_sync_positive=vl[4] == "P",
        interlaced=interlaced,
        h_border=int(hl[5] or 0),
        v_border=int(vl[5] or 0),
    )


def cvt_problem(
    w: int, h: int, hz: float, rb: ReducedBlanking, opts: Options
) -> str | None:
    out = decode("--cvt", cvt_args(w, h, hz, rb, opts))
    m = CVT_RE.search(out)
    assert m, out
    ref = timing_from_text(out, w, h, m[1] == "i", float(m[2]))
    result = cvt_exact(w, h, hz, rb, **opts)
    t = result.timing
    # edidgen clamps the 6-bit DTD front porch to 63, keeping the total.
    ref_v_front = min(ref.v_front, 63)
    ref = dataclasses.replace(
        ref, v_front=ref_v_front, v_back=ref.v_back + ref.v_front - ref_v_front
    )
    if dataclasses.replace(t, pclk_mhz=0) != dataclasses.replace(ref, pclk_mhz=0):
        return f"timing {t} vs {ref}"

    # edid-decode's clock steps; edidgen then rounds to the DTD's 10 kHz the same way.
    ref_step = Fraction(1, 4) if rb <= ReducedBlanking.V1 else Fraction(1, 1000)
    dtd_step = Fraction(1, 4) if rb <= ReducedBlanking.V1 else Fraction(1, 100)
    ref_mhz = Fraction(m[2])
    to_dtd = math.ceil if rb is ReducedBlanking.V3 else math.floor
    if Fraction(repr(t.pclk_mhz)) == to_dtd(ref_mhz / dtd_step) * dtd_step:
        return None
    # edid-decode rounds in double precision, so when the exact clock is a whole
    # number of steps it can land one step off. edidgen uses exact fractions.
    exact = result.exact_clock_mhz
    if (exact / ref_step).denominator == 1 and abs(ref_mhz - exact) == ref_step:
        return None
    return f"clock {t.pclk_mhz} vs edid-decode {m[2]} (exact {float(exact)})"


@pytest.mark.parametrize(
    ("rb", "opts"),
    VARIANTS,
    ids=[f"rb{int(rb)}-{'-'.join(o) or 'plain'}" for rb, o in VARIANTS],
)
def test_cvt_matches_edid_decode(rb: ReducedBlanking, opts: Options) -> None:
    problems = [
        f"{w}x{h}@{hz}: {msg}"
        for (w, h), hz in itertools.product(SIZES, RATES)
        if (msg := cvt_problem(w, h, hz, rb, opts))
    ]
    assert problems == []


# --- DTD round trip ---------------------------------------------------------------


def edge_timings() -> list[Timing]:
    """Explicit timings that exercise every bit of the DTD's packed fields."""
    base = Timing(100.0, 1920, 88, 44, 148, 1080, 4, 5, 36, True, True)
    return [
        dataclasses.replace(base, h_active=4095, v_active=4095, pclk_mhz=655.35),
        dataclasses.replace(base, h_front=1023, h_sync=1023, h_back=2049),
        dataclasses.replace(base, v_front=63, v_sync=63, v_back=3969),
        dataclasses.replace(base, h_border=255, v_border=255, h_back=1),
        dataclasses.replace(base, interlaced=True, v_active=4094),
        dataclasses.replace(base, h_sync_positive=False, v_sync_positive=False),
        dataclasses.replace(base, pclk_mhz=10.01, h_active=256, v_active=1),
    ]


def round_trip_timings() -> list[Timing]:
    sizes = [(640, 480), (1366, 768), (1920, 1080), (2560, 1600), (3840, 2160)]
    timings = [
        cvt_exact(w, h, hz, rb, **opts).timing
        for (w, h), hz, (rb, opts) in itertools.product(sizes, [30, 60, 120], VARIANTS)
    ]
    return [t for t in timings + edge_timings() if not dtd_limit_errors(t)]


def decoded_dtds(edid: bytes, tmp_path: Path) -> list[Timing]:
    path = tmp_path / "edid.bin"
    path.write_bytes(edid)
    out = decode(str(path))
    starts = list(DTD_RE.finditer(out))
    return [
        timing_from_text(
            out[m.start() :], int(m[1]), int(m[2]), m[3] == "i", float(m[4])
        )
        for m in starts
    ]


def test_dtd_round_trip(tmp_path: Path) -> None:
    cfg, diag = parse_text(
        'vics = []\n[display]\ninterface = "dp"\n' + MINIMAL.split("\n", 1)[1]
    )
    assert cfg is not None, diag.errors
    timings = round_trip_timings()
    per_edid = 8  # 2 in the base block, 6 in the CTA block with only a VCDB
    problems = []
    for i in range(0, len(timings), per_edid):
        batch = tuple(timings[i : i + per_edid])
        edid = build_edid(dataclasses.replace(cfg, modes=batch))
        decoded = decoded_dtds(edid, tmp_path)
        assert len(decoded) == len(batch)
        for want, got in zip(batch, decoded, strict=True):
            # The DTD stores 10 kHz units, and the source clock is already a multiple.
            if dataclasses.replace(want, pclk_mhz=round(want.pclk_mhz, 2)) != got:
                problems.append(f"{want} decoded as {got}")
    assert problems == []
    assert len(timings) > 300


# --- Conformance --------------------------------------------------------------------

KNOWN_HDMI_14_FAILURE = (
    "Vendor-Specific Data Block (HDMI), OUI 00-0C-03: "
    "The HDMI Specification requires EDID 1.3 instead of 1.4."
)
BORDER_WARNING = "The use of non-zero borders in a DTD is not recommended."


def mode(w: int, h: int, hz: float, timing: str = "cvt-rb", extra: str = "") -> str:
    return f'[[modes]]\nwidth = {w}\nheight = {h}\nrefresh = {hz}\ntiming = "{timing}"\n{extra}'


DP = 'vics = []\n[display]\ninterface = "dp"\n'
CONFIGS = {
    "dp-cvt": DP + mode(1920, 1080, 60, "cvt"),
    "dp-interlaced": DP + mode(1920, 1080, 60, "cvt", "interlaced = true\n"),
    "dp-rb3": DP
    + mode(2560, 1440, 120, "cvt-rb3", "h_blank = 160\nearly_vsync = true\n"),
    "dp-rb2-video": DP + mode(1920, 1080, 60, "cvt-rb2", "video_optimized = true\n"),
    "dp-mixed-aspects": DP
    + "".join(
        mode(w, h, hz, kind)
        for w, h, hz, kind in [
            (1280, 720, 60, "cvt"),
            (1280, 800, 90, "cvt-rb"),
            (1920, 1080, 120, "cvt-rb2"),
            (1920, 1200, 60, "cvt"),
            (2560, 1080, 75, "cvt-rb"),
            (1366, 768, 60, "cvt-rb"),
            (1024, 768, 60, "cvt"),
            (800, 600, 75, "cvt"),
        ]
    ),
    "hdmi-vics": "vics = [16, 4, 1]\n[hdmi]\nmax_tmds_mhz = 600\n"
    + mode(2560, 1440, 120),
    "hdmi-hdr": "vics = [16]\n[display]\nbit_depth = 10\n[hdmi]\nmax_tmds_mhz = 600\n"
    "deep_color = [30]\n[hdr]\nenabled = true\nmax_luminance_nits = 1000\n"
    + mode(1920, 1080, 60),
}
# Margins are stored as DTD borders, which edid-decode always discourages.
WITH_BORDERS = {"dp-margins": DP + mode(1920, 1080, 60, "cvt-rb", "margins = true\n")}


def findings(text: str, tmp_path: Path) -> list[str]:
    path = tmp_path / "edid.bin"
    path.write_bytes(build_text(text))
    out = decode("-c", str(path))
    report = out.split("\nWarnings:", 1)[-1] if "\nWarnings:" in out else ""
    report = report or (out.split("\nFailures:", 1)[-1] if "\nFailures:" in out else "")
    lines = [ln.strip() for ln in report.splitlines() if ln.strip()]
    return [
        ln
        for ln in lines
        if not ln.startswith(
            ("Block ", "EDID conformity", "Failures:", "Warnings:", "EDID:")
        )
        and "and the first DTD are not identical"
        not in ln  # VICs needn't repeat the DTD
    ]


@pytest.mark.parametrize("name", [*CONFIGS, *WITH_BORDERS])
def test_conformance(name: str, tmp_path: Path) -> None:
    text = CONFIGS.get(name) or WITH_BORDERS[name]
    allowed = {KNOWN_HDMI_14_FAILURE} | (
        {BORDER_WARNING} if name in WITH_BORDERS else set()
    )
    problems = [
        ln for ln in findings(text, tmp_path) if not ln.endswith(tuple(allowed))
    ]
    assert problems == []


def test_golden_binary_has_only_the_known_conformance_note() -> None:
    # The HDMI VSDB technically wants EDID 1.3, but 10-bit color needs 1.4.
    out = decode("-c", str(GOLDEN_BIN))
    failures = out.split("Failures:", 1)[1] if "Failures:" in out else ""
    lines = [ln.strip() for ln in failures.splitlines() if ln.strip()]
    problems = [ln for ln in lines if not ln.startswith(("Block ", "EDID conformity"))]
    assert problems == [KNOWN_HDMI_14_FAILURE]
