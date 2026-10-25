"""Lossless MP3 volume changes, the way mp3gain does it.

Every MP3 frame stores a "global gain" for each granule and channel: the decoder's overall scale for
that slice of audio. Adding 1 to every global gain makes the decoded audio 1.505 dB louder without
re-encoding anything, so quality is untouched and the change can be undone. Gains already at the
limit (0 or 255, seen only in an encoder's first and last frame) stay there.
"""

import math
from pathlib import Path
from typing import NamedTuple

STEP_DB = 20 * math.log10(2 ** 0.25)  # 1.505 dB of volume per global-gain step

_BITRATES_KBPS = {  # Layer III, by bitrate index
    "mpeg1": [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    "mpeg2": [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
_SAMPLE_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


class Frame(NamedTuple):
    offset: int
    length: int
    mpeg1: bool  # MPEG-1 (two granules per frame), else MPEG-2/2.5 (one)
    channels: int
    crc: bool  # a CRC follows the header and covers it and the side info


def _crc_table() -> list[int]:
    table = []
    for n in range(256):
        crc = n << 8
        for _ in range(8):
            crc = (crc << 1) ^ 0x8005 if crc & 0x8000 else crc << 1
        table.append(crc & 0xFFFF)
    return table


_CRC_TABLE = _crc_table()


def _crc16(data: bytes) -> int:
    """The MPEG audio frame checksum: CRC-16, polynomial 0x8005, starting from 0xFFFF."""
    crc = 0xFFFF
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[(crc >> 8) ^ byte]
    return crc


def _header(data: bytes, pos: int) -> Frame | None:
    """The Layer III frame starting at pos, or None if there isn't one."""
    if pos + 4 > len(data) or data[pos] != 0xFF or data[pos + 1] & 0xE0 != 0xE0:
        return None
    b1, b2, b3 = data[pos + 1], data[pos + 2], data[pos + 3]
    version, layer = (b1 >> 3) & 3, (b1 >> 1) & 3  # version 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
    bitrate_index, rate_index = b2 >> 4, (b2 >> 2) & 3
    if version == 1 or layer != 1 or bitrate_index in (0, 15) or rate_index == 3:
        return None  # reserved values, not Layer III, or free-format bitrate
    mpeg1 = version == 3
    bitrate = _BITRATES_KBPS["mpeg1" if mpeg1 else "mpeg2"][bitrate_index] * 1000
    length = (144 if mpeg1 else 72) * bitrate // _SAMPLE_RATES[version][rate_index] + ((b2 >> 1) & 1)
    return Frame(pos, length, mpeg1, 1 if b3 >> 6 == 3 else 2, not b1 & 1)


def frames(data: bytes) -> list[Frame]:
    """Every audio frame, skipping an ID3v2 tag at the start and any tags or junk elsewhere."""
    pos = 0
    if data[:3] == b"ID3" and len(data) >= 10:
        size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
        pos = 10 + size + (10 if data[5] & 0x10 else 0)
    found, in_sync = [], False
    while pos + 4 <= len(data):
        frame = _header(data, pos)
        # Out of sync, a header only counts if another one follows it, so stray 0xFF bytes in tags
        # are never mistaken for audio.
        if frame and (in_sync or _header(data, pos + frame.length)):
            found.append(frame)
            pos += frame.length
            in_sync = True
        else:
            pos += 1
            in_sync = False
    return found


def _side_info(frame: Frame) -> tuple[int, list[int]]:
    """Side info length in bytes, and the bit offset of each global gain inside it."""
    if frame.mpeg1:  # main_data_begin 9, private bits 5 or 3, scfsi 4 per channel; 59-bit blocks
        length = 17 if frame.channels == 1 else 32
        first, block, count = 9 + (5 if frame.channels == 1 else 3) + 4 * frame.channels, 59, 2 * frame.channels
    else:  # main_data_begin 8, private bits 1 or 2; one granule of 63-bit blocks
        length = 9 if frame.channels == 1 else 17
        first, block, count = 8 + frame.channels, 63, frame.channels
    # in each block, global_gain follows part2_3_length (12 bits) and big_values (9 bits)
    return length, [first + k * block + 21 for k in range(count)]


def apply_gain(data: bytes, steps: int) -> bytes | None:
    """A copy of an MP3 that plays steps * 1.5 dB louder (or quieter, if negative), or None if
    it isn't an MPEG Layer III file."""
    found = frames(data)
    if not found:
        return None
    out = bytearray(data)
    for n, frame in enumerate(found):
        length, offsets = _side_info(frame)
        start = frame.offset + (6 if frame.crc else 4)  # side info comes after the header and CRC
        if start + length > len(out):
            break  # truncated last frame
        if n == 0 and out[start + length:start + length + 4] in (b"Xing", b"Info"):
            continue  # LAME/Xing header frame: holds no audio
        bits = int.from_bytes(out[start:start + length], "big")
        for offset in offsets:
            shift = length * 8 - offset - 8
            gain = min(max(((bits >> shift) & 0xFF) + steps, 0), 255)
            bits = bits & ~(0xFF << shift) | (gain << shift)
        out[start:start + length] = bits.to_bytes(length, "big")
        if frame.crc:
            crc = _crc16(out[frame.offset + 2:frame.offset + 4] + out[start:start + length])
            out[frame.offset + 4:frame.offset + 6] = crc.to_bytes(2, "big")
    return bytes(out)


def copy_with_gain(src: Path, dst: Path, steps: int) -> bool:
    """Write src to dst with its volume changed by steps. Returns False, and copies src unchanged,
    if the file can't be adjusted losslessly."""
    data = src.read_bytes()
    adjusted = apply_gain(data, steps) if steps else data
    dst.write_bytes(adjusted if adjusted is not None else data)
    return adjusted is not None
