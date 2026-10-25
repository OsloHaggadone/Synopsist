"""Audio analysis with Essentia.

analyze() does the expensive work once per audio file: decoding, Discogs-EffNet embeddings and what
Essentia's classifiers hear in them (instruments, moods and themes, genres, voice, danceability),
beat tracking, onsets, chroma and chords, the main melody and its notes, loudness, the power in
three frequency bands, and how dense the sound is, all kept at frame level and cached in
data/analysis/<sha1>.npz. track_features() and segment_features() summarize that analysis, so
re-cutting segments with a different window never needs the audio again.
"""

import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")  # quiet TensorFlow; must be set before essentia loads it

import json
import urllib.request
from pathlib import Path

import essentia

essentia.log.infoActive = False  # before importing essentia.standard, which logs on import
essentia.log.warningActive = False

import essentia.standard as es
import numpy as np

from synopsist.config import ANALYSIS_DIR, MODELS_DIR
from synopsist.segment import locate

ANALYSIS_VERSION = 5  # bump when analyze() output changes, so cached analyses are redone

MODELS_URL = "https://essentia.upf.edu/models"
MODEL_NAME = "discogs-effnet-bs64-1"
MODEL_PATH = MODELS_DIR / f"{MODEL_NAME}.pb"
# Classifiers that read the Discogs-EffNet embeddings (from Essentia's model collection), each giving
# a row of scores for every embedding: which instruments, moods and themes, and genres it sounds
# like, whether there's a voice, and how danceable it is. Name in the analysis -> model.
HEADS = {
    "instruments": "mtg_jamendo_instrument",
    "moods": "mtg_jamendo_moodtheme",
    "genres": "mtg_jamendo_genre",
    "voice": "voice_instrumental",
    "danceability": "danceability",
}

SR = 44100  # rhythm, onsets, and chroma run at this rate
EFFNET_SR = 16000
PATCH_HOP_S = 62 * 256 / EFFNET_SR  # one embedding every 0.992 s,
PATCH_S = 128 * 256 / EFFNET_SR  # each describing 2.048 s of audio
CHROMA_FRAME = 4096  # samples per chroma frame (~93 ms), centered on multiples of itself
LOUDNESS_HOP_S = 0.1  # EBU R128 momentary loudness: 400 ms windows every 100 ms
MELODY_HOP = 256  # samples between main-melody pitch frames (~6 ms)
SILENCE_LUFS = -70.0  # floor for momentary loudness (the EBU R128 absolute gate)
BANDS_HZ = ((20, 150), (150, 1500), (1500, 16000))  # bass, mids, highs (what the website's backgrounds follow)

# Chroma and key settings copied from Essentia's KeyExtractor, so a whole song gets exactly the key
# KeyExtractor would give it, and segments get the same method applied to their own frames.
_window = es.Windowing(type="hann", size=CHROMA_FRAME)
_spectrum = es.Spectrum()
_peaks = es.SpectralPeaks(orderBy="magnitude", magnitudeThreshold=1e-4, maxPeaks=60,
                          minFrequency=25, maxFrequency=3500, sampleRate=SR)
_whitening = es.SpectralWhitening(maxFrequency=3500, sampleRate=SR)
_hpcp = es.HPCP(size=12, bandPreset=False, harmonics=4, minFrequency=25, maxFrequency=3500,
                nonLinear=False, normalized="none", referenceFrequency=440, sampleRate=SR,
                weightType="cosine", windowSize=1.0, maxShifted=False)
_key = es.Key(profileType="bgate", pcpSize=12, numHarmonics=4, slope=0.6,
              usePolyphony=False, useThreeChords=False)
_spectral_complexity = es.SpectralComplexity(sampleRate=SR, magnitudeThreshold=0.005)
_effnet = None  # loaded on first use, once per process
_classifiers = None


def _head_path(model: str, ext: str) -> Path:
    return MODELS_DIR / f"{model}-discogs-effnet-1.{ext}"


def _model_files() -> list[tuple[str, Path]]:
    files = [(f"{MODELS_URL}/feature-extractors/discogs-effnet/{MODEL_NAME}.pb", MODEL_PATH)]
    for model in HEADS.values():
        for ext in ("pb", "json"):
            files.append((f"{MODELS_URL}/classification-heads/{model}/{model}-discogs-effnet-1.{ext}", _head_path(model, ext)))
    return files


def models_ready() -> bool:
    return all(path.exists() for _, path in _model_files())


def ensure_models() -> None:
    """Download the models into models/ if they aren't there yet: Discogs-EffNet (18 MB) and the
    classifiers that read its embeddings (9 MB together)."""
    missing = [(url, path) for url, path in _model_files() if not path.exists()]
    if missing:
        print(f"Downloading {len(missing)} model files to {MODELS_DIR}/")
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        for url, path in missing:
            tmp = path.with_suffix(path.suffix + ".part")
            urllib.request.urlretrieve(url, tmp)
            tmp.replace(path)


def _effnet_model():
    global _effnet
    if _effnet is None:
        ensure_models()
        _effnet = es.TensorflowPredictEffnetDiscogs(graphFilename=str(MODEL_PATH), output="PartitionedCall:1")
    return _effnet


def _classifier_models() -> dict:
    """name -> (classifier, its class labels)"""
    global _classifiers
    if _classifiers is None:
        ensure_models()
        _classifiers = {}
        for name, model in HEADS.items():
            meta = json.loads(_head_path(model, "json").read_text())
            output = next(o["name"] for o in meta["schema"]["outputs"] if o.get("output_purpose") == "predictions")
            classify = es.TensorflowPredict2D(graphFilename=str(_head_path(model, "pb")),
                                              input=meta["schema"]["inputs"][0]["name"], output=output)
            _classifiers[name] = (classify, meta["classes"])
    return _classifiers


def _spectral(mono: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One row per CHROMA_FRAME: chroma (n, 12), the power in each of BANDS_HZ (n, 3), and the
    spectral complexity (n,): how many peaks the spectrum has, a measure of how dense the sound is."""
    edges = [(round(low * CHROMA_FRAME / SR), round(high * CHROMA_FRAME / SR)) for low, high in BANDS_HZ]
    chroma, bands, complexity = [], [], []
    for frame in es.FrameGenerator(mono, frameSize=CHROMA_FRAME, hopSize=CHROMA_FRAME):
        spectrum = _spectrum(_window(frame))
        power = np.square(spectrum)
        bands.append([power[low:high].sum() for low, high in edges])
        complexity.append(_spectral_complexity(spectrum))
        freqs, mags = _peaks(spectrum)
        chroma.append(_hpcp(freqs, _whitening(spectrum, freqs, mags)))
    return (np.array(chroma, dtype=np.float32).reshape(-1, 12),
            np.array(bands, dtype=np.float32).reshape(-1, len(BANDS_HZ)),
            np.array(complexity, dtype=np.float32))


def analyze(path: Path) -> dict:
    """Frame-level analysis of one audio file. Takes a few seconds per song."""
    stereo, sr, *_ = es.AudioLoader(filename=str(path))()
    momentary, _, integrated, loudness_range = es.LoudnessEBUR128(sampleRate=sr, hopSize=LOUDNESS_HOP_S)(stereo)
    mono = stereo.mean(axis=1).astype(np.float32)  # same downmix as Essentia's MonoLoader
    if sr != SR:
        mono = es.Resample(inputSampleRate=sr, outputSampleRate=SR)(mono)
    embeddings = _effnet_model()(es.Resample(inputSampleRate=SR, outputSampleRate=EFFNET_SR, quality=4)(mono))
    if len(embeddings) == 0:
        raise ValueError(f"{path.name} is too short to analyze")
    bpm, beats, bpm_confidence, _, _ = es.RhythmExtractor2013(method="multifeature")(mono)
    onsets, _ = es.OnsetRate()(mono)
    momentary = np.nan_to_num(np.asarray(momentary), nan=SILENCE_LUFS, neginf=SILENCE_LUFS)
    chroma, bands, spectral_complexity = _spectral(mono)
    chords, chord_strength = es.ChordsDetection(hopSize=CHROMA_FRAME, sampleRate=SR, windowSize=2)(chroma)
    dynamic_complexity, _ = es.DynamicComplexity(sampleRate=SR)(mono)
    melody, _ = es.PredominantPitchMelodia(sampleRate=SR, hopSize=MELODY_HOP)(es.EqualLoudness(sampleRate=SR)(mono))
    note_starts, note_lengths, note_pitches = es.PitchContourSegmentation(hopSize=MELODY_HOP, sampleRate=SR)(melody, mono)
    analysis = {
        "analysis_version": ANALYSIS_VERSION,
        "duration_s": len(mono) / SR,
        "loudness_lufs": float(integrated),
        "loudness_range": float(loudness_range),  # LU: how far the loudness swings (EBU R128 LRA)
        "peak_dbfs": float(20 * np.log10(max(float(np.abs(stereo).max()), 1e-6))),  # loudest sample
        "bpm": float(bpm),
        "bpm_confidence": float(bpm_confidence),
        "embeddings": np.asarray(embeddings, dtype=np.float32),  # (n, 1280), one per PATCH_HOP_S
        "beats": np.asarray(beats, dtype=np.float32),  # beat times, seconds
        "onsets": np.asarray(onsets, dtype=np.float32),  # onset times, seconds
        "chroma": chroma,  # (n, 12), one per CHROMA_FRAME
        "chords": np.asarray(chords),  # chord name ("Am", "F", ...) per CHROMA_FRAME, over 2 s windows
        "chord_strength": np.asarray(chord_strength, dtype=np.float32),
        "bands": bands,  # (n, 3): power in BANDS_HZ, one per CHROMA_FRAME
        "spectral_complexity": spectral_complexity,  # spectral peaks, one per CHROMA_FRAME
        "dynamic_complexity": float(dynamic_complexity),  # dB: how far the loudness strays from its usual level
        "momentary_lufs": np.maximum(momentary, SILENCE_LUFS).astype(np.float32),  # one per LOUDNESS_HOP_S
        "melody_hz": np.asarray(melody, dtype=np.float32),  # main melody's pitch per MELODY_HOP (0: no melody)
        # its notes: start (s), length (s), and pitch (MIDI note number)
        "notes": np.column_stack([note_starts, note_lengths, note_pitches]).astype(np.float32).reshape(-1, 3),
    }
    for name, (classify, labels) in _classifier_models().items():
        analysis[name] = np.asarray(classify(embeddings), dtype=np.float32)  # (n, len(labels)), one row per embedding
        analysis[f"{name}_labels"] = np.asarray(labels)
    return analysis


def cache_path(sha1: str) -> Path:
    return ANALYSIS_DIR / f"{sha1}.npz"


def load_cached(sha1: str) -> dict | None:
    """The cached analysis for this audio, or None if there is none from the current version."""
    path = cache_path(sha1)
    if not path.exists():
        return None
    try:
        with np.load(path) as data:
            analysis = {name: data[name] for name in data.files}
    except Exception:  # unreadable cache file: redo the analysis
        return None
    analysis = {name: value.item() if value.ndim == 0 else value for name, value in analysis.items()}
    return analysis if analysis.get("analysis_version") == ANALYSIS_VERSION else None


def analyze_cached(path: Path, sha1: str) -> dict:
    """analyze(), reusing the cache for this exact audio when possible."""
    analysis = load_cached(sha1)
    if analysis is None:
        analysis = analyze(path)
        ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = cache_path(sha1).with_suffix(".tmp")
        with tmp.open("wb") as f:
            np.savez(f, **analysis)
        tmp.replace(cache_path(sha1))
    return analysis


def estimate_key(chroma: np.ndarray) -> tuple[str | None, str | None, float]:
    """Key, scale, and strength from chroma frames (KeyExtractor's averaging and 0.2 gate)."""
    pcp = chroma.mean(axis=0) if len(chroma) else np.zeros(12, dtype=np.float32)
    if pcp.max() <= 0:  # silence
        return None, None, 0.0
    pcp = pcp / pcp.max()
    pcp[pcp < 0.2] = 0
    key, scale, strength, _ = _key(pcp.astype(np.float32))
    return key, scale, float(strength)


def track_features(analysis: dict) -> dict:
    key, scale, strength = estimate_key(analysis["chroma"])
    return {
        "duration_s": float(analysis["duration_s"]),
        "bpm": float(analysis["bpm"]),
        "bpm_confidence": float(analysis["bpm_confidence"]),
        "key": key,
        "scale": scale,
        "key_strength": strength,
        "loudness_lufs": float(analysis["loudness_lufs"]),
        "peak_dbfs": float(analysis["peak_dbfs"]),
        "onset_rate": len(analysis["onsets"]) / analysis["duration_s"],
        "embedding": analysis["embeddings"].mean(axis=0),
    }


def segment_embeddings(analysis: dict, bounds: np.ndarray) -> np.ndarray:
    """Mean embedding per segment, from the embeddings centered inside it, shape (n, 1280)."""
    embeddings = analysis["embeddings"]
    centers = np.arange(len(embeddings)) * PATCH_HOP_S + PATCH_S / 2
    which = locate(centers, bounds)
    out = np.empty((len(bounds), embeddings.shape[1]), dtype=np.float32)
    for idx, (start, end) in enumerate(bounds):
        inside = embeddings[which == idx]
        # a window shorter than the embedding hop can miss every center: use the closest one
        out[idx] = inside.mean(axis=0) if len(inside) else embeddings[np.abs(centers - (start + end) / 2).argmin()]
    return out


def segment_features(analysis: dict, bounds: np.ndarray) -> list[dict]:
    """One row per segment: embedding, local tempo, key, onset rate, and loudness."""
    beats, onsets = analysis["beats"], analysis["onsets"]
    chroma, loudness = analysis["chroma"], analysis["momentary_lufs"]
    chroma_seg = locate(np.arange(len(chroma)) * CHROMA_FRAME / SR, bounds)
    loudness_seg = locate(np.arange(len(loudness)) * LOUDNESS_HOP_S + 0.2, bounds)  # window centers
    embeddings = segment_embeddings(analysis, bounds)

    segments = []
    for idx, (start, end) in enumerate(bounds):
        seg_beats = beats[(beats >= start) & (beats < end)]
        seg_loudness = loudness[loudness_seg == idx]
        key, scale, strength = estimate_key(chroma[chroma_seg == idx])
        segments.append({
            "idx": idx,
            "start_s": float(start),
            "end_s": float(end),
            "bpm": float(60 / np.median(np.diff(seg_beats))) if len(seg_beats) >= 3 else None,
            "key": key,
            "scale": scale,
            "key_strength": strength,
            "onset_rate": float(np.count_nonzero((onsets >= start) & (onsets < end)) / (end - start)),
            # average the power, not the decibels
            "loudness_lufs": float(10 * np.log10(np.mean(10 ** (seg_loudness / 10)))) if len(seg_loudness) else None,
            "embedding": embeddings[idx],
        })
    return segments
