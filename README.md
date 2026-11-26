# Winner Game Manager (WGM)

Système de gestion automatisée pour salles de jeux (PlayStation, Xbox, PC) :
un boîtier ESP32 coupe le courant d'un poste quand le temps payé est écoulé,
et une application Flutter pilote les postes depuis un PC ou un téléphone.

Le boîtier crée son propre WiFi privé, le système fonctionne donc sans internet.
Voir `RESUME.md` pour la présentation et `DOCUMENTATION_SYSTEME.md` pour l'architecture.

## Contenu

| Dossier / fichier | Rôle |
|---|---|
| `lib/` | Application Flutter (écrans gérant et admin, services boîtier, stockage, audit) |
| `hardware/esp32_controller.ino` | Firmware du boîtier (10 relais, serveur HTTP, minuteur, reprise après coupure) |
| `tools/` | Faux boîtier Python et ses tests, pour développer sans matériel |
| `build_project.bat`, `winner_setup.iss` | Compilation Windows et création de l'installateur (Inno Setup) |
| `GUIDE_INSTALLATION.txt` | Installation chez un client |

## Configuration des secrets (obligatoire avant de compiler)

Les mots de passe et la clé API ne sont pas dans le dépôt. Deux fichiers sont à créer à partir des modèles :

| Modèle | À copier en | Contenu |
|---|---|---|
| `lib/secrets.example.dart` | `lib/secrets.dart` | clé API, mot de passe administrateur de l'application |
| `hardware/secrets.example.h` | `hardware/secrets.h` | mot de passe WiFi du boîtier, clé API |

La clé API doit être **identique** dans les deux fichiers. Choisir une clé longue et aléatoire,
différente pour chaque installation.

## Lancer l'application sans boîtier

```
python tools/test_fake_esp32.py                    # vérifie le faux boîtier
python tools/fake_esp32.py --key <clé de lib/secrets.dart>   # le démarre sur le port 8080

flutter pub get
flutter run -d windows --dart-define=WGM_HOST=127.0.0.1:8080 --dart-define=WGM_SKIP_WIFI_CHECK=true
```

Pour simuler une coupure de courant, arrêter (Ctrl+C) puis relancer le faux boîtier.

## Firmware

Ouvrir `hardware/esp32_controller.ino` dans l'Arduino IDE, carte « ESP32 Dev Module »,
bibliothèque `RTClib` (Adafruit). Les routes `/activate`, `/stop`, `/resume` et `/update`
exigent la clé API, passée en paramètre `key`.
