"""Contrôle des prises de voix par transcription (faster-whisper, CPU) et choix de la meilleure."""
import difflib
import re
import unicodedata

from audio import lire

_modele = None


def modele():
    global _modele
    if _modele is None:
        from faster_whisper import WhisperModel
        _modele = WhisperModel("large-v3", device="cpu", compute_type="int8")
    return _modele


def normaliser(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9' ]+", " ", t).replace("'", " ")
    mots = [m for m in t.split() if m not in ("ho", "oh", "hoho", "ohoh")]
    return " ".join(mots)


def transcrire(f):
    segs, _ = modele().transcribe(lire(f, 16000), language="fr", word_timestamps=True, beam_size=5)
    segs = list(segs)
    texte = " ".join(s.text.strip() for s in segs)
    mots = [w for s in segs for w in s.words]
    return texte, mots


def score(f, attendu):
    texte, mots = transcrire(f)
    ratio = difflib.SequenceMatcher(None, normaliser(texte), normaliser(attendu)).ratio()
    proba = min((w.probability for w in mots), default=0.0)
    return {"fichier": str(f), "texte": texte, "ratio": round(ratio, 3), "proba_min": round(proba, 3)}


def choisir(candidats, attendu):
    """Renvoie (meilleur, tous les scores). Trie sur la fidélité au texte puis la confiance."""
    scores = [score(f, attendu) for f in candidats]
    exclam = attendu.strip().endswith("!")
    for s in scores:
        s["ton"] = 1 if (exclam and s["texte"].strip().endswith("!")) else 0
    scores.sort(key=lambda s: (round(s["ratio"], 2), s["ton"], s["proba_min"]), reverse=True)
    return scores[0], scores
