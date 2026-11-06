import json
import threading
import time

import websocket
from flask import render_template

from pything import App, LabelSetting, StringSetting, SelectSetting

app = App(
    [
        StringSetting("instance", "Instance URL", "http://homeassistant.local:8123"),
        StringSetting(
            "token",
            "Access Token (Get one from your profile page in the security tab)",
            "",
        ),
        LabelSetting("msg", "Domains supported: switch, light, sensor"),
        StringSetting("device1", "Entity id (1)", ""),
        StringSetting("device2", "Entity id (2)", ""),
        StringSetting("device3", "Entity id (3)", ""),
        StringSetting("device4", "Entity id (4)", ""),
        SelectSetting(
            "percentstyle",
            "Percentage style",
            "fill",
            {"off": "Off", "fill": "Fill", "fade": "Fade"},
        ),
    ]
)


_cache: dict = {}
_cache_lock = threading.Lock()


@app.blueprint.route("/launch")
def launch():
    app.logger.debug("Launch requested")
    with _cache_lock:
        cards = [make_card(i, _cache.get(eid)) for i, eid in enumerate(entity_ids())]
    app.logger.debug("Rendering launch with %d cached cards: %s", len(cards), cards)
    # Kick a refresh so fresh data is pushed even if cache is stale/empty
    threading.Thread(target=_refresh_and_send, daemon=True).start()
    return render_template(
        f"{app.dirname}/pages/home.html",
        initial_cards=cards,
        percentstyle=app.settings["percentstyle"].get_value(),
    )


def _refresh_and_send():
    app.logger.debug("Triggered refresh after launch")
    time.sleep(0.3)
    with _cache_lock:
        cached = dict(_cache)
    app.logger.debug("Sending cached cards after launch: %s", list(cached))
    if cached:
        send_cards(cached)


# Attributes with a meaningful 0-100 percentage (fan speed, light brightness, etc.)
# Fans expose "percentage" directly; lights expose "brightness" (0-255).
PERCENTAGE_ATTRS = ["percentage", "brightness"]


def compute_percentage(attrs: dict) -> int | None:
    """Return a 0-100 percentage for entities that support it, else None."""
    if attrs.get("percentage") is not None:
        try:
            pct = round(float(attrs["percentage"]))
        except (TypeError, ValueError):
            app.logger.debug("Could not parse percentage %r", attrs.get("percentage"))
            return None
        app.logger.debug("Percentage from 'percentage' attribute: %d", pct)
        return max(0, min(100, pct))
    if attrs.get("brightness") is not None:
        try:
            pct = round(float(attrs["brightness"]) / 255 * 100)
        except (TypeError, ValueError):
            app.logger.debug("Could not parse brightness %r", attrs.get("brightness"))
            return None
        app.logger.debug("Percentage from 'brightness' attribute: %d", pct)
        return max(0, min(100, pct))
    app.logger.debug("Entity does not support percentage (no percentage/brightness)")
    return None


SECONDARY_ATTRS = [
    "temperature",
    "humidity",
    "color_temp",
    "speed",
    "volume",
    "level",
    "current_position",
    "battery",
]


def entity_ids() -> list[str]:
    return [
        app.settings[f"device{i}"].get_value().strip()
        for i in range(1, 5)
        if app.settings[f"device{i}"].get_value().strip()
    ]


def make_card(idx: int, state_obj: dict | None):
    app.logger.debug("Building card %d from state: %s", idx, state_obj)
    if not state_obj:
        return {
            "i": idx,
            "label": "",
            "state": "",
            "secondary": "",
            "percentage": None,
            "percentstyle": app.settings["percentstyle"].get_value(),
            "enabled": False,
        }
    attrs = state_obj.get("attributes") or {}
    label = attrs.get("friendly_name") or state_obj.get("entity_id", "")
    state = str(state_obj.get("state", ""))
    percentage = compute_percentage(attrs)
    secondary = f"{percentage}%" if percentage is not None else ""
    for key in SECONDARY_ATTRS:
        if secondary:
            break
        if key in attrs and attrs[key] is not None:
            val = attrs[key]
            if key == "brightness" and isinstance(val, (int, float)):
                secondary = f"{round(val / 255 * 100)}%"
            elif key == "color_temp":
                secondary = f"{val}K"
            elif key in (
                "temperature",
                "humidity",
                "volume",
                "level",
                "battery",
                "percentage",
                "speed",
            ) and isinstance(val, (int, float)):
                secondary = f"{val}{attrs.get('unit_of_measurement', '')}"
            else:
                secondary = str(val)
            break
    app.logger.debug(
        "Card %d: label=%r state=%r secondary=%r percentage=%r enabled=%s",
        idx,
        label,
        state,
        secondary,
        percentage,
        state.lower() == "on",
    )
    return {
        "i": idx,
        "label": label,
        "state": state,
        "secondary": secondary,
        "percentage": percentage,
        "percentstyle": app.settings["percentstyle"].get_value(),
        "enabled": state.lower() == "on",
    }


def send_cards(state_map: dict):
    app.logger.debug(
        "send_cards called with entity_ids=%s state_map_keys=%s",
        entity_ids(),
        list(state_map),
    )
    with _cache_lock:
        _cache.update(state_map)
    cards = [make_card(i, state_map.get(eid)) for i, eid in enumerate(entity_ids())]
    app.logger.debug("Sending upd to clients: %s", cards)
    app.send("upd", {"cards": cards})


def ws_url(base: str) -> str:
    app.logger.debug("Building websocket URL from base %r", base)
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :].rstrip("/") + "/api/websocket"
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :].rstrip("/") + "/api/websocket"
    scheme = "wss" if ":443" in base or base.endswith(":443") else "ws"
    return f"{scheme}://{base.rstrip('/')}/api/websocket"


def ha_thread():
    state_map: dict = {}
    msg_id = 1

    while True:
        if not app.should_poll():
            time.sleep(1)
            continue
        instance = app.settings["instance"].get_value().strip()
        token = app.settings["token"].get_value().strip()
        ids = entity_ids()
        if not instance or not token or not ids:
            app.logger.debug("HA missing instance/token/entities, skipping")
            time.sleep(2)
            continue

        try:
            app.logger.debug(
                "Connecting to Home Assistant websocket at %s for entities %s",
                ws_url(instance),
                ids,
            )
            ws = websocket.create_connection(ws_url(instance), timeout=10)
            app.logger.debug("Websocket connected")
            raw = ws.recv()
            app.logger.debug("Received from HA: %s", raw)
            # auth_required expected
            app.logger.debug("Sending auth message")
            ws.send(json.dumps({"type": "auth", "access_token": token}))
            resp = json.loads(ws.recv())
            app.logger.debug("Auth response: %s", resp)
            if resp.get("type") != "auth_ok":
                app.logger.error(f"Home Assistant auth failed: {resp}")
                ws.close()
                time.sleep(5)
                continue

            app.logger.debug("Requesting get_states with id %d", msg_id)
            ws.send(json.dumps({"id": msg_id, "type": "get_states"}))
            msg_id += 1
            # read until result
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == msg_id - 1:
                    break
            app.logger.debug(
                "get_states response: %d states", len(msg.get("result") or [])
            )
            states = msg.get("result") or []
            state_map = {s["entity_id"]: s for s in states if s.get("entity_id") in ids}
            app.logger.debug(
                "Initial state_map for tracked entities: %s", list(state_map)
            )
            send_cards(state_map)

            app.logger.debug("Subscribing to state_changed with id %d", msg_id)
            ws.send(
                json.dumps(
                    {
                        "id": msg_id,
                        "type": "subscribe_events",
                        "event_type": "state_changed",
                    }
                )
            )
            msg_id += 1

            ws.settimeout(30)
            while True:
                if not app.should_poll():
                    break
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw:
                    break
                # app.logger.debug("Received HA message: %s", raw)
                msg = json.loads(raw)
                if msg.get("type") != "event":
                    # app.logger.debug("Ignoring non-event message type=%s", msg.get("type"))
                    continue
                data = msg.get("event", {}).get("data", {})
                new_state = data.get("new_state")
                eid = data.get("entity_id")
                app.logger.verbose("state_changed for %s new_state=%s", eid, new_state)
                if new_state and eid in ids:
                    state_map[eid] = new_state
                    send_cards(state_map)
            app.logger.debug(
                "Closing websocket (inner loop ended), should_poll=%s",
                app.should_poll(),
            )
            ws.close()
        except Exception as e:
            app.logger.warning(f"Home Assistant connection lost: {e}")
            time.sleep(3)


@app.on_startup
def start_ha():
    app.logger.debug("Starting Home Assistant websocket thread")
    threading.Thread(target=ha_thread, daemon=True).start()
