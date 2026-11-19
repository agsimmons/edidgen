"""Encode a validated `Config` into EDID bytes."""

import math
from typing import TYPE_CHECKING

from edidgen.tables import BIT_DEPTHS, DEEP_COLOR_BITS, INTERFACES, VICS


if TYPE_CHECKING:
    from edidgen.model import Config, Timing


def encode_dtd(t: Timing, size_cm: tuple[int, int]) -> bytes:
    p = round(t.pclk_mhz * 100)
    hb, vb = t.h_total - t.h_active, t.v_total - t.v_active
    hmm, vmm = size_cm[0] * 10, size_cm[1] * 10
    flags = (
        0x18 | (0x04 if t.v_sync_positive else 0) | (0x02 if t.h_sync_positive else 0)
    )
    return bytes(
        [
            p & 0xFF,
            p >> 8,
            t.h_active & 0xFF,
            hb & 0xFF,
            ((t.h_active >> 8) << 4) | (hb >> 8),
            t.v_active & 0xFF,
            vb & 0xFF,
            ((t.v_active >> 8) << 4) | (vb >> 8),
            t.h_front & 0xFF,
            t.h_sync & 0xFF,
            ((t.v_front & 0xF) << 4) | (t.v_sync & 0xF),
            ((t.h_front >> 8) << 6)
            | ((t.h_sync >> 8) << 4)
            | ((t.v_front >> 4) << 2)
            | (t.v_sync >> 4),
            hmm & 0xFF,
            vmm & 0xFF,
            ((hmm >> 8) << 4) | (vmm >> 8),
            0,
            0,
            flags,
        ]
    )


def text_descriptor(tag: int, text: str) -> bytes:
    raw = text.encode("ascii")
    if len(raw) < 13:
        raw += b"\n" + b" " * (12 - len(raw))
    return bytes([0, 0, 0, tag, 0]) + raw


def range_descriptor(cfg: Config) -> bytes:
    r = cfg.range_limits
    modes = cfg.modes
    vics = [VICS[v] for v in cfg.vics]
    rates = [t.refresh for t in modes] + [v.refresh for v in vics]
    hfreqs = [t.hfreq_khz for t in modes]
    clocks = [t.pclk_mhz for t in modes] + [v.pclk_mhz for v in vics]
    vmin, vmax = r.vrefresh_hz or (
        max(1, math.floor(min(rates))),
        min(255, math.ceil(max(rates))),
    )
    hmin, hmax = r.hfreq_khz or (
        max(1, math.floor(min(hfreqs, default=15))),
        min(255, math.ceil(max(hfreqs, default=255))),
    )
    pmax = r.max_pixel_clock_mhz or math.ceil(max(clocks) / 10) * 10
    return (
        bytes(
            [0, 0, 0, 0xFD, 0, vmin, vmax, hmin, hmax, min(255, pmax // 10), 0x01, 0x0A]
        )
        + b" " * 6
    )  # 0x01 = range limits only (no GTF/CVT)


def nits_to_cv(nits: float) -> int:
    return 0 if nits <= 0 else max(0, min(255, round(32 * math.log2(nits / 50))))


def data_block(tag: int, payload: bytes) -> bytes:
    return bytes([(tag << 5) | len(payload)]) + payload


def cta_data_blocks(cfg: Config) -> bytes:
    out = b""
    if cfg.vics:
        out += data_block(
            2, bytes(v | 0x80 if v == cfg.native_vic else v for v in cfg.vics)
        )
    if cfg.hdmi.enabled:
        dc = 0
        for bits in cfg.hdmi.deep_color:
            dc |= DEEP_COLOR_BITS[bits]
        if dc and cfg.hdmi.y444_deep_color:
            dc |= 0x08
        vsdb_tmds = min(cfg.hdmi.max_tmds_mhz, 340) // 5  # HDMI 1.4 VSDB caps at 340
        out += data_block(3, bytes([0x03, 0x0C, 0x00, 0x10, 0x00, dc, vsdb_tmds]))
        if cfg.hdmi.max_tmds_mhz > 340 or cfg.hdmi.scdc:
            hf_tmds = cfg.hdmi.max_tmds_mhz // 5 if cfg.hdmi.max_tmds_mhz > 340 else 0
            out += data_block(
                3,
                bytes(
                    [
                        0xD8,
                        0x5D,
                        0xC4,
                        0x01,
                        hf_tmds,
                        0x80 if cfg.hdmi.scdc else 0x00,
                        0x00,
                    ]
                ),
            )
    out += data_block(7, bytes([0x00, 0x4A]))  # VCDB: RGB quant. selectable, underscan
    if cfg.hdr.enabled:
        if cfg.hdr.bt2020:
            out += data_block(7, bytes([0x05, 0xC0, 0x00]))
        payload = bytes(
            [0x06, 0x05, 0x01]
        )  # EOTF: SDR + SMPTE ST2084; static metadata type 1
        if cfg.hdr.max_luminance_nits or cfg.hdr.max_frame_avg_nits:
            payload += bytes(
                [
                    nits_to_cv(cfg.hdr.max_luminance_nits),
                    nits_to_cv(cfg.hdr.max_frame_avg_nits),
                    0x00,
                ]
            )
        out += data_block(7, payload)
    return out


def with_checksum(block: bytes) -> bytes:
    assert len(block) == 127, len(block)
    return block + bytes([(-sum(block)) & 0xFF])


def build_edid(cfg: Config) -> bytes:
    d = cfg.display
    mfg = 0
    for c in d.manufacturer:
        mfg = (mfg << 5) | (ord(c) - 64)

    base = bytearray(b"\x00\xff\xff\xff\xff\xff\xff\x00")
    base += (
        mfg.to_bytes(2, "big")
        + d.product_code.to_bytes(2, "little")
        + d.serial.to_bytes(4, "little")
    )
    base += bytes([d.week, d.year - 1990, 1, 4])
    base += bytes([0x80 | (BIT_DEPTHS[d.bit_depth] << 4) | INTERFACES[d.interface]])
    base += bytes([d.size_cm[0], d.size_cm[1], round(d.gamma * 100) - 100])
    base += bytes([0x06])  # RGB 4:4:4, sRGB default, preferred timing is native
    base += bytes(
        [0xEE, 0x91, 0xA3, 0x54, 0x4C, 0x99, 0x26, 0x0F, 0x50, 0x54]
    )  # sRGB primaries
    base += bytes([0x20, 0x00, 0x00])  # established timing: 640x480@60
    base += b"\x01\x01" * 8  # no standard timings
    base += encode_dtd(cfg.modes[0], d.size_cm)
    base += (
        encode_dtd(cfg.modes[1], d.size_cm)
        if len(cfg.modes) > 1
        else bytes([0, 0, 0, 0x10]) + bytes(14)
    )  # dummy descriptor
    base += range_descriptor(cfg) + text_descriptor(0xFC, d.name)
    base += bytes([1])  # one extension block

    blocks = cta_data_blocks(cfg)
    cta = bytearray([0x02, 0x03, 4 + len(blocks), 0x80]) + blocks  # 0x80: underscan
    for t in cfg.modes[2:]:
        cta += encode_dtd(t, d.size_cm)
    cta += bytes(127 - len(cta))

    return with_checksum(bytes(base)) + with_checksum(bytes(cta))
