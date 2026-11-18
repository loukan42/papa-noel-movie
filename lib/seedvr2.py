"""Super-résolution vidéo SeedVR2 avec les nœuds natifs de ComfyUI.

Ajoute du détail réel (peau, barbe, tissus) aux images animées, avant les recadrages des plans.
Les images sont traitées par tranches qui se chevauchent (fondu sur le chevauchement), pour tenir
en mémoire vive.
"""
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image

import comfy

VAE = "seedvr2_ema_vae_fp16.safetensors"


def graphe(video, echelle, prefixe, modele, graine=42, couleur="lab"):
    return {
        "lv": {"class_type": "LoadVideo", "inputs": {"file": video}},
        "gc": {"class_type": "GetVideoComponents", "inputs": {"video": ["lv", 0]}},
        "rs": {"class_type": "ResizeImageMaskNode", "inputs": {
            "input": ["gc", 0], "resize_type": "scale by multiplier", "resize_type.multiplier": echelle,
            "scale_method": "lanczos"}},
        "pp": {"class_type": "SeedVR2Preprocess", "inputs": {"resized_images": ["rs", 0]}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": modele, "weight_dtype": "default"}},
        "enc": {"class_type": "VAEEncodeTiled", "inputs": {
            "pixels": ["pp", 0], "vae": ["vae", 0], "tile_size": 512, "overlap": 128,
            "temporal_size": 64, "temporal_overlap": 8}},
        "cond": {"class_type": "SeedVR2Conditioning", "inputs": {"model": ["unet", 0], "vae_conditioning": ["enc", 0]}},
        "ks": {"class_type": "KSampler", "inputs": {
            "model": ["unet", 0], "positive": ["cond", 0], "negative": ["cond", 1], "latent_image": ["enc", 0],
            "seed": graine, "steps": 1, "cfg": 1, "sampler_name": "euler", "scheduler": "simple", "denoise": 1}},
        "dec": {"class_type": "VAEDecodeTiled", "inputs": {
            "samples": ["ks", 0], "vae": ["vae", 0], "tile_size": 512, "overlap": 128,
            "temporal_size": 64, "temporal_overlap": 8}},
        "post": {"class_type": "SeedVR2PostProcessing", "inputs": {
            "images": ["dec", 0], "original_resized_images": ["rs", 0], "color_correction_method": couleur}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["post", 0], "filename_prefix": prefixe}},
    }


def ameliorer(source: Path, sortie: Path, etiquette: str, echelle=1.5, modele="seedvr2_3b_int8_convrot.safetensors",
              tranche=57, chevauchement=8, journal=print, images=None, reprendre=False):
    """Images source/%05d.png → sortie/%05d.png agrandies. Renvoie le nombre d'images.

    `reprendre` : garde les images déjà agrandies et saute les tranches complètes.
    """
    fichiers = sorted(source.glob("*.png"))
    if images:
        fichiers = fichiers[:images]
    n = len(fichiers)
    if sortie.exists() and not reprendre:
        shutil.rmtree(sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    comfy.liberer()  # le modèle d'animation occupe sinon une grande partie de la mémoire vive
    dossier_in = comfy.INPUT_DIR / "pere-noel" / "seedvr2"
    dossier_in.mkdir(parents=True, exist_ok=True)
    pas = tranche - chevauchement
    debut, k = 0, 0
    while debut < n:
        fin = min(n, debut + tranche)
        k += 1
        clip = dossier_in / f"{etiquette}-{k:03d}.mp4"
        if reprendre and all((sortie / f"{i:05d}.png").exists() for i in range(debut, fin)):
            if fin == n:
                break
            debut += pas
            continue
        # vidéo sans perte de la tranche, déposée dans input/ de ComfyUI (images numérotées %05d.png)
        cmd = ["ffmpeg", "-v", "error", "-y", "-framerate", "25", "-start_number", str(debut),
               "-i", str(source.resolve() / "%05d.png"), "-frames:v", str(fin - debut),
               "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(clip)]
        for essai in range(4):  # ffmpeg plante parfois quand la mémoire vive manque
            if subprocess.run(cmd).returncode == 0:
                break
            journal(f"  ffmpeg a échoué (essai {essai + 1}), nouvel essai")
            time.sleep(5)
        else:
            raise RuntimeError("ffmpeg échoue à préparer la tranche " + clip.name)
        journal(f"  super-résolution, tranche {k} : images {debut}-{fin - 1} sur {n}")
        entree = comfy.executer(graphe(f"pere-noel/seedvr2/{clip.name}", echelle,
                                       f"pere-noel/seedvr2/{etiquette}-{k:03d}", modele))
        sorties = [comfy.OUTPUT_DIR / it.get("subfolder", "") / it["filename"]
                   for it in entree.get("outputs", {}).get("save", {}).get("images", [])
                   if it.get("type", "output") == "output"]
        for i, f in enumerate(sorties[: fin - debut]):
            idx = debut + i
            dst = sortie / f"{idx:05d}.png"
            if dst.exists():  # chevauchement avec la tranche précédente : fondu linéaire
                a = (i + 1) / (chevauchement + 1)
                mix = (1 - a) * np.asarray(Image.open(dst), np.float32) + a * np.asarray(Image.open(f), np.float32)
                Image.fromarray(np.clip(mix + 0.5, 0, 255).astype(np.uint8)).save(dst)
                f.unlink()
            else:
                shutil.move(str(f), dst)
        for f in sorties:
            if f.exists():
                f.unlink()
        if len(sorties) < fin - debut:
            journal(f"  ATTENTION : {len(sorties)} images rendues pour {fin - debut} attendues")
        clip.unlink(missing_ok=True)
        if fin == n:
            break
        debut += pas
    return n
