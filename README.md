# Vidéo du Père Noël personnalisée

Un Père Noël photoréaliste, assis devant son sapin, dit bonjour à votre enfant par son prénom puis lui souhaite un joyeux Noël (environ 13 secondes en tout). Tout se calcule sur votre ordinateur.

Usage personnel et gratuit uniquement, pas d'usage commercial.

## Le plus simple : avec Claude Code

1. Cloner ce dépôt et ouvrir le dossier dans Claude Code.
2. Écrire par exemple : « Fais une vidéo du Père Noël pour Léa. »
3. Claude Code vérifie la machine, installe ce qui manque (la première fois), vous demande quelle voix utiliser, puis lance la vidéo.

Deux voix possibles :

| Voix | Coût | Première fois | Ensuite, par prénom |
| --- | --- | --- | --- |
| Gratuite (Qwen3-TTS, sur votre PC) | rien | ~45 min (message dit, animé, affiné une fois) | 15 à 30 min |
| ElevenLabs (votre compte) | ~250 crédits, puis ~80 par prénom | ~45 min | 15 à 30 min |

Seule la salutation est animée pour chaque prénom ; le message, identique pour tous, est réutilisé.

Avec ElevenLabs en offre gratuite, l'API n'accepte que les voix « premade » et celles créées dans votre compte, pas celles de la bibliothèque publique.

## Ce qu'il faut

- Windows 10 ou 11 avec une carte NVIDIA. Testé sur une RTX 4090 (24 Go). Avec moins de mémoire vidéo, ça n'a pas été essayé.
- Environ 55 Go libres : 35 Go de modèles d'animation et de super-résolution, environ 8 Go pour la voix et la transcription, plus ComfyUI.
- ffmpeg et Python 3.12 ou plus récent.

## Sans Claude Code

Tout est décrit dans [CLAUDE.md](CLAUDE.md) : installation, puis les commandes.

```
.venv\Scripts\python.exe pere_noel.py preparer-corps          (une fois, environ 45 min)
.venv\Scripts\python.exe pere_noel.py generer Léa             (15 à 30 min)
Ouvrir-Pere-Noel.cmd                                          (page web : prénom, suivi en direct, historique)
```

## Comment c'est fait

- Animation du visage : InfiniteTalk (Wan 2.1 14B, LoRA lightx2v) dans ComfyUI.
- Voix gratuite : Qwen3-TTS, voix de grand-père créée par description puis clonée. Le message est dit d'un seul tenant, et la salutation imite un extrait de ce message pour que la voix ne change pas.
- Choix des prises : Whisper vérifie le texte, une empreinte vocale compare les voix.
- Détail de peau et de barbe : super-résolution SeedVR2 (nœuds natifs de ComfyUI).
- Rendu « vrai film » : caméra tenue à la main, lumière du feu qui vacille, grain, son du salon (écho de la pièce, crépitement du feu). Pas de musique.
- Montage et son : ffmpeg.

Le portrait (`base/santa.png`) a été généré avec Z-Image-Turbo, façon photo de salon. Aucune musique n'est fournie : mettre un fichier à vous dans `sons/` et son chemin dans `config.json` (clé `musique`).
