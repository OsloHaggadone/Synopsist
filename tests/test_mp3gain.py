import shutil
import subprocess

import numpy as np
import pytest

from synopsist import embed  # loads Essentia quietly
from synopsist.mp3gain import STEP_DB, _crc16, _side_info, apply_gain, copy_with_gain, frames

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg to make test MP3s")


def make_mp3(path, rate=44100, channels=2, bitrate="128k"):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration=2:sample_rate={rate}",
                    "-ac", str(channels), "-c:a", "libmp3lame", "-b:a", bitrate, str(path)], check=True)
    return path.read_bytes()


def decode(path):
    return embed.es.MonoLoader(filename=str(path), sampleRate=44100)()


def test_crc_is_the_standard_mpeg_checksum():
    assert _crc16(b"123456789") == 0xAEE7  # CRC-16/CMS check value


@needs_ffmpeg
@pytest.mark.parametrize("rate, channels, bitrate", [(44100, 2, "128k"), (44100, 1, "96k"),  # MPEG-1
                                                     (22050, 2, "64k"), (22050, 1, "32k")])  # MPEG-2
def test_gain_changes_volume_exactly(tmp_path, rate, channels, bitrate):
    original = make_mp3(tmp_path / "a.mp3", rate, channels, bitrate)
    (tmp_path / "b.mp3").write_bytes(apply_gain(original, 2))
    a, b = decode(tmp_path / "a.mp3"), decode(tmp_path / "b.mp3")
    assert len(a) == len(b)
    loud = np.abs(a) > 1e-3
    assert 20 * np.log10(np.median(np.abs(b[loud]) / np.abs(a[loud]))) == pytest.approx(2 * STEP_DB, abs=0.01)


@needs_ffmpeg
def test_gain_can_be_undone_and_zero_is_a_copy(tmp_path):
    original = make_mp3(tmp_path / "a.mp3")
    assert apply_gain(apply_gain(original, 3), -3) == original
    assert apply_gain(original, 0) == original


def test_crc_protected_frames_get_new_checksums():
    # MPEG-1 Layer III, 128 kbps, 44.1 kHz, stereo, protection bit 0 (a CRC follows the header)
    header = bytes([0xFF, 0xFA, 0x90, 0x00])
    length = 144 * 128000 // 44100
    rng = np.random.default_rng(0)
    data = b"".join(header + b"\0\0" + rng.integers(0, 256, length - 6, dtype=np.uint8).tobytes() for _ in range(5))
    found = frames(data)
    assert len(found) == 5 and all(f.crc for f in found)

    louder = apply_gain(data, 1)
    side, offsets = _side_info(found[0])
    for f in found:
        info = louder[f.offset + 6:f.offset + 6 + side]
        assert int.from_bytes(louder[f.offset + 4:f.offset + 6], "big") == _crc16(louder[f.offset + 2:f.offset + 4] + info)
        bits_before = int.from_bytes(data[f.offset + 6:f.offset + 6 + side], "big")
        bits_after = int.from_bytes(info, "big")
        for offset in offsets:
            shift = side * 8 - offset - 8
            before, after = (bits_before >> shift) & 0xFF, (bits_after >> shift) & 0xFF
            assert after == min(before + 1, 255)


@needs_ffmpeg
def test_tags_are_left_alone(tmp_path):
    audio = make_mp3(tmp_path / "a.mp3")
    # an ID3v2 tag whose contents look like an MP3 frame header
    payload = bytes([0xFF, 0xFB, 0x90, 0x00]) * 8
    size = len(payload)
    tag = b"ID3\x04\x00\x00" + bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F]) + payload
    louder = apply_gain(tag + audio, 2)
    assert louder[:len(tag)] == tag
    assert louder[len(tag):] == apply_gain(audio, 2)


def test_files_that_are_not_mp3_are_copied_unchanged(tmp_path):
    src = tmp_path / "notes.mp3"
    src.write_bytes(b"not really audio" * 100)
    assert apply_gain(src.read_bytes(), 2) is None
    assert copy_with_gain(src, tmp_path / "out.mp3", 2) is False
    assert (tmp_path / "out.mp3").read_bytes() == src.read_bytes()
