"""A read-only stand-in for Spoolman's HTTP API, fed from the U1 stock print_task.

Moonraker's built-in `[spoolman]` component points at this on localhost when no real Spoolman
server is configured, so the AFC panel (which resolves a lane's filament name from the Spoolman
spool list) shows names synthesized from the filament the user selected on the printer screen.
It conforms to Spoolman's public REST contract; it never touches the printer firmware.
"""
import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# Must match AFC_lane.CHANNEL_SPOOL_BASE: the synthetic per-channel spool id the lane emits and the
# id this shim serves it under. High range never collides with a real server's auto-increment ids.
CHANNEL_SPOOL_BASE = 9_000_000
NOMINAL_WEIGHT_G = 1000
DEFAULT_PORT = 7912
SPOOL_ID_PATH = re.compile(r"^/v1/spool/(\d+)/?$")


def _filament_name(vendor: str, material: str, subtype: str) -> str:
    parts = [part for part in (vendor, material, subtype) if part and part != "NONE"]
    return " ".join(parts) if parts else "Unknown"


def _entry_at(print_task: dict, key: str, index: int, default: Any) -> Any:
    values = print_task.get(key, [])
    return values[index] if index < len(values) else default


def _spool_for(print_task: dict, extruder: int) -> dict:
    vendor = str(_entry_at(print_task, "filament_vendor", extruder, "NONE"))
    material = str(_entry_at(print_task, "filament_type", extruder, "NONE"))
    subtype = str(_entry_at(print_task, "filament_sub_type", extruder, "NONE"))
    color = str(_entry_at(print_task, "filament_color_rgba", extruder, "FFFFFFFF"))[:6]
    spool_id = CHANNEL_SPOOL_BASE + extruder
    return {
        "id": spool_id,
        "remaining_weight": NOMINAL_WEIGHT_G,
        "used_weight": 0,
        "archived": False,
        "filament": {
            "id": spool_id,
            "name": _filament_name(vendor, material, subtype),
            "material": material,
            "color_hex": color,
            "weight": NOMINAL_WEIGHT_G,
            "vendor": {"id": spool_id, "name": vendor},
        },
    }


def synthesize_spools(print_task: dict) -> list[dict]:
    """One Spoolman-shaped spool per loaded extruder; loaded comes from the sensor-derived flag."""
    exist = print_task.get("filament_exist", [])
    return [_spool_for(print_task, extruder) for extruder in range(len(exist)) if exist[extruder]]


def load_print_task(path: str) -> dict:
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalized_path(raw_path: str) -> str:
    return raw_path[4:] if raw_path.startswith("/api/") else raw_path


class SpoolmanShimHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _spools(self) -> list[dict]:
        print_task_path = getattr(self.server, "print_task_path", "")
        return synthesize_spools(load_print_task(print_task_path))

    def _send_one(self, spool_id: int) -> None:
        found = next((spool for spool in self._spools() if spool["id"] == spool_id), None)
        self._send_json(found if found is not None else {"message": "Spool not found"},
                        status=200 if found is not None else 404)

    def do_GET(self) -> None:
        path = _normalized_path(self.path)
        if path.startswith("/v1/info"):
            self._send_json({"version": "1.0.0", "git_version": "bespok3d-shim"})
            return
        spool_match = SPOOL_ID_PATH.match(path)
        if spool_match is not None:
            self._send_one(int(spool_match.group(1)))
            return
        if path.startswith("/v1/spool"):
            self._send_json(self._spools())
            return
        self._send_json({"message": "Not found"}, status=404)

    def _consume_body(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)

    def do_PUT(self) -> None:
        self._consume_body()
        self._send_json({})

    def do_POST(self) -> None:
        self._consume_body()
        self._send_json({})

    def log_message(self, *args: Any) -> None:
        pass


class SpoolmanShimServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], print_task_path: str) -> None:
        super().__init__(address, SpoolmanShimHandler)
        self.print_task_path = print_task_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Spoolman-API stand-in for the AFC panel")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--print-task", required=True)
    args = parser.parse_args()
    SpoolmanShimServer(("127.0.0.1", args.port), args.print_task).serve_forever()


if __name__ == "__main__":
    main()
