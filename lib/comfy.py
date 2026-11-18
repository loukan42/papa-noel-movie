"""Client minimal de l'API ComfyUI (bibliothèque standard uniquement)."""
import json
import shutil
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

URL = "http://127.0.0.1:8188"
COMFY_DIR = Path(r"C:\AI\ComfyUI_windows_portable\ComfyUI")
INPUT_DIR = COMFY_DIR / "input"
OUTPUT_DIR = COMFY_DIR / "output"


def configurer(racine):
    """Indique le dossier de ComfyUI portable (celui qui contient python_embeded et ComfyUI)."""
    global COMFY_DIR, INPUT_DIR, OUTPUT_DIR
    COMFY_DIR = Path(racine) / "ComfyUI"
    INPUT_DIR = COMFY_DIR / "input"
    OUTPUT_DIR = COMFY_DIR / "output"


def _get(path):
    with urllib.request.urlopen(URL + path, timeout=30) as r:
        return json.loads(r.read())


def disponible():
    try:
        _get("/system_stats")
        return True
    except Exception:
        return False


def attendre_serveur(timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if disponible():
            return
        time.sleep(3)
    raise RuntimeError("ComfyUI ne répond pas sur " + URL)


def liberer():
    """Demande à ComfyUI de décharger ses modèles (mémoire vidéo et vive)."""
    try:
        req = urllib.request.Request(URL + "/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        time.sleep(3)
    except Exception:
        pass


def deposer(fichier: Path, sous_dossier="pere-noel") -> str:
    """Copie un fichier dans input/ de ComfyUI et renvoie le nom à donner aux nœuds Load*."""
    dest = INPUT_DIR / sous_dossier
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fichier, dest / Path(fichier).name)
    return f"{sous_dossier}/{Path(fichier).name}"


def executer(graphe: dict, timeout=7200, verbeux=True) -> dict:
    """Envoie un graphe au format API, attend la fin et renvoie l'entrée d'historique."""
    data = json.dumps({"prompt": graphe, "client_id": str(uuid.uuid4())}).encode()
    req = urllib.request.Request(URL + "/prompt", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            pid = json.loads(r.read())["prompt_id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError("ComfyUI a refusé le graphe : " + e.read().decode(errors="replace")) from e
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = _get("/history/" + pid)
        if pid in h:
            entree = h[pid]
            statut = entree.get("status", {})
            if statut.get("status_str") == "error":
                msgs = [m for m in statut.get("messages", []) if m[0] == "execution_error"]
                raise RuntimeError("Erreur ComfyUI : " + json.dumps(msgs, ensure_ascii=False)[:2000])
            if verbeux:
                print(f"  ComfyUI : terminé en {time.time() - t0:.0f} s", flush=True)
            return entree
        time.sleep(2)
    raise TimeoutError("ComfyUI n'a pas terminé à temps")


def fichiers_sortie(entree: dict, cle="images"):
    """Chemins locaux des fichiers produits (SaveImage, etc.), dans l'ordre."""
    res = []
    for sortie in entree.get("outputs", {}).values():
        for it in sortie.get(cle, []):
            res.append(OUTPUT_DIR / it.get("subfolder", "") / it["filename"])
    return res
