"""Télécharge les modèles d'animation dans ComfyUI (environ 31 Go, reprise possible).

  python outils/telecharger_modeles.py                      # dossier ComfyUI lu dans config.json
  python outils/telecharger_modeles.py D:/ComfyUI_windows_portable

Bibliothèque standard uniquement. Un téléchargement interrompu reprend là où il s'était arrêté.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
HF = "https://huggingface.co"
WAN = "Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files"

# (dossier de ComfyUI/models, chemin sur Hugging Face, taille en octets)
MODELES = [
    ("diffusion_models", f"{WAN}/diffusion_models/wan2.1_i2v_480p_14B_fp8_scaled.safetensors", 16401356938),
    ("text_encoders", f"{WAN}/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", 6735906897),
    ("model_patches", f"{WAN}/model_patches/wan2.1_infiniteTalk_single_fp16.safetensors", 5125258232),
    ("clip_vision", f"{WAN}/clip_vision/clip_vision_h.safetensors", 1264219396),
    ("loras", "Kijai/WanVideo_comfy/resolve/main/Lightx2v/"
              "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", 738005744),
    ("vae", f"{WAN}/vae/wan_2.1_vae.safetensors", 253815318),
    ("audio_encoders", "Kijai/wav2vec2_safetensors/resolve/main/wav2vec2-chinese-base_fp16.safetensors", 190115368),
]


def dossier_comfyui():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    c = json.loads((RACINE / "config.json").read_text(encoding="utf-8"))
    r = Path(c.get("comfyui", "outils/ComfyUI_windows_portable"))
    return r if r.is_absolute() else RACINE / r


def telecharger(url, dest, taille):
    deja = dest.stat().st_size if dest.exists() else 0
    if deja == taille:
        print(f"  déjà là : {dest.name}")
        return
    req = urllib.request.Request(url, headers={"Range": f"bytes={deja}-"} if deja else {})
    t0, recu = time.time(), deja
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "ab" if deja else "wb") as f:
        while True:
            bloc = r.read(1 << 22)
            if not bloc:
                break
            f.write(bloc)
            recu += len(bloc)
            vitesse = (recu - deja) / max(1e-3, time.time() - t0) / 1e6
            print(f"\r  {dest.name} : {recu / 1e9:5.2f} / {taille / 1e9:.2f} Go  ({vitesse:.0f} Mo/s)   ",
                  end="", flush=True)
    print()
    if dest.stat().st_size != taille:
        raise RuntimeError(f"Taille inattendue pour {dest.name} : relancer le script pour reprendre.")


def main():
    racine = dossier_comfyui()
    modeles = racine / "ComfyUI" / "models"
    if not modeles.is_dir():
        raise SystemExit(f"ComfyUI introuvable : {modeles} n'existe pas. Installer ComfyUI portable d'abord.")
    for sous, chemin, taille in MODELES:
        dest = modeles / sous / Path(chemin).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        telecharger(f"{HF}/{chemin}", dest, taille)
    print("Modèles prêts.")


if __name__ == "__main__":
    main()
