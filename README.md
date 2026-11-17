# Vidéo du Père Noël personnalisée

Un Père Noël photoréaliste, assis devant son sapin, dit bonjour à votre enfant par son prénom puis lui délivre un message d'environ 35 secondes. Tout se calcule sur votre ordinateur.

Usage personnel et gratuit uniquement, pas d'usage commercial.

## Le plus simple : avec Claude Code

1. Cloner ce dépôt et ouvrir le dossier dans Claude Code.
2. Écrire par exemple : « Fais une vidéo du Père Noël pour Léa. »
3. Claude Code vérifie la machine, installe ce qui manque (la première fois), vous demande quelle voix utiliser, puis lance la vidéo.

Deux voix possibles :

| Voix | Coût | Temps par vidéo | Remarque |
| --- | --- | --- | --- |
| Gratuite (Qwen3-TTS, sur votre PC) | rien | ~7 min, après une préparation unique d'environ 1 h | seul le prénom change d'une vidéo à l'autre |
| ElevenLabs (votre compte) | ~600 crédits par prise | ~1 h | toute la vidéo est recalculée avec la voix choisie |

Avec ElevenLabs en offre gratuite, l'API n'accepte que les voix « premade » et celles créées dans votre compte, pas celles de la bibliothèque publique.

## Ce qu'il faut

- Windows 10 ou 11 avec une carte NVIDIA. Testé sur une RTX 4090 (24 Go). Avec moins de mémoire vidéo, ça n'a pas été essayé.
- Environ 50 Go libres : 31 Go de modèles d'animation, environ 8 Go pour la voix et la transcription, plus ComfyUI.
- ffmpeg et Python 3.12 ou plus récent.

## Sans Claude Code

Tout est décrit dans [CLAUDE.md](CLAUDE.md) : installation, puis les commandes.

```
.venv\Scripts\python.exe pere_noel.py preparer-corps          (une fois, environ 1 h)
.venv\Scripts\python.exe pere_noel.py generer Léa             (environ 7 min)
Ouvrir-Pere-Noel.cmd                                          (page web : prénom, suivi en direct, historique)
```

## Comment c'est fait

- Animation du visage : InfiniteTalk (Wan 2.1 14B, LoRA lightx2v) dans ComfyUI.
- Voix gratuite : Qwen3-TTS, voix de grand-père créée par description puis clonée. Le message est dit d'un seul tenant, et la salutation imite un extrait de ce message pour que la voix ne change pas.
- Choix des prises : Whisper vérifie le texte, une empreinte vocale compare les voix.
- Montage et son : ffmpeg.

Le portrait (`base/santa.png`) a été généré avec Z-Image-Turbo. Aucune musique n'est fournie : mettre un fichier à vous dans `sons/` et son chemin dans `config.json` (clé `musique`).
