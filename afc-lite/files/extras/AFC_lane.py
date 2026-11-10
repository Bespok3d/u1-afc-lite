# Originally from the Extended Firmware overlay 31-feature-afc-lite (paxx12), GPL-3.0.
# Modified by the Bespok3d project on 2026-07-28: extended with per-lane RFID data and the lane
# state this plugin reports.

import json
import os
import re
from typing import Any

RFID_DATA_FILE = "/oem/printer_data/config/bespok3d/data/rfid_data.json"
TOOL_COUNT_MACRO = "gcode_macro AFC_TOOLS_IN_PLAY"
# A print that failed keeps its file loaded on the U1 (only a finished or cancelled print closes
# it), so a loaded file alone does not mean a print is in play.
PRINT_STATES_WITH_A_FILE_IN_PLAY = ("printing", "paused")
NOTHING_THE_TAG_KNOWS = "NONE"
FILAMENT_STATUS_KEYS = {'vendor': 'filament_vendor', 'type': 'filament_type',
                        'subtype': 'filament_sub_type'}
# The slicer writes the list of filaments a file uses near its top; a few kilobytes reach it.
HEADER_BYTES_TO_SCAN = 4096
SLICER_FILAMENT_LIST = re.compile(r"^; filament: *([0-9][0-9, ]*)\r?$", re.MULTILINE)


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


def tools_the_header_lists(header: str) -> list[int] | None:
    """The logical tools a file uses, from the slicer's `; filament: 2,1` header line, which counts
    filaments from 1 in the order the print first uses them. None when the file carries no such
    line, so the caller can tell "this file names no tools" from "this file uses none"."""
    match = SLICER_FILAMENT_LIST.search(header)
    if match is None:
        return None
    filament_numbers = (int(word) for word in match.group(1).split(",") if word.strip())
    return sorted({number - 1 for number in filament_numbers if number > 0})


def read_tools_the_file_uses(file_path: str) -> list[int] | None:
    try:
        with open(file_path, encoding="utf-8", errors="replace") as handle:
            return tools_the_header_lists(handle.read(HEADER_BYTES_TO_SCAN))
    except OSError:
        return None


def lane_colors(color_multi: dict) -> list[str]:
    """Every colour of the reel in a lane, as the printer holds it since firmware 2.0: a reel can
    carry up to five. Empty when the printer gave none, so the caller keeps its single colour."""
    color_count = color_multi.get('nums', 0) if isinstance(color_multi, dict) else 0
    colors = color_multi.get('colors', []) if color_count else []
    return [f"#{color[:6]}" for color in colors[:color_count] if isinstance(color, str)]


def name_the_tag_gives(state: dict) -> str:
    """The filament description the printer's own tag read gives a lane: brand, material, sub-type,
    the same three words in the same order the Spoolman bridge publishes, so the card reads the
    same with the bridge and without it.

    Empty when the reel is out, and empty when the tag names no material: a brand on its own tells
    nobody what is in the lane, and it is the material a slicer matches on."""
    if not state.get('loaded', False):
        return ""
    if state.get('type', NOTHING_THE_TAG_KNOWS) == NOTHING_THE_TAG_KNOWS:
        return ""
    words = (state.get('vendor'), state.get('type'), state.get('subtype'))
    return " ".join(word for word in words if word and word != NOTHING_THE_TAG_KNOWS)


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
        self.virtual_sdcard = None
        self.toolhead_sensor = None
        self.filament_feed = None

        self.spool_id_from_spoolman: Any = None
        self.spoolman_has_spoken_for_this_lane = False
        self.filament_name = ""
        self._rfid_cache: dict = {}
        self._rfid_mtime: float | None = None
        self._file_tools_cache: tuple[Any, list[int] | None] = (None, None)

        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        self.printer.register_event_handler("print_stats:stop", self._forget_declared_tools)

    def _handle_connect(self):
        try:
            self.print_task_config = self.printer.lookup_object("print_task_config")
        except Exception:
            pass
        self.virtual_sdcard = self.printer.lookup_object("virtual_sdcard", None)

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

    def _declared_tool_count(self) -> int:
        """How many logical tools the file about to print uses, as declared by the web interface
        through the AFC_TOOLS_IN_PLAY macro. Zero when nothing has been declared."""
        macro = self.printer.lookup_object(TOOL_COUNT_MACRO, None)
        if macro is None:
            return 0
        return int(macro.get_status(None).get('count', 0))

    def _forget_declared_tools(self) -> None:
        """A finished or cancelled print leaves the printer on its default map, so a count the web
        interface declared for it would make an idle lane claim tools again. Written the way
        SET_GCODE_VARIABLE writes it, a fresh dict, because the macro hands out the old one."""
        macro = self.printer.lookup_object(TOOL_COUNT_MACRO, None)
        variables = getattr(macro, "variables", {})
        if not variables.get('count'):
            return
        macro.variables = {**variables, 'count': 0}

    def _file_in_play(self) -> str | None:
        """The file the printer is printing or holding paused, whoever started it: the screen, a
        slicer, a browser or the cloud. None between prints."""
        if self.virtual_sdcard is None or not self._print_in_play():
            return None
        return self.virtual_sdcard.file_path()

    def _print_in_play(self) -> bool:
        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is None:
            return False
        return print_stats.state in PRINT_STATES_WITH_A_FILE_IN_PLAY

    def _tools_the_file_uses(self, file_path: str) -> list[int] | None:
        try:
            file_stamp = (file_path, os.stat(file_path).st_mtime)
        except OSError:
            return None
        if self._file_tools_cache[0] != file_stamp:
            self._file_tools_cache = (file_stamp, read_tools_the_file_uses(file_path))
        return self._file_tools_cache[1]

    def _tools_in_play(self) -> list[int]:
        """The logical tools the current print uses, read from the file itself, so a print started
        from the screen or a slicer is mapped as right as one started from a browser. With no
        file, or a file that does not list its tools, the count a web interface declared while its
        print dialog is open; with neither, no tool at all."""
        file_path = self._file_in_play()
        tools_in_file = self._tools_the_file_uses(file_path) if file_path else None
        if tools_in_file is not None:
            return tools_in_file
        return list(range(self._declared_tool_count()))

    def _mapped_tools(self, status):
        """Every logical tool the printer feeds from this lane. The U1 has 32 logical tools over 4
        physical lanes, so a file that uses more tools than the printer has lanes puts several of
        them on one lane; reporting only the first left the rest showing as fed by no lane.

        The table is always 32 entries long and an entry the file never set still reads as lane 0,
        so only the tools the file actually uses are counted; otherwise the first lane claims every
        unused tool and lists T0 through T30.

        A lane feeding none of the file's tools reports none. It used to fall back to its own tool,
        which put a tool back on a lane the user had just moved it off, so the assignment could
        never be emptied and moving another tool in appeared to move the first one away.

        With no print in play a lane reports no tool either: between prints the printer holds its
        default map, T0 on the first lane and so on, which says nothing about any print."""
        lane_of_tool = dict(enumerate(status.get('extruder_map_table', [])))
        return [f"T{tool_index}" for tool_index in self._tools_in_play()
                if lane_of_tool.get(tool_index) == self.lane_index]

    def _read_print_task_state(self, state, eventtime):
        status = self.print_task_config.get_status(eventtime)
        state['loaded'] = self._indexed(status, 'filament_exist', False)
        state['vendor'] = self._indexed(status, 'filament_vendor', 'NONE')
        state['type'] = self._indexed(status, 'filament_type', 'NONE')
        state['subtype'] = self._indexed(status, 'filament_sub_type', 'NONE')
        state['color'] = self._indexed(status, 'filament_color_rgba', 'FFFFFFFF')
        state['colors'] = lane_colors(self._indexed(status, 'filament_color_multi', {}))
        if status.get('auto_replenish_filament', False):
            state['runout_lane'] = 'AUTO'
        state['map'] = self._mapped_tools(status)

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
            'map': [],
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

    @property
    def spool_id(self) -> Any:
        """The spool the Spoolman bridge (or SET_SPOOL_ID) put on this lane, None once taken off."""
        return self.spool_id_from_spoolman

    @spool_id.setter
    def spool_id(self, spool_id: Any) -> None:
        """Once Spoolman has spoken for a lane it is the only word on it, taking a spool off
        included: otherwise "clear all spools" would leave the tag's own id on the panel, since the
        tag file belongs to the RFID reader and no clear ever touches it."""
        self.spool_id_from_spoolman = spool_id
        self.spoolman_has_spoken_for_this_lane = True
        if coerce_spool_id(spool_id) is None:
            self.filament_name = ""

    def _rfid_spool_id(self) -> int | None:
        entry = self._rfid_data().get(str(self.lane_index))
        if not isinstance(entry, dict):
            return None
        return coerce_spool_id(entry.get("SPOOL_ID"))

    def _macro_spool_id(self, tool: str) -> int | None:
        macro = self.printer.lookup_object(f"gcode_macro {tool}", None)
        if macro is None:
            return None
        return coerce_spool_id(getattr(macro, "variables", {}).get("spool_id"))

    def _tools_owning_the_pick(self, state: dict) -> list[str]:
        """Between prints the printer holds its default map, so a lane owns the pick on its own
        tool. During a print a lane feeding none of its tools owns no pick: its own tool may be fed
        from another lane, and the same spool would show on both."""
        if state.get('map'):
            return state['map']
        if self._tools_in_play():
            return []
        return [f"T{self.lane_index}"]

    def _tool_spool_id(self, state: dict) -> int | None:
        """Spool the user picked for this lane's tool in the Spoolman panel. The web UI writes it to
        the mapped T<n> macro's `spool_id` variable (SET_GCODE_VARIABLE), never to the lane. One
        lane can feed several tools, and they all draw the same spool, so the first pick wins."""
        picks = (self._macro_spool_id(tool) for tool in self._tools_owning_the_pick(state))
        return next((spool_id for spool_id in picks if spool_id is not None), None)

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

    def _filament_name_field(self, state: dict) -> dict:
        """The filament description the printer publishes for this lane to the slicer. A name the
        Spoolman bridge pushed (SET_LANE_FILAMENT_NAME) wins, because it reads the whole spool
        record and the tag holds three words; with no bridge installed the printer's own tag read
        names the lane.
        Emitted only when there is a name at all, so a lane neither of them can name still falls
        back to the panel's own spool.filament.name (default display preserved)."""
        name = self.filament_name or name_the_tag_gives(state)
        return {'filament_name': name} if name else {}

    def _resolve_spool_id(self, state: dict) -> int | None:
        """Spoolman's word is final for a lane it has spoken for, an empty lane included. With no
        word from it: the RFID tag, then the spool picked for the lane's tool in the Spoolman panel,
        else nothing. A screen pick with no Spoolman carries its NAME on `filament_name` (pushed by
        the Spoolman bridge), never a synthetic spool id."""
        if self.spoolman_has_spoken_for_this_lane:
            return coerce_spool_id(self.spool_id_from_spoolman)
        candidates = (self._rfid_spool_id(), self._tool_spool_id(state))
        return next((value for value in candidates if value is not None), None)

    def filament(self) -> dict:
        """The brand, material and sub-type the printer holds for this lane."""
        if not self.print_task_config:
            return {field: NOTHING_THE_TAG_KNOWS for field in FILAMENT_STATUS_KEYS}
        status = self.print_task_config.get_status(None)
        return {field: self._indexed(status, status_key, NOTHING_THE_TAG_KNOWS)
                for field, status_key in FILAMENT_STATUS_KEYS.items()}

    def get_status(self, eventtime=None):
        response = {}

        state = self._get_state(eventtime)

        response['name'] = self.name
        response['unit'] = self.unit_name
        response['lane'] = self.lane_index
        response['extruder'] = self.extruder_name
        response['map'] = state.get('map', [])
        response['load'] = state.get('loaded', False)
        response['prep'] = state.get('loaded', False)
        response['tool_loaded'] = state.get('tool_loaded', response['load'])
        response['loaded_to_hub'] = False
        response['material'] = state.get('type', 'NONE')
        response['spool_id'] = self._resolve_spool_id(state)
        response['color'] = f"#{state.get('color', 'FFFFFFFF')[:6]}" # RGB only, ignore alpha
        response['colors'] = state.get('colors') or [response['color']]
        # No weight: the U1 weighs nothing on a lane, and the panel reads a lane's remaining weight
        # off Spoolman when there is a spool. The number this used to report was invented, and it
        # read on every card as a full roll nobody had measured.
        response['runout_lane'] = state.get('runout_lane', '?')
        response['filament_status'] = 'unknown'
        response['filament_status_led'] = 'gray'
        response['status'] = AFCLaneState.EMPTY
        response.update({**self._mounted_field(), **self._filament_name_field(state)})
        return response

def load_config_prefix(config):
    return AFCLane(config)
