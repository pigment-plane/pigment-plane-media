import json, os, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "publish_queue.json"
BASE = "https://graph.instagram.com"

def save(data):
    QUEUE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def request(method, path, token, data=None):
    encoded = urllib.parse.urlencode(data or {}).encode() if data is not None else None
    req = urllib.request.Request(f"{BASE}/{path.lstrip('/')}", data=encoded, method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode())

def due(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc) <= datetime.now(timezone.utc)

def main():
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN GitHub Secret is missing")
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    entries = data["entries"]
    resumable = [e for e in entries if e["status"] == "publishing" and e["container_id"] and not e["published_media_id"]]
    pending = [e for e in entries if e["status"] == "approved" and not e["published_media_id"] and due(e["scheduled_at"])]
    pending = resumable or pending
    if not pending:
        print("No due Reel.")
        return
    entry = sorted(pending, key=lambda e: e["sequence"])[0]
    ig = data["instagram_user_id"]
    if not entry["container_id"]:
        result = request("POST", f"{ig}/media", token, {
            "media_type": "REELS",
            "video_url": f"https://pigment-plane.github.io/pigment-plane-media/{entry['sequence']}.mp4",
            "caption": entry["caption"],
            "share_to_feed": str(entry["share_to_feed"]).lower(),
        })
        entry["container_id"] = result["id"]
        entry["status"] = "publishing"
        save(data)
    for _ in range(60):
        state = request("GET", f"{entry['container_id']}?fields=status_code,status", token)
        if state.get("status_code") == "FINISHED":
            break
        if state.get("status_code") in {"ERROR", "EXPIRED"}:
            entry["status"] = "failed"
            entry["error"] = state.get("status", "container failed")
            save(data)
            raise RuntimeError(entry["error"])
        time.sleep(10)
    else:
        raise RuntimeError("Container processing timed out; rerun resumes this container.")
    if entry.get("publish_attempt_started_at"):
        raise RuntimeError("A prior publish attempt is ambiguous. Stop rather than risk a duplicate post.")
    entry["publish_attempt_started_at"] = datetime.now(timezone.utc).isoformat()
    save(data)
    result = request("POST", f"{ig}/media_publish", token, {"creation_id": entry["container_id"]})
    entry["published_media_id"] = result["id"]
    entry["published_at"] = datetime.now(timezone.utc).isoformat()
    entry["status"] = "published"
    save(data)
    print(f"Published {entry['sequence']}")

if __name__ == "__main__":
    main()
