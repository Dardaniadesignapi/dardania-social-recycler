# Dardania Social Recycler

Postet automatisch bereits vorhandene Reels/Bilder erneut auf Instagram, Facebook
und TikTok — in einem festen Rhythmus, ohne dass du es jedes Mal manuell machen musst.

## Wie es funktioniert

1. Deine Reels/Bilder liegen in `content/media/`
2. `content/library.json` listet sie mit Caption, Ziel-Plattformen und dem Datum,
   wann sie zuletzt auf welcher Plattform gepostet wurden
3. `config.json` legt fest, wie oft (in Tagen) etwas pro Plattform wiederholt werden darf
4. Ein GitHub Actions Workflow läuft täglich automatisch, prüft was fällig ist,
   postet es über die offiziellen APIs, und aktualisiert `library.json`

## Einmalige Einrichtung

### 1. Repo erstellen
Dieses Verzeichnis als **öffentliches** GitHub-Repo namens `dardania-social-recycler`
anlegen (öffentlich, weil Meta/TikTok deine Video-/Bilddateien über eine öffentliche
URL abrufen müssen — die Zugangsdaten selbst bleiben trotzdem geheim, siehe unten).

```bash
cd dardania-social-recycler
git init
git add .
git commit -m "Initial setup"
git branch -M main
git remote add origin https://github.com/DEIN_USERNAME/dardania-social-recycler.git
git push -u origin main
```

### 2. `config.json` anpassen
`github_repo` auf `DEIN_USERNAME/dardania-social-recycler` setzen.

### 3. Geheimnisse (Secrets) hinterlegen
Im GitHub-Repo: **Settings → Secrets and variables → Actions → New repository secret**.
Diese fünf anlegen:

| Name | Woher |
|---|---|
| `IG_ACCESS_TOKEN` | Der langlebige Instagram-Access-Token aus dem Meta-Entwicklerportal |
| `IG_USER_ID` | Deine Instagram-Business-Konto-ID (auch aus dem Portal ersichtlich) |
| `FB_PAGE_ACCESS_TOKEN` | Page Access Token deiner Facebook-Seite |
| `FB_PAGE_ID` | Die ID deiner Facebook-Seite |
| `TIKTOK_ACCESS_TOKEN` | Access Token aus der TikTok Content Posting API |

Diese Werte stehen **nur** hier als Secret, nirgends im Code oder Repo-Inhalt selbst.

### 4. Content hinzufügen
Datei in `content/media/` legen, dann in `content/library.json` einen Eintrag ergänzen
(Beispiel ist schon drin). `"type"` ist `"video"` oder `"image"`.

## Wichtige Einschränkungen

- **Instagram/Facebook Token läuft nach 60 Tagen ab.** Du musst ihn manuell erneuern
  (im Entwicklerportal) und den Secret-Wert aktualisieren — sonst pausiert das Posten
  automatisch (Fehler erscheint im Actions-Log).
- **TikTok:** Solange deine TikTok-App noch nicht von TikTok geprüft wurde, kann sie
  nur mit `privacy_level: SELF_ONLY` posten — das landet als **privater Entwurf** in
  deiner TikTok-App, den du dort manuell veröffentlichen musst. Nach erfolgreicher
  App-Prüfung durch TikTok kann das Skript auf `PUBLIC_TO_EVERYONE` umgestellt werden.
- Instagram erlaubt maximal 100 API-Posts pro 24h — bei unserem Rhythmus (alle paar
  Tage) niemals ein Thema.

## Manuell testen

Im Repo unter **Actions → Content Recycling → Run workflow** kannst du den Ablauf
jederzeit sofort auslösen, statt auf den täglichen Zeitplan zu warten.

Lokal testen (z. B. bevor du pushst):
```bash
pip install -r requirements.txt
export IG_ACCESS_TOKEN=... IG_USER_ID=... FB_PAGE_ACCESS_TOKEN=... FB_PAGE_ID=... TIKTOK_ACCESS_TOKEN=...
python scripts/recycle_post.py
```

## Rhythmus ändern

In `config.json` unter `rotation_days` einfach die Zahl der Tage pro Plattform anpassen.
