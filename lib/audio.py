"""Outils audio (numpy + ffmpeg) : lecture, détourage des silences, gain, assemblage."""
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48000


def lire(f, sr=SR) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def ecrire(f, y, sr=SR):
    Path(f).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(f), np.clip(y, -1, 1).astype(np.float32), sr, subtype="PCM_24")


def silence(sec, sr=SR):
    return np.zeros(int(round(sec * sr)), np.float32)


def detourer(y, sr=SR, seuil_db=-42.0, marge_avant=0.04, marge_apres=0.12):
    """Retire les silences de début et de fin (enveloppe RMS sur 10 ms)."""
    win = int(sr * 0.01)
    n = len(y) // win
    if n == 0:
        return y
    rms = np.sqrt(np.mean(y[: n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms / (rms.max() + 1e-12))
    actif = np.where(db > seuil_db)[0]
    if len(actif) == 0:
        return y
    debut = max(0, actif[0] * win - int(marge_avant * sr))
    fin = min(len(y), (actif[-1] + 1) * win + int(marge_apres * sr))
    out = y[debut:fin].copy()
    # petits fondus pour éviter les clics
    f = min(int(0.01 * sr), len(out) // 4)
    if f > 0:
        out[:f] *= np.linspace(0, 1, f)
        out[-f:] *= np.linspace(1, 0, f)
    return out


def niveau_parole(y, sr=SR):
    """RMS des passages actifs (en dB), pour aligner le niveau des prises."""
    win = int(sr * 0.02)
    n = len(y) // win
    rms = np.sqrt(np.mean(y[: n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
    actifs = rms[rms > rms.max() * 0.1]
    return 20 * np.log10(np.mean(actifs) + 1e-12)


def ajuster_niveau(y, cible_db=-20.0, sr=SR):
    return y * (10 ** ((cible_db - niveau_parole(y, sr)) / 20))


def ralentir(y, facteur, sr=SR):
    """Ralentit sans changer la hauteur (atempo de ffmpeg). facteur < 1 ralentit."""
    if abs(facteur - 1) < 1e-3:
        return y
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-",
         "-af", f"atempo={facteur}", "-f", "f32le", "-"],
        input=y.astype(np.float32).tobytes(), capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.float32).copy()
