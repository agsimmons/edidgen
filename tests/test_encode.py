"""Byte-level output of build_edid."""

from helpers import EXAMPLE_TOML, GOLDEN_BIN, MINIMAL, build_text, with_tables

from edidgen.encode import nits_to_cv


HDMI_OUI = bytes([0x03, 0x0C, 0x00])
HF_OUI = bytes([0xD8, 0x5D, 0xC4])
BT2020_BLOCK = bytes([0xE3, 0x05, 0xC0, 0x00])  # colorimetry: BT2020 RGB + YCC


def test_example_config_matches_golden_binary() -> None:
    assert build_text(EXAMPLE_TOML.read_text()) == GOLDEN_BIN.read_bytes()


def test_structure_and_checksums() -> None:
    edid = build_text(MINIMAL)
    assert len(edid) == 256
    assert edid[:8] == b"\x00\xff\xff\xff\xff\xff\xff\x00"
    assert edid[18:20] == bytes([1, 4])  # EDID 1.4
    assert edid[126] == 1  # one extension
    assert edid[128:130] == bytes([0x02, 0x03])  # CTA-861 rev 3
    assert sum(edid[:128]) % 256 == 0
    assert sum(edid[128:]) % 256 == 0


def test_manufacturer_and_name() -> None:
    edid = build_text(with_tables('[display]\nmanufacturer = "ABC"\nname = "Hello"'))
    mfg = int.from_bytes(edid[8:10], "big")
    assert "".join(chr(((mfg >> s) & 0x1F) + 64) for s in (10, 5, 0)) == "ABC"
    assert b"\x00\x00\x00\xfc\x00Hello\n       " in edid[:128]


def test_13_char_name_has_no_terminator() -> None:
    edid = build_text(with_tables('[display]\nname = "ThirteenChars"'))
    assert b"\x00\x00\x00\xfc\x00ThirteenChars" in edid[:128]


def test_single_mode_uses_dummy_second_descriptor() -> None:
    edid = build_text(MINIMAL)
    assert edid[72:76] == bytes([0, 0, 0, 0x10])


def test_preferred_mode_is_first_dtd() -> None:
    edid = build_text(MINIMAL)
    pclk = int.from_bytes(edid[54:56], "little")
    assert pclk == 13850  # 1920x1080@60 CVT-RB: 138.50 MHz
    assert edid[56] | ((edid[58] >> 4) << 8) == 1920


def test_hdmi_blocks_follow_config() -> None:
    hdmi = build_text(with_tables("[hdmi]\nmax_tmds_mhz = 600"))
    assert HDMI_OUI in hdmi[128:]
    assert HF_OUI in hdmi[128:]
    vsdb = hdmi.index(HDMI_OUI)
    assert hdmi[vsdb + 6] == 340 // 5  # HDMI 1.4 VSDB is capped at 340 MHz
    hf = hdmi.index(HF_OUI)
    assert hdmi[hf + 4] == 600 // 5

    # HDMI 1.4 only: no HF-VSDB unless above 340 MHz or SCDC is wanted.
    hdmi14 = build_text(with_tables("[hdmi]\nscdc = false"))
    assert HDMI_OUI in hdmi14[128:]
    assert HF_OUI not in hdmi14[128:]

    plain = build_text(with_tables('[display]\ninterface = "dp"'))
    assert HDMI_OUI not in plain[128:]
    assert HF_OUI not in plain[128:]


def test_native_vic_flag() -> None:
    edid = build_text(with_tables("", top="vics = [16]\nnative_vic = 16"))
    assert edid[132] == 0x40 | 1  # video data block, length 1
    assert edid[133] == 0x80 | 16


def test_hdr_blocks_only_when_enabled() -> None:
    hdr_tag = bytes([0xE6, 0x06])  # extended tag 7, len 6, HDR static metadata
    assert hdr_tag not in build_text(MINIMAL)
    enabled = build_text(with_tables("[hdr]\nenabled = true\nmax_luminance_nits = 670"))
    assert hdr_tag in enabled
    assert BT2020_BLOCK in enabled

    no_bt2020 = build_text(with_tables("[hdr]\nenabled = true\nbt2020 = false"))
    assert bytes([0xE3, 0x06, 0x05, 0x01]) in no_bt2020  # HDR block without luminance
    assert BT2020_BLOCK not in no_bt2020


def test_nits_to_cv() -> None:
    assert nits_to_cv(0) == 0
    assert nits_to_cv(50) == 0
    assert nits_to_cv(670) == 120
    assert nits_to_cv(350) == 90
    assert nits_to_cv(1e9) == 255


def test_extra_modes_go_into_cta_block() -> None:
    modes = "".join(
        f"[[modes]]\nwidth = 1920\nheight = 1080\nrefresh = {hz}\n"
        for hz in (60, 75, 100, 120)
    )
    edid = build_text("vics = []\n" + modes)
    offset = edid[130]
    # Two DTDs in the base block, the other two at the CTA DTD offset.
    assert int.from_bytes(edid[128 + offset : 130 + offset], "little") != 0
    assert int.from_bytes(edid[128 + offset + 18 : 130 + offset + 18], "little") != 0
