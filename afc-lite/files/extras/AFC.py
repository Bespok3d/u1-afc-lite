# ruff: noqa: N802  Klipper registers g-code handlers by method name; they must be cmd_UPPERCASE.
import base64


def _decode_name(raw: str) -> str:
    """Base64-decode a pushed filament name (encoded so spaces survive Klipper's gcode parser)."""
    try:
        return base64.b64decode(raw).decode('utf-8', 'replace') if raw else ''
    except ValueError:
        return ''


class AFCState:
    IDLE = "idle"
    LOADING = "loading"
    UNLOADING = "unloading"
    TOOL_CHANGE = "tool_change"
    ERROR = "error"

class AFC:
    def __init__(self, config):
        self.printer = config.get_printer()
        config.get("enabled", "True")
        self.gcode = self.printer.lookup_object("gcode")

        self.units = {}
        self.lanes = {}

        self.gcode.register_command("SET_SPOOL_ID", self.cmd_SET_SPOOL_ID,
                                    desc="Assign a Spoolman spool id to an AFC lane")
        self.gcode.register_command("SET_LANE_FILAMENT_NAME", self.cmd_SET_LANE_FILAMENT_NAME,
                                    desc="Set a lane filament display name by extruder")
        self.printer.register_event_handler("klippy:connect", self._handle_connect)

    def cmd_SET_SPOOL_ID(self, gcmd):
        lane_name = gcmd.get('LANE')
        spool_id = gcmd.get_int('SPOOL_ID', None)
        lane = self.lanes.get(lane_name)
        if lane is None:
            raise gcmd.error(f"unknown AFC lane: {lane_name}")
        lane.spool_id = spool_id

    def cmd_SET_LANE_FILAMENT_NAME(self, gcmd):
        extruder = gcmd.get_int('EXTRUDER')
        lane = self._lane_for_extruder(extruder)
        if lane is None:
            raise gcmd.error(f"no AFC lane for extruder index: {extruder}")
        lane.filament_name = _decode_name(gcmd.get('NAME_B64', ''))

    def _lane_for_extruder(self, extruder):
        return next((lane for lane in self.lanes.values()
                     if getattr(lane, 'lane_index', None) == extruder), None)

    def _handle_connect(self):
        for name, obj in self.printer.lookup_objects("AFC_unit"):
            unit_name = name.replace("AFC_", "", 1)
            self.units[unit_name] = obj

        for name, obj in self.printer.lookup_objects("AFC_lane"):
            lane_name = name.split(None, 1)[1] if " " in name else name
            self.lanes[lane_name] = obj

    def _lane_park_states(self):
        states = {}
        for lane_name, lane in self.lanes.items():
            extruder = self.printer.lookup_object(lane.extruder_name, None)
            read_state = getattr(extruder, "get_park_detector_status", None)
            states[lane_name] = read_state() if read_state else None
        return states

    def _toolhead_lane(self):
        try:
            mounted = self.printer.lookup_object('toolhead').get_extruder().get_name()
        except Exception:
            return None
        for lane_name, lane in self.lanes.items():
            if lane.extruder_name == mounted:
                return lane_name
        return None

    def _get_current_lane(self):
        """The lane whose tool is mounted on the carrier. With park detectors that is the extruder
        reporting ACTIVATE; if none is ACTIVATE nothing is mounted, so return None (no active lane,
        every Eject greys out). Without detectors, fall back to the live extruder."""
        try:
            states = self._lane_park_states()
        except Exception:
            return None
        active = [name for name, state in states.items()
                  if state and state.get('state') == 'ACTIVATE']
        if active:
            return active[0]
        has_detectors = any(state is not None for state in states.values())
        return None if has_detectors else self._toolhead_lane()

    def get_status(self, eventtime=None):
        return {
            'current_load': None,
            'current_lane': self._get_current_lane(),
            'next_lane': None,
            'current_state': AFCState.IDLE,
            'current_toolchange': 0,
            'number_of_toolchanges': 0,
            'spoolman': True,
            'td1_present': False,
            'lane_data_enabled': False,
            'error_state': False,
            'bypass_state': False,
            'quiet_mode': False,
            'position_saved': False,
            'units': list(self.units.keys()),
            'lanes': list(self.lanes.keys()),
            'extruders': [],
            'hubs': [],
            'buffers': [],
            'message': "",
            'led_state': "",
        }

def load_config(config):
    return AFC(config)
