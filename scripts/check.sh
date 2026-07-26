#!/usr/bin/env bash
# This plugin's own gate: it must pass from this repo's root, with no sibling repo cloned except
# lib_bespok3d. Exits non-zero on any failure.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The shared gate helpers and the detectors that enforce a workspace-wide rule live in one place.
# See lib_bespok3d/tooling/README.md. This is the only line that knows where they are.
B3D_TOOLING="${B3D_TOOLING:-$REPO_ROOT/lib_bespok3d/tooling}"
# lib_bespok3d is a submodule. A clone made without it leaves an empty directory here, so say what
# is actually wrong instead of letting every check below fail on a missing file.
if [ ! -f "$B3D_TOOLING/gate-lib.sh" ]; then
    echo "The shared gate helpers are missing: the lib_bespok3d submodule is not checked out." >&2
    echo "Run this once from the repo root, then try again:" >&2
    echo "  git submodule sync --recursive && git submodule update --init --recursive" >&2
    echo "See CONTRIBUTING.md for the full environment setup." >&2
    exit 1
fi

# shellcheck source=/dev/null
. "$B3D_TOOLING/gate-lib.sh"

cd "$REPO_ROOT" || exit 1

PLUGIN_DIR="$REPO_ROOT/afc-lite"

echo ""
echo "u1-afc-lite gate"

b3d_python_tools

# afc-lite is ruff-only: every module under files/extras is a Klipper extra (config.get_printer(),
# gcode), which mypy cannot resolve, and the one pure module was dropped in 0.1.7. pytest covers the
# logic.
run_check "pytest"  pytest_in_dir "$PLUGIN_DIR" tests
run_check "ruff"    ruff_in_dir "$PLUGIN_DIR" files tests

workflow_pinning_check "$REPO_ROOT"
em_dash_check "$REPO_ROOT"
shellcheck_repo "$REPO_ROOT"

gate_summary || exit 1
