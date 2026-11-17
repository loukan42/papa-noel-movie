"""Voix ElevenLabs par l'API (bibliothèque standard uniquement).

Clé : variable d'environnement ELEVENLABS_API_KEY, ou fichier `elevenlabs.key` à la racine du projet
(une seule ligne, jamais publié : il est dans .gitignore).

  python voix/elevenlabs.py voix            # liste les voix utilisables avec ce compte
  python voix/elevenlabs.py essai VOICE_ID  # fait dire une phrase courte (quelques crédits)

Offre gratuite : l'API refuse les voix de la bibliothèque publique (Voice Library). Les voix
« premade » d'ElevenLabs et celles créées dans le compte (Voice Design) restent utilisables.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.elevenlabs.io/v1"
RACINE = Path(__file__).resolve().parents[1]
MODELE_DEFAUT = "eleven_multilingual_v2"


def cle():
    k = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    f = RACINE / "elevenlabs.key"
    if not k and f.exists():
        k = f.read_text(encoding="utf-8").strip()
    if not k:
        raise SystemExit("Clé ElevenLabs absente : la mettre dans elevenlabs.key ou dans ELEVENLABS_API_KEY.")
    return k


def _appel(chemin, corps=None, accept="application/json"):
    req = urllib.request.Request(API + chemin, method="POST" if corps is not None else "GET",
                                 data=json.dumps(corps).encode() if corps is not None else None,
                                 headers={"xi-api-key": cle(), "Content-Type": "application/json",
                                          "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"ElevenLabs a répondu {e.code} : {detail[:800]}") from e


def voix():
    """[(voice_id, nom, catégorie)] des voix du compte."""
    d = json.loads(_appel("/voices"))
    return [(v["voice_id"], v.get("name", ""), v.get("category", "")) for v in d.get("voices", [])]


def synthese(texte, voice_id, sortie, modele=None, graine=None, stabilite=0.5, ressemblance=0.75):
    """Écrit le MP3 de `texte` dit par `voice_id` dans `sortie`."""
    corps = {"text": texte, "model_id": modele or MODELE_DEFAUT,
             "voice_settings": {"stability": stabilite, "similarity_boost": ressemblance}}
    if graine is not None:
        corps["seed"] = int(graine)
    audio = _appel(f"/text-to-speech/{voice_id}?output_format=mp3_44100_128", corps, accept="audio/mpeg")
    sortie = Path(sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_bytes(audio)
    return sortie


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "voix":
        for vid, nom, cat in voix():
            print(f"{vid}\t{cat}\t{nom}")
    elif len(sys.argv) >= 3 and sys.argv[1] == "essai":
        f = synthese("Ho, ho, ho ! Bonjour !", sys.argv[2], RACINE / "travail" / "essai-elevenlabs.mp3")
        print(f)
    else:
        print(__doc__)
