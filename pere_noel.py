"""Vidéo personnalisée du Père Noël : seul le prénom change.

À lancer avec le Python de l'environnement qui contient qwen-tts et faster-whisper (voir les .cmd).

  python pere_noel.py preparer-corps            # une seule fois : voix + vidéo de la partie fixe (~1 h)
  python pere_noel.py generer Léa               # ~6 min par prénom
  python pere_noel.py generer Maël --prononciation "Ma-elle"
  python pere_noel.py generer --liste prenoms.txt   # un prénom par ligne, "Prénom;prononciation" possible
"""
import argparse
import difflib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI / "lib"))

import audio as A  # noqa: E402
import comfy  # noqa: E402
import infinitetalk as IT  # noqa: E402
import verif  # noqa: E402

PY_TTS = Path(sys.executable)  # la synthèse tourne dans le même environnement Python
COMFY_DEFAUT = os.environ.get("PERE_NOEL_COMFYUI", r"C:\AI\ComfyUI_windows_portable")
FPS = 25
SORTIE_L, SORTIE_H = 1920, 1080


def cfg():
    c = json.loads((ICI / "config.json").read_text(encoding="utf-8"))
    comfy.configurer(racine_comfyui(c))
    return c


def racine_comfyui(c):
    """Dossier de ComfyUI portable (clé « comfyui » de config.json, relative au projet ou absolue)."""
    r = Path(c.get("comfyui") or COMFY_DEFAUT)
    return r if r.is_absolute() else ICI / r


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


EVT = bool(os.environ.get("PERE_NOEL_EVT"))


def evt(type_, **kw):
    """Événement suivi par la page web (serveur.py). Muet hors de la page."""
    if EVT:
        print("@evt " + json.dumps({"type": type_, **kw}, ensure_ascii=False, default=str), flush=True)


def relatif(f):
    try:
        return Path(f).resolve().relative_to(ICI).as_posix()
    except ValueError:
        return str(f)


def slug(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "prenom"


# ---------------------------------------------------------------- ComfyUI

def assurer_comfyui(c=None):
    racine = racine_comfyui(c or cfg())
    if comfy.disponible():
        return
    log("Démarrage de ComfyUI…")
    journal = open(ICI / "logs" / "comfyui.log", "a", encoding="utf-8")
    subprocess.Popen(
        [str(racine / "python_embeded" / "python.exe"), "-s", "ComfyUI/main.py",
         "--windows-standalone-build", "--port", "8188", "--disable-auto-launch"],
        cwd=racine, stdout=journal, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    comfy.attendre_serveur(600)


# ---------------------------------------------------------------- voix

def tts(lot, c, ref=None, ref_texte=None, similarite=None):
    """Lance la synthèse (sous-processus pour libérer la carte graphique ensuite).

    `ref`/`ref_texte` : extrait à imiter (par défaut la voix de référence de config.json).
    `similarite` : voix cible ; renvoie alors {nom de fichier: ressemblance} pour chaque prise.
    """
    f = ICI / "logs" / f"lot-{int(time.time() * 1000)}.json"
    f.write_text(json.dumps(lot, ensure_ascii=False), encoding="utf-8")
    err = f.with_suffix(".err")
    cmd = [str(PY_TTS), str(ICI / "voix" / "tts.py"), "--ref", str(ref or ICI / c["voix_reference"]),
           "--ref-texte", ref_texte or c["voix_reference_texte"], "--lot", str(f),
           "--temperature", str(c.get("temperature_voix", 0.8))]
    if similarite:
        cmd += ["--similarite", str(similarite)]
    sims = {}
    with open(err, "w", encoding="utf-8") as fe:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=fe, text=True, encoding="utf-8", errors="replace",
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        for ligne in p.stdout:  # tts.py écrit « chemin<TAB>durée[<TAB>ressemblance] » à chaque prise terminée
            champs = ligne.rstrip("\n").split("\t")
            try:
                duree = float(champs[1])
                sim = float(champs[2]) if len(champs) > 2 else None
            except (ValueError, IndexError):
                continue
            sims[Path(champs[0]).name] = sim
            evt("prise", fichier=relatif(champs[0]), duree=duree, sim=sim)
        p.wait()
    if p.returncode != 0:
        raise RuntimeError("Synthèse vocale en échec :\n" + err.read_text(encoding="utf-8", errors="replace")[-3000:])
    f.unlink(missing_ok=True)
    err.unlink(missing_ok=True)
    return sims


def choisir_voix(fichiers, attendu, sims, marge=0.05):
    """Prise fidèle au texte (Whisper) dont la voix ressemble le plus à la cible."""
    _, scores = verif.choisir(fichiers, attendu)
    for s in scores:
        s["sim"] = sims.get(Path(s["fichier"]).name)
    haut = max(s["ratio"] for s in scores)
    fideles = [s for s in scores if s["ratio"] >= haut - marge]
    best = max(fideles, key=lambda s: (s["sim"] if s["sim"] is not None else 0, s["ratio"], s["proba_min"]))
    return best, scores


def dossier_corps(c):
    return ICI / c.get("dossier_corps", "base/corps")


def preparer_prise(f, c):
    y = A.detourer(A.lire(f))
    y = A.ajuster_niveau(y, -20.0)
    return A.ralentir(y, c.get("ralenti_voix", 1.0))


def voix_corps(c, refaire=False, prises_externes=None):
    """Message fixe dit d'un seul tenant, pour garder la même voix du début à la fin.

    Les pauses entre phrases sont allongées jusqu'aux valeurs de config.json. Les deux premières
    phrases, à vitesse naturelle, servent ensuite de modèle aux salutations (reference-salut.wav).
    `prises_externes` : enregistrements du message (ou du texte complet) au lieu de la voix gratuite.
    """
    dossier = dossier_corps(c)
    prises_dir = dossier / "prises"
    phrases = [p["texte"] for p in c["corps"]]
    texte = " ".join(phrases)
    if prises_externes:
        prises_dir.mkdir(parents=True, exist_ok=True)
        prises = []
        for k, f in enumerate(prises_externes, 1):
            dst = prises_dir / f"corps-{k}.wav"
            A.ecrire(dst, A.lire(f))
            prises.append(dst)
        sims = {}
    else:
        n = int(c.get("essais_corps", 4))
        prises = [prises_dir / f"corps-{k}.wav" for k in range(1, n + 1)]
        sims_f = prises_dir / "ressemblance.json"
        if refaire or not sims_f.exists() or not all(p.exists() for p in prises):
            log(f"Synthèse du message d'un seul tenant ({n} prises)…")
            sims = tts([{"texte": texte, "sortie": str(prises_dir / "corps.wav"), "essais": n, "graine": 500}], c,
                       similarite=ICI / c["voix_reference"])
            sims_f.write_text(json.dumps(sims), encoding="utf-8")
        sims = json.loads(sims_f.read_text(encoding="utf-8"))
    best, tous = choisir_voix(prises, texte, sims, marge=0.02)
    for s in tous:
        log(f"   {Path(s['fichier']).name} : fidélité {s['ratio']}, voix {s['sim']}")
    log(f"   gardée : {Path(best['fichier']).name}")
    if best["ratio"] < 0.9:
        log("   ATTENTION : la transcription s'écarte du texte, écouter la prise.")

    brute = A.ajuster_niveau(A.detourer(A.lire(best["fichier"])), -20.0)
    A.ecrire(dossier / "prise-choisie.wav", brute)
    _, mots = verif.transcrire(dossier / "prise-choisie.wav")
    bornes = aligner(mots, phrases)
    if any(b[0] is None for b in bornes):
        raise RuntimeError(f"Phrases introuvables dans la prise : {[i for i, b in enumerate(bornes) if b[0] is None]}")
    db, fen = niveaux_db(brute)
    coupes = [creux(db, fen, bornes[i][1] - 0.3, bornes[i + 1][0] + 0.6) for i in range(len(phrases) - 1)]
    if bornes[0][0] > 1.0:  # la prise commence par autre chose (salutation) : on part du silence d'avant
        t0, _ = creux(db, fen, bornes[0][0] - 1.0, bornes[0][0] + 0.1)
        brute = brute[int(t0 * A.SR):]
        coupes = [(t - t0, nat) for t, nat in coupes]

    # modèle des salutations : du début jusqu'à la pause qui suit la deuxième phrase
    A.ecrire(dossier / "reference-salut.wav", brute[: int(coupes[1][0] * A.SR)])
    (dossier / "reference-salut.json").write_text(
        json.dumps({"texte": phrases[0] + " " + phrases[1]}, ensure_ascii=False), encoding="utf-8")

    r = c.get("ralenti_voix", 1.0)
    bords = [0.0] + [t for t, _ in coupes] + [len(brute) / A.SR]
    t = c.get("corps_debut_silence", 0.15)
    morceaux, milieux, ajouts = [A.silence(t)], [], []
    for i, ph in enumerate(c["corps"]):
        seg = A.ralentir(brute[int(bords[i] * A.SR):int(bords[i + 1] * A.SR)], r)
        morceaux.append(seg)
        t += len(seg) / A.SR
        if i < len(phrases) - 1:  # la coupe est au milieu du silence naturel : on complète au même endroit
            ajout = max(0.0, ph["pause"] - coupes[i][1] / r)
            morceaux.append(A.silence(ajout))
            milieux.append(t + ajout / 2)
            ajouts.append(round(ajout, 2))
            t += ajout
        else:
            morceaux.append(A.silence(ph["pause"]))
            t += ph["pause"]
    corps = A.np.concatenate(morceaux)
    A.ecrire(dossier / "corps.wav", corps)
    limites = [c.get("corps_debut_silence", 0.15)] + milieux + [len(corps) / A.SR]
    plans = [{"phrase": i + 1, "debut": round(limites[i], 3), "fin": round(limites[i + 1], 3),
              "plan": ph.get("plan", "large")} for i, ph in enumerate(c["corps"])]
    (dossier / "plans.json").write_text(json.dumps(plans, indent=1), encoding="utf-8")
    nb = len(verif.normaliser(texte).split())
    log(f"Voix du corps : {len(corps) / A.SR:.1f} s, {nb / (len(corps) / A.SR) * 60:.0f} mots/min, "
        f"pauses ajoutées {ajouts}")
    return dossier / "corps.wav"


# ---------------------------------------------------------------- image

def filtre_plan(plan, c, taille=None):
    """Recadrage d'un plan puis mise à l'échelle en 1920x1080.

    `taille` : dimensions des images (plus grandes après super-résolution) ; le centre du visage
    de config.json, donné pour le portrait, est mis à la même échelle.
    """
    l, h = taille or (c["largeur"], c["hauteur"])
    s = l / c["largeur"]
    if plan == "serre":
        z = c.get("zoom_serre", 1.25)
        cx, cy = [v * s for v in c.get("centre_visage", [640, 300])]
        w, hh = int(round(l / z / 2) * 2), int(round(h / z / 2) * 2)
        x = int(min(max(0, cx - w // 2), l - w))
        y = int(min(max(0, cy - hh // 2), h - hh))
        rec = f"crop={w}:{hh}:{x}:{y},"
    else:
        rec = ""
    net = "" if s > 1.01 else ",unsharp=5:5:0.4:5:5:0.0"  # la super-résolution a déjà le détail
    return f"{rec}scale={SORTIE_L}:{SORTIE_H}:flags=lanczos{net},setsar=1"


def images_rendu(dossier):
    """Dossier d'images à monter (version agrandie si elle existe) et leur taille."""
    hd = dossier / "frames-hd"
    d = hd if hd.exists() and any(hd.glob("*.png")) else dossier / "frames"
    from PIL import Image
    with Image.open(next(iter(sorted(d.glob("*.png"))))) as im:
        return d, im.size


def finition_video(c, entree, sortie):
    """Rendu « tourné en caméra », de l'étiquette [entree] à [sortie] dans un filter_complex.

    Caméra tenue à la main (dérive lente), lumière du feu qui vacille, étalonnage moins saturé,
    halo autour des lumières, légère frange colorée d'objectif, vignettage, grain.
    """
    f = c.get("finition_film")
    if not f:
        return f"[{entree}]null[{sortie}]"
    f = f if isinstance(f, dict) else {}
    grain = int(f.get("grain", 5))
    halo = float(f.get("halo", 0.15))
    return (f"[{entree}]crop=w=iw*0.95:h=ih*0.95"
            ":x='(iw-ow)/2+(iw-ow)/2*0.5*(0.6*sin(2*PI*t*0.23)+0.4*sin(2*PI*t*0.61+1.3))'"
            ":y='(ih-oh)/2+(ih-oh)/2*0.5*(0.6*sin(2*PI*t*0.19+0.7)+0.4*sin(2*PI*t*0.53+2.1))'"
            f",scale={SORTIE_L}:{SORTIE_H}:flags=lanczos"
            ",eq=contrast=1.05:saturation=0.9:gamma=0.97"
            ":brightness='0.012*sin(2*PI*t*1.7)*sin(2*PI*t*0.53+0.4)':eval=frame"
            ",colorbalance=rs=0.03:bs=-0.03:rh=0.02:bh=-0.02,split[fa][fb];"
            "[fb]curves=all='0/0 0.86/0 1/1',gblur=sigma=14[fh];"
            f"[fa][fh]blend=all_mode=screen:all_opacity={halo},rgbashift=rh=-1:bh=1,vignette=angle=PI/5"
            f",noise=c0s={grain}:c0f=t+u:c1s=3:c1f=t+u:c2s=3:c2f=t+u[{sortie}]")


def ffmpeg(cmd):
    """Lance ffmpeg ; en cas d'échec, une seconde tentative avec un seul fil pour les filtres."""
    r = subprocess.run(cmd)
    if r.returncode:
        log("   ffmpeg a échoué, nouvel essai avec un seul fil de filtres")
        subprocess.run(cmd[:1] + ["-filter_complex_threads", "1"] + cmd[1:], check=True)


def _convoluer(y, ir):
    n = 1 << int(math.ceil(math.log2(len(y) + len(ir))))
    return A.np.fft.irfft(A.np.fft.rfft(y, n) * A.np.fft.rfft(ir, n), n)[: len(y)].astype(A.np.float32)


def _rms(y):
    return float(A.np.sqrt(A.np.mean(y ** 2)) + 1e-9)


def son_de_la_piece(y, c):
    """La voix comme enregistrée dans le salon : écho de petite pièce, feu de cheminée, micro de caméra."""
    a = c.get("ambiance")
    if not a:
        return y
    a = a if isinstance(a, dict) else {}
    np_, sr = A.np, A.SR
    rng = np_.random.default_rng(7)
    # petite pièce meublée : quelques premières réflexions puis une queue d'environ 0,3 s
    n = int(0.45 * sr)
    t = np_.arange(n) / sr
    ir = rng.standard_normal(n) * np_.exp(-6.9 * t / a.get("rt60", 0.3))
    ir = np_.convolve(ir, np_.ones(10) / 10, mode="same")  # queue plus sourde
    ir[: int(0.004 * sr)] = 0
    for d, g in ((0.006, 0.6), (0.011, 0.4), (0.017, 0.3), (0.023, 0.2)):
        ir[int(d * sr)] += g
    ir /= np_.sqrt(np_.sum(ir ** 2))
    reverb = _convoluer(y, ir)
    sortie = y + a.get("piece", 0.16) * reverb * (_rms(y) / _rms(reverb))
    # feu : grondement grave + crépitements au hasard
    nn = len(y)
    brun = np_.cumsum(rng.standard_normal(nn)).astype(np_.float64)
    k = 2401
    cs = np_.concatenate([[0], np_.cumsum(brun)])
    moy = (cs[k:] - cs[:-k]) / k
    brun = brun[k // 2: k // 2 + len(moy)] - moy
    brun = np_.pad(brun, (0, nn - len(brun)))
    feu = 0.4 * brun / (np_.max(np_.abs(brun)) + 1e-9)
    for _ in range(rng.poisson(a.get("crepitements", 4.0) * nn / sr)):
        pos = int(rng.integers(0, nn))
        L = int(rng.uniform(0.002, 0.014) * sr)
        b = rng.standard_normal(L) * np_.exp(-np_.arange(L) / (L / 4)) * rng.exponential(0.6)
        b = np_.diff(b, prepend=0.0)
        fin = min(nn, pos + L)
        feu[pos:fin] += b[: fin - pos]
    feu *= (10 ** (a.get("feu_db", -24) / 20)) * _rms(y) / _rms(feu)
    sortie = sortie + feu.astype(np_.float32)
    return (sortie / max(1.0, float(np_.max(np_.abs(sortie))) / 0.97)).astype(np_.float32)


FILTRE_MICRO = "highpass=f=90,lowpass=f=13000,acompressor=threshold=-20dB:ratio=2:attack=10:release=150"


def superresolution(c, rendu, etiquette, reprendre=False):
    """rendu/frames → rendu/frames-hd avec SeedVR2, si la clé « superresolution » est réglée."""
    sr = c.get("superresolution")
    if not sr:
        return
    import seedvr2
    log(f"Super-résolution SeedVR2 ({sr.get('modele')}, ×{sr.get('echelle', 1.5)})…")
    seedvr2.ameliorer(rendu / "frames", rendu / "frames-hd", etiquette, echelle=sr.get("echelle", 1.5),
                      modele=sr.get("modele", "seedvr2_3b_int8_convrot.safetensors"), journal=log,
                      reprendre=reprendre)


def video_corps(c):
    dossier = dossier_corps(c)
    son = dossier / "corps.wav"
    rendu = dossier / "rendu"
    log("Rendu vidéo de la partie fixe (InfiniteTalk)…")
    assurer_comfyui()
    n = IT.rendre(c, ICI / c["portrait"], son, rendu, "corps", c["graine_video"], journal=log)
    if (rendu / "frames-hd").exists():
        shutil.rmtree(rendu / "frames-hd")  # images agrandies d'un ancien rendu
    superresolution(c, rendu, "corps")
    composer_corps(c, n)


def composer_corps(c, n=None):
    """Applique les plans (large / serré) aux images du corps → <dossier_corps>/corps-1080p.mp4."""
    dossier = dossier_corps(c)
    frames = dossier / "rendu" / "frames"
    n = n or len(list(frames.glob("*.png")))
    plans = json.loads((dossier / "plans.json").read_text(encoding="utf-8"))
    duree = len(A.lire(dossier / "corps.wav")) / A.SR
    n_utiles = min(n, int(math.ceil(duree * FPS)))
    # coupes au milieu des pauses entre phrases
    coupes = [0]
    for a, b in zip(plans, plans[1:]):
        coupes.append(int(round((a["fin"] + b["debut"]) / 2 * FPS)))
    coupes.append(n_utiles)
    segs = []
    for i, p in enumerate(plans):
        d, f = coupes[i], coupes[i + 1]
        if segs and segs[-1][2] == p["plan"]:
            segs[-1][1] = f
        else:
            segs.append([d, f, p["plan"]])
    composer_segments(c, dossier, segs)


def composer_segments(c, dossier, segs):
    """Images de dossier/rendu/frames découpées en plans [[début, fin, plan], ...] → corps-1080p.mp4."""
    frames, taille = images_rendu(dossier / "rendu")
    chaines = [f"[0:v]trim=start_frame={d}:end_frame={f},setpts=PTS-STARTPTS,{filtre_plan(plan, c, taille)}[s{i}]"
               for i, (d, f, plan) in enumerate(segs)]
    fc = ";".join(chaines) + ";" + "".join(f"[s{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0[v]"
    sortie = dossier / "corps-1080p.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", str(frames / "%05d.png"),
                    "-filter_complex", fc, "-map", "[v]", "-c:v", "libx264", "-preset", "slow", "-crf", "12",
                    "-pix_fmt", "yuv420p", "-r", str(FPS), str(sortie)], check=True)
    (dossier / "segments.json").write_text(json.dumps(segs), encoding="utf-8")
    log(f"Partie fixe prête : {sortie.name} ({segs[-1][1]} images, plans {[s[2] for s in segs]})")


def corps_depuis_complet(c, source, voix=None, ralenti=None, suffixe=None):
    """Partie fixe tirée d'une vidéo « complet » déjà animée : tout ce qui suit la salutation.

    Évite de réanimer le message : seules les salutations seront animées ensuite.
    """
    dossier = dossier_corps(c)
    r = json.loads((source / "rapport.json").read_text(encoding="utf-8"))
    segs = r["segments"]
    debut = segs[0][1]  # fin du plan de la salutation
    if c["corps"][0].get("plan", "large") == segs[0][2]:
        raise SystemExit("La salutation et la première phrase sont dans le même plan : coupe introuvable.")
    dossier.mkdir(parents=True, exist_ok=True)
    voix_wav = A.lire(source / "voix.wav")
    A.ecrire(dossier / "corps.wav", voix_wav[int(debut / FPS * A.SR):])
    dst = dossier / "rendu" / "frames"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    images = sorted((source / "rendu" / "frames").glob("*.png"))
    for i, f in enumerate(images[debut:segs[-1][1]]):
        shutil.copy2(f, dst / f"{i:05d}.png")
    (dossier / "voix.json").write_text(json.dumps(
        {"voix": voix or r.get("voix"), "ralenti": ralenti, "suffixe": suffixe, "depuis": relatif(source),
         "image_debut": debut},
        ensure_ascii=False), encoding="utf-8")
    composer_segments(c, dossier, [[d - debut, f - debut, p] for d, f, p in segs[1:]])


def infos_voix(c):
    """Réglages de la voix de la partie fixe (voix.json), s'il y en a."""
    f = dossier_corps(c) / "voix.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def extraire_salut(y, c, texte, tmp):
    """Dans une prise du texte complet, ne garde que la salutation (coupe au silence qui la suit)."""
    A.ecrire(tmp, y)
    _, mots = verif.transcrire(tmp)
    bornes = aligner(mots, [texte, c["corps"][0]["texte"]])
    if bornes[0][1] is None or bornes[1][0] is None:
        raise RuntimeError(f"Salutation introuvable dans {tmp.name}")
    db, fen = niveaux_db(y)
    t, _ = creux(db, fen, bornes[0][1] - 0.3, bornes[1][0] + 0.6)
    return y[: int(t * A.SR)]


# ---------------------------------------------------------------- génération par prénom

def prochain_export(nom):
    exp = ICI / "exports"
    exp.mkdir(exist_ok=True)
    try:  # un nom déjà livré ne resert pas, même si le fichier a été supprimé depuis
        deja = {e.get("fichier") for e in json.loads((ICI / "historique.json").read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        deja = set()
    f = exp / f"pere-noel-{nom}.mp4"
    k = 1
    while f.exists() or f.name in deja:
        k += 1
        f = exp / f"pere-noel-{nom}-v{k}.mp4"
    return f


def generer(prenom, prononciation=None, c=None, salut_audio=None, elevenlabs_id=None, suffixe=None):
    """Salutation animée pour ce prénom + partie fixe déjà prête.

    Voix de la salutation : Qwen3-TTS imitant la partie fixe (défaut), des fichiers audio
    (`salut_audio`, salutation seule ou texte complet), ou ElevenLabs (`elevenlabs_id`).
    """
    c = dict(c or cfg())
    t0 = time.time()
    corps_mp4 = dossier_corps(c) / "corps-1080p.mp4"
    if not corps_mp4.exists():
        raise SystemExit("La partie fixe n'est pas prête : lancer d'abord « preparer-corps ».")
    infos = infos_voix(c)
    if infos.get("ralenti"):
        c["ralenti_voix"] = infos["ralenti"]
    suffixe = suffixe or infos.get("suffixe")
    if not salut_audio and not elevenlabs_id:
        elevenlabs_id = infos.get("elevenlabs_id")  # partie fixe faite avec ElevenLabs : même voix
    nom = slug(prenom) + (f"-{slug(suffixe)}" if suffixe else "")
    travail = ICI / "travail" / nom
    if travail.exists():
        shutil.rmtree(travail)
    travail.mkdir(parents=True)
    texte = c["salutation"].format(prenom=prononciation or prenom)
    log(f"{prenom} : synthèse de « {texte} »")
    evt("etape", nom="voix", texte=texte)
    if elevenlabs_id:
        salut_audio = prises_elevenlabs(prenom, elevenlabs_id, c, prononciation, int(c.get("essais_salut", 3)),
                                        texte=texte, nom_fichier="salut")
    if salut_audio:
        candidats, sims = [], {}
        for k, f in enumerate(salut_audio, 1):
            y = A.lire(f)
            if len(y) / A.SR > 8:  # texte complet : on n'en garde que la salutation
                y = extraire_salut(y, c, texte, travail / f"complet-{k}.wav")
            dst = travail / f"salut-{k}.wav"
            A.ecrire(dst, y)
            candidats.append(dst)
            evt("prise", fichier=relatif(dst), duree=round(len(y) / A.SR, 2), sim=None)
    else:
        # la salutation imite un extrait du message fixe, pour que la voix ne change pas à la jonction
        modele = dossier_corps(c) / "reference-salut.wav"
        if modele.exists():
            ref, ref_texte = modele, json.loads(modele.with_suffix(".json").read_text(encoding="utf-8"))["texte"]
        else:
            ref, ref_texte = None, None
        n_essais = int(c.get("essais_salut", 3))
        sims = tts([{"texte": texte, "sortie": str(travail / "salut.wav"), "essais": n_essais, "graine": 31}], c,
                   ref=ref, ref_texte=ref_texte, similarite=modele if modele.exists() else None)
        candidats = [travail / f"salut-{k}.wav" for k in range(1, n_essais + 1)]
    evt("etape", nom="ecoute")
    best, tous = choisir_voix(candidats, texte, sims)
    for s in tous:
        log(f"   prise {Path(s['fichier']).name} : « {s['texte']} » ({s['ratio']}, voix {s['sim']})")
    evt("choix", prises=[{"fichier": relatif(s["fichier"]), "texte": s["texte"], "ratio": s["ratio"],
                          "sim": s["sim"], "gardee": s is best} for s in tous])
    if best["ratio"] < 0.8:
        log("   ATTENTION : aucune prise ne correspond bien au texte, écouter le résultat "
            "ou donner une --prononciation.")
        evt("alerte", message="Aucune prise ne correspond bien au texte : écouter la voix, "
                              "ou relancer avec une prononciation.")
    y = preparer_prise(best["fichier"], c)
    # marges autour de la phrase : on les réduit si ça évite un second morceau de rendu
    parole = len(y) / A.SR
    budget = IT.MAX_LEN / FPS - 0.02
    avant, apres = 0.2, 0.45
    if parole + avant + apres > budget:
        avant, apres = 0.12, max(0.2, min(0.45, budget - 0.12 - parole))
    salut = A.np.concatenate([A.silence(avant), y, A.silence(apres)])
    A.ecrire(travail / "salut-final.wav", salut)
    evt("voix", fichier=relatif(travail / "salut-final.wav"), duree=round(len(salut) / A.SR, 2))

    log(f"{prenom} : rendu vidéo de la salutation ({len(salut) / A.SR:.2f} s)")
    evt("etape", nom="animation", comfyui_pret=comfy.disponible())
    assurer_comfyui()
    n = IT.rendre(c, ICI / c["portrait"], travail / "salut-final.wav", travail / "rendu", f"salut-{nom}",
                  c["graine_video"], journal=log,
                  progres=lambda k, nb, faites, total: evt("morceau", k=k, n=nb, faites=faites, total=total))
    superresolution(c, travail / "rendu", f"salut-{nom}")
    evt("etape", nom="montage")
    sortie = prochain_export(nom)
    duree_tot = assembler(c, travail, salut, n, corps_mp4, sortie)
    calcul = round(time.time() - t0)
    (travail / "rapport.json").write_text(json.dumps({
        "prenom": prenom, "prononciation": prononciation, "texte": texte, "prise": best,
        "duree": round(duree_tot, 2), "export": str(sortie)}, ensure_ascii=False, indent=1, default=float),
        encoding="utf-8")
    ajouter_historique({"prenom": prenom, "prononciation": prononciation, "fichier": sortie.name,
                        "voix": infos.get("voix") or ("ElevenLabs" if elevenlabs_id else None),
                        "cree": time.strftime("%Y-%m-%dT%H:%M:%S"), "duree": round(duree_tot, 2),
                        "temps_calcul": calcul, "prise": best["texte"], "ratio": best["ratio"]})
    log(f"{prenom} : prêt en {calcul} s → {sortie}")
    evt("fini", fichier=sortie.name, duree=round(duree_tot, 2), temps_calcul=calcul)
    return sortie


# ---------------------------------------------------------------- vidéo entière d'une seule prise
# Pour une voix venue d'ailleurs (ElevenLabs...) : salutation et message dits d'un seul tenant,
# donc le même timbre du début à la fin. Toute la vidéo est animée (≈ 1 h de calcul).

def aligner(mots, phrases):
    """[(début, fin)] de chaque phrase attendue, d'après les mots transcrits (None si introuvable)."""
    attendus = [(t, i) for i, ph in enumerate(phrases) for t in verif.normaliser(ph).split()]
    entendus = [(t, w.start, w.end) for w in mots for t in verif.normaliser(w.word).split()]
    sm = difflib.SequenceMatcher(None, [t for t, _ in attendus], [t for t, *_ in entendus], autojunk=False)
    bornes = [[None, None] for _ in phrases]
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            i = attendus[a + k][1]
            _, s, e = entendus[b + k]
            bornes[i][0] = s if bornes[i][0] is None else min(bornes[i][0], s)
            bornes[i][1] = e if bornes[i][1] is None else max(bornes[i][1], e)
    return bornes


def niveaux_db(y, fen=0.02):
    h = int(fen * A.SR)
    n = len(y) // h
    rms = A.np.sqrt(A.np.mean(y[: n * h].reshape(n, h) ** 2, axis=1))
    return 20 * A.np.log10(rms + 1e-9), fen


def creux(db, fen, t0, t1, seuil=-45.0):
    """Plus long silence qui touche [t0, t1] : (milieu, durée). Sans silence : point le plus calme, 0."""
    a, b = max(0, int(t0 / fen)), min(len(db), int(math.ceil(t1 / fen)))
    if b <= a:
        return t0, 0.0
    meilleur = None
    k = a
    while k < b:
        if db[k] <= seuil:
            g, d = k, k
            while g > 0 and db[g - 1] <= seuil:
                g -= 1
            while d < len(db) - 1 and db[d + 1] <= seuil:
                d += 1
            if meilleur is None or d - g > meilleur[1] - meilleur[0]:
                meilleur = (g, d)
            k = d + 1
        else:
            k += 1
    if meilleur is None:
        k = a + int(A.np.argmin(db[a:b]))
        return (k + 0.5) * fen, 0.0
    g, d = meilleur
    return (g + d + 1) / 2 * fen, (d - g + 1) * fen


def generer_complet(prenom, audios, c, prononciation=None, suffixe=None, voix=None, ralenti=1.0):
    t0 = time.time()
    nom = slug(prenom) + (f"-{slug(suffixe)}" if suffixe else "")
    travail = ICI / "travail" / nom
    if travail.exists():
        shutil.rmtree(travail)
    travail.mkdir(parents=True)
    salut = c["salutation"].format(prenom=prononciation or prenom)
    phrases = [salut] + [p["texte"] for p in c["corps"]]
    texte = " ".join(phrases)

    # 1. préparation des prises (même traitement pour toutes), puis choix par transcription
    prises = []
    for k, f in enumerate(audios, 1):
        y = A.ajuster_niveau(A.detourer(A.lire(f)), -20.0)
        y = A.ralentir(y, ralenti)
        p = travail / f"prise-{k}.wav"
        A.ecrire(p, y)
        prises.append(p)
    best, tous = verif.choisir(prises, texte)
    for s in tous:
        log(f"   {Path(s['fichier']).name} : fidélité {s['ratio']}, confiance min {s['proba_min']}")
    if best["ratio"] < 0.85:
        log("   ATTENTION : la transcription s'écarte du texte, écouter la prise.")
    choisie = Path(best["fichier"])
    y = A.lire(choisie)
    _, mots = verif.transcrire(choisie)
    bornes = aligner(mots, phrases)
    if any(b[0] is None for b in bornes):
        raise RuntimeError(f"Phrases introuvables dans la prise : {[i for i, b in enumerate(bornes) if b[0] is None]}")

    # 2. pauses : on coupe au plus calme entre deux phrases et on complète le silence jusqu'à la cible
    db, fen = niveaux_db(y)
    cibles = [0.5] + [p["pause"] for p in c["corps"][:-1]]
    coupes = []
    for i in range(len(phrases) - 1):
        t, naturel = creux(db, fen, bornes[i][1] - 0.3, bornes[i + 1][0] + 0.6)  # Whisper date souvent en avance
        coupes.append((t, naturel, max(0.0, cibles[i] - naturel)))
    morceaux, debut, t_prec, decalage, milieux = [A.silence(0.2)], 0.2, 0.0, 0.2, []
    for t, naturel, ajout in coupes:
        morceaux += [y[int(t_prec * A.SR):int(t * A.SR)], A.silence(ajout)]
        milieux.append(decalage + t + ajout / 2)  # milieu de la pause, dans le temps final
        decalage += ajout
        t_prec = t
    morceaux += [y[int(t_prec * A.SR):], A.silence(c["corps"][-1]["pause"])]
    final = A.np.concatenate(morceaux)
    A.ecrire(travail / "voix.wav", final)
    duree = len(final) / A.SR
    nb_mots = len(verif.normaliser(texte).split())
    log(f"{prenom} : voix {duree:.1f} s, {nb_mots / duree * 60:.0f} mots/min, "
        f"pauses ajoutées {[round(a, 2) for *_, a in coupes]}")

    # 3. animation de toute la vidéo
    log(f"{prenom} : animation de la vidéo entière ({duree:.1f} s)")
    assurer_comfyui()
    n = IT.rendre(c, ICI / c["portrait"], travail / "voix.wav", travail / "rendu", f"complet-{nom}",
                  c["graine_video"], journal=log)

    # 4. plans : salutation en large, puis ceux du message ; coupes au milieu des pauses
    plans = ["large"] + [p.get("plan", "large") for p in c["corps"]]
    n_utiles = min(n, int(math.ceil(duree * FPS)))
    bords = [0] + [int(round(m * FPS)) for m in milieux] + [n_utiles]
    segs = []
    for i, plan in enumerate(plans):
        if segs and segs[-1][2] == plan:
            segs[-1][1] = bords[i + 1]
        else:
            segs.append([bords[i], bords[i + 1], plan])
    superresolution(c, travail / "rendu", f"complet-{nom}")
    sortie = prochain_export(nom)
    monter(c, travail / "rendu", segs, travail / "voix.wav", duree, sortie)
    calcul = round(time.time() - t0)
    (travail / "rapport.json").write_text(json.dumps({
        "prenom": prenom, "prononciation": prononciation, "voix": voix, "sources": [str(a) for a in audios],
        "prise": best, "segments": segs, "duree": round(duree, 2), "export": str(sortie)},
        ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    ajouter_historique({"prenom": prenom, "prononciation": prononciation, "fichier": sortie.name, "voix": voix,
                        "cree": time.strftime("%Y-%m-%dT%H:%M:%S"), "duree": round(duree, 2),
                        "temps_calcul": calcul, "prise": best["texte"], "ratio": best["ratio"]})
    log(f"{prenom} : prêt en {calcul} s → {sortie} (plans {[s[2] for s in segs]})")
    return sortie


def prises_elevenlabs(prenom, voice_id, c, prononciation=None, essais=2, modele=None, texte=None,
                      nom_fichier="complet"):
    """Fait dire un texte par ElevenLabs (par défaut salutation + message), une requête par prise."""
    sys.path.insert(0, str(ICI / "voix"))
    import elevenlabs
    texte = texte or " ".join([c["salutation"].format(prenom=prononciation or prenom)]
                              + [p["texte"] for p in c["corps"]])
    dossier = ICI / "sources" / slug(prenom)
    fichiers = []
    for k in range(1, essais + 1):
        f = dossier / f"elevenlabs-{voice_id}-{nom_fichier}-{k}.mp3"
        if not f.exists():
            log(f"{prenom} : ElevenLabs, prise {k} ({len(texte)} caractères)")
            elevenlabs.synthese(texte, voice_id, f, modele=modele, graine=1000 + k)
        fichiers.append(f)
    return fichiers


def monter(c, rendu, segs, voix_wav, duree, sortie):
    """Images + plans + voix + musique → MP4 final (mêmes réglages que assembler)."""
    frames, taille = images_rendu(rendu)
    chaines = [f"[0:v]trim=start_frame={d}:end_frame={f},setpts=PTS-STARTPTS,{filtre_plan(p, c, taille)}[s{i}]"
               for i, (d, f, p) in enumerate(segs)]
    fondu = 1.0
    fc = (";".join(chaines) + ";" + "".join(f"[s{i}]" for i in range(len(segs)))
          + f"concat=n={len(segs)}:v=1:a=0[cc];{finition_video(c, 'cc', 'ff')};"
          + f"[ff]fade=t=in:st=0:d=0.3,fade=t=out:st={duree - fondu:.3f}:d={fondu}[v];")
    if c.get("ambiance"):
        piece = Path(voix_wav).with_name("voix-piece.wav")
        A.ecrire(piece, son_de_la_piece(A.lire(voix_wav), c))
        voix_wav = piece
    entrees = ["-framerate", str(FPS), "-i", str(frames / "%05d.png"), "-i", str(voix_wav)]
    musique = c.get("musique")
    if musique and (ICI / musique).exists():
        entrees += ["-stream_loop", "-1", "-i", str(ICI / musique)]
        fc += (f"[2:a]atrim=0:{duree:.3f},volume={c.get('musique_volume_db', -24)}dB,afade=t=in:d=1.5[m];"
               f"[1:a][m]amix=inputs=2:duration=first:normalize=0[mx];[mx]")
    else:
        fc += "[1:a]"
    micro = FILTRE_MICRO + "," if c.get("ambiance") else ""
    fc += f"{micro}loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st={duree - fondu:.3f}:d={fondu},aresample=48000[a]"
    ffmpeg(["ffmpeg", "-v", "error", "-y", *entrees, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{duree:.3f}", str(sortie)])


def ajouter_historique(entree):
    """historique.json : une ligne par vidéo produite (lu par la page web)."""
    f = ICI / "historique.json"
    h = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    h.append(entree)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(h, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    tmp.replace(f)


def assembler(c, travail, salut, n, corps_mp4, sortie, corps_wav=None):
    """Salutation (images travail/rendu/frames + audio `salut`) + partie fixe → MP4 final."""
    n_salut = min(n, int(math.ceil(len(salut) / A.SR * FPS)))
    duree_salut = n_salut / FPS

    # audio complet : salutation calée sur sa vidéo + partie fixe
    corps = A.lire(corps_wav or dossier_corps(c) / "corps.wav")
    salut = salut[: int(duree_salut * A.SR)]
    salut = A.np.concatenate([salut, A.silence(duree_salut - len(salut) / A.SR)])
    voix = A.np.concatenate([salut, corps])
    A.ecrire(travail / "voix.wav", son_de_la_piece(voix, c))

    musique = c.get("musique")
    frames, taille = images_rendu(travail / "rendu")
    entrees = ["-framerate", str(FPS), "-i", str(frames / "%05d.png"),
               "-i", str(corps_mp4), "-i", str(travail / "voix.wav")]
    duree_tot = duree_salut + len(corps) / A.SR
    fondu = 1.0
    fc = (f"[0:v]trim=end_frame={n_salut},setpts=PTS-STARTPTS,{filtre_plan('large', c, taille)},fps={FPS}[g];"
          f"[1:v]setpts=PTS-STARTPTS,fps={FPS}[b];"
          f"[g][b]concat=n=2:v=1:a=0[cc];{finition_video(c, 'cc', 'ff')};"
          f"[ff]fade=t=in:st=0:d=0.3,fade=t=out:st={duree_tot - fondu:.3f}:d={fondu}[v];")
    if musique and (ICI / musique).exists():
        entrees += ["-stream_loop", "-1", "-i", str(ICI / musique)]
        vol = c.get("musique_volume_db", -24)
        fc += (f"[3:a]atrim=0:{duree_tot:.3f},volume={vol}dB,afade=t=in:d=1.5[m];"
               f"[2:a][m]amix=inputs=2:duration=first:normalize=0[mx];[mx]")
    else:
        fc += "[2:a]"
    micro = FILTRE_MICRO + "," if c.get("ambiance") else ""
    fc += (f"{micro}loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st={duree_tot - fondu:.3f}:d={fondu},"
           "aresample=48000[a]")
    ffmpeg(["ffmpeg", "-v", "error", "-y", *entrees, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{duree_tot:.3f}", str(sortie)])
    return duree_tot


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    pc = sp.add_parser("preparer-corps")
    pc.add_argument("--etape", choices=["tout", "voix", "video", "superresolution", "composer"], default="tout")
    pc.add_argument("--refaire-voix", action="store_true")
    pc.add_argument("--dossier", help="dossier de la partie fixe (remplace dossier_corps de config.json)")
    pv = pc.add_mutually_exclusive_group()
    pv.add_argument("--audio", nargs="+", help="prises du message (ou du texte complet) au lieu de la voix gratuite")
    pv.add_argument("--elevenlabs", metavar="VOICE_ID", help="message dit par cette voix ElevenLabs")
    pv.add_argument("--depuis-complet", metavar="DOSSIER",
                    help="reprend le message d'une vidéo « complet » déjà animée (travail/<nom>)")
    pc.add_argument("--essais", type=int, default=2, help="prises ElevenLabs du message")
    pc.add_argument("--voix", help="nom de la voix, affiché dans l'historique")
    pc.add_argument("--suffixe", help="ajouté au nom des vidéos faites avec cette partie fixe")
    pc.add_argument("--ralenti", type=float, help="débit (remplace ralenti_voix)")
    pg = sp.add_parser("generer")
    pg.add_argument("prenom", nargs="?")
    pg.add_argument("--prononciation")
    pg.add_argument("--liste")
    pg.add_argument("--dossier-corps", help="partie fixe à utiliser (remplace dossier_corps de config.json)")
    pgv = pg.add_mutually_exclusive_group()
    pgv.add_argument("--salut-audio", nargs="+", help="prises de la salutation (ou du texte complet)")
    pgv.add_argument("--elevenlabs", metavar="VOICE_ID", help="salutation dite par cette voix ElevenLabs")
    pg.add_argument("--suffixe", help="ajouté au nom du fichier")
    pk = sp.add_parser("complet", help="vidéo entière à partir d'un enregistrement complet (une seule voix)")
    pk.add_argument("prenom")
    src = pk.add_mutually_exclusive_group(required=True)
    src.add_argument("--audio", nargs="+", help="une ou plusieurs prises du texte complet")
    src.add_argument("--elevenlabs", metavar="VOICE_ID", help="fait dire le texte complet par cette voix ElevenLabs")
    pk.add_argument("--modele-elevenlabs", help="modèle ElevenLabs (défaut eleven_multilingual_v2)")
    pk.add_argument("--essais", type=int, default=2, help="nombre de prises ElevenLabs (chacune coûte des crédits)")
    pk.add_argument("--prononciation", help="orthographe utilisée pour l'enregistrement")
    pk.add_argument("--suffixe", help="ajouté au nom du fichier, ex. paul-k")
    pk.add_argument("--voix", help="nom de la voix, affiché dans l'historique")
    pk.add_argument("--ralenti", type=float, default=1.0)
    a = p.parse_args()
    (ICI / "logs").mkdir(exist_ok=True)
    c = cfg()
    if a.cmd == "preparer-corps":
        if a.dossier:
            c["dossier_corps"] = a.dossier
        if a.ralenti:
            c["ralenti_voix"] = a.ralenti
        if a.depuis_complet:
            corps_depuis_complet(c, ICI / a.depuis_complet, a.voix, a.ralenti, a.suffixe)
            return
        externes, infos = None, {}
        if a.elevenlabs:
            texte = " ".join(p["texte"] for p in c["corps"])
            externes = prises_elevenlabs("message", a.elevenlabs, c, essais=a.essais, texte=texte, nom_fichier="corps")
            infos = {"voix": a.voix or "ElevenLabs", "elevenlabs_id": a.elevenlabs, "suffixe": a.suffixe or "elevenlabs"}
        elif a.audio:
            externes = [Path(f) for f in a.audio]
            infos = {"voix": a.voix, "suffixe": a.suffixe}
        if a.etape in ("tout", "voix"):
            voix_corps(c, a.refaire_voix, externes)
            if externes:
                (dossier_corps(c) / "voix.json").write_text(json.dumps(
                    {**infos, "ralenti": c.get("ralenti_voix")}, ensure_ascii=False), encoding="utf-8")
        if a.etape in ("tout", "video"):
            video_corps(c)
        if a.etape == "superresolution":  # images déjà animées : seulement agrandir puis remonter
            superresolution(c, dossier_corps(c) / "rendu", "corps", reprendre=True)
            composer_corps(c)
        if a.etape == "composer":
            composer_corps(c)
    elif a.cmd == "complet":
        if a.elevenlabs:
            audios = prises_elevenlabs(a.prenom, a.elevenlabs, c, a.prononciation, a.essais, a.modele_elevenlabs)
        else:
            audios = [Path(f) for f in a.audio]
        generer_complet(a.prenom, audios, c, a.prononciation, a.suffixe, a.voix, a.ralenti)
    else:
        if a.dossier_corps:
            c["dossier_corps"] = a.dossier_corps
        options = {"salut_audio": [Path(f) for f in a.salut_audio] if a.salut_audio else None,
                   "elevenlabs_id": a.elevenlabs, "suffixe": a.suffixe}
        if a.liste:
            for ligne in Path(a.liste).read_text(encoding="utf-8").splitlines():
                if ligne.strip():
                    nom, _, pron = ligne.partition(";")
                    generer(nom.strip(), pron.strip() or None, c, **options)
        elif a.prenom:
            generer(a.prenom, a.prononciation, c, **options)
        else:
            p.error("donner un prénom ou --liste")


if __name__ == "__main__":
    main()
