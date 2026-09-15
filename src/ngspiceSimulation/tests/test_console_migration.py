"""Simulation console is a bounded QPlainTextEdit fed by coalesced writes.

The console used to be an unbounded rich-text QTextEdit written per readyRead
burst -- every insert relaid the whole document and memory grew without limit
on a chatty run. It is now a QPlainTextEdit (log-optimised) with a block cap,
and NgspiceWidget buffers bursts behind a 50 ms flush.

These pin the .ui migration (uic must accept the swapped widget) and the
buffer/flush + auto-scroll-only-at-bottom behaviour.
"""
from PyQt6 import QtCore, QtWidgets

from frontEnd.TerminalUi import TerminalUi
from ngspiceSimulation.NgspiceWidget import NgspiceWidget


def test_console_is_bounded_plaintextedit(qapp):
    ui = TerminalUi(QtCore.QProcess(), [], "ngspice")
    try:
        assert isinstance(ui.simulationConsole, QtWidgets.QPlainTextEdit)
        assert ui.simulationConsole.maximumBlockCount() == 20000
        # HTML status banners still render, and clear() resets (was setText).
        ui.simulationConsole.appendHtml('<span>ok</span>')
        ui.simulationConsole.clear()
        assert ui.simulationConsole.toPlainText() == ""
    finally:
        ui.deleteLater()


class _StubConsoleHost:
    """Minimal host exposing NgspiceWidget's coalescing methods against a real
    QPlainTextEdit, without launching ngspice in the full widget __init__."""

    _queue_console = NgspiceWidget._queue_console
    _flush_console = NgspiceWidget._flush_console

    def __init__(self, console):
        self._console_buffer = []
        self._console_flush_timer = QtCore.QTimer()
        self._console_flush_timer.setSingleShot(True)

        class _T:
            pass
        self.terminal_ui = _T()
        self.terminal_ui.simulationConsole = console


def test_queue_buffers_and_flush_writes_once(qapp):
    console = QtWidgets.QPlainTextEdit()
    host = _StubConsoleHost(console)

    host._queue_console("line1\n")
    host._queue_console("line2\n")
    # Buffered, not yet written.
    assert console.toPlainText() == ""
    host._flush_console()
    assert console.toPlainText() == "line1\nline2\n"
    # Buffer drained after flush.
    assert host._console_buffer == []


def test_flush_keeps_user_scrollback_when_not_at_bottom(qapp):
    console = QtWidgets.QPlainTextEdit()
    console.resize(200, 40)
    host = _StubConsoleHost(console)
    # Fill enough lines to make the scrollbar meaningful, at bottom.
    host._queue_console("x\n" * 500)
    host._flush_console()
    sb = console.verticalScrollBar()
    assert sb.value() == sb.maximum()          # followed to bottom
    # Scroll up, then flush more: position must be preserved (not yanked down).
    sb.setValue(0)
    host._queue_console("y\n" * 50)
    host._flush_console()
    assert sb.value() == 0
