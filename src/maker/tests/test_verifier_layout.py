"""Verify-stage toolbar declutter and dock space priority.

Pins the information architecture so a later refactor cannot
silently regress it: file actions folded into one menu, a single accented
primary action, the iverilog lock driven off one widget list, and splitters
that give growth to the editor (not the console/sidebar).

Ungated -- constructs the widget headlessly; needs no iverilog.
"""
import pytest

from PyQt6 import QtCore, QtWidgets


@pytest.fixture
def verifier(qapp):
    from maker.VerilogVerifier import VerilogVerifier
    w = VerilogVerifier()
    w.unlock_ui()  # normalise to the unlocked state regardless of toolchain
    yield w
    w.deleteLater()


def test_file_actions_are_folded_into_one_menu(verifier):
    labels = [a.text() for a in verifier.file_button.menu().actions() if a.text()]
    assert any("Open Source" in t for t in labels)
    assert any("Open Testbench" in t for t in labels)
    assert "Save" in labels
    assert any("Save As" in t for t in labels)
    assert any("Export Waveform CSV" in t for t in labels)


def test_standard_editor_shortcuts(verifier):
    assert verifier.act_open_source.shortcut().toString() == "Ctrl+O"
    assert verifier.act_save.shortcut().toString() == "Ctrl+S"
    assert verifier.act_save_as.shortcut().toString() == "Ctrl+Shift+S"
    assert verifier.sc_simulate.key().toString() == "F5"


def test_simulate_is_the_single_primary_action(verifier):
    # Aurora paints the accented primary via the verifierPrimary cssClass.
    assert verifier.btn_simulate.property("cssClass") == "verifierPrimary"
    # No other control claims the primary accent.
    primaries = [b for b in verifier.findChildren(QtWidgets.QPushButton)
                 if b.property("cssClass") == "verifierPrimary"]
    assert primaries == [verifier.btn_simulate]


def test_export_csv_disabled_until_a_run(verifier):
    assert verifier.act_export_csv.isEnabled() is False


def test_lock_flow_disables_every_lockable(verifier):
    verifier.lock_ui()
    assert all(not w.isEnabled() for w in verifier._lockable)
    assert verifier.btn_unlock.isHidden() is False  # the only live control
    verifier.unlock_ui()
    assert all(w.isEnabled() for w in verifier._lockable)
    assert verifier.btn_unlock.isHidden() is True


def test_lockable_covers_the_real_controls(verifier):
    # Guards against a future button being added but forgotten by the lock.
    expected = {verifier.editor_tabs, verifier.hierarchy_list,
                verifier.btn_add_module, verifier.btn_auto_detect,
                verifier.btn_syntax, verifier.btn_stub, verifier.btn_simulate,
                verifier.file_button, verifier.sc_simulate,
                verifier.act_open_source, verifier.act_open_tb,
                verifier.act_save, verifier.act_save_as}
    assert expected <= set(verifier._lockable)


def _splitters(w):
    spls = w.findChildren(QtWidgets.QSplitter)
    vert = next(s for s in spls
                if s.orientation() == QtCore.Qt.Orientation.Vertical)
    horz = next(s for s in spls
                if s.orientation() == QtCore.Qt.Orientation.Horizontal)
    return vert, horz


def test_extra_height_goes_to_the_editor_not_the_console(verifier, qapp):
    verifier.show()
    qapp.processEvents()
    vert, _ = _splitters(verifier)
    verifier.resize(1100, 650); qapp.processEvents()
    before = vert.sizes()
    verifier.resize(1100, 1050); qapp.processEvents()  # +400 tall
    after = vert.sizes()
    assert (after[0] - before[0]) > (after[1] - before[1])  # editor grew more
    assert abs(after[1] - before[1]) < 60                   # console ~fixed


def test_extra_width_goes_to_the_editor_not_the_sidebar(verifier, qapp):
    verifier.show()
    qapp.processEvents()
    _, horz = _splitters(verifier)
    verifier.resize(1100, 650); qapp.processEvents()
    before = horz.sizes()
    verifier.resize(1600, 650); qapp.processEvents()  # +500 wide
    after = horz.sizes()
    assert (after[1] - before[1]) > (after[0] - before[0])  # editor grew more
    assert abs(after[0] - before[0]) < 60                   # sidebar ~fixed
