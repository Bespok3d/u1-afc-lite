"""Regression tests for the print-start hold that lets the lane-to-tool map be made.

A print sent from a slicer with "start printing after upload" never reaches a browser, so nothing
opens the lane assignment dialog either web interface already carries. This keeps the print from
starting and raises a flag the browser can see; the dialog opens on that flag, and the print starts
once the map is made.

Nothing is drawn from here. The print is never started and then stopped: Klipper's own
print_task_config refuses SET_PRINT_EXTRUDER_MAP while print_stats.state is 'printing' or 'paused',
so a print that has begun can never have its map set.

It must never define a section for a macro the printer already defines. Klipper reads every config
file into one namespace with `strict=False`, so a second `[gcode_macro PRINT_START]` does not wrap
the printer's own one, it overwrites its lines; `rename_existing` then names a command that does not
exist and Klipper halts. Only a command registered by Klipper's own python, which owns no config
section, can be wrapped. That halt happened on a printer, which is why the first test below exists.
"""
import ast
import json
import re
import shlex
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
TOOLMAP_TEMPLATE = PLUGIN_DIR / "files" / "cfg" / "klipper" / "afc-toolmap.cfg.tmpl"
MANIFEST = PLUGIN_DIR / "manifest.json"

STORES_THE_HELD_REQUEST = (
    "SET_GCODE_VARIABLE MACRO=_AFC_TOOLMAP VARIABLE=held_print VALUE='{rawparams|tojson}'"
)

MACROS_THE_PRINTER_DEFINES = {
    "PRINT_START", "PRINT_END", "START_PRINT", "END_PRINT",
    "PAUSE", "RESUME", "CANCEL_PRINT", "M600",
}
COMMANDS_KLIPPER_PYTHON_REGISTERS = {
    "SDCARD_PRINT_FILE", "SDCARD_PRINT_FILE_WITH_PARAMETERS", "SDCARD_RESET_FILE",
}


def macro_body(macro_name):
    text = TOOLMAP_TEMPLATE.read_text()
    pattern = rf"\[gcode_macro {re.escape(macro_name)}\](.*?)(?=\n\[|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if match is None:
        raise AssertionError(f"macro {macro_name} not found in afc-toolmap.cfg.tmpl")
    return match.group(1)


def declared_macros():
    return re.findall(r"^\[gcode_macro ([^\]]+)\]", TOOLMAP_TEMPLATE.read_text(), re.MULTILINE)


def manifest():
    return json.loads(MANIFEST.read_text())


def test_no_macro_the_printer_already_defines_is_redefined():
    assert MACROS_THE_PRINTER_DEFINES.isdisjoint(declared_macros())


def test_only_a_klipper_registered_command_is_wrapped():
    text = TOOLMAP_TEMPLATE.read_text()
    wrapped = re.findall(r"^\[gcode_macro ([^\]]+)\]\nrename_existing:", text, re.MULTILINE)
    assert wrapped
    assert set(wrapped) <= COMMANDS_KLIPPER_PYTHON_REGISTERS


def test_the_screen_keeps_starting_prints_its_own_way():
    assert "SDCARD_PRINT_FILE_WITH_PARAMETERS" not in TOOLMAP_TEMPLATE.read_text()


def held_branch():
    """The lines that run when the setting is on, up to the else that runs when it is off."""
    body = macro_body("SDCARD_PRINT_FILE")
    assert "ask|lower == 'on'" in body
    return body.split("ask|lower == 'on' %}", 1)[1].split("{% else %}", 1)[0]


def test_the_print_still_starts_with_the_arguments_it_was_given():
    body = macro_body("SDCARD_PRINT_FILE")
    assert "rename_existing: _AFC_TOOLMAP_START_PRINT_BASE" in body
    unheld = body.split("{% else %}", 1)[1]
    assert "_AFC_TOOLMAP_START_PRINT_BASE {rawparams}" in unheld


def test_nothing_happens_unless_the_owner_turned_it_on():
    assert "_AFC_TOOLMAP_HOLD" in held_branch()


def test_a_held_print_is_never_started_and_then_stopped():
    """Klipper refuses SET_PRINT_EXTRUDER_MAP while printing OR paused, so a print that has begun
    can never have its map set. The held branch must not start the print, and must not pause."""
    assert "_AFC_TOOLMAP_START_PRINT_BASE" not in held_branch()
    assert "PAUSE" not in TOOLMAP_TEMPLATE.read_text()
    assert "RESUME" not in TOOLMAP_TEMPLATE.read_text()


def test_the_browser_is_told_which_file_is_held_before_it_is_told_to_ask():
    """print_stats.filename is empty while nothing has been selected, so the held request is the
    only place the browser can read the filename, and it has to be there when the flag goes up."""
    assert 'variable_held_print: ""' in TOOLMAP_TEMPLATE.read_text()
    branch = held_branch()
    stores_request = branch.index(STORES_THE_HELD_REQUEST)
    assert stores_request < branch.index("_AFC_TOOLMAP_HOLD")


def test_a_filename_with_a_space_in_it_is_stored_and_read_back_unchanged():
    """A print of "spool test.gcode" arrives as FILENAME="spool test.gcode", quotes and all, and
    Klipper reads its own command through shlex before reading VALUE as a python literal. Quoting
    the request by hand lost the quotes around the name, and a name with a space in it failed the
    command outright, so the print was never started."""
    assert STORES_THE_HELD_REQUEST in held_branch()
    for filename in [
        "plain.gcode",
        "spool test.gcode",
        "an owner's part.gcode",
        'an odd" name.gcode',
        "a<b&c.gcode",
    ]:
        request = f'FILENAME="{filename}"'
        assert klipper_reads_back(stored_request_command(request)) == request


def stored_request_command(request):
    """The command the template renders, with tojson doing what jinja2 does to the request."""
    return STORES_THE_HELD_REQUEST.replace("{rawparams|tojson}", as_jinja_tojson(request))


def as_jinja_tojson(text):
    """jinja2's own tojson: a json string, with the characters that end an html attribute or a
    shell quote escaped as well."""
    escaped = json.dumps(text)
    html_escapes = [("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), ("'", "\\u0027")]
    for character, escape in html_escapes:
        escaped = escaped.replace(character, escape)
    return escaped


def klipper_reads_back(commandline):
    """How Klipper parses an extended command: shlex over the arguments, then a python literal."""
    arguments = commandline.split(None, 1)[1]
    parameters = dict(token.split("=", 1) for token in shlex.split(arguments))
    return ast.literal_eval(parameters["VALUE"])


def test_the_browser_can_see_that_a_print_is_being_held():
    assert "variable_holding_for_map: 0" in TOOLMAP_TEMPLATE.read_text()
    body = macro_body("_AFC_TOOLMAP_HOLD")
    assert "SET_GCODE_VARIABLE MACRO=_AFC_TOOLMAP VARIABLE=holding_for_map VALUE=1" in body


def test_a_held_print_never_starts_by_itself():
    """A print that starts unanswered is a ruined plate, so nothing times out and starts it."""
    text = TOOLMAP_TEMPLATE.read_text()
    assert "delayed_gcode" not in text
    assert "UPDATE_DELAYED_GCODE" not in text


def test_the_printer_draws_no_question_of_its_own():
    text = TOOLMAP_TEMPLATE.read_text()
    assert "action:prompt" not in text
    assert "SET_MAP" not in text


def test_both_answers_are_commands_the_browser_can_send():
    typeable = set(declared_macros()) - COMMANDS_KLIPPER_PYTHON_REGISTERS
    assert {name for name in typeable if not name.startswith("_")} == {
        "AFC_TOOLMAP_GO", "AFC_TOOLMAP_CANCEL",
    }


def test_dismissing_the_question_drops_the_print_instead_of_starting_it():
    body = macro_body("AFC_TOOLMAP_CANCEL")
    assert "SET_GCODE_VARIABLE MACRO=_AFC_TOOLMAP VARIABLE=holding_for_map VALUE=0" in body
    assert "SET_GCODE_VARIABLE MACRO=_AFC_TOOLMAP VARIABLE=held_print VALUE=\"''\"" in body
    assert "_AFC_TOOLMAP_START_PRINT_BASE" not in body


def test_releasing_the_hold_runs_the_print():
    body = macro_body("AFC_TOOLMAP_GO")
    assert "SET_GCODE_VARIABLE MACRO=_AFC_TOOLMAP VARIABLE=holding_for_map VALUE=0" in body
    assert "_AFC_TOOLMAP_START_PRINT_BASE {held_print}" in body


def test_releasing_twice_cannot_start_the_same_print_twice():
    body = macro_body("AFC_TOOLMAP_GO")
    assert "{% if held_print %}" in body
    assert "SET_GCODE_VARIABLE MACRO=_AFC_TOOLMAP VARIABLE=held_print VALUE=\"''\"" in body


def test_the_lanes_the_print_needs_are_fed_before_it_starts():
    """The lanes are known only once the map is made, and filament cannot be loaded into a lane
    while the print runs, so the feed sits between the answer and the start."""
    body = macro_body("AFC_TOOLMAP_GO")
    assert body.index("_AFC_TOOLMAP_FEED_EMPTY_LANES") < body.index("_AFC_TOOLMAP_START_PRINT_BASE")


def test_only_a_print_that_was_held_is_fed():
    """Nothing is fed when no print is held: the map belongs to a file that is not starting."""
    body = macro_body("AFC_TOOLMAP_GO")
    after_the_guard = body.split("{% if held_print %}", 1)[1]
    assert "_AFC_TOOLMAP_FEED_EMPTY_LANES" in after_the_guard


def test_nothing_is_fed_unless_the_owner_turned_it_on():
    body = macro_body("_AFC_TOOLMAP_FEED_EMPTY_LANES")
    assert "feed|lower == 'on'" in body
    assert "if feeding_is_on else 0" in body


def test_only_the_lanes_this_print_uses_are_fed():
    """The map table is always 32 entries long and an entry the file never set still reads as lane
    0, so reading the whole table would feed lane 0 for every print, whatever it uses."""
    body = macro_body("_AFC_TOOLMAP_FEED_EMPTY_LANES")
    assert "extruder_map_table[:tools_in_play]" in body
    assert "lane in lanes_this_print_uses" in body


def test_a_lane_that_already_holds_filament_is_left_alone():
    body = macro_body("_AFC_TOOLMAP_FEED_EMPTY_LANES")
    assert "not lane_has_filament[lane]" in body


def test_each_lane_is_fed_once_and_by_the_printers_own_loader():
    """Several tools of one file share a lane, so walking the tools would feed the same lane again
    for each of them. Walking the lanes instead feeds each at most once."""
    body = macro_body("_AFC_TOOLMAP_FEED_EMPTY_LANES")
    assert "for lane in range(lane_has_filament|length)" in body
    assert "AUTO_FEEDING EXTRUDER={lane} LOAD=1 PRINTING=1" in body


def test_the_feed_is_off_by_default():
    feed = next(entry for entry in manifest()["config"] if entry["key"] == "AFC_TOOLMAP_FEED")
    assert feed["default"] == "off"
    assert feed["options"] == ["off", "on"]


def test_the_rendered_settings_stay_valid_klipper_config():
    assert 'variable_ask: "$AFC_TOOLMAP_ASK"' in TOOLMAP_TEMPLATE.read_text()
    assert 'variable_feed: "$AFC_TOOLMAP_FEED"' in TOOLMAP_TEMPLATE.read_text()


def test_every_template_variable_is_declared_in_the_manifest():
    used = set(re.findall(r"\$([A-Z][A-Z0-9_]+)", TOOLMAP_TEMPLATE.read_text()))
    declared = {entry["key"] for entry in manifest()["config"]}
    assert used
    assert used <= declared


def test_the_question_is_off_by_default():
    ask = next(entry for entry in manifest()["config"] if entry["key"] == "AFC_TOOLMAP_ASK")
    assert ask["default"] == "off"
    assert ask["options"] == ["off", "on"]


def test_the_template_is_rendered_onto_the_printer_as_a_cfg():
    placed = next(
        entry for entry in manifest()["install"]["place"]
        if entry["src"].endswith("afc-toolmap.cfg.tmpl")
    )
    assert placed["class"] == "klipper-config"
    assert placed["name"] == "afc-toolmap.cfg"
    assert placed["render"] is True
