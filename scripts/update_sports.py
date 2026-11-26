
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

API = (
    "https://tflix.uk/multiview_catalog.php"
    "?q=&type=all&limit=100&offset={}"
)

OUTPUT = "data/sports.json"
MAX_PAGES = 20
TIMEOUT = 25

DIRECT_URL_FIELDS = (
    "playable_url",
    "playback_url",
    "stream_url",
    "manifest_url",
    "mpd_url",
    "m3u8_url",
    "url"
)

PLAYER_URL_FIELDS = (
    "player_url",
    "href",
    "embed_url",
    "iframe_url"
)

DRM_FIELDS = (
    "drm",
    "drm_type",
    "license_url",
    "license_server",
    "widevine"
)


def valid_url(value):
    if not isinstance(value, str):
        return False

    value = value.strip()

    if not value or len(value) > 8192:
        return False

    try:
        parsed = urlparse(value)
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
        )
    except Exception:
        return False


def detect_format(url):
    if not url:
        return "UNKNOWN"

    path = urlparse(url).path.lower()

    if path.endswith(".mpd"):
        return "DASH"

    if path.endswith(".m3u8"):
        return "HLS"

    return "UNKNOWN"


def get_first_url(item, fields):
    for field in fields:
        value = item.get(field)

        if valid_url(value):
            return value.strip()

    return None


def get_drm_info(item):
    drm = {}

    for field in DRM_FIELDS:
        if field in item:
            value = item[field]

            if value is not None and value != "":
                drm[field] = value

    return drm or None


def classify_item(item):
    item_type = str(
        item.get("type", "")
    ).strip().lower()

    name = str(
        item.get("name", "")
    ).strip()

    if not name:
        return None

    item_id = item.get("id")

    if item_id is None:
        return None

    direct_url = get_first_url(
        item,
        DIRECT_URL_FIELDS
    )

    player_url = get_first_url(
        item,
        PLAYER_URL_FIELDS
    )

    # Some catalogs put a direct URL in "stream".
    stream_value = item.get("stream")

    if not direct_url and valid_url(stream_value):
        direct_url = stream_value.strip()

    # If the source explicitly identifies a direct
    # manifest, keep its actual format.
    stream_format = detect_format(direct_url)

    if stream_format == "UNKNOWN":
        stream_format = detect_format(player_url)

    if item_type == "channel":
        category = "channel"
    elif item_type == "event":
        category = "event"
    else:
        category = "other"

    return {
        "id": str(item_id),
        "name": name,
        "type": category,
        "original_type": item.get("type"),
        "player_url": player_url,
        "playable_url": direct_url,
        "stream_format": detect_format(direct_url),
        "drm": get_drm_info(item),
        "stream_label": (
            stream_value
            if isinstance(stream_value, str)
            and not valid_url(stream_value)
            else None
        ),
        "source": "tflix",
        "status": (
            "url_available"
            if direct_url
            else (
                "player_available"
                if player_url
                else "metadata_only"
            )
        )
    }


def fetch_page(offset):
    request = urllib.request.Request(
        API.format(offset),
        headers={
            "User-Agent": "FARABI-TV-Sports/2.0",
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=TIMEOUT
    ) as response:

        if response.status != 200:
            raise RuntimeError(
                f"Catalog HTTP error: {response.status}"
            )

        raw = response.read().decode("utf-8")
        data = json.loads(raw)

    if not isinstance(data, dict):
        raise ValueError("Invalid catalog response")

    if not isinstance(data.get("items"), list):
        raise ValueError("Catalog items missing")

    return data


def load_previous():
    if not os.path.exists(OUTPUT):
        return {}

    with open(OUTPUT, "r", encoding="utf-8") as file:
        data = json.load(file)

    return data if isinstance(data, dict) else {}


def main():
    print("Starting FARABI TV Sports Update...")

    previous = load_previous()

    all_items = {}
    offset = 0

    for page_number in range(MAX_PAGES):
        print(f"Fetching catalog page {page_number + 1}...")

        data = fetch_page(offset)
        items = data["items"]

        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue

            item = classify_item(raw_item)

            if item:
                key = item["id"]
                all_items[key] = item

        if not data.get("has_more") or not items:
            break

        offset += len(items)

    if not all_items:
        raise RuntimeError(
            "No valid catalog items found. "
            "Previous JSON will not be overwritten."
        )

    channels = []
    events = []
    others = []

    for item in all_items.values():
        if item["type"] == "channel":
            channels.append(item)

        elif item["type"] == "event":
            events.append(item)

        else:
            others.append(item)

    # Preserve manually managed stream records.
    manual_streams = previous.get("streams", [])

    if not isinstance(manual_streams, list):
        manual_streams = []

    result = {
        "version": 2,

        "last_updated": datetime.now(
            timezone.utc
        ).isoformat(),

        "source_status": {
            "tflix": {
                "status": "success",
                "records": len(all_items)
            }
        },

        "channels": channels,
        "live_events": events,
        "upcoming_events": [],

        "other_items": others,

        "streams": manual_streams
    }

    os.makedirs(
        os.path.dirname(OUTPUT),
        exist_ok=True
    )

    temp_file = OUTPUT + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2
        )

        file.write("\n")

    os.replace(temp_file, OUTPUT)

    print("--------------------------------")
    print("SPORTS DATA UPDATE SUCCESSFUL")
    print("--------------------------------")
    print("Channels:", len(channels))
    print("Events:", len(events))
    print("Other:", len(others))

    playable_count = sum(
        1 for item in all_items.values()
        if item["playable_url"]
    )

    player_count = sum(
        1 for item in all_items.values()
        if item["player_url"]
    )

    print("Direct playable URLs:", playable_count)
    print("Player page URLs:", player_count)
    print("Output:", OUTPUT)


if __name__ == "__main__":
    main()
