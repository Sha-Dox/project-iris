import os
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from monitor import TikTokMonitorService
from scraper import TikTokScrapeError, fetch_tiktok_profile, normalize_username
from storage import MonitorStore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MONITOR_DB_PATH = os.environ.get("MONITOR_DB_PATH", os.path.join(BASE_DIR, "iris.db"))

ENV_DEFAULT_PORT = int(os.environ.get("PORT", "8000"))
ENV_DEFAULT_DEBUG_MODE = os.environ.get("DEBUG", "1") == "1"
ENV_DEFAULT_MONITOR_INTERVAL_SECONDS = int(os.environ.get("MONITOR_INTERVAL_SECONDS", "900"))
ENV_DEFAULT_AUTO_START_MONITOR = os.environ.get("AUTO_START_MONITOR", "1") == "1"

SETTING_DEFINITIONS: dict[str, dict[str, Any]] = {
    "app_port": {
        "label": "Web port",
        "type": "int",
        "default": ENV_DEFAULT_PORT,
        "min": 1,
        "max": 65535,
        "restart_required": True,
        "description": "Port used by Flask on next restart.",
    },
    "debug_mode": {
        "label": "Debug mode",
        "type": "bool",
        "default": ENV_DEFAULT_DEBUG_MODE,
        "restart_required": True,
        "description": "Enable Flask debug mode on next restart.",
    },
    "monitor_interval_seconds": {
        "label": "Monitor interval (seconds)",
        "type": "int",
        "default": ENV_DEFAULT_MONITOR_INTERVAL_SECONDS,
        "min": 30,
        "max": 86400,
        "restart_required": False,
        "description": "Time between periodic monitor cycles.",
    },
    "auto_start_monitor": {
        "label": "Auto-start monitor",
        "type": "bool",
        "default": ENV_DEFAULT_AUTO_START_MONITOR,
        "restart_required": True,
        "description": "Start monitor automatically when app boots.",
    },
    "dashboard_events_limit": {
        "label": "Dashboard events limit",
        "type": "int",
        "default": 30,
        "min": 1,
        "max": 500,
        "restart_required": False,
        "description": "How many change events are shown on dashboard.",
    },
    "dashboard_failures_limit": {
        "label": "Dashboard failures limit",
        "type": "int",
        "default": 20,
        "min": 1,
        "max": 500,
        "restart_required": False,
        "description": "How many failures are shown on dashboard.",
    },
    "api_default_limit": {
        "label": "API default limit",
        "type": "int",
        "default": 100,
        "min": 1,
        "max": 2000,
        "restart_required": False,
        "description": "Default API list limit when query param is omitted.",
    },
    "api_max_limit": {
        "label": "API max limit",
        "type": "int",
        "default": 500,
        "min": 1,
        "max": 5000,
        "restart_required": False,
        "description": "Maximum allowed API limit value.",
    },
    "history_default_limit": {
        "label": "History default limit",
        "type": "int",
        "default": 100,
        "min": 1,
        "max": 2000,
        "restart_required": False,
        "description": "Default number of snapshots returned for account history.",
    },
}

SETTINGS_ORDER = list(SETTING_DEFINITIONS.keys())


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _serialize_setting_value(key: str, value: Any) -> str:
    setting_type = SETTING_DEFINITIONS[key]["type"]
    if setting_type == "bool":
        return "1" if bool(value) else "0"
    return str(value)


def _parse_setting_value(key: str, raw: str | int | bool) -> Any:
    definition = SETTING_DEFINITIONS[key]
    setting_type = definition["type"]

    if setting_type == "bool":
        if isinstance(raw, bool):
            return raw
        return _parse_bool(str(raw), bool(definition["default"]))

    if setting_type == "int":
        try:
            parsed = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{definition['label']} must be a valid integer.") from exc

        min_value = int(definition.get("min", parsed))
        max_value = int(definition.get("max", parsed))
        if parsed < min_value or parsed > max_value:
            raise ValueError(f"{definition['label']} must be between {min_value} and {max_value}.")
        return parsed

    return str(raw)


store = MonitorStore(MONITOR_DB_PATH)


def _load_settings() -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    for key in SETTINGS_ORDER:
        default_value = _parse_setting_value(key, SETTING_DEFINITIONS[key]["default"])
        raw_value = store.get_setting(key)
        if raw_value is None:
            parsed_value = default_value
        else:
            try:
                parsed_value = _parse_setting_value(key, raw_value)
            except ValueError:
                parsed_value = default_value
        loaded[key] = parsed_value
        store.set_setting(key, _serialize_setting_value(key, parsed_value))
    return loaded


settings_state = _load_settings()
monitor = TikTokMonitorService(store, interval_seconds=int(settings_state["monitor_interval_seconds"]))
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))


def _apply_runtime_settings() -> None:
    monitor.interval_seconds = int(settings_state["monitor_interval_seconds"])


def _get_setting_limit(name: str) -> int:
    return int(settings_state[name])


def _resolve_limit(limit_raw: str | None, default_limit: int, max_limit: int) -> tuple[int | None, str | None]:
    if not limit_raw:
        return default_limit, None
    try:
        limit = int(limit_raw)
    except ValueError:
        return None, "limit must be an integer."
    if limit < 1 or limit > max_limit:
        return None, f"limit must be between 1 and {max_limit}."
    return limit, None


def _settings_view_model() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in SETTINGS_ORDER:
        definition = SETTING_DEFINITIONS[key]
        rows.append(
            {
                "key": key,
                "label": definition["label"],
                "type": definition["type"],
                "description": definition["description"],
                "restart_required": bool(definition.get("restart_required", False)),
                "value": settings_state[key],
                "min": definition.get("min"),
                "max": definition.get("max"),
            }
        )
    return rows


def _dashboard_context() -> dict[str, Any]:
    return {
        "watchlist": store.list_watch_accounts_with_latest(),
        "events": store.get_recent_events(limit=_get_setting_limit("dashboard_events_limit")),
        "failures": store.get_recent_failures(limit=_get_setting_limit("dashboard_failures_limit")),
        "monitor_status": monitor.status(),
        "settings_rows": _settings_view_model(),
    }


@app.route("/", methods=["GET", "POST"])
def index():
    manual_result = None
    manual_error = None
    username = ""
    watch_username = ""

    # Read flash from session (set by POST redirect)
    status_message = session.pop("_flash_msg", None)
    status_kind = session.pop("_flash_kind", "success")

    if request.method == "POST":
        action = request.form.get("action", "").strip()

        if action == "save_settings":
            proposed: dict[str, Any] = {}
            errors: list[str] = []

            for key in SETTINGS_ORDER:
                definition = SETTING_DEFINITIONS[key]
                if definition["type"] == "bool":
                    raw_value: Any = request.form.get(key) == "1"
                else:
                    raw_value = request.form.get(key, "").strip()
                try:
                    proposed[key] = _parse_setting_value(key, raw_value)
                except ValueError as exc:
                    errors.append(str(exc))

            if not errors and proposed["api_default_limit"] > proposed["api_max_limit"]:
                errors.append("API default limit cannot be greater than API max limit.")
            if not errors and proposed["history_default_limit"] > proposed["api_max_limit"]:
                errors.append("History default limit cannot be greater than API max limit.")

            if errors:
                session["_flash_msg"] = errors[0]
                session["_flash_kind"] = "error"
            else:
                restart_required_changes = []
                for key, value in proposed.items():
                    if settings_state[key] != value and bool(SETTING_DEFINITIONS[key].get("restart_required", False)):
                        restart_required_changes.append(SETTING_DEFINITIONS[key]["label"])
                    settings_state[key] = value
                    store.set_setting(key, _serialize_setting_value(key, value))
                _apply_runtime_settings()
                msg = "Settings saved."
                if restart_required_changes:
                    msg += " Restart required for: " + ", ".join(restart_required_changes) + "."
                session["_flash_msg"] = msg
                session["_flash_kind"] = "success"
            return redirect(url_for("index"))

        elif action == "reset_monitor_data":
            if monitor.is_running:
                session["_flash_msg"] = "Stop the monitor before clearing data."
                session["_flash_kind"] = "error"
            else:
                store.clear_monitor_data()
                session["_flash_msg"] = "All watchlist/history/events/failures data cleared."
                session["_flash_kind"] = "success"
            return redirect(url_for("index"))

        elif action == "manual_check":
            username = request.form.get("username", "").strip()
            if not username:
                manual_error = "Please enter a TikTok username."
            else:
                try:
                    manual_result = fetch_tiktok_profile(username)
                except TikTokScrapeError as exc:
                    manual_error = str(exc)

        elif action == "add_watch":
            watch_username = request.form.get("watch_username", "").strip()
            try:
                normalized = normalize_username(watch_username)
                store.add_watch_account(normalized)
                session["_flash_msg"] = f"@{normalized} added to watchlist."
                session["_flash_kind"] = "success"
            except TikTokScrapeError as exc:
                session["_flash_msg"] = str(exc)
                session["_flash_kind"] = "error"
            return redirect(url_for("index"))

        elif action == "remove_watch":
            watch_username = request.form.get("watch_username", "").strip().lstrip("@")
            if not watch_username:
                session["_flash_msg"] = "Missing watchlist username."
                session["_flash_kind"] = "error"
            elif store.deactivate_watch_account(watch_username):
                session["_flash_msg"] = f"@{watch_username} removed from watchlist."
                session["_flash_kind"] = "success"
            else:
                session["_flash_msg"] = f"@{watch_username} is not in your active watchlist."
                session["_flash_kind"] = "error"
            return redirect(url_for("index"))

        elif action == "check_watch_now":
            watch_username = request.form.get("watch_username", "").strip().lstrip("@")
            if not watch_username:
                session["_flash_msg"] = "Missing watchlist username."
                session["_flash_kind"] = "error"
            elif monitor.check_account(watch_username):
                session["_flash_msg"] = f"Manual check completed for @{watch_username}."
                session["_flash_kind"] = "success"
            else:
                session["_flash_msg"] = f"Manual check failed for @{watch_username}. See failures below."
                session["_flash_kind"] = "error"
            return redirect(url_for("index"))

        elif action == "run_monitor_now":
            summary = monitor.run_once()
            if summary["status"] == "busy":
                session["_flash_msg"] = "Iris monitor is already running a cycle."
                session["_flash_kind"] = "error"
            else:
                session["_flash_msg"] = (
                    f"Cycle complete: checked {summary['checked']}/{summary['accounts']} account(s), "
                    f"failed {summary['failed']}."
                )
                session["_flash_kind"] = "success"
            return redirect(url_for("index"))

        elif action == "start_monitor":
            if monitor.start():
                session["_flash_msg"] = "Periodic Iris monitor started."
                session["_flash_kind"] = "success"
            else:
                session["_flash_msg"] = "Iris monitor is already running."
                session["_flash_kind"] = "error"
            return redirect(url_for("index"))

        elif action == "stop_monitor":
            if monitor.stop():
                session["_flash_msg"] = "Periodic Iris monitor stopped."
                session["_flash_kind"] = "success"
            else:
                session["_flash_msg"] = "Iris monitor is not running."
                session["_flash_kind"] = "error"
            return redirect(url_for("index"))

        # unknown or empty action — just fall through to GET render

    return render_template(
        "index.html",
        manual_result=manual_result,
        manual_error=manual_error,
        username=username,
        watch_username=watch_username,
        status_message=status_message,
        status_kind=status_kind,
        **_dashboard_context(),
    )


@app.get("/api/status")
def api_status():
    payload = monitor.status()
    payload["settings"] = settings_state
    return jsonify(payload)


@app.get("/api/settings")
def api_settings():
    return jsonify(settings_state)


@app.get("/api/watchlist")
def api_watchlist():
    return jsonify(store.list_watch_accounts_with_latest())


@app.get("/api/events")
def api_events():
    max_limit = _get_setting_limit("api_max_limit")
    default_limit = min(_get_setting_limit("api_default_limit"), max_limit)
    limit, error = _resolve_limit(request.args.get("limit"), default_limit, max_limit)
    if error:
        return jsonify({"error": error}), 400
    return jsonify(store.get_recent_events(limit=limit or default_limit))


@app.get("/api/failures")
def api_failures():
    max_limit = _get_setting_limit("api_max_limit")
    default_limit = min(_get_setting_limit("api_default_limit"), max_limit)
    limit, error = _resolve_limit(request.args.get("limit"), default_limit, max_limit)
    if error:
        return jsonify({"error": error}), 400
    return jsonify(store.get_recent_failures(limit=limit or default_limit))


@app.get("/api/history/<username>")
def api_history(username: str):
    try:
        normalized = normalize_username(username)
    except TikTokScrapeError as exc:
        return jsonify({"error": str(exc)}), 400

    max_limit = _get_setting_limit("api_max_limit")
    default_limit = min(_get_setting_limit("history_default_limit"), max_limit)
    limit, error = _resolve_limit(request.args.get("limit"), default_limit, max_limit)
    if error:
        return jsonify({"error": error}), 400
    return jsonify(store.get_snapshots(normalized, limit=limit or default_limit))


if __name__ == "__main__":
    debug_mode = bool(settings_state["debug_mode"])
    app_port = int(settings_state["app_port"])
    auto_start = bool(settings_state["auto_start_monitor"])

    if auto_start and (not debug_mode or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        monitor.start()
    app.run(debug=debug_mode, port=app_port)
