"""Config validation: every error is collected and points at the right key."""

from collections.abc import Callable

import pytest
from helpers import EXAMPLE_TOML, MINIMAL, errors_of, parse_text, with_tables

from edidgen import Timing, TimingKind


def test_minimal_config_is_valid() -> None:
    cfg, diag = parse_text(MINIMAL)
    assert cfg is not None
    assert diag.errors == []
    assert len(cfg.modes) == 1
    assert cfg.vics == (16,)


def test_example_config_is_valid_without_warnings() -> None:
    cfg, diag = parse_text(EXAMPLE_TOML.read_text())
    assert cfg is not None
    assert diag.warnings == []


def test_defaults() -> None:
    cfg, _ = parse_text(MINIMAL)
    assert cfg is not None
    assert cfg.display.interface == "hdmi-a"
    assert cfg.hdmi.enabled  # on by default for HDMI interfaces
    assert not cfg.hdr.enabled
    assert cfg.output is None


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        (
            '[display]\nmanufacturer = "vd"',
            "display.manufacturer: must be 3 uppercase letters",
        ),
        (
            '[display]\nname = "fourteen chars"',
            "display.name: must be 1-13 printable ASCII",
        ),
        (
            "[display]\nbit_depth = 9",
            "display.bit_depth: must be one of [6, 8, 10, 12, 14, 16]",
        ),
        (
            "[display]\nsize_cm = [60]",
            "display.size_cm: expected exactly 2 values, got 1",
        ),
        ('[display]\nyear = "2026"', "display.year: expected integer, got string"),
        (
            "[display]\nyear = 1980",
            "display.year: must be between 1990 and 2245 (got 1980)",
        ),
        ('[display]\ninterface = "vga"', "display.interface: must be one of"),
        ('[display]\ninterfase = "dp"', "display.interfase: unknown option"),
        ("[hdmi]\nmax_tmds_mhz = 601", "hdmi.max_tmds_mhz: must be between 25 and 600"),
        ("[hdmi]\nmax_tmds_mhz = 342", "hdmi.max_tmds_mhz: must be a multiple of 5"),
        (
            "[hdmi]\ndeep_color = [30, 32]",
            "hdmi.deep_color[1]: must be one of [30, 36, 48]",
        ),
        ('[hdr]\nenabled = "yes"', "hdr.enabled: expected true/false, got string"),
        (
            "[hdr]\nmax_luminance_nits = 20",
            "hdr.max_luminance_nits: must be 0 (unspecified) or at least 50",
        ),
        (
            "[hdr]\nmax_luminance_nits = 100\nmax_frame_avg_nits = 200",
            "hdr.max_frame_avg_nits: cannot exceed max_luminance_nits",
        ),
        (
            "[range]\nvrefresh_hz = [120, 24]",
            "range.vrefresh_hz: min 120 is greater than max 24",
        ),
        ("display = 3", "display: expected table, got integer"),
        ('[display]\ngamma = "2.2"', "display.gamma: expected number, got string"),
        ("[display]\ngamma = 5", "display.gamma: must be between 1 and 3.54 (got 5)"),
        ("[display]\nname = 1", "display.name: expected string, got integer"),
    ],
)
def test_field_errors(snippet: str, expected: str) -> None:
    errors = errors_of(with_tables(snippet))
    assert any(expected in e for e in errors), errors


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("width = 1920\nrefresh = 60", "modes[0].height: required"),
        (
            "width = 5000\nheight = 1080\nrefresh = 60",
            "modes[0].width: must be between 1 and 4095",
        ),
        (
            'width = 1920\nheight = 1080\nrefresh = 60\ntiming = "gtf"',
            "modes[0].timing: must be one of",
        ),
        ("width = 1920\nheight = 1080", "modes[0].refresh: required"),
        (
            "width = 1920\nheight = 1080\nrefresh = 60\nh_front = 8",
            "modes[0].pixel_clock_mhz: required",
        ),
        (
            'width = 1920\nheight = 1080\nrefresh = 60\ntiming = "cvt-rb"\nh_front = 8',
            'modes[0].h_front: only allowed with timing = "explicit"',
        ),
        (
            "width = 2560\nheight = 1440\nrefresh = 165",
            "exceeds the DTD limit of 655.35 MHz",
        ),
        ("height = 1080\nrefresh = 60", "modes[0].width: required"),
        (
            "width = 1920\nheight = 1080\nrefresh = 60\nfoo = 1",
            "modes[0].foo: unknown option",
        ),
    ],
)
def test_mode_errors(mode: str, expected: str) -> None:
    errors = errors_of(f"vics = []\n[[modes]]\n{mode}\n")
    assert any(expected in e for e in errors), errors


def test_explicit_mode_with_refresh_reports_one_error() -> None:
    errors = errors_of(
        "vics = []\n[[modes]]\nwidth = 3840\nheight = 2160\nrefresh = 60\npixel_clock_mhz = 594\n"
        "h_front = 176\nh_sync = 88\nh_back = 296\nv_front = 8\nv_sync = 10\nv_back = 72\n"
    )
    assert errors == [
        "modes[0].refresh: not allowed with explicit timings (it is derived from pixel_clock_mhz and the totals)"
    ]


def test_explicit_mode_is_inferred() -> None:
    cfg, diag = parse_text(
        "vics = []\n[hdmi]\nmax_tmds_mhz = 600\n"
        "[[modes]]\nwidth = 3840\nheight = 2160\npixel_clock_mhz = 594\n"
        "h_front = 176\nh_sync = 88\nh_back = 296\nv_front = 8\nv_sync = 10\nv_back = 72\n"
    )
    assert cfg is not None, diag.errors
    assert cfg.modes[0].refresh == pytest.approx(60.0)
    assert TimingKind("explicit") is TimingKind.EXPLICIT


@pytest.mark.parametrize("text", ["vics = [16]\n", "vics = [16]\nmodes = []\n"])
def test_missing_or_empty_modes(text: str) -> None:
    assert errors_of(text) == [
        "modes: at least one [[modes]] entry is required (the first is the preferred mode)"
    ]


def test_modes_of_wrong_type_is_reported_once() -> None:
    assert errors_of("vics = [16]\nmodes = 3\n") == [
        "modes: expected an array of tables ([[modes]])"
    ]


@pytest.mark.parametrize(
    ("vics", "expected"),
    [
        ("[200]", "vics[0]: VIC 200 is not in the supported table"),
        ('[16, "x"]', "vics[1]: expected integer, got string"),
        ("16", "vics: expected array of integers, got integer"),
        ("[300]", "vics[0]: must be between 1 and 219 (got 300)"),
        (
            "[97]",
            "vics[0]: VIC 97 (3840x2160@60) needs 594 MHz but hdmi.max_tmds_mhz is 340",
        ),
    ],
)
def test_vic_errors(vics: str, expected: str) -> None:
    errors = errors_of(MINIMAL.replace("vics = [16]", f"vics = {vics}"))
    assert any(expected in e for e in errors), errors


def test_native_vic_must_be_listed() -> None:
    errors = errors_of("native_vic = 4\n" + MINIMAL)
    assert "native_vic: VIC 4 must also be listed in vics" in errors


def test_root_key_after_table_gets_a_hint() -> None:
    errors = errors_of(MINIMAL + "native_vic = 16\n")
    assert any(
        "modes[0].native_vic: unknown option; `native_vic` is a top-level option" in e
        for e in errors
    )


def test_mode_above_tmds_limit() -> None:
    errors = errors_of(
        "vics = []\n[[modes]]\nwidth = 2560\nheight = 1440\nrefresh = 120\n"
    )
    assert any("needs 497.75 MHz but hdmi.max_tmds_mhz is 340" in e for e in errors), (
        errors
    )


def test_too_many_modes() -> None:
    modes = "".join(
        f"[[modes]]\nwidth = 1280\nheight = 720\nrefresh = {hz}\n"
        for hz in range(50, 140, 10)
    )
    errors = errors_of("vics = []\n" + modes)
    assert any("9 modes given but only 7 fit" in e for e in errors), errors


def test_all_errors_are_collected() -> None:
    errors = errors_of(
        'vics = [200]\n[display]\nmanufacturer = "x"\nbit_depth = 9\n'
        "[[modes]]\nwidth = 0\nheight = 1080\nrefresh = 60\n"
    )
    assert len(errors) == 4, errors


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            with_tables('[display]\ninterface = "dp"\n[hdmi]\nenabled = true'),
            "HDMI data blocks enabled but display.interface is 'dp'",
        ),
        (
            MINIMAL + "[[modes]]\nwidth = 1920\nheight = 1080\nrefresh = 60\n",
            "duplicates modes[0]",
        ),
        (with_tables("[range]\nvrefresh_hz = [24, 50]"), "outside range.vrefresh_hz"),
        (
            with_tables("[hdr]\nenabled = true"),
            "HDR usually needs display.bit_depth >= 10",
        ),
        (
            with_tables("[hdmi]\ndeep_color = [30]"),
            "deep color advertised but display.bit_depth is below 10",
        ),
        (with_tables("", top="vics = [16, 16]"), "vics: contains duplicates"),
        (
            with_tables("[range]\nhfreq_khz = [15, 50]"),
            "line rate 66.6 kHz is outside range.hfreq_khz [15, 50]",
        ),
        (
            with_tables("[range]\nmax_pixel_clock_mhz = 100"),
            "pixel clock 138.50 MHz is above range.max_pixel_clock_mhz 100",
        ),
        (
            (
                "vics = []\n[hdmi]\nmax_tmds_mhz = 600\nscdc = false\n"
                "[[modes]]\nwidth = 2560\nheight = 1440\nrefresh = 120\n"
            ),
            "above 340 MHz; HDMI 2.0 rates usually need hdmi.scdc = true",
        ),
    ],
)
def test_warnings_do_not_block(text: str, expected: str) -> None:
    cfg, diag = parse_text(text)
    assert cfg is not None, diag.errors
    assert any(expected in w for w in diag.warnings), diag.warnings


def _mode(extra: str, size: str = "width = 1920\nheight = 1080\nrefresh = 60\n") -> str:
    return f"vics = []\n[[modes]]\n{size}{extra}"


EXPLICIT_1080 = (
    "pixel_clock_mhz = 148.5\nh_front = 88\nh_sync = 44\nh_back = 148\n"
    "v_front = 4\nv_sync = 5\nv_back = 36\n"
)


@pytest.mark.parametrize(
    ("extra", "check"),
    [
        ('timing = "cvt"\n', lambda t: not t.h_sync_positive and t.v_sync_positive),
        ('timing = "cvt-rb3"\n', lambda t: t.h_front == 8),
        ('timing = "cvt"\ninterlaced = true\n', lambda t: t.interlaced),
        ("margins = true\n", lambda t: t.h_border == 32 and t.v_border == 19),
        (
            'timing = "cvt-rb2"\nvideo_optimized = true\n',
            lambda t: t.pclk_mhz == 133.18,
        ),
        (
            'timing = "cvt-rb3"\nh_blank = 160\nv_blank_us = 600\nearly_vsync = true\n',
            lambda t: t.h_back == 120,
        ),
    ],
)
def test_new_cvt_options_are_applied(
    extra: str, check: Callable[[Timing], bool]
) -> None:
    cfg, diag = parse_text(_mode(extra))
    assert cfg is not None, diag.errors
    assert check(cfg.modes[0])


def test_explicit_interlaced_with_borders() -> None:
    size = "width = 1920\nheight = 1080\n"
    cfg, diag = parse_text(
        _mode(EXPLICIT_1080 + "interlaced = true\nh_border = 4\nv_border = 2\n", size)
    )
    assert cfg is not None, diag.errors
    t = cfg.modes[0]
    assert (t.interlaced, t.h_border, t.v_border) == (True, 4, 2)


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (
            "video_optimized = true\n",
            "modes[0].video_optimized: only allowed with timing = \"cvt-rb2\" (timing is 'cvt-rb')",
        ),
        (
            'timing = "cvt-rb2"\nh_blank = 120\n',
            'modes[0].h_blank: only allowed with timing = "cvt-rb3"',
        ),
        (
            "early_vsync = true\n",
            'modes[0].early_vsync: only allowed with timing = "cvt-rb3"',
        ),
        (
            "h_border = 4\n",
            'modes[0].h_border: only allowed with timing = "explicit"',
        ),
        (
            'timing = "cvt-rb3"\nh_blank = 100\n',
            "modes[0].h_blank: must be a multiple of 8 (got 100)",
        ),
        (
            'timing = "cvt-rb3"\nh_blank = 240\n',
            "modes[0].h_blank: must be between 80 and 200 (got 240)",
        ),
        (
            'timing = "cvt-rb3"\nv_blank_us = 300\n',
            "modes[0].v_blank_us: must be between 460 and 920 (got 300)",
        ),
        (
            'interlaced = "yes"\n',
            "modes[0].interlaced: expected true/false, got string",
        ),
        (
            'timing = "cvt"\ninterlaced = true\n',
            "",  # 1080 is even: valid
        ),
    ],
)
def test_new_option_errors(extra: str, expected: str) -> None:
    cfg, diag = parse_text(_mode(extra))
    if not expected:
        assert cfg is not None, diag.errors
        return
    assert cfg is None
    assert any(e.startswith(expected) for e in diag.errors), diag.errors


def test_margins_not_allowed_with_explicit() -> None:
    errors = errors_of(
        _mode(EXPLICIT_1080 + "margins = true\n", "width = 1920\nheight = 1080\n")
    )
    assert errors == [
        (
            'modes[0].margins: only allowed with timing = "cvt" or "cvt-rb" or "cvt-rb2" or "cvt-rb3" '
            "(timing is 'explicit')"
        )
    ]


def test_odd_interlaced_height_is_rejected() -> None:
    size = "width = 1920\nheight = 1081\n"
    errors = errors_of(_mode(EXPLICIT_1080 + "interlaced = true\n", size))
    assert errors == ["modes[0]: interlaced height must be even"]


def test_pixel_clock_below_dtd_minimum() -> None:
    # Interlaced 640x480 at 30 fields/s needs under 10 MHz, which decoders reject.
    errors = errors_of(
        _mode(
            'timing = "cvt"\ninterlaced = true\n',
            "width = 640\nheight = 480\nrefresh = 30\n",
        )
    )
    assert errors == [
        "modes[0]: pixel clock 5.75 MHz is below the DTD minimum of 10 MHz; decoders treat it as invalid"
    ]


def test_high_rb3_v_blank_warns() -> None:
    cfg, diag = parse_text(_mode('timing = "cvt-rb3"\nv_blank_us = 800\n'))
    assert cfg is not None, diag.errors
    assert diag.warnings == [
        "modes[0].v_blank_us: above 705 may not be supported by RB3 sources"
    ]
