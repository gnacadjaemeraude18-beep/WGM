#!/usr/bin/env python3
"""
Faux boîtier WGM : imite le firmware esp32_controller.ino pour tester
l'application Flutter sans matériel. Aucune dépendance (Python 3.8+).

Lancer :   python tools/fake_esp32.py
Options :  --port 8080   --speed 1   --state fake_esp32_state.json   --key <clé API>
La clé peut aussi venir de la variable d'environnement WGM_API_KEY.

Comportement repris du firmware :
  - routes /activate /stop /resume /status /update
  - clé obligatoire sauf pour /status
  - décompte d'une seconde par seconde, sauvegarde "flash" quand le temps
    restant est un multiple de 60 s, et à chaque activation / arrêt
  - au démarrage : temps sauvegardé >= 600 s -> session en "coupure" (attend /resume),
    sinon la session est effacée (règle des 10 minutes)

Pour simuler une coupure de courant : tuer le script (Ctrl+C) puis le relancer.
Le script ne sauvegarde PAS en quittant, comme un vrai boîtier privé de courant.

--speed N accélère le temps (ex. 60 = 1 minute par seconde). L'appli se recale
sur le boîtier toutes les 5 s, donc son affichage saute : c'est normal.
"""
import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

SECRET_KEY = os.environ.get("WGM_API_KEY", "cle-de-test")   # doit être celle de l'appli (lib/secrets.dart)
NB_POSTES = 10
MIN_REPRISE = 600                          # règle des 10 minutes (secondes)

lock = threading.Lock()
sessions = [{"active": False, "isCoupure": False, "remains": 0} for _ in range(NB_POSTES)]
flash = {}                                 # imite Preferences (NVS)
state_path = "fake_esp32_state.json"


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def save_flash():
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(flash, f)


def save_session(i):
    flash[f"p{i}"] = sessions[i]["remains"]
    save_flash()


def stop_poste(i):
    sessions[i].update(active=False, isCoupure=False, remains=0)
    save_session(i)
    log(f"P{i + 1}: relais OFF")


def boot():
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            flash.update(json.load(f))
    for i in range(NB_POSTES):
        last = int(flash.get(f"p{i}", 0))
        if last >= MIN_REPRISE:
            sessions[i].update(active=True, isCoupure=True, remains=last)
            log(f"P{i + 1}: coupure détectée, {last} s restantes, attente de /resume")
        else:
            flash[f"p{i}"] = 0
    save_flash()


def ticker(speed):
    while True:
        time.sleep(1.0 / speed)
        with lock:
            for i, s in enumerate(sessions):
                if s["active"] and not s["isCoupure"]:
                    s["remains"] -= 1
                    if s["remains"] % 60 == 0:
                        save_session(i)
                    if s["remains"] <= 0:
                        stop_poste(i)


def poste_index(args):
    """Reproduit : id.substring(1).toInt() - 1 (valide si 0 <= index < NB_POSTES)."""
    try:
        idx = int(args.get("id", [""])[0][1:]) - 1
    except ValueError:
        return None
    return idx if 0 <= idx < NB_POSTES else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        pass  # on journalise nous-mêmes

    def reply(self, code, body, ctype="text/plain"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self, args):
        return args.get("key", [""])[0] == SECRET_KEY

    def do_GET(self):
        url = urlparse(self.path)
        args = parse_qs(url.query, keep_blank_values=True)
        route = url.path

        if route == "/status":
            with lock:
                postes = [
                    {"id": f"P{i + 1}", "active": s["active"],
                     "isCoupure": s["isCoupure"], "remains": s["remains"]}
                    for i, s in enumerate(sessions)
                ]
            return self.reply(200, json.dumps({"postes": postes}), "application/json")

        if route not in ("/activate", "/stop", "/resume"):
            return self.reply(404, "NOT FOUND")

        if not self.authorized(args):
            log(f"{route}: REFUSÉ, clé reçue = {args.get('key', [''])[0]!r}")
            return self.reply(401, "NON AUTORISE")

        i = poste_index(args)
        if i is None:
            log(f"{route}: id invalide ({args.get('id')})")
            return self.reply(400, "ID INVALIDE")

        with lock:
            s = sessions[i]
            if route == "/activate":
                minutes = int(args.get("time", ["0"])[0] or 0)
                s["remains"] += minutes * 60
                s.update(active=True, isCoupure=False)
                save_session(i)
                log(f"P{i + 1}: relais ON, +{minutes} min (reste {s['remains']} s)")
            elif route == "/resume":
                if not s["isCoupure"]:
                    return self.reply(409, "PAS EN COUPURE")
                s["isCoupure"] = False
                log(f"P{i + 1}: reprise, relais ON ({s['remains']} s)")
            elif route == "/stop":
                stop_poste(i)
        self.reply(200, "OK")

    def do_POST(self):
        url = urlparse(self.path)
        args = parse_qs(url.query, keep_blank_values=True)
        length = int(self.headers.get("Content-Length", 0))
        remaining, received = length, 0
        while remaining > 0:                 # on lit le corps pour ne pas couper la connexion
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            received += len(chunk)

        if url.path != "/update":
            return self.reply(404, "NOT FOUND")
        if not self.authorized(args):
            log(f"/update: REFUSÉ (clé invalide), {received} octets ignorés, RIEN écrit en flash")
            return self.reply(401, "NON AUTORISE")
        log(f"/update: {received} octets reçus, firmware accepté (redémarrage simulé)")
        self.reply(200, "OK")


def main():
    global state_path, SECRET_KEY
    ap = argparse.ArgumentParser(description="Faux boîtier WGM")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--state", default=state_path)
    ap.add_argument("--key", default=None, help="clé API (sinon WGM_API_KEY, sinon 'cle-de-test')")
    a = ap.parse_args()
    state_path = a.state
    if a.key:
        SECRET_KEY = a.key

    boot()
    threading.Thread(target=ticker, args=(a.speed,), daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    log(f"Faux boîtier WGM prêt sur http://127.0.0.1:{a.port} (vitesse x{a.speed})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("Coupure de courant simulée (aucune sauvegarde finale)")
        sys.exit(0)


if __name__ == "__main__":
    main()
