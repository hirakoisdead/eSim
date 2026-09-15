"""Regression guards for the Flow Navigator's single-source-of-truth design.

The Author / Verify / Convert stages are *views on one in-memory design* (a
``DesignBus``), not three editors that sync through disk. The Flow Navigator
collects the stage being left into the bus and renders the bus into the stage
being entered -- all in memory -- so navigating in any order (or skipping
Verify) always lands on the same current design, with no "send"/hand-off step
and no disk round-trip on a tab switch.

Disk is persistence only: an explicit Save, and a lazy ``materialize`` right
before Convert (whose toolchain reads a real file path). The machinery that
existed *only* because disk was the message bus -- the per-load watchdog
Observer, the red-blink toggle thread, the ``toggle_flag`` global, the Refresh
button and its modal "please click Refresh" popup -- is gone.

If one of these fails, fix the wiring in the source rather than relaxing the
guard.
"""
import ast
import os

_HERE = os.path.dirname(__file__)
_FLOWNAV = os.path.join(_HERE, "..", "FlowNavigator.py")
_VERIFIER = os.path.join(_HERE, "..", "VerilogVerifier.py")
_MAKER = os.path.join(_HERE, "..", "Maker.py")


def _read(path):
    with open(path) as fh:
        return fh.read()


def _func(src, name):
    """Return the FunctionDef node named ``name`` from a source string."""
    return next((n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)


def _calls_in(node):
    """Attribute-call names (e.g. 'self.foo' -> 'foo') found under ``node``."""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            names.add(sub.func.attr)
    return names


# ---------------------------------------------------------------------------
# Flow Navigator: owns the bus and syncs both directions in memory
# ---------------------------------------------------------------------------

def test_flownav_owns_a_design_bus():
    src = _read(_FLOWNAV)
    assert "DesignBus(" in src, \
        "FlowNavigator must construct the shared DesignBus"
    assert "externalChange" in src, \
        "FlowNavigator must subscribe to the bus's externalChange signal"


def test_flownav_defines_sync_model():
    src = _read(_FLOWNAV)
    for fn in ("_sync_in", "_sync_out", "_goto_stage"):
        assert _func(src, fn) is not None, \
            f"FlowNavigator must define {fn} for the shared-design model"


def test_stage_switch_syncs_both_directions():
    """Every Verilog stage switch must collect the stage being left and render
    the stage being entered, so the one design is carried in any order."""
    src = _read(_FLOWNAV)
    goto = _func(src, "_goto_stage")
    calls = _calls_in(goto)
    assert "_sync_out" in calls and "_sync_in" in calls, \
        "_goto_stage must call both _sync_out and _sync_in"


def test_convert_materializes_design_to_disk():
    """Entering Convert must materialize the in-memory design to a real file,
    since the converter toolchain reads Maker.verilogFile[...] as a path."""
    src = _read(_FLOWNAV)
    sync_in = _func(src, "_sync_in")
    assert sync_in is not None and "materialize" in _calls_in(sync_in), \
        "_sync_in must materialize the design before Convert"


def test_external_change_is_a_non_modal_reload():
    src = _read(_FLOWNAV)
    assert _func(src, "_on_external_change") is not None, \
        "FlowNavigator must handle externalChange with a reload offer"
    assert _func(src, "_do_reload") is not None and \
        _func(src, "_dismiss_reload") is not None, \
        "the reload bar must offer Reload / Keep-mine (non-modal)"


def test_flownav_close_stops_makerchip_loopback_session():
    """Closing the dock must release a browser bridge owned by its Author.

    Child widgets are destroyed with the dock but do not reliably receive a
    close event of their own, so the host owns this explicit lifecycle call.
    """
    src = _read(_FLOWNAV)
    close = _func(src, "closeEvent")
    assert close is not None and "stop_makerchip_bridge" in _calls_in(close)


def test_no_send_handoff_remains():
    """The old explicit hand-off (Verify -> _on_verified -> Author -> Convert)
    is replaced by automatic in-memory sync; it must be gone."""
    src = _read(_FLOWNAV)
    assert _func(src, "_on_verified") is None, \
        "the _on_verified hand-off must be removed (sync is automatic now)"
    assert "sendToNgVeri" not in src, \
        "FlowNavigator must not depend on the sendToNgVeri hand-off signal"


# ---------------------------------------------------------------------------
# Verifier: edits the shared bus in memory; no disk write on leave
# ---------------------------------------------------------------------------

def test_verifier_exposes_bus_contract():
    src = _read(_VERIFIER)
    for fn in ("set_design_bus", "render_from_bus", "collect_into_bus",
               "get_design_code"):
        assert _func(src, fn) is not None, \
            f"VerilogVerifier must define {fn}"


def test_verifier_collect_does_not_write_disk():
    """Leaving Verify must push edits into the bus IN MEMORY -- the bus owns disk
    I/O. collect_into_bus must not save/materialize itself (that disk-as-IPC
    write was what triggered the watchdog popup on every tab switch)."""
    src = _read(_VERIFIER)
    collect = _func(src, "collect_into_bus")
    calls = _calls_in(collect)
    assert "set_content" in calls, \
        "collect_into_bus must push the design into the bus (set_content)"
    assert "save_to_disk" not in calls and "materialize" not in calls, \
        "collect_into_bus must stay in memory; it must not write disk"


def test_verifier_send_button_removed():
    src = _read(_VERIFIER)
    assert "btn_send" not in src, \
        "the 'Send to Makerchip' button must be removed"
    assert _func(src, "send_to_makerchip") is None, \
        "the send_to_makerchip hand-off must be removed"


# ---------------------------------------------------------------------------
# Maker (Author): the disk-as-IPC machinery is gone
# ---------------------------------------------------------------------------

def test_author_binds_and_renders_the_bus():
    src = _read(_MAKER)
    assert "DesignBus" in src and _func(src, "set_design_bus") is not None, \
        "Maker must bind to the shared DesignBus"
    assert _func(src, "_render_from_bus") is not None, \
        "Maker must render the bus back into its editor"


def test_old_watchdog_machinery_removed():
    src = _read(_MAKER)
    # Exact definitions, not prefixes: "def refresh" also matches any honest
    # later method whose name merely starts that way (refresh_library_list),
    # which would make this guard fail for a reason it does not care about.
    for dead in ("toggle_flag", "import watchdog", ".Observer(",
                 "def refresh(", "def refresh_change("):
        assert dead not in src, \
            f"dead disk-as-IPC machinery still in Maker.py: {dead!r}"
