"""Rendu d'un Père Noël qui parle avec InfiniteTalk (Wan 2.1 I2V 14B) via ComfyUI.

La vidéo est produite par morceaux de 81 images (3,24 s à 25 i/s). Chaque morceau suivant
reprend les 9 dernières images du précédent comme contexte de mouvement ; l'audio est découpé
pour commencer à la première de ces 9 images.
"""
import math
import shutil
import time
from pathlib import Path

import audio as A
import comfy

FPS = 25
MOTION = 9
MAX_LEN = 81


def _len4(n):
    """Plus petit 4k+1 >= n."""
    return int(math.ceil((n - 1) / 4) * 4 + 1)


def graphe(cfg, image, son, longueur, precedentes, graine, prefixe):
    g = {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.1_i2v_480p_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["unet", 0], "lora_name": "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", "strength_model": 1.0}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "patch": {"class_type": "ModelPatchLoader", "inputs": {"name": "wan2.1_infiniteTalk_single_fp16.safetensors"}},
        "aenc": {"class_type": "AudioEncoderLoader", "inputs": {"audio_encoder_name": "wav2vec2-chinese-base_fp16.safetensors"}},
        "son": {"class_type": "LoadAudio", "inputs": {"audio": son}},
        "aout": {"class_type": "AudioEncoderEncode", "inputs": {"audio_encoder": ["aenc", 0], "audio": ["son", 0]}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"text": cfg["prompt_video"], "clip": ["clip", 0]}},
        "neg": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["pos", 0]}},
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "cvl": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "clip_vision_h.safetensors"}},
        "cv": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["cvl", 0], "image": ["img", 0], "crop": "none"}},
        "it": {"class_type": "WanInfiniteTalkToVideo", "inputs": {
            "mode": "single_speaker", "model": ["lora", 0], "model_patch": ["patch", 0],
            "positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0],
            "width": cfg["largeur"], "height": cfg["hauteur"], "length": longueur,
            "clip_vision_output": ["cv", 0], "start_image": ["img", 0],
            "audio_encoder_output_1": ["aout", 0], "motion_frame_count": MOTION, "audio_scale": 1.0}},
        "bruit": {"class_type": "RandomNoise", "inputs": {"noise_seed": graine}},
        "guide": {"class_type": "CFGGuider", "inputs": {"model": ["it", 0], "positive": ["it", 1], "negative": ["it", 2], "cfg": 1.0}},
        "ech": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "sigmas": {"class_type": "BasicScheduler", "inputs": {"model": ["it", 0], "scheduler": "normal", "steps": cfg.get("etapes", 6), "denoise": 1.0}},
        "samp": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["bruit", 0], "guider": ["guide", 0], "sampler": ["ech", 0], "sigmas": ["sigmas", 0], "latent_image": ["it", 3]}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["samp", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefixe, "images": ["dec", 0]}},
    }
    if precedentes:
        dernier = None
        for i, nom in enumerate(precedentes):
            g[f"p{i}"] = {"class_type": "LoadImage", "inputs": {"image": nom}}
            if dernier is None:
                dernier = [f"p{i}", 0]
            else:
                g[f"b{i}"] = {"class_type": "ImageBatch", "inputs": {"image1": dernier, "image2": [f"p{i}", 0]}}
                dernier = [f"b{i}", 0]
        g["it"]["inputs"]["previous_frames"] = dernier
    return g


def rendre(cfg, portrait: Path, son: Path, dossier: Path, etiquette: str, graine: int, journal=print,
           progres=None):
    """Rend la vidéo parlante de `son` à partir de `portrait`. Écrit dossier/frames/00000.png...

    `progres(k, nb_morceaux, faites, total)` est appelé avant chaque morceau.
    Renvoie le nombre d'images (>= durée audio x 25).
    """
    frames = dossier / "frames"
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir(parents=True)
    tmp = dossier / "morceaux"
    tmp.mkdir(parents=True, exist_ok=True)

    y = A.lire(son, 16000)
    total = int(math.ceil(len(y) / 16000 * FPS))
    image = comfy.deposer(portrait, f"pere-noel/{etiquette}")
    faites = 0
    k = 0
    t_debut = time.time()
    while faites < total:
        k += 1
        if k == 1:
            longueur = min(MAX_LEN, _len4(total))
            debut_audio = 0.0
            precedentes = []
        else:
            reste = total - faites
            longueur = min(MAX_LEN, _len4(reste + MOTION))
            debut_audio = (faites - MOTION) / FPS
            precedentes = [comfy.deposer(frames / f"{i:05d}.png", f"pere-noel/{etiquette}/prev{k}")
                           for i in range(faites - MOTION, faites)]
        # audio du morceau : depuis debut_audio, complété de silence jusqu'à la longueur demandée
        seg = y[int(round(debut_audio * 16000)):]
        besoin = int(math.ceil(longueur / FPS * 16000)) + 1600
        seg = seg[:besoin]
        if len(seg) < besoin:
            seg = A.np.concatenate([seg, A.np.zeros(besoin - len(seg), A.np.float32)])
        f_son = tmp / f"audio-{k:02d}.wav"
        A.ecrire(f_son, seg, 16000)
        nom_son = comfy.deposer(f_son, f"pere-noel/{etiquette}")
        journal(f"  morceau {k} : {longueur} images, audio à {debut_audio:.2f} s ({faites}/{total} faites)")
        if progres:
            progres(k, 1 + math.ceil(max(0, total - MAX_LEN) / (MAX_LEN - MOTION)), faites, total)
        prefixe = f"pere-noel/{etiquette}/m{k:02d}"
        entree = comfy.executer(graphe(cfg, image, nom_son, longueur, precedentes, graine + k, prefixe))
        sorties = comfy.fichiers_sortie(entree)
        garder = sorties if k == 1 else sorties[MOTION:]
        for f in garder:
            shutil.move(str(f), frames / f"{faites:05d}.png")
            faites += 1
        for f in sorties:
            if f.exists():
                f.unlink()
    journal(f"  {faites} images en {time.time() - t_debut:.0f} s")
    return faites


def encoder(dossier: Path, sortie: Path, son: Path = None, crf=14):
    """Assemble dossier/frames en MP4 (H.264, 25 i/s), avec l'audio si fourni."""
    import subprocess
    cmd = ["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", str(dossier / "frames" / "%05d.png")]
    if son:
        cmd += ["-i", str(son), "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p", str(sortie)]
    subprocess.run(cmd, check=True)
