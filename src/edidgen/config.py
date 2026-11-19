"""Parse and validate a TOML config into a `Config`."""

from typing import Final

from edidgen.encode import cta_data_blocks, dtd_limit_errors, dtd_violations
from edidgen.model import Config, Display, Hdmi, Hdr, RangeLimits, Timing, TimingKind
from edidgen.reader import Diagnostics, Reader, Table
from edidgen.tables import (
    BIT_DEPTHS,
    DEEP_COLOR_BITS,
    DTD_MAX_PCLK_MHZ,
    INTERFACES,
    VICS,
)
from edidgen.timing import ReducedBlanking, cvt_exact


EXPLICIT_KEYS: Final = (
    "pixel_clock_mhz",
    "h_front",
    "h_sync",
    "h_back",
    "v_front",
    "v_sync",
    "v_back",
)
CVT_KINDS: Final = {
    TimingKind.CVT: ReducedBlanking.NONE,
    TimingKind.CVT_RB: ReducedBlanking.V1,
    TimingKind.CVT_RB2: ReducedBlanking.V2,
    TimingKind.CVT_RB3: ReducedBlanking.V3,
}
EXPLICIT: Final = frozenset({TimingKind.EXPLICIT})
# Mode options that only make sense for some timing kinds.
OPTION_KINDS: Final[dict[str, frozenset[TimingKind]]] = {
    **dict.fromkeys(
        (*EXPLICIT_KEYS, "h_sync_positive", "v_sync_positive", "h_border", "v_border"),
        EXPLICIT,
    ),
    "refresh": frozenset(CVT_KINDS),
    "margins": frozenset(CVT_KINDS),
    "video_optimized": frozenset({TimingKind.CVT_RB2}),
    "h_blank": frozenset({TimingKind.CVT_RB3}),
    "v_blank_us": frozenset({TimingKind.CVT_RB3}),
    "early_vsync": frozenset({TimingKind.CVT_RB3}),
}


def _check_option_kinds(r: Reader, kind: TimingKind) -> None:
    for key, kinds in OPTION_KINDS.items():
        if r.has(key) and kind not in kinds:
            allowed = " or ".join(f'"{k.value}"' for k in TimingKind if k in kinds)
            if key == "refresh":
                msg = "not allowed with explicit timings (it is derived from pixel_clock_mhz and the totals)"
            else:
                msg = f"only allowed with timing = {allowed} (timing is {kind.value!r})"
            r.diag.error(r.where(key), msg)
            r.seen.add(key)


def _parse_explicit(r: Reader, width: int, height: int, *, interlaced: bool) -> Timing:
    for k in EXPLICIT_KEYS:
        if not r.has(k):
            r.diag.error(r.where(k), 'required for timing = "explicit"')
    return Timing(
        # 0.01 MHz is the smallest a DTD can hold; below 10 MHz is a violation.
        pclk_mhz=r.number("pixel_clock_mhz", 0.0, 0.01, DTD_MAX_PCLK_MHZ),
        h_active=width,
        h_front=r.integer("h_front", 0, 0, 1023),
        h_sync=r.integer("h_sync", 0, 1, 1023),
        h_back=r.integer("h_back", 0, 0, 4095),
        v_active=height,
        v_front=r.integer("v_front", 0, 0, 63),
        v_sync=r.integer("v_sync", 0, 1, 63),
        v_back=r.integer("v_back", 0, 0, 4095),
        h_sync_positive=r.boolean("h_sync_positive", default=True),
        v_sync_positive=r.boolean("v_sync_positive", default=True),
        interlaced=interlaced,
        h_border=r.integer("h_border", 0, 0, 255),
        v_border=r.integer("v_border", 0, 0, 255),
    )


def _parse_cvt(
    r: Reader,
    kind: TimingKind,
    width: int,
    height: int,
    *,
    interlaced: bool,
    n_errors: int,
) -> Timing | None:
    """Read every CVT option, then compute the timing if the mode had no errors so far."""
    if not r.has("refresh"):
        r.diag.error(r.where("refresh"), "required")
    refresh = r.number("refresh", 60.0, 1.0, 1000.0)
    margins = r.boolean("margins", default=False)
    video_optimized = r.boolean("video_optimized", default=False)
    early_vsync = r.boolean("early_vsync", default=False)
    h_blank = r.integer("h_blank", 80, 80, 200)
    if h_blank % 8:
        r.diag.error(r.where("h_blank"), f"must be a multiple of 8 (got {h_blank})")
    # edid-decode's --cvt raises anything below 460 µs to 460, so that is the floor here.
    v_blank_us = r.integer("v_blank_us", 460, 460, 920)
    if v_blank_us > 705:
        r.diag.warn(
            r.where("v_blank_us"), "above 705 may not be supported by RB3 sources"
        )
    if len(r.diag.errors) != n_errors:
        return None
    return cvt_exact(
        width,
        height,
        refresh,
        CVT_KINDS[kind],
        interlaced=interlaced,
        margins=margins,
        video_optimized=video_optimized,
        h_blank=h_blank,
        v_blank_us=v_blank_us,
        early_vsync=early_vsync,
    ).timing


def parse_mode(r: Reader) -> Timing | None:
    n_errors = len(r.diag.errors)
    width = r.integer("width", 0, 1, 4095)
    height = r.integer("height", 0, 1, 4095)
    if not r.has("width"):
        r.diag.error(r.where("width"), "required")
    if not r.has("height"):
        r.diag.error(r.where("height"), "required")
    default_kind = "explicit" if any(r.has(k) for k in EXPLICIT_KEYS) else "cvt-rb"
    kind = TimingKind(r.choice("timing", default_kind, [k.value for k in TimingKind]))
    interlaced = r.boolean("interlaced", default=False)
    _check_option_kinds(r, kind)

    timing: Timing | None
    if kind is TimingKind.EXPLICIT:
        timing = _parse_explicit(r, width, height, interlaced=interlaced)
    else:
        timing = _parse_cvt(
            r, kind, width, height, interlaced=interlaced, n_errors=n_errors
        )
    r.finish()
    if len(r.diag.errors) != n_errors or timing is None:
        return None

    limits = dtd_limit_errors(timing)
    for msg in limits:
        r.diag.error(r.path, msg)
    for msg in dtd_violations(timing):
        r.diag.violation(r.path, msg)
    return None if len(r.diag.errors) != n_errors else timing


def parse_config(data: Table, diag: Diagnostics) -> Config | None:
    root = Reader(data, "", diag)
    output = root.string("output", "") or None

    d = root.table_("display")
    manufacturer = d.string("manufacturer", "XXX")
    if not (
        len(manufacturer) == 3
        and manufacturer.isascii()
        and manufacturer.isupper()
        and manufacturer.isalpha()
    ):
        diag.error(
            d.where("manufacturer"),
            f"must be 3 uppercase letters A-Z (got {manufacturer!r})",
        )
    name = d.string("name", "VirtDisplay")
    if not name or len(name) > 13 or not all(0x20 <= ord(c) < 0x7F for c in name):
        diag.error(
            d.where("name"), f"must be 1-13 printable ASCII characters (got {name!r})"
        )
    bit_depth = d.integer("bit_depth", 8, 6, 16)
    if bit_depth not in BIT_DEPTHS:
        diag.error(
            d.where("bit_depth"),
            f"must be one of {sorted(BIT_DEPTHS)} (got {bit_depth})",
        )
    size = d.int_pair("size_cm", 1, 255) or (60, 34)
    display = Display(
        name=name,
        manufacturer=manufacturer,
        product_code=d.integer("product_code", 0, 0, 0xFFFF),
        serial=d.integer("serial", 0, 0, 0xFFFFFFFF),
        week=d.integer("week", 1, 0, 54),
        year=d.integer("year", 2026, 1990, 2245),
        size_cm=size,
        gamma=d.number("gamma", 2.2, 1.0, 3.54),
        bit_depth=bit_depth,
        interface=d.choice("interface", "hdmi-a", list(INTERFACES)),
    )
    d.finish()

    h = root.table_("hdmi")
    is_hdmi = display.interface.startswith("hdmi")
    hdmi = Hdmi(
        enabled=h.boolean("enabled", default=is_hdmi),
        max_tmds_mhz=h.integer("max_tmds_mhz", 340, 25, 600),
        deep_color=tuple(h.int_list("deep_color", 30, 48) or ()),
        y444_deep_color=h.boolean("y444_deep_color", default=True),
        scdc=h.boolean("scdc", default=True),
    )
    for i, dc in enumerate(hdmi.deep_color):
        if dc not in DEEP_COLOR_BITS:
            diag.error(
                f"{h.where('deep_color')}[{i}]",
                f"must be one of {sorted(DEEP_COLOR_BITS)} (got {dc})",
            )
    if hdmi.enabled and not is_hdmi:
        diag.warn(
            h.path,
            f"HDMI data blocks enabled but display.interface is {display.interface!r}",
        )
    if hdmi.max_tmds_mhz % 5:
        diag.error(h.where("max_tmds_mhz"), "must be a multiple of 5")
    h.finish()

    x = root.table_("hdr")
    hdr = Hdr(
        enabled=x.boolean("enabled", default=False),
        bt2020=x.boolean("bt2020", default=True),
        max_luminance_nits=x.number("max_luminance_nits", 0.0, 0.0, 12000.0),
        max_frame_avg_nits=x.number("max_frame_avg_nits", 0.0, 0.0, 12000.0),
    )
    for key in ("max_luminance_nits", "max_frame_avg_nits"):
        nits: float = getattr(hdr, key)
        if 0 < nits < 50:
            diag.error(x.where(key), "must be 0 (unspecified) or at least 50")
    if hdr.max_frame_avg_nits > hdr.max_luminance_nits > 0:
        diag.violation(
            x.where("max_frame_avg_nits"), "cannot exceed max_luminance_nits"
        )
    x.finish()

    g = root.table_("range")
    range_limits = RangeLimits(
        vrefresh_hz=g.int_pair("vrefresh_hz", 1, 255),
        hfreq_khz=g.int_pair("hfreq_khz", 1, 255),
        max_pixel_clock_mhz=g.integer("max_pixel_clock_mhz", 0, 10, 2550) or None,
    )
    for key, pair in (
        ("vrefresh_hz", range_limits.vrefresh_hz),
        ("hfreq_khz", range_limits.hfreq_khz),
    ):
        if pair and pair[0] > pair[1]:
            diag.violation(g.where(key), f"min {pair[0]} is greater than max {pair[1]}")
    g.finish()

    mode_readers = root.table_list("modes")
    # A non-array `modes` was already reported by table_list.
    if not mode_readers and data.get("modes", []) == []:
        diag.error(
            "modes",
            "at least one [[modes]] entry is required (the first is the preferred mode)",
        )
    parsed = [parse_mode(m) for m in mode_readers]
    modes = tuple(t for t in parsed if t is not None)

    vics = root.int_list("vics", 1, 219) or []
    for i, v in enumerate(vics):
        if v not in VICS:
            diag.error(
                f"vics[{i}]",
                f"VIC {v} is not in the supported table ({', '.join(map(str, sorted(VICS)))})",
            )
    native_vic = root.integer("native_vic", 0, 1, 64) or None
    if native_vic is not None and native_vic not in vics:
        diag.error("native_vic", f"VIC {native_vic} must also be listed in vics")
    root.finish()

    if diag.errors:
        return None
    cfg = Config(
        output, display, range_limits, hdmi, hdr, modes, tuple(vics), native_vic
    )
    cross_check(cfg, diag)
    return None if diag.errors else cfg


def cross_check(cfg: Config, diag: Diagnostics) -> None:
    """Checks that involve more than one option.

    Only called once every field parsed cleanly, so `cfg.modes` is complete and non-empty.
    """
    seen: dict[tuple[int, int, int], str] = {}
    for i, t in enumerate(cfg.modes):
        key = (t.h_active, t.v_active, round(t.refresh))
        where = f"modes[{i}]"
        if key in seen:
            diag.warn(where, f"{t.label()} duplicates {seen[key]}")
        seen.setdefault(key, where)
        if cfg.hdmi.enabled and t.pclk_mhz > cfg.hdmi.max_tmds_mhz:
            diag.violation(
                where,
                f"{t.label()} needs {t.pclk_mhz:.2f} MHz but hdmi.max_tmds_mhz is "
                f"{cfg.hdmi.max_tmds_mhz}; the driver would drop this mode",
            )
        if t.pclk_mhz > 340 and cfg.hdmi.enabled and not cfg.hdmi.scdc:
            diag.warn(
                where,
                f"{t.label()} is above 340 MHz; HDMI 2.0 rates usually need hdmi.scdc = true",
            )

    for i, v in enumerate(cfg.vics):
        vic = VICS[v]
        if cfg.hdmi.enabled and vic.pclk_mhz > cfg.hdmi.max_tmds_mhz:
            diag.violation(
                f"vics[{i}]",
                f"VIC {v} ({vic.width}x{vic.height}@{vic.refresh:g}) needs "
                f"{vic.pclk_mhz:g} MHz but hdmi.max_tmds_mhz is {cfg.hdmi.max_tmds_mhz}",
            )
    if len(set(cfg.vics)) != len(cfg.vics):
        diag.warn("vics", "contains duplicates")

    r = cfg.range_limits
    if r.vrefresh_hz:
        for i, t in enumerate(cfg.modes):
            if not r.vrefresh_hz[0] <= round(t.refresh) <= r.vrefresh_hz[1]:
                diag.warn(
                    f"modes[{i}]",
                    f"{t.label()} is outside range.vrefresh_hz {list(r.vrefresh_hz)}",
                )
    if r.hfreq_khz:
        for i, t in enumerate(cfg.modes):
            if not r.hfreq_khz[0] <= t.hfreq_khz <= r.hfreq_khz[1] + 0.999:
                diag.warn(
                    f"modes[{i}]",
                    f"{t.label()} line rate {t.hfreq_khz:.1f} kHz is outside "
                    f"range.hfreq_khz {list(r.hfreq_khz)}",
                )
    if r.max_pixel_clock_mhz:
        for i, t in enumerate(cfg.modes):
            if t.pclk_mhz > r.max_pixel_clock_mhz:
                diag.warn(
                    f"modes[{i}]",
                    f"{t.label()} pixel clock {t.pclk_mhz:.2f} MHz is above "
                    f"range.max_pixel_clock_mhz {r.max_pixel_clock_mhz}",
                )

    if cfg.hdmi.deep_color and cfg.display.bit_depth < 10:
        diag.warn(
            "hdmi.deep_color", "deep color advertised but display.bit_depth is below 10"
        )
    if cfg.hdr.enabled and cfg.display.bit_depth < 10:
        diag.warn("hdr.enabled", "HDR usually needs display.bit_depth >= 10")

    # Space in the CTA block: 4 header bytes + data blocks + 18 bytes per DTD.
    extra_dtds = max(0, len(cfg.modes) - 2)
    room = (127 - 4 - len(cta_data_blocks(cfg))) // 18
    if extra_dtds > room:
        diag.error(
            "modes",
            f"{len(cfg.modes)} modes given but only {2 + room} fit (2 in the base "
            f"block, {room} in the CTA block with the current data blocks). Remove modes, "
            "or move standard modes to `vics`",
        )
