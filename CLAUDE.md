# Guide pour Claude Code : vidéo du Père Noël personnalisée

Ce dépôt produit un MP4 (1920×1080, environ 13 s) où un Père Noël photoréaliste dit « Ho, ho, ho ! Bonjour {prénom} ! » puis le message de `config.json`. L'utilisateur n'est pas forcément développeur : parle-lui simplement, en français, et fais les manipulations à sa place.

Usage personnel, non commercial. Ne publie rien et ne pousse rien sur Git sans qu'il le demande.

## Quand l'utilisateur demande une vidéo

1. Demande le prénom (et comment il se prononce s'il est rare), puis la voix :
   - **gratuite** : voix de grand-père calculée sur le PC (Qwen3-TTS).
   - **ElevenLabs** : la voix de son choix dans son compte ElevenLabs.

   Dans les deux cas, le message fixe est dit et animé **une seule fois** (environ 45 min avec la super-résolution), puis chaque prénom ne demande que la salutation animée (15 à 30 min selon sa longueur). Ne réanime jamais tout le message pour un nouveau prénom.
2. Vérifie l'installation (section suivante) et complète ce qui manque.
3. Lance la génération (sections « Voix gratuite » ou « Voix ElevenLabs »), en tâche de fond : c'est long.
4. Donne le chemin du fichier dans `exports/` et demande à l'utilisateur de la regarder. Tu ne peux pas entendre la voix : ne dis pas qu'elle est bonne, dis ce que tu as vérifié (durée, transcription).

Un fichier déjà produit n'est jamais écrasé : une nouvelle version du même prénom sort en `-v2`, `-v3`, etc.

## Installation (une seule fois)

Vérifie chaque point avant d'installer, et annonce les gros téléchargements (taille) avant de les lancer.

1. **Carte NVIDIA** : `nvidia-smi`. Testé sur RTX 4090 24 Go. Avec moins de 16 Go de mémoire vidéo, préviens que ce n'est pas testé et que ce sera lent ou impossible.
2. **ffmpeg** dans le PATH (`ffmpeg -version`), sinon `winget install Gyan.FFmpeg` puis rouvrir le terminal.
3. **ComfyUI portable** dans `outils/ComfyUI_windows_portable` (chemin réglable par la clé `comfyui` de `config.json`) :
   - télécharger `ComfyUI_windows_portable_nvidia.7z` depuis https://github.com/comfyanonymous/ComfyUI/releases/latest (environ 2 Go) ;
   - l'extraire dans `outils/` avec 7-Zip (`winget install 7zip.7zip`, puis `"C:\Program Files\7-Zip\7z.exe" x fichier.7z -ooutils`).
   - Version testée : v0.44.0. Il faut le nœud natif `WanInfiniteTalkToVideo` : une fois ComfyUI lancé, `http://127.0.0.1:8188/object_info/WanInfiniteTalkToVideo` doit répondre autre chose que `{}`.
4. **Modèles d'animation** (environ 35 Go, reprise possible) : `python outils/telecharger_modeles.py`.
5. **Environnement Python** `.venv` (Python 3.12 ou plus) :
   ```
   py -3 -m venv .venv
   .venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
   Choisis l'index CUDA de PyTorch compatible avec le pilote (`nvidia-smi` affiche la version CUDA maximale). Vérifie ensuite : `.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"`.
6. Les modèles de voix (Qwen3-TTS, environ 4,5 Go dans `outils/hf-cache`) et de transcription (Whisper large-v3, environ 3 Go) se téléchargent tout seuls au premier usage.

ComfyUI est démarré automatiquement par le script s'il ne tourne pas (port 8188, journal dans `logs/comfyui.log`). Le premier rendu charge les modèles : compte une à deux minutes de plus.

## Voix gratuite

Une fois, pour fabriquer la partie fixe (message dit d'un seul tenant, puis animé) :

```
.venv\Scripts\python.exe -u pere_noel.py preparer-corps
```

Environ 45 min : synthèse de 4 prises, choix par Whisper et par ressemblance de voix, animation de 10 s (environ 20 min), puis super-résolution SeedVR2 (15 à 30 min). À refaire seulement si `corps` ou le portrait change. Si la super-résolution s'interrompt, `preparer-corps --etape superresolution` reprend là où elle s'est arrêtée.

Ensuite, pour chaque prénom (15 à 30 min) :

```
.venv\Scripts\python.exe -u pere_noel.py generer Léa
.venv\Scripts\python.exe -u pere_noel.py generer Maël --prononciation "Ma-elle"
```

La salutation imite un extrait du message fixe : la voix reste la même à la jonction. Le journal affiche, pour chaque prise, la fidélité au texte et la ressemblance de voix. Si aucune prise n'est fidèle (alerte dans le journal), relance avec une `--prononciation` écrite comme le prénom se dit.

Page web (prénom, suivi en direct, historique, file d'attente) : `Ouvrir-Pere-Noel.cmd`, puis http://127.0.0.1:5195.

## Voix ElevenLabs

1. L'utilisateur crée une clé API dans son compte ElevenLabs (menu du profil, « API Keys », droits Text to Speech et lecture des voix). Demande-lui de l'enregistrer **lui-même** dans un fichier `elevenlabs.key` à la racine du dépôt (une ligne), ou dans la variable `ELEVENLABS_API_KEY`. Ne lui demande pas de la coller dans la conversation, ne l'affiche jamais, ne la mets jamais dans Git (`elevenlabs.key` est dans `.gitignore`).
2. Liste ses voix et laisse-le choisir :
   ```
   .venv\Scripts\python.exe voix\elevenlabs.py voix
   .venv\Scripts\python.exe voix\elevenlabs.py essai VOICE_ID      (quelques crédits, pour écouter)
   ```
   En offre gratuite, l'API refuse les voix de la bibliothèque publique (erreur 402 ou `free_users_not_allowed`) : proposer une voix « premade » ou une voix créée dans son compte.
3. Une seule fois pour cette voix : le message est dit d'un seul tenant (2 prises, environ 250 crédits en tout), puis animé (environ 45 min). Annonce le coût avant de lancer :
   ```
   .venv\Scripts\python.exe -u pere_noel.py preparer-corps --dossier base/corps-elevenlabs --elevenlabs VOICE_ID --voix "Nom de la voix" --ralenti 0.95
   ```
   `--ralenti 0.95` calme un peu le débit des voix ElevenLabs (environ 190 mots/min sinon).
4. Ensuite, pour chaque prénom (15 à 30 min, 3 prises de la salutation, environ 80 crédits) :
   ```
   .venv\Scripts\python.exe -u pere_noel.py generer Léa --dossier-corps base/corps-elevenlabs
   ```
   La voix ElevenLabs et le débit sont relus dans `base/corps-elevenlabs/voix.json`. Résultat : `exports/pere-noel-lea-elevenlabs.mp4`. Pour que la page web utilise cette voix, mettre `"dossier_corps": "base/corps-elevenlabs"` dans `config.json`.

Avec des enregistrements déjà prêts (par exemple téléchargés depuis le site ElevenLabs) : le message se prépare avec `preparer-corps --dossier base/corps-ma-voix --audio prise1.mp3 prise2.mp3 --voix "Ma voix" --suffixe ma-voix`, et chaque prénom avec `generer Léa --dossier-corps base/corps-ma-voix --salut-audio salut1.mp3 salut2.mp3`. Une prise du texte complet convient aussi : le script n'en garde que la partie utile.

## Personnaliser

Tout se règle dans `config.json` :

| Changement | Clé | Ensuite |
| --- | --- | --- |
| Salutation | `salutation` (garder `{prenom}`) | rien |
| Message | `corps` (une entrée par phrase : texte, pause qui suit, plan `large` ou `serre`) | `preparer-corps` (voix gratuite) |
| Débit de la voix gratuite | `ralenti_voix` (0,9 = 10 % plus lent) | `preparer-corps` |
| Musique | `musique` (chemin d'un fichier de l'utilisateur, `null` pour aucune), `musique_volume_db` | rien |
| Portrait | `portrait` (image 1280×720, visage vers `centre_visage`) | `preparer-corps --etape video` |
| Détail de peau et de barbe | `superresolution` (SeedVR2, `null` pour s'en passer : plus rapide, plus flou) | `preparer-corps --etape video` |
| Rendu « tourné en caméra » | `finition_film` (caméra à la main, feu qui vacille, halo, grain ; `null` pour aucun) | rien |
| Son du salon | `ambiance` (écho de la pièce, crépitement du feu, micro de caméra ; `null` pour une voix sèche) | rien |

Le portrait fourni est une image générée façon photo de salon. Pour un rendu encore plus vrai, une vraie photo d'une personne déguisée, de face, assise, cadrée à mi-poitrine, donne le meilleur résultat (règle `centre_visage` sur le centre de son visage).

## Dépannage

- `ComfyUI ne répond pas` : lire `logs/comfyui.log`.
- Erreur de mémoire vidéo : fermer les autres programmes qui utilisent la carte graphique, puis relancer.
- La transcription tourne sur le processeur (Whisper en int8) : c'est voulu, ça évite les problèmes de bibliothèques CUDA.
- Le rendu se fait par morceaux de 81 images (3,24 s) ; la progression est dans le journal et dans `logs/comfyui.log`.
- Sous Windows, ffmpeg plante parfois quand la mémoire vive manque : le script relance automatiquement, et libère la mémoire de ComfyUI avant la super-résolution.
