"""
Dardania Social Recycler
-------------------------
Postet automatisch bereits vorhandene Reels/Bilder erneut auf
Instagram, Facebook und TikTok, in einem festen Rhythmus.

Läuft normalerweise über GitHub Actions (siehe .github/workflows/recycle.yml),
kann aber auch lokal getestet werden mit: python scripts/recycle_post.py
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY_PATH = os.path.join(ROOT, "content", "library.json")
CONFIG_PATH = os.path.join(ROOT, "config.json")

GRAPH_VERSION = "v21.0"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def raw_url(config, relative_path):
    """Baut die öffentlich erreichbare raw.githubusercontent.com URL für eine Datei im Repo."""
    repo = config["github_repo"]
    branch = config["github_branch"]
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{relative_path}"


def is_due(last_posted_iso, rotation_days):
    if not last_posted_iso:
        return True
    last = datetime.fromisoformat(last_posted_iso)
    return datetime.now(timezone.utc) - last >= timedelta(days=rotation_days)


def pick_due_item(library, platform, rotation_days):
    """Wählt den Eintrag, der für diese Plattform am längsten nicht gepostet wurde und fällig ist."""
    candidates = [
        item for item in library
        if platform in item["platforms"] and is_due(item["last_posted"].get(platform), rotation_days)
    ]
    if not candidates:
        return None
    # Ältester zuerst (None = noch nie gepostet, hat Priorität)
    candidates.sort(key=lambda i: i["last_posted"].get(platform) or "")
    return candidates[0]


def mark_posted(item, platform):
    item["last_posted"][platform] = datetime.now(timezone.utc).isoformat()


# ---------- INSTAGRAM ----------

def post_to_instagram(item, media_url, config):
    token = os.environ["IG_ACCESS_TOKEN"]
    ig_user_id = os.environ["IG_USER_ID"]

    is_video = item["type"] == "video"
    create_url = f"https://graph.instagram.com/{GRAPH_VERSION}/{ig_user_id}/media"
    payload = {
        "caption": item["caption"],
        "access_token": token,
    }
    if is_video:
        payload["media_type"] = "REELS"
        payload["video_url"] = media_url
    else:
        payload["image_url"] = media_url

    resp = requests.post(create_url, data=payload, timeout=60)
    resp.raise_for_status()
    container_id = resp.json()["id"]

    # Auf Fertigstellung warten (nur bei Video nötig)
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

def post_to_facebook(item, media_url, config):
    token = os.environ["FB_PAGE_ACCESS_TOKEN"]
    page_id = os.environ["FB_PAGE_ID"]

    if item["type"] == "video":
        url = f"https://graph-video.facebook.com/{GRAPH_VERSION}/{page_id}/videos"
        payload = {"file_url": media_url, "description": item["caption"], "access_token": token}
    else:
        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/photos"
        payload = {"url": media_url, "caption": item["caption"], "access_token": token}

    resp = requests.post(url, data=payload, timeout=120)
    resp.raise_for_status()
    print(f"[Facebook] Gepostet: {resp.json()}")


# ---------- TIKTOK ----------

def post_to_tiktok(item, media_url, config):
    token = os.environ["TIKTOK_ACCESS_TOKEN"]
    url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    body = {
        "post_info": {
            "title": item["caption"],
            "privacy_level": "SELF_ONLY",  # Wichtig: solange die App nicht von TikTok geprüft ist,
                                            # ist nur SELF_ONLY (privater Entwurf) erlaubt.
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "video_url": media_url,
        },
    }
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    print(f"[TikTok] Gepostet (als Entwurf, da App noch nicht geprüft): {resp.json()}")


# ---------- MAIN ----------

def main():
    config = load_json(CONFIG_PATH)
    library = load_json(LIBRARY_PATH)

    platform_handlers = {
        "instagram": post_to_instagram,
        "facebook": post_to_facebook,
        "tiktok": post_to_tiktok,
    }

    any_posted = False

    for platform, handler in platform_handlers.items():
        rotation_days = config["rotation_days"][platform]
        item = pick_due_item(library, platform, rotation_days)
        if not item:
            print(f"[{platform}] Nichts fällig.")
            continue

        media_url = raw_url(config, item["file"])
        try:
            handler(item, media_url, config)
            mark_posted(item, platform)
            any_posted = True
        except Exception as e:
            print(f"[{platform}] FEHLER beim Posten von {item['id']}: {e}", file=sys.stderr)

    if any_posted:
        save_json(LIBRARY_PATH, library)
        print("library.json aktualisiert.")
    else:
        print("Keine Änderungen.")


if __name__ == "__main__":
    main()
