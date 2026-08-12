"""
Dardania Social Recycler
-------------------------
Postet automatisch bereits vorhandene Reels/Bilder erneut auf
Instagram, Facebook und TikTok. Jede Plattform hat pro Post ihr
eigenes Startdatum, ihre eigene Uhrzeit (Schweizer Zeit) und ihren
eigenen Rhythmus, und kann unabhängig pausiert/aktiviert werden
(siehe content/library.json -> platforms).

Läuft alle 15 Minuten über GitHub Actions (siehe .github/workflows/recycle.yml),
damit die gewählte Uhrzeit zuverlässig getroffen wird.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python <3.9 Fallback, sollte auf GitHub Actions nicht nötig sein
    from backports.zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY_PATH = os.path.join(ROOT, "content", "library.json")
CONFIG_PATH = os.path.join(ROOT, "config.json")
HISTORY_PATH = os.path.join(ROOT, "content", "history.json")

GRAPH_VERSION = "v21.0"
SWISS_TZ = ZoneInfo("Europe/Zurich")
TIME_BUCKET_MINUTES = 15  # muss zum Cron-Intervall in recycle.yml passen


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def raw_url(config, relative_path):
    repo = config["github_repo"]
    branch = config["github_branch"]
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{relative_path}"


def full_caption(item):
    caption = item.get("caption", "")
    hashtags = item.get("hashtags", "")
    if hashtags:
        return f"{caption}\n\n{hashtags}"
    return caption


def is_time_slot_match(post_time_str):
    """Prüft, ob JETZT (Schweizer Zeit) die gewünschte Uhrzeit bereits erreicht ist.
    Bewusst grosszügig: einmal erreicht, bleibt es für den Rest des Tages 'wahr' -
    ausgelöst wird trotzdem nur einmal, weil last_posted danach sofort gesetzt wird
    und der Rhythmus (rotation_days) ein erneutes Auslösen am selben Tag verhindert."""
    if not post_time_str:
        post_time_str = "10:00"
    try:
        hh, mm = map(int, post_time_str.split(":"))
    except ValueError:
        hh, mm = 10, 0

    now_local = datetime.now(SWISS_TZ)
    desired_minutes = hh * 60 + mm
    now_minutes = now_local.hour * 60 + now_local.minute
    return now_minutes >= desired_minutes


def is_due(platform_cfg):
    if not platform_cfg or not platform_cfg.get("enabled"):
        return False

    last_posted_iso = platform_cfg.get("last_posted")

    # Einmalige Posts: nach dem ersten Mal nie wieder fällig
    if platform_cfg.get("one_time") and last_posted_iso:
        return False

    # Eigenes Startdatum dieser Plattform: vor diesem Datum nie fällig
    scheduled = platform_cfg.get("scheduled_date")
    if scheduled:
        scheduled_dt = datetime.fromisoformat(scheduled).replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < scheduled_dt:
            return False

    # Datum grundsätzlich fällig?
    if last_posted_iso:
        last = datetime.fromisoformat(last_posted_iso)
        rotation_days = platform_cfg.get("rotation_days", 10)
        if datetime.now(timezone.utc) - last < timedelta(days=rotation_days):
            return False

    # Zusätzlich: nur im passenden Zeitfenster (Schweizer Zeit) wirklich posten
    return is_time_slot_match(platform_cfg.get("post_time"))


def pick_due_item(library, platform):
    candidates = []
    for item in library:
        cfg = (item.get("platforms") or {}).get(platform)
        if cfg and is_due(cfg):
            candidates.append(item)
    if not candidates:
        return None
    candidates.sort(key=lambda i: i["platforms"][platform].get("last_posted") or "")
    return candidates[0]


def mark_posted(item, platform):
    item["platforms"][platform]["last_posted"] = datetime.now(timezone.utc).isoformat()


def log_history(entry):
    history = load_json(HISTORY_PATH, default=[])
    history.append(entry)
    save_json(HISTORY_PATH, history)


# ---------- INSTAGRAM ----------

def post_to_instagram(item, media_url, caption, config):
    token = os.environ["IG_ACCESS_TOKEN"]
    ig_user_id = os.environ["IG_USER_ID"]

    is_video = item["type"] == "video"
    create_url = f"https://graph.instagram.com/{GRAPH_VERSION}/{ig_user_id}/media"
    payload = {"caption": caption, "access_token": token}
    if is_video:
        payload["media_type"] = "REELS"
        payload["video_url"] = media_url
    else:
        payload["image_url"] = media_url

    resp = requests.post(create_url, data=payload, timeout=60)
    resp.raise_for_status()
    container_id = resp.json()["id"]

    if is_video:
        status_url = f"https://graph.instagram.com/{GRAPH_VERSION}/{container_id}"
        for _ in range(20):
            time.sleep(15)
            status = requests.get(status_url, params={"fields": "status_code", "access_token": token}, timeout=30)
            code = status.json().get("status_code")
            if code == "FINISHED":
                break
            if code == "ERROR":
                raise RuntimeError(f"Instagram Container-Fehler: {status.json()}")

    publish_url = f"https://graph.instagram.com/{GRAPH_VERSION}/{ig_user_id}/media_publish"
    resp = requests.post(publish_url, data={"creation_id": container_id, "access_token": token}, timeout=60)
    resp.raise_for_status()
    print(f"[Instagram] Gepostet: {resp.json()}")


# ---------- FACEBOOK ----------

def post_to_facebook(item, media_url, caption, config):
    token = os.environ["FB_PAGE_ACCESS_TOKEN"]
    page_id = os.environ["FB_PAGE_ID"]

    if item["type"] == "video":
        url = f"https://graph-video.facebook.com/{GRAPH_VERSION}/{page_id}/videos"
        payload = {"file_url": media_url, "description": caption, "access_token": token}
    else:
        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/photos"
        payload = {"url": media_url, "caption": caption, "access_token": token}

    resp = requests.post(url, data=payload, timeout=120)
    resp.raise_for_status()
    print(f"[Facebook] Gepostet: {resp.json()}")


# ---------- TIKTOK ----------

def post_to_tiktok(item, media_url, caption, config):
    token = os.environ["TIKTOK_ACCESS_TOKEN"]
    url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    body = {
        "post_info": {
            "title": caption,
            "privacy_level": "SELF_ONLY",
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {"source": "PULL_FROM_URL", "video_url": media_url},
    }
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    print(f"[TikTok] Gepostet (als Entwurf, da App noch nicht geprüft): {resp.json()}")


# ---------- MAIN ----------

def main():
    config = load_json(CONFIG_PATH, default={})
    library = load_json(LIBRARY_PATH, default=[])

    platform_handlers = {
        "instagram": post_to_instagram,
        "facebook": post_to_facebook,
        "tiktok": post_to_tiktok,
    }

    any_posted = False

    for platform, handler in platform_handlers.items():
        item = pick_due_item(library, platform)
        if not item:
            continue

        media_url = raw_url(config, item["file"])
        caption = full_caption(item)
        try:
            handler(item, media_url, caption, config)
            mark_posted(item, platform)
            log_history({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "platform": platform,
                "id": item["id"],
                "caption": caption,
            })
            any_posted = True
        except Exception as e:
            print(f"[{platform}] FEHLER beim Posten von {item['id']}: {e}", file=sys.stderr)

    if any_posted:
        save_json(LIBRARY_PATH, library)
        print("library.json und history.json aktualisiert.")
    else:
        print("Kein passendes Zeitfenster / nichts fällig in diesem Lauf.")


if __name__ == "__main__":
    main()
