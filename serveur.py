"""Page web locale du générateur : saisir un prénom, suivre le calcul en direct, revoir les vidéos.

  python serveur.py      puis http://127.0.0.1:5195  (avec le Python du projet)
  (ou double-clic sur Ouvrir-Pere-Noel.cmd)

Bibliothèque standard uniquement. Une génération à la fois (une seule carte graphique) :
les prénoms suivants attendent dans une file. Chaque génération lance
« pere_noel.py generer » et lit ses événements « @evt {...} ».
"""
import json
import mimetypes
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ICI = Path(__file__).resolve().parent
PY = Path(sys.executable)  # même environnement Python que le serveur
PORT = int(os.environ.get("PERE_NOEL_PORT", "5195"))
WEB = ICI / "web"
EXPORTS = ICI / "exports"
HISTORIQUE = ICI / "historique.json"
LOG_COMFY = ICI / "logs" / "comfyui.log"
VIGNETTES = ICI / "cache" / "vignettes"
# fichiers que la page peut lire (rien d'autre n'est servi)
LISIBLES = [EXPORTS, ICI / "travail", ICI / "base" / "santa.png", VIGNETTES, WEB]

PRENOM_OK = re.compile(r"^[^\W\d_]+(?:[ '’\-][^\W\d_]+)*$")

verrou = threading.Lock()
reveil = threading.Event()
attente = []        # jobs en file
courant = None      # job en cours
termines = []       # jobs finis depuis le lancement du serveur (le plus récent d'abord)


def nouveau_job(prenom, prononciation):
    return {"id": uuid.uuid4().hex[:10], "prenom": prenom, "prononciation": prononciation or None,
            "statut": "attente", "demande": time.time(), "debut": None, "fin": None,
            "etape": None, "etapes": {}, "texte": None, "prises": [], "choix": None, "voix": None,
            "morceau": None, "offset_log": None, "comfyui_pret": True, "alerte": None,
            "fichier": None, "duree": None, "temps_calcul": None, "erreur": None, "journal": []}


# ---------------------------------------------------------------- génération

def pas_comfyui(offset):
    """Dernière étape d'échantillonnage (« 4/6 ») écrite par ComfyUI depuis `offset`."""
    if offset is None:
        return None
    try:
        with open(LOG_COMFY, "rb") as f:
            taille = f.seek(0, 2)
            f.seek(max(offset if offset <= taille else 0, taille - 30000))
            data = f.read()
    except OSError:
        return None
    m = re.findall(rb"(\d+)/(\d+) \[", data)
    return [int(m[-1][0]), int(m[-1][1])] if m else None


def traiter(job, e):
    t = e.get("type")
    if t == "etape":
        job["etape"] = e["nom"]
        job["etapes"][e["nom"]] = time.time()
        if e.get("texte"):
            job["texte"] = e["texte"]
        if e["nom"] == "animation":
            job["comfyui_pret"] = bool(e.get("comfyui_pret", True))
    elif t == "prise":
        job["prises"].append({"fichier": e["fichier"], "duree": e.get("duree")})
    elif t == "choix":
        job["choix"] = e["prises"]
    elif t == "voix":
        job["voix"] = e["fichier"]
    elif t == "alerte":
        job["alerte"] = e.get("message")
    elif t == "morceau":
        job["morceau"] = {"k": e["k"], "n": e["n"]}
        try:
            job["offset_log"] = LOG_COMFY.stat().st_size
        except OSError:
            job["offset_log"] = 0
    elif t == "fini":
        job["statut"] = "fini"
        job["fichier"] = e["fichier"]
        job["duree"] = e.get("duree")
        job["temps_calcul"] = e.get("temps_calcul")


def lancer(job):
    cmd = [str(PY), "-u", str(ICI / "pere_noel.py"), "generer", job["prenom"]]
    if job["prononciation"]:
        cmd += ["--prononciation", job["prononciation"]]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PERE_NOEL_EVT": "1"}
    p = subprocess.Popen(cmd, cwd=ICI, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", env=env,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for ligne in p.stdout:
        ligne = ligne.rstrip()
        if ligne.startswith("@evt "):
            try:
                traiter(job, json.loads(ligne[5:]))
            except (ValueError, KeyError):
                pass
        elif ligne:
            job["journal"].append(ligne)
            del job["journal"][:-300]
    p.wait()
    if p.returncode != 0 or job["statut"] != "fini":
        job["statut"] = "erreur"
        job["erreur"] = "\n".join(job["journal"][-25:]) or f"code de sortie {p.returncode}"


def travailleur():
    global courant
    while True:
        reveil.wait()
        with verrou:
            if not attente:
                reveil.clear()
                continue
            job = attente.pop(0)
            job["statut"] = "en_cours"
            job["debut"] = time.time()
            courant = job
        try:
            lancer(job)
        except Exception as ex:  # noqa: BLE001 - toute panne doit remonter dans la page
            job["statut"] = "erreur"
            job["erreur"] = f"{type(ex).__name__} : {ex}"
        job["fin"] = time.time()
        with verrou:
            termines.insert(0, job)
            del termines[30:]
            courant = None


# ---------------------------------------------------------------- historique

def lire_historique():
    try:
        h = json.loads(HISTORIQUE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        h = []
    par_fichier = {e["fichier"]: e for e in h if e.get("fichier")}
    for f in EXPORTS.glob("*.mp4"):  # vidéos faites hors historique (anciennes, ligne de commande)
        if f.name not in par_fichier:
            nom = re.sub(r"^pere-noel-|(-v\d+)?\.mp4$", "", f.name).replace("-", " ").title()
            par_fichier[f.name] = {"prenom": nom, "fichier": f.name,
                                   "cree": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(f.stat().st_mtime))}
    res = []
    for e in par_fichier.values():
        f = EXPORTS / e["fichier"]
        if not f.exists():
            continue
        m = re.search(r"-v(\d+)\.mp4$", e["fichier"])
        res.append({**e, "version": int(m.group(1)) if m else 1, "taille": f.stat().st_size,
                    "url": "/f/exports/" + e["fichier"], "vignette": "/vignette/" + e["fichier"]})
    res.sort(key=lambda e: e.get("cree", ""), reverse=True)
    return res


def signature_historique():
    try:
        s = HISTORIQUE.stat().st_mtime_ns
    except OSError:
        s = 0
    return f"{s}-{sum(1 for _ in EXPORTS.glob('*.mp4'))}"


def estimation():
    temps = [e["temps_calcul"] for e in lire_historique() if e.get("temps_calcul")]
    return round(statistics.median(temps[:6])) if temps else 420


def vignette(nom):
    src = EXPORTS / nom
    if not re.fullmatch(r"[\w\-]+\.mp4", nom) or not src.exists():
        return None
    VIGNETTES.mkdir(parents=True, exist_ok=True)
    dst = VIGNETTES / (src.stem + ".jpg")
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.6", "-i", str(src), "-frames:v", "1",
                        "-vf", "scale=640:-2", "-q:v", "3", str(dst)],
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return dst if dst.exists() else None


# ---------------------------------------------------------------- état pour la page

def public(job):
    if job is None:
        return None
    j = {k: v for k, v in job.items() if k not in ("offset_log",)}
    j["journal"] = job["journal"][-120:]
    if job["statut"] == "en_cours":
        j["ecoule"] = round(time.time() - job["debut"], 1)
        if job["etape"] == "animation":
            j["pas"] = pas_comfyui(job["offset_log"])
    elif job["debut"]:
        j["ecoule"] = round((job["fin"] or time.time()) - job["debut"], 1)
    return j


def etat():
    with verrou:
        return {"courant": public(courant), "attente": [public(j) for j in attente],
                "termines": [public(j) for j in termines[:10]],
                "historique": signature_historique(), "estimation": estimation()}


def ajouter(prenom, prononciation):
    prenom = re.sub(r"\s+", " ", (prenom or "").strip())
    prononciation = re.sub(r"\s+", " ", (prononciation or "").strip()) or None
    if not prenom or len(prenom) > 40 or not PRENOM_OK.match(prenom):
        raise ValueError("Prénom invalide : lettres, espaces, tirets ou apostrophes, 40 caractères au plus.")
    if prononciation and (len(prononciation) > 60 or not PRENOM_OK.match(prononciation)):
        raise ValueError("Prononciation invalide : lettres, espaces, tirets ou apostrophes seulement.")
    job = nouveau_job(prenom, prononciation)
    with verrou:
        attente.append(job)
    reveil.set()
    return job


def retirer(id_):
    with verrou:
        for j in attente:
            if j["id"] == id_:
                attente.remove(j)
                return True
    return False


# ---------------------------------------------------------------- HTTP

def autorise(chemin: Path):
    chemin = chemin.resolve()
    for base in LISIBLES:
        base = base.resolve()
        if chemin == base or base in chemin.parents:
            return chemin.is_file()
    return False


class Gestion(BaseHTTPRequestHandler):
    server_version = "PereNoel/1.0"

    def log_message(self, *a):
        pass

    def json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def fichier(self, chemin: Path, cache="no-cache"):
        if not autorise(chemin):
            return self.send_error(404)
        taille = chemin.stat().st_size
        ctype = mimetypes.guess_type(chemin.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        debut, fin, code = 0, taille - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                debut = int(m.group(1))
                fin = min(int(m.group(2)), taille - 1) if m.group(2) else taille - 1
            else:
                debut = max(0, taille - int(m.group(2)))
            if debut > fin:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{taille}")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(fin - debut + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", cache)
        if code == 206:
            self.send_header("Content-Range", f"bytes {debut}-{fin}/{taille}")
        self.end_headers()
        try:
            with open(chemin, "rb") as f:
                f.seek(debut)
                reste = fin - debut + 1
                while reste > 0:
                    bloc = f.read(min(1 << 16, reste))
                    if not bloc:
                        break
                    self.wfile.write(bloc)
                    reste -= len(bloc)
        except OSError:
            pass  # le navigateur a coupé (lecture vidéo, changement de position)

    def do_GET(self):
        url = urlparse(self.path)
        chemin = unquote(url.path)
        if chemin in ("/", "/index.html"):
            return self.fichier(WEB / "index.html")
        if chemin == "/api/etat":
            return self.json(etat())
        if chemin == "/api/historique":
            return self.json(lire_historique())
        if chemin.startswith("/vignette/"):
            v = vignette(chemin[len("/vignette/"):])
            return self.fichier(v, "max-age=3600") if v else self.send_error(404)
        if chemin.startswith("/f/"):
            return self.fichier(ICI / chemin[3:])
        if chemin.startswith("/web/"):
            return self.fichier(WEB / chemin[5:], "max-age=60")
        self.send_error(404)

    def do_POST(self):
        chemin = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", "0"))
            corps = json.loads(self.rfile.read(n) or b"{}") if n < 10000 else {}
        except ValueError:
            return self.json({"erreur": "Requête illisible."}, 400)
        if chemin == "/api/generer":
            try:
                job = ajouter(corps.get("prenom"), corps.get("prononciation"))
            except ValueError as ex:
                return self.json({"erreur": str(ex)}, 400)
            return self.json({"id": job["id"]})
        if chemin == "/api/retirer":
            return self.json({"ok": retirer(corps.get("id"))})
        self.send_error(404)


def main():
    threading.Thread(target=travailleur, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Gestion)
    srv.daemon_threads = True
    print(f"Père Noël : http://127.0.0.1:{PORT}  (Ctrl+C pour arrêter)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
