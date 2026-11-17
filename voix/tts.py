"""Synthèse avec la voix clonée du Père Noël (Qwen3-TTS Base, mode ICL).

S'exécute avec le Python du projet (qwen-tts installé).
Usage :
  python tts.py --ref voix/reference.wav --ref-texte "..." --lot lot.json [--similarite cible.wav]
  python tts.py --similarite cible.wav --mesurer a.wav b.wav ...     # ressemblance de voix seulement
lot.json : [{"texte": "...", "sortie": "chemin.wav", "essais": 3, "graine": 7}, ...]
Avec essais > 1, écrit chemin-1.wav ... chemin-N.wav (graines successives).
Sortie : une ligne « chemin<TAB>durée[<TAB>ressemblance] » par prise. La ressemblance est le cosinus
entre l'empreinte vocale de la prise et celle de --similarite (1 = même voix).
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

_cache = Path(__file__).resolve().parents[2] / "tools" / "hf-cache"
if not _cache.exists():  # installation autonome : cache dans le projet
    _cache = Path(__file__).resolve().parents[1] / "outils" / "hf-cache"
os.environ.setdefault("HF_HOME", str(_cache))

import librosa
import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

p = argparse.ArgumentParser()
p.add_argument("--ref")
p.add_argument("--ref-texte")
p.add_argument("--lot")
p.add_argument("--temperature", type=float, default=0.8)
p.add_argument("--similarite", help="voix cible pour mesurer la ressemblance de chaque prise")
p.add_argument("--mesurer", nargs="+", help="fichiers à comparer à --similarite, sans synthèse")
a = p.parse_args()

model = Qwen3TTSModel.from_pretrained(
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    device_map="cuda:0",
    dtype=torch.bfloat16,
    attn_implementation="sdpa",
)


def charger(f):
    """Audio mono float32 à 24 kHz (ffmpeg lit aussi les mp3)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-ac", "1", "-ar", "24000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy(), 24000


@torch.inference_mode()
def empreinte(wav, sr):
    m = model.model
    if sr != m.speaker_encoder_sample_rate:
        wav = librosa.resample(y=wav.astype(np.float32), orig_sr=int(sr), target_sr=m.speaker_encoder_sample_rate)
    e = m.extract_speaker_embedding(audio=wav, sr=m.speaker_encoder_sample_rate).float().flatten()
    return e / e.norm()


cible = empreinte(*charger(a.similarite)) if a.similarite else None


def ressemblance(wav, sr):
    return "" if cible is None else f"\t{float((empreinte(wav, sr) * cible).sum()):.4f}"


if a.mesurer:
    for f in a.mesurer:
        wav, sr = charger(f)
        print(f"{f}\t{len(wav) / sr:.2f}{ressemblance(wav, sr)}", flush=True)
    raise SystemExit(0)

lot = json.loads(Path(a.lot).read_text(encoding="utf-8"))
prompt = model.create_voice_clone_prompt(ref_audio=a.ref, ref_text=a.ref_texte)

for item in lot:
    sortie = Path(item["sortie"])
    sortie.parent.mkdir(parents=True, exist_ok=True)
    essais = int(item.get("essais", 1))
    graine = int(item.get("graine", 7))
    for i in range(essais):
        torch.manual_seed(graine + i)
        np.random.seed(graine + i)
        wavs, sr = model.generate_voice_clone(
            text=item["texte"], language="French", voice_clone_prompt=prompt, temperature=a.temperature,
        )
        f = sortie if essais == 1 else sortie.with_name(f"{sortie.stem}-{i + 1}{sortie.suffix}")
        sf.write(f, wavs[0], sr)
        print(f"{f}\t{len(wavs[0]) / sr:.2f}{ressemblance(wavs[0], sr)}", flush=True)
