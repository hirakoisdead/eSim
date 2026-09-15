from PyQt6 import QtCore, QtGui, QtWidgets, uic
import logging
import os

logger = logging.getLogger(__name__)


class TerminalUi(QtWidgets.QMainWindow):
    """This is a class that represents the GUI required to provide
    details regarding the ngspice simulation. This GUI consists of
    a progress bar, a console window which displays the log of the
    simulation and button required for re-simulation and cancellation
    of the simulation"""
    def __init__(self, qProcess, args, ngspice_bin='ngspice', pre_start=None):
        """The constructor of the TerminalUi class
        param: qProcess: a PyQt QProcess that runs ngspice
        type: qProcess: :class:`QtCore.QProcess`
        param: args: arguments to be passed on to the ngspice call
        type: args: list
        param: ngspice_bin: ngspice executable to launch on re-run/redo (eSim's
               resolved ngspice; d_cosim netlists need the bundled build)
        type: ngspice_bin: str
        param: pre_start: optional callable run just before a redo relaunches
               ngspice, for work the owner also does before the first run
               (NgspiceWidget re-stages rebuilt d_cosim models here). Kept as
               a plain callback so this widget stays simulation-agnostic.
        type: pre_start: callable or None
        """
        super(TerminalUi, self).__init__()

        # Other variables
        # The console inherits its colours from the global QSS rule
        # `QPlainTextEdit#simulationConsole` (see style_dark.qss /
        # style_light.qss).
        # We deliberately do NOT keep an internal dark/light toggle here — that
        # was a legacy per-widget override that broke the user's selected
        # theme. The lightDarkModeButton now cycles the application's theme via
        # app.apply_theme() so the entire window stays in sync.
        self.qProcess = qProcess
        self.args = args
        self.ngspice_bin = ngspice_bin
        self.pre_start = pre_start

        # Load the ui file
        uic.loadUi(os.path.join(os.path.dirname(__file__), "TerminalUi.ui"), self)

        # Define Our Widgets
        self.progressBar = self.findChild(
            QtWidgets.QProgressBar,
            "progressBar"
        )
        self.simulationConsole = self.findChild(
            QtWidgets.QPlainTextEdit,
            "simulationConsole"
        )
        # A chatty transient can emit tens of thousands of lines. QPlainTextEdit
        # is built for logs (cheap per-line append, no full-document relayout
        # like QTextEdit); cap the scrollback so memory can't grow without
        # bound during a long simulation.
        self.simulationConsole.setMaximumBlockCount(20000)

        self.lightDarkModeButton = self.findChild(
            QtWidgets.QPushButton,
            "lightDarkModeButton"
        )
        self.cancelSimulationButton = self.findChild(
            QtWidgets.QPushButton,
            "cancelSimulationButton"
        )
        self.cancelSimulationButton.setEnabled(True)

        self.redoSimulationButton = self.findChild(
            QtWidgets.QPushButton,
            "redoSimulationButton"
        )
        self.redoSimulationButton.setEnabled(False)

        # Theme cycle — clicking this button asks the running application to
        # swap palette to the next theme (System → Light → Dark → System).
        # The QSS rule for `QPlainTextEdit#simulationConsole` then re-applies
        # automatically via apply_theme.
        self.lightDarkModeButton.setToolTip(
            "Cycle application theme (Light → Dark → System)"
        )
        self.lightDarkModeButton.setText("◐")
        # 13pt is the design size of the ◐ glyph; run it through the app's
        # text curve so the button's label tracks zoom like every other label.
        from frontEnd.theme_utils import scale_font
        font = self.lightDarkModeButton.font()
        font.setPointSize(13)
        font.setBold(True)
        self.lightDarkModeButton.setFont(scale_font(font))
        self.lightDarkModeButton.clicked.connect(self._cycle_theme)
        self.cancelSimulationButton.clicked.connect(self.cancelSimulation)
        self.redoSimulationButton.clicked.connect(self.redoSimulation)

        self.simulationCancelled = False

    @staticmethod
    def _cycle_theme():
        """Cycle the application's theme preference and re-apply."""
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        apply_fn = getattr(app, 'apply_theme', None)
        if apply_fn is None:
            return
        from frontEnd.theme_utils import get_preferences
        from configuration import paths
        prefs = get_preferences()
        order = ("System", "Light", "Dark")
        try:
            idx = order.index(prefs.get("theme_mode", "System"))
        except ValueError:
            idx = 0
        next_mode = order[(idx + 1) % len(order)]
        try:
            prefs["theme_mode"] = next_mode
            path = paths.esim_config_path("preferences.json")
            paths.write_json_atomic(path, prefs)
        except Exception:
            pass
        apply_fn()

    def cancelSimulation(self):
        """This function cancels the ongoing ngspice simulation.
        """
        self.cancelSimulationButton.setEnabled(False)
        self.redoSimulationButton.setEnabled(True)

        if (self.qProcess.state() == QtCore.QProcess.ProcessState.NotRunning):
            return

        self.simulationCancelled = True
        self.qProcess.kill()

        # To show progressBar completed
        self.progressBar.setMaximum(100)
        self.progressBar.setProperty("value", 100)

        cancelFormat = '<span style="color:#FF8624; font-size:26px;">{}</span>'
        self.simulationConsole.appendHtml(
            cancelFormat.format("Simulation Cancelled!"))
        self.simulationConsole.verticalScrollBar().setValue(
            self.simulationConsole.verticalScrollBar().maximum()
        )

    def redoSimulation(self):
        """This function reruns the ngspice simulation
        """
        self.Flag = False
        self.cancelSimulationButton.setEnabled(True)
        self.redoSimulationButton.setEnabled(False)

        if (self.qProcess.state() != QtCore.QProcess.ProcessState.NotRunning):
            return

        # To make the progressbar running
        self.progressBar.setMaximum(0)
        self.progressBar.setProperty("value", -1)

        self.simulationConsole.clear()
        self.simulationCancelled = False

        self.Flag = self._resolveNgspicePlotChoice()

        self.qProcess.setProperty("redoPlotFlag", self.Flag)

        # A redo is a fresh run: give the owner the same pre-launch hook the
        # first run got. Never let a hook failure block the re-simulation --
        # the run is still valid, it just may use the artifacts it already had.
        if callable(self.pre_start):
            try:
                self.pre_start()
            except Exception:
                logger.exception("redoSimulation: pre_start hook failed")

        self.qProcess.start(self.ngspice_bin, self.args)

    def _resolveNgspicePlotChoice(self):
        """Return whether to also generate ngspice plots for this run.

        Thin wrapper over ``dialogs.ask_ngspice_plots`` (the single copy of the
        popup + its "remember my choice" persistence, shared with
        Application.plotFlagPopBox).
        """
        from frontEnd.dialogs import ask_ngspice_plots
        return ask_ngspice_plots(self)

    # Note: the legacy `changeColor()` per-widget dark/light toggle has been
    # removed; use `_cycle_theme()` (the lightDarkModeButton target) instead so
    # the entire application stays in sync with the user's chosen theme.
