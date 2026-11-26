
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

# =========================================================
# FARABI TV - SPORTS DATA AUTO UPDATER
# =========================================================

BASE_URL = "https://tflix.uk/"
CATALOG_URL = (
    "https://tflix.uk/multiview_catalog.php"
    "?q=&type=all&limit=100&offset={offset}"
)

OUTPUT_FILE = Path("data/sports.json")
MAX_PAGES = 20
TIMEOUT = 25

OWNER = "Monirul Islam"
TELEGRAM_CHANNEL = "https://t.me/sm_iptv_bd"

# এখানে কেবল যাচাই করা TouchCric ID এবং Channel Name বসাবে।
# উদাহরণ:
# TOUCHCRIC_CHANNELS = {
#     "ID": "Verified Channel Name"
# }
#
# অনুমান করে ID বা channel name যোগ করবে না।
TOUCHCRIC_CHANNELS = {
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
)


def now_dhaka():
    return datetime.now(
        ZoneInfo("Asia/Dhaka")
    )


def formatted_time():
    return now_dhaka().strftime(
        "%I:%M:%S %p %d-%m-%Y"
    )


def fetch_json(url):
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*"
        }
    )

    with urlopen(request, timeout=TIMEOUT) as response:
        content = response.read().decode("utf-8")

    return json.loads(content)


def valid_http_url(value):
    if not isinstance(value, str):
        return False

    value = value.strip().lower()

    return value.startswith("https://") or value.startswith("http://")


def absolute_url(value):
    if not isinstance(value, str) or not value.strip():
        return None

    resolved = urljoin(BASE_URL, value.strip())

    if valid_http_url(resolved):
        return resolved

    return None


def first_value(item, fields, default=None):
    for field in fields:
        value = item.get(field)

        if value is not None and value != "":
            return value

    return default


def get_player_url(item):
    return absolute_url(
        first_value(
            item,
            (
                "player_url",
                "href",
                "embed_url",
                "iframe_url"
            )
        )
    )


def get_direct_stream_url(item):
    """
    Only uses a direct URL explicitly supplied by the source.
    Does not extract DRM-protected media from player pages.
    """

    value = first_value(
        item,
        (
            "stream_url",
            "playable_url",
            "media_url",
            "manifest_url",
            "m3u8",
            "mpd"
        )
    )

    if valid_http_url(value):
        return value.strip()

    return None


def detect_stream_format(url):
    if not url:
        return "UNKNOWN"

    lower = url.lower()

    if ".m3u8" in lower:
        return "HLS"

    if ".mpd" in lower:
        return "DASH"

    return "UNKNOWN"


def normalize_status(item):
    value = str(
        first_value(
            item,
            ("status", "match_status", "state"),
            "UPCOMING"
        )
    ).upper()

    if value in ("LIVE", "IN PLAY", "IN_PROGRESS", "IN-PROGRESS"):
        return "LIVE"

    if value in ("FINISHED", "COMPLETED", "ENDED"):
        return "FINISHED"

    return "UPCOMING"


def normalize_category(item):
    value = first_value(
        item,
        ("category", "Category", "sport", "sport_name"),
        "Sports"
    )

    return str(value).strip()


def fetch_tflix_catalog():
    all_items = []
    pages_fetched = 0

    for page in range(MAX_PAGES):
        offset = page * 100
        url = CATALOG_URL.format(offset=offset)

        print(f"Fetching TFLIX page {page + 1}: offset={offset}")

        data = fetch_json(url)

        if not isinstance(data, dict):
            raise ValueError("Unexpected TFLIX response format")

        items = data.get("items", [])

        if not isinstance(items, list):
            raise ValueError("TFLIX items field is not a list")

        if not items:
            break

        all_items.extend(items)
        pages_fetched += 1

        if not data.get("has_more", False):
            break

        time.sleep(0.3)

    return all_items, pages_fetched


def normalize_channel(item):
    name = str(
        first_value(item, ("name", "channel_name"), "Unknown Channel")
    ).strip()

    player_url = get_player_url(item)
    direct_url = get_direct_stream_url(item)

    return {
        "id": str(item.get("id", "")),
        "name": name,
        "player_url": player_url,
        "stream_url": direct_url,
        "stream_format": detect_stream_format(direct_url),
        "source": "tflix",
        "status": (
            "player_available"
            if player_url
            else "metadata_only"
        )
    }


def normalize_touchcric_channels():
    channels = []

    for channel_id, channel_name in TOUCHCRIC_CHANNELS.items():
        channel_id = str(channel_id).strip()
        channel_name = str(channel_name).strip()

        if not channel_id or not channel_name:
            continue

        player_url = (
            "https://api.touchcric.vip/drm/player.php?id="
            + channel_id
        )

        channels.append({
            "id": channel_id,
            "name": channel_name,
            "player_url": player_url,
            "stream_url": None,
            "stream_format": "UNKNOWN",
            "source": "touchcric",
            "status": "player_reference"
        })

    return channels


def normalize_event(item):
    event_name = str(
        first_value(
            item,
            ("event_name", "name", "title"),
            "Unknown Event"
        )
    ).strip()

    channel_name = str(
        first_value(
            item,
            ("stream", "channel_name", "provider"),
            "Unknown Channel"
        )
    ).strip()

    player_url = get_player_url(item)
    direct_url = get_direct_stream_url(item)

    stream = {
        "channel_name": channel_name,
        "player_url": player_url,
        "stream_url": direct_url,
        "stream_format": detect_stream_format(direct_url),
        "source": "tflix"
    }

    event_info = {
        "teamA": first_value(item, ("teamA", "team_a")),
        "teamB": first_value(item, ("teamB", "team_b")),
        "teamAFlag": first_value(item, ("teamAFlag", "team_a_flag")),
        "teamBFlag": first_value(item, ("teamBFlag", "team_b_flag")),
        "eventName": first_value(
            item,
            ("eventName", "tournament", "competition")
        ),
        "event_logo": first_value(
            item,
            ("event_logo", "eventLogo", "logo")
        ),
        "startTime": first_value(
            item,
            ("startTime", "start_time", "date")
        )
    }

    return {
        "status": normalize_status(item),
        "Category": normalize_category(item),
        "event_name": event_name,
        "eventInfo": event_info,
        "streams": [stream]
    }


def merge_events(items):
    """
    Same event appearing under multiple providers/channels
    will be merged into one match with multiple streams.
    """

    matches = {}

    for item in items:
        item_type = str(item.get("type", "")).lower()

        if item_type != "event":
            continue

        event = normalize_event(item)
        key = event["event_name"].strip().lower()

        if key not in matches:
            matches[key] = event
            continue

        existing = matches[key]

        for stream in event["streams"]:
            existing["streams"].append(stream)

        # Prefer LIVE status if any source explicitly reports LIVE.
        if event["status"] == "LIVE":
            existing["status"] = "LIVE"

        # Fill missing event information without overwriting known data.
        for field, value in event["eventInfo"].items():
            if existing["eventInfo"].get(field) in (None, "") and value:
                existing["eventInfo"][field] = value

    # Remove duplicate stream entries.
    for match in matches.values():
        unique_streams = []
        seen = set()

        for stream in match["streams"]:
            identity = (
                stream.get("channel_name"),
                stream.get("player_url"),
                stream.get("stream_url")
            )

            if identity not in seen:
                seen.add(identity)
                unique_streams.append(stream)

        match["streams"] = unique_streams

    return list(matches.values())


def build_output(items, pages_fetched):
    tflix_channels = []
    events = []

    for item in items:
        item_type = str(item.get("type", "")).lower()

        if item_type == "channel":
            tflix_channels.append(normalize_channel(item))

        elif item_type == "event":
            events.append(item)

    touchcric_channels = normalize_touchcric_channels()

    matches = merge_events(events)

    live_matches = [
        match for match in matches
        if match["status"] == "LIVE"
    ]

    upcoming_matches = [
        match for match in matches
        if match["status"] == "UPCOMING"
    ]

    return {
        "name": "Live and Upcoming Sports Data",
        "owner": OWNER,
        "telegram_channel": TELEGRAM_CHANNEL,
        "last_update_time": formatted_time(),
        "total_matches": len(matches),
        "live_match": len(live_matches),

        "matches": matches,

        "channels": tflix_channels + touchcric_channels,

        "source_status": {
            "tflix": {
                "status": "success",
                "records": len(items),
                "channels": len(tflix_channels),
                "events": len(events),
                "pages_fetched": pages_fetched
            },
            "touchcric": {
                "status": (
                    "configured"
                    if TOUCHCRIC_CHANNELS
                    else "mapping_not_configured"
                ),
                "mapped_channels": len(touchcric_channels)
            }
        }
    }


def main():
    print("========================================")
    print(" FARABI TV SPORTS DATA UPDATER")
    print("========================================")

    try:
        items, pages_fetched = fetch_tflix_catalog()

        if not items:
            raise RuntimeError("TFLIX returned no records")

        output = build_output(items, pages_fetched)

        OUTPUT_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temporary_file = OUTPUT_FILE.with_suffix(".tmp")

        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(
                output,
                file,
                ensure_ascii=False,
                indent=2
            )

        temporary_file.replace(OUTPUT_FILE)

        print(f"Total source records: {len(items)}")
        print(f"Total matches: {output['total_matches']}")
        print(f"Live matches: {output['live_match']}")
        print(f"Channels: {len(output['channels'])}")
        print(f"Updated: {OUTPUT_FILE}")

    except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError) as error:
        print(f"UPDATE FAILED: {error}", file=sys.stderr)
        sys.exit(1)

    except Exception as error:
        print(f"UNEXPECTED ERROR: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
