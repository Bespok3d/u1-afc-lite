import json
import os
from typing import Any

RFID_DATA_FILE = "/oem/printer_data/config/bespok3d/data/rfid_data.json"


class AFCLaneState:
    EMPTY = "empty"
    LOADING = "loading"
    LOADED = "loaded"
    UNLOADING = "unloading"
    TOOL_LOADED = "tool_loaded"
    ERROR = "error"


def coerce_spool_id(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number or None


class AFCLane:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.name = config.get_name().replace("AFC_lane ", "", 1)

        self.unit_name = config.get("unit", "")
        self.lane_index = config.getint("lane", 0)
        self.extruder_name = config.get("extruder", None)
        self.toolhead_sensor_name = config.get("toolhead_sensor", None)
        self.filament_feed_name = config.get("filament_feed", None)

        self.print_task_config = None
        self.toolhead_sensor = None
        self.filament_feed = None

        self.spool_id = None
        self.filament_name = ""
        self._rfid_cache: dict = {}
        self._rfid_mtime: float | None = None

        self.printer.register_event_handler("klippy:connect", self._handle_connect)

    def _handle_connect(self):
        try:
            self.print_task_config = self.printer.lookup_object("print_task_config")
        except Exception:
            pass

        if self.filament_feed_name:
            try:
                self.filament_feed = self.printer.lookup_object(self.filament_feed_name)
            except Exception:
                pass

        if self.toolhead_sensor_name:
            try:
                self.toolhead_sensor = self.printer.lookup_object(self.toolhead_sensor_name)
            except Exception:
                pass

    def _indexed(self, status, key, default):
        return dict(enumerate(status.get(key, []))).get(self.lane_index, default)

    def _mapped_tool(self, status):
        tool_to_extruder = dict(enumerate(status.get('extruder_map_table', [])))
        for tool_idx, extruder_idx in tool_to_extruder.items():
            if extruder_idx == self.lane_index:
                return f"T{tool_idx}"  # AFC only supports a single tool mapped
        return f"T{self.lane_index}"

    def _read_print_task_state(self, state, eventtime):
        status = self.print_task_config.get_status(eventtime)
        state['loaded'] = self._indexed(status, 'filament_exist', False)
        state['vendor'] = self._indexed(status, 'filament_vendor', 'NONE')
        state['type'] = self._indexed(status, 'filament_type', 'NONE')
        state['subtype'] = self._indexed(status, 'filament_sub_type', 'NONE')
        state['color'] = self._indexed(status, 'filament_color_rgba', 'FFFFFFFF')
        if status.get('auto_replenish_filament', False):
            state['runout_lane'] = 'AUTO'
        state['map'] = self._mapped_tool(status)

    def _get_state(self, eventtime=None):
        """Get filament info from print_task_config based on lane index"""
        if not self.print_task_config:
            return {}

        state = {
            'loaded': False,
            'tool_loaded': False,
            'vendor': 'NONE',
            'type': 'NONE',
            'subtype': 'NONE',
            'color': 'FFFFFFFF',
            'map': f"T{self.lane_index}",
            'runout_lane': 'NONE',
        }

        try:
            self._read_print_task_state(state, eventtime)
        except Exception:
            pass

        try:
            status = self.toolhead_sensor.get_status(eventtime)
            state['tool_loaded'] = status.get('filament_detected', True)
        except Exception:
            state['tool_loaded'] = state['loaded']

        return state

    def _read_rfid_file(self) -> dict:
        try:
            with open(RFID_DATA_FILE) as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _rfid_data(self) -> dict:
        try:
            mtime = os.stat(RFID_DATA_FILE).st_mtime
        except OSError:
            self._rfid_cache, self._rfid_mtime = {}, None
            return self._rfid_cache
        if mtime != self._rfid_mtime:
            self._rfid_cache, self._rfid_mtime = self._read_rfid_file(), mtime
        return self._rfid_cache

    def _rfid_spool_id(self) -> int | None:
        entry = self._rfid_data().get(str(self.lane_index))
        if not isinstance(entry, dict):
            return None
        return coerce_spool_id(entry.get("SPOOL_ID"))

    def _tool_spool_id(self, state: dict) -> int | None:
        """Spool the user picked for this lane's tool in the Spoolman panel. The web UI writes it to
        the mapped T<n> macro's `spool_id` variable (SET_GCODE_VARIABLE), never to the lane."""
        tool = state.get('map')
        macro = self.printer.lookup_object(f"gcode_macro {tool}", None) if tool else None
        if macro is None:
            return None
        return coerce_spool_id(getattr(macro, "variables", {}).get("spool_id"))

    def _park_detector_state(self) -> dict | None:
        if not self.extruder_name:
            return None
        extruder = self.printer.lookup_object(self.extruder_name, None)
        read_state = getattr(extruder, "get_park_detector_status", None)
        return read_state() if read_state else None

    def _mounted(self) -> bool | None:
        """True when this lane's tool is the one parked on the carrier. None when the lane has no
        park detector (a buffer-fed setup, where 'mounted' is meaningless): the panel then falls
        back to tool-loaded gating instead of toolchanger gating."""
        state = self._park_detector_state()
        if state is None:
            return None
        return state.get('state') == 'ACTIVATE'

    def _mounted_field(self) -> dict:
        mounted = self._mounted()
        return {} if mounted is None else {'mounted': mounted}

    def _filament_name_field(self) -> dict:
        """A vendor+name display label pushed by the Spoolman bridge (SET_LANE_FILAMENT_NAME).
        Emitted only when enriched, so the panel falls back to its own spool.filament.name when the
        bridge is absent (default display preserved)."""
        return {'filament_name': self.filament_name} if self.filament_name else {}

    def _resolve_spool_id(self, state: dict) -> int | None:
        """First real id wins: direct (helper push / SET_SPOOL_ID), then RFID tag, then the spool
        picked for the lane's tool in the Spoolman panel; else nothing. A screen pick with no
        Spoolman carries its NAME on `filament_name` (pushed by the Spoolman bridge), never a
        synthetic spool id."""
        candidates = (
            coerce_spool_id(self.spool_id),
            self._rfid_spool_id(),
            self._tool_spool_id(state),
        )
        return next((value for value in candidates if value is not None), None)

    def get_status(self, eventtime=None):
        response = {}

        state = self._get_state(eventtime)

        response['name'] = self.name
        response['unit'] = self.unit_name
        response['lane'] = self.lane_index
        response['extruder'] = self.extruder_name
        response['map'] = state.get('map', f"T{self.lane_index}")
        response['load'] = state.get('loaded', False)
        response['prep'] = state.get('loaded', False)
        response['tool_loaded'] = state.get('tool_loaded', response['load'])
        response['loaded_to_hub'] = False
        response['material'] = state.get('type', 'NONE')
        response['spool_id'] = self._resolve_spool_id(state)
        response['color'] = f"#{state.get('color', 'FFFFFFFF')[:6]}" # RGB only, ignore alpha
        response['weight'] = 1000 # AFC doesn't track weight
        response['runout_lane'] = state.get('runout_lane', '?')
        response['filament_status'] = 'unknown'
        response['filament_status_led'] = 'gray'
        response['status'] = AFCLaneState.EMPTY
        response.update({**self._mounted_field(), **self._filament_name_field()})
        return response

def load_config_prefix(config):
    return AFCLane(config)
