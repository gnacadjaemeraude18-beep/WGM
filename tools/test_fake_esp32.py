#!/usr/bin/env python3
"""
Tests automatiques du faux boîtier (et du protocole utilisé par l'appli).
Lancer :  python tools/test_fake_esp32.py
Il démarre lui-même le faux boîtier sur le port 8099 avec un fichier d'état temporaire.
"""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PORT = 8099
KEY = "T#st!k*y$1@x"   # clé de test avec des caractères spéciaux (# ! * $ @), comme une vraie clé
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(tempfile.mkdtemp(), "state.json")

ok_count = 0
fail_count = 0


def check(name, cond, detail=""):
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print(f"  OK    {name}")
    else:
        fail_count += 1
        print(f"  ECHEC {name} {detail}")


def start():
    p = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "fake_esp32.py"), "--port", str(PORT), "--state", STATE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "WGM_API_KEY": KEY})
    for _ in range(50):
        try:
            get("/status", key=False)
            return p
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("le faux boîtier ne démarre pas")


def get(path, params=None, key=True):
    q = dict(params or {})
    if key:
        q["key"] = KEY
    url = f"http://127.0.0.1:{PORT}{path}"
    if q:
        url += "?" + urllib.parse.urlencode(q)      # même encodage que Uri.http côté Dart
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def status():
    return {p["id"]: p for p in json.loads(get("/status", key=False)[1])["postes"]}


def kill(p):
    p.kill()           # pas de sauvegarde finale = coupure de courant
    p.wait()


print("== Clé et routes ==")
proc = start()
check("/status accessible sans clé", get("/status", key=False)[0] == 200)
check("/activate sans clé -> 401", get("/activate", {"id": "P1", "time": 1}, key=False)[0] == 401)
check("/stop sans clé -> 401", get("/stop", {"id": "P1"}, key=False)[0] == 401)

# Ce que envoyait l'ancien code Dart : '#' non encodé, l'URL est coupée après "X9"
conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=3)
conn.request("GET", f"/activate?id=P1&time=1&key={KEY}".split("#")[0])
check("clé tronquée à 'X9' (ancien bug du '#') -> 401", conn.getresponse().status == 401)
conn.close()

check("/activate avec clé encodée -> 200", get("/activate", {"id": "P1", "time": 1})[0] == 200)
s = status()["P1"]
check("P1 active avec ~60 s restantes", s["active"] and 55 <= s["remains"] <= 60, str(s))
check("id invalide -> 400", get("/activate", {"id": "P99", "time": 1})[0] == 400)

print("== Cumul de temps et arrêt ==")
get("/activate", {"id": "P1", "time": 2})
check("temps cumulé (~3 min)", 175 <= status()["P1"]["remains"] <= 180, str(status()["P1"]))
check("/stop -> 200", get("/stop", {"id": "P1"})[0] == 200)
check("P1 arrêtée, 0 s", not status()["P1"]["active"] and status()["P1"]["remains"] == 0)

print("== Coupure de courant ==")
get("/activate", {"id": "P3", "time": 15})   # 900 s : reprise possible
get("/activate", {"id": "P4", "time": 5})    # 300 s : < 10 min, doit être annulée
kill(proc)
proc = start()
s = status()
check("P3 (15 min) en coupure après redémarrage", s["P3"]["active"] and s["P3"]["isCoupure"], str(s["P3"]))
check("P3 garde son temps (~900 s)", 890 <= s["P3"]["remains"] <= 900, str(s["P3"]))
check("P4 (5 min) annulée (règle des 10 min)", not s["P4"]["active"] and s["P4"]["remains"] == 0, str(s["P4"]))
check("/resume sans clé -> 401", get("/resume", {"id": "P3"}, key=False)[0] == 401)
check("/resume avec clé -> 200", get("/resume", {"id": "P3"})[0] == 200)
check("P3 reprend, plus en coupure", not status()["P3"]["isCoupure"])
check("/resume hors coupure -> 409", get("/resume", {"id": "P3"})[0] == 409)

print("== Mise à jour firmware ==")
def post_update(with_key):
    boundary = "----wgm"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"update\"; filename=\"update.bin\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + os.urandom(200000) + f"\r\n--{boundary}--\r\n".encode()
    path = "/update" + ("?" + urllib.parse.urlencode({"key": KEY}) if with_key else "")
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    c.request("POST", path, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    code = c.getresponse().status
    c.close()
    return code
check("/update sans clé -> 401", post_update(False) == 401)
check("/update avec clé -> 200", post_update(True) == 200)

kill(proc)
print(f"\n{ok_count} réussis, {fail_count} échoués")
sys.exit(1 if fail_count else 0)
