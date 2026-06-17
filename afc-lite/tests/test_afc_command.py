# ruff: noqa: PLR2004  Tests assert against literal spool ids and colors.
"""Regression tests for the SET_SPOOL_ID g-code command."""
import base64

import pytest
from AFC import AFC


def _b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class FakeGcode:
    def register_command(self, *args, **kwargs):
        pass


class FakePrinter:
    def __init__(self):
        self._gcode = FakeGcode()

    def lookup_object(self, name, default=None):
        return self._gcode if name == "gcode" else default

    def register_event_handler(self, *args):
        pass


class FakeConfig:
    def get_printer(self):
        return FakePrinter()

    def get(self, key, default=None):
        return default


class FakeGcmd:
    def __init__(self, params):
        self._params = params

    def get(self, key, default=None):
        if key in self._params:
            return self._params[key]
        if default is None:
            raise self.error(f"missing {key}")
        return default

    def get_int(self, key, default=None):
        value = self._params.get(key, default)
        return None if value is None else int(value)

    def error(self, message):
        return ValueError(message)


class FakeLane:
    def __init__(self, lane_index=0):
        self.spool_id = None
        self.lane_index = lane_index
        self.filament_name = ""


def make_afc():
    return AFC(FakeConfig())


def test_set_spool_id_assigns_to_named_lane():
    afc = make_afc()
    lane = FakeLane()
    afc.lanes = {"E0": lane}
    afc.cmd_SET_SPOOL_ID(FakeGcmd({"LANE": "E0", "SPOOL_ID": "42"}))
    assert lane.spool_id == 42


def test_set_spool_id_unknown_lane_raises():
    afc = make_afc()
    afc.lanes = {}
    with pytest.raises(ValueError):
        afc.cmd_SET_SPOOL_ID(FakeGcmd({"LANE": "E9", "SPOOL_ID": "1"}))


def test_set_lane_filament_name_targets_lane_by_extruder():
    afc = make_afc()
    lane = FakeLane(lane_index=3)
    afc.lanes = {"E3": lane}
    afc.cmd_SET_LANE_FILAMENT_NAME(FakeGcmd({"EXTRUDER": "3", "NAME_B64": _b64("ZIRO Silk Gold")}))
    assert lane.filament_name == "ZIRO Silk Gold"


def test_set_lane_filament_name_unknown_extruder_raises():
    afc = make_afc()
    afc.lanes = {"E0": FakeLane(lane_index=0)}
    with pytest.raises(ValueError):
        afc.cmd_SET_LANE_FILAMENT_NAME(FakeGcmd({"EXTRUDER": "9", "NAME_B64": _b64("x")}))


class FakeExtruder:
    def __init__(self, state):
        self._state = state

    def get_park_detector_status(self):
        return {"state": self._state} if self._state else None


class FakeLaneObj:
    def __init__(self, extruder_name):
        self.extruder_name = extruder_name


class FakeNamed:
    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


class FakeToolhead:
    def __init__(self, mounted):
        self._mounted = mounted

    def get_extruder(self):
        return FakeNamed(self._mounted)


class CarrierPrinter:
    def __init__(self, objects):
        self._objects = objects

    def lookup_object(self, name, default=None):
        return self._objects.get(name, default)


def make_afc_with_lanes(objects, lanes):
    afc = make_afc()
    afc.printer = CarrierPrinter(objects)
    afc.lanes = lanes
    return afc


def test_current_lane_is_the_activated_extruder():
    objects = {"extruder": FakeExtruder("PARKED"), "extruder3": FakeExtruder("ACTIVATE")}
    lanes = {"E0": FakeLaneObj("extruder"), "E3": FakeLaneObj("extruder3")}
    afc = make_afc_with_lanes(objects, lanes)
    assert afc._get_current_lane() == "E3"


def test_current_lane_none_when_all_parked():
    objects = {"extruder": FakeExtruder("PARKED"), "extruder3": FakeExtruder("PARKED")}
    lanes = {"E0": FakeLaneObj("extruder"), "E3": FakeLaneObj("extruder3")}
    afc = make_afc_with_lanes(objects, lanes)
    assert afc._get_current_lane() is None


def test_current_lane_falls_back_to_toolhead_without_detectors():
    objects = {
        "extruder": FakeExtruder(None),
        "extruder3": FakeExtruder(None),
        "toolhead": FakeToolhead("extruder3"),
    }
    lanes = {"E0": FakeLaneObj("extruder"), "E3": FakeLaneObj("extruder3")}
    afc = make_afc_with_lanes(objects, lanes)
    assert afc._get_current_lane() == "E3"
