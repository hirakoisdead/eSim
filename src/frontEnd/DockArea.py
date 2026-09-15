from PyQt6 import QtCore, QtWidgets, sip
from configuration import Dialogs
from configuration.Appconfig import Appconfig
from browser.Welcome import Welcome
from PyQt6.QtWidgets import QLineEdit, QLabel, QPushButton, QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt
import os

# Every tool widget below is imported inside the method that opens its dock,
# not here: DockArea is on the Application startup path, and these pull the
# heavy stacks (plotWindow -> matplotlib.pyplot + numpy; makerchip -> Maker/
# NgVeri/VerilogVerifier -> matplotlib; KicadtoNgspice; the converters). On a
# cold Windows launch Defender scans every native module on first load, so
# eagerly importing them all here is what made the splash sit frozen for tens
# of seconds. Deferring moves that one-time cost onto the first click of the
# tool that actually needs it:
#   plottingEditor      -> ngspiceSimulation.plot_window.plotWindow
#   ngspiceEditor       -> ngspiceSimulation.NgspiceWidget.NgspiceWidget
#   modelEditor         -> modelEditor.ModelEditor.ModelEditorclass
#   subcircuiteditor    -> subcircuit.Subcircuit.Subcircuit
#   makerchip           -> maker.makerchip.makerchip
#   kicadToNgspiceEditor-> kicadtoNgspice.KicadtoNgspice.MainWindow
#   modelicaEditor      -> ngspicetoModelica.ModelicaUI.OpenModelicaEditor
#   eSimConverter       -> converter.*


class WaveformDock(QtWidgets.QDockWidget):
    """The Verilog waveform's own eSim tab.

    Deletes itself on close (the plot widget is heavy, so it must not linger
    across repeated simulate/close cycles) and emits ``closed`` first so the
    host can drop its bookkeeping and return focus to the Verify stage.
    """

    closed = QtCore.pyqtSignal()

    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.setObjectName(title)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


class DockArea(QtWidgets.QMainWindow):
    """
    This class contains function for designing UI of all the editors
    in dock area part:

        - Test Editor.
        - Model Editor.
        - Python Plotting.
        - Ngspice Editor.
        - Kicad to Ngspice Editor.
        - Subcircuit Editor.
        - Modelica editor.
    """

    def __init__(self):
        """This act as constructor for class DockArea."""
        QtWidgets.QMainWindow.__init__(self)
        self.obj_appconfig = Appconfig()
        # Track plotting docks
        self.active_plotting_docks = set()
        # Wire the tab-activation slot exactly once. Connecting it per plot
        # (the old plottingEditor path) stacked duplicate connections -- Qt does
        # not dedupe them -- so after N plots the slot fired N times per switch.
        self.tabifiedDockWidgetActivated.connect(self.on_dock_activated)
        # Verilog waveform tab per Model Creation dock (source dock -> wave
        # dock), so a re-simulate reuses one viewer instead of stacking tabs.
        self._wave_docks = {}

        # Per-instance dock registry + naming counter. These were module-level
        # globals (dock / count / dockList) that only worked because exactly
        # one DockArea exists; as instance state they no longer leak across
        # tests or instances and are visible to readers of this class.
        self._docks = {}
        self._count = 1

        # Dock-area tab bars whose close-X is wired to us, keyed by C++
        # pointer. Holding the wrapper keeps the connection alive; see
        # enable_tab_close_buttons for why that matters.
        self._armed_tab_bars = {}

        # Single-instance registry: (tool kind, project key) -> live dock.
        # Every tool opener consults this first, so clicking a launcher button
        # N times raises the one existing tab instead of stacking N heavy
        # widget trees (each plot dock alone holds a matplotlib canvas; each
        # Model Creation dock a full Flow Navigator). The dock's inner tool
        # widget is kept on the dock as ``_tool_widget`` so reuse can poke it
        # (reload plot data, jump the Flow Navigator to VHDL, ...).
        self._tool_docks = {}

        for dockName in ['Welcome']:
            self._docks[dockName] = QtWidgets.QDockWidget(dockName)
            self.welcomeWidget = QtWidgets.QWidget()
            self.welcomeLayout = QtWidgets.QVBoxLayout()
            self.welcomeLayout.addWidget(Welcome())  # Call browser

            # Adding to main Layout
            self.welcomeWidget.setLayout(self.welcomeLayout)
            self._docks[dockName].setWidget(self.welcomeWidget)
            # No title strip here either -- the bottom tab already labels it, so
            # the home tab matches the title-less tool docks (see
            # apply_fullscreen_feature).
            self._docks[dockName].setTitleBarWidget(QtWidgets.QWidget())
            # Welcome is the permanent "home" tab: keep it movable/floatable but
            # drop the Closable feature so its title bar has no close button.
            # The tab-strip X is stripped separately in enable_tab_close_buttons.
            self._docks[dockName].setFeatures(
                QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable |
                QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable)
            self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, self._docks[dockName])

        # self.tabifyDockWidget(self._docks['Notes'],self._docks['Blank'])

    def tabifyDockWidget(self, first, second):
        """Tabify two docks, then (re)arm the close-X on the bottom tab bar so
        every tabified tool can be closed straight from its tab."""
        super().tabifyDockWidget(first, second)
        self.enable_tab_close_buttons()

    def enable_tab_close_buttons(self):
        """Turn on the close button for the QMainWindow's own dock tab bars.

        Only the dock-area tab bars are targeted (parent is the QMainWindow, not
        a QTabWidget), so tab strips *inside* a tool (NgVeri, Flow Navigator …)
        are left untouched."""
        for tb in self.findChildren(QtWidgets.QTabBar):
            if isinstance(tb.parent(), QtWidgets.QTabWidget):
                continue
            tb.setTabsClosable(True)
            # Never elide tab text: dock titles are made unique by their
            # ``-<count>`` suffix, and handle_tab_close matches a tab to its
            # dock by *exact* windowTitle. An elided ("Simulation-RLC-2...")
            # tab would break that identity and could close the wrong dock.
            tb.setElideMode(QtCore.Qt.TextElideMode.ElideNone)
            self._arm_tab_bar(tb)
            # Welcome is the permanent home tab -- strip its close button so it
            # can never be closed from the tab strip.
            for i in range(tb.count()):
                if tb.tabText(i).replace('&', '').strip() == 'Welcome':
                    tb.setTabButton(
                        i,
                        QtWidgets.QTabBar.ButtonPosition.RightSide,
                        None)

    def _arm_tab_bar(self, tab_bar):
        """Wire one dock tab bar's close-X to us, exactly once, and keep it.

        The slot is a BOUND METHOD and the bar is remembered on this DockArea.
        Both halves matter, and neither is cosmetic:

        The old wiring was ``tb.tabCloseRequested.connect(lambda index,
        tab_bar=tb: self.handle_tab_close(index, tab_bar))``. Nothing outside
        PyQt's connection proxy ever referenced that lambda, and the lambda
        referenced the tab bar's Python wrapper, which in turn owned the
        proxy -- an unreachable reference cycle. Python's cyclic collector
        reaped it a second or two after the tab opened (the plot window's
        matplotlib import is enough to trigger a pass), and from then on
        clicking the X did *nothing at all* for the rest of the session: Qt
        still listed the connection -- ``receivers(tabCloseRequested)`` kept
        counting it -- but the Python callable behind it was gone, so the
        emit reached nobody. Nothing was logged, because nothing raised.

        A bound method is owned by this DockArea (alive for the whole session)
        and needs no captured tab bar: the emitting bar comes from
        ``sender()``. Keeping the wrapper in ``_armed_tab_bars`` additionally
        stops PyQt from handing out a fresh wrapper later, so the connection
        can never be re-created behind our back.
        """
        # Qt deletes surplus dock tab bars; drop those entries first so a
        # recycled address cannot make a live bar look already-armed.
        for key in [k for k, v in self._armed_tab_bars.items()
                    if sip.isdeleted(v)]:
            del self._armed_tab_bars[key]

        key = sip.unwrapinstance(tab_bar)
        if key in self._armed_tab_bars:
            return
        self._armed_tab_bars[key] = tab_bar
        tab_bar.tabCloseRequested.connect(self._on_tab_close_requested)

    def _on_tab_close_requested(self, index):
        """Close-X clicked on a dock tab strip.

        Carries no captured state -- the tab bar that emitted comes from
        ``sender()`` -- so this slot can safely be a plain bound method (see
        _arm_tab_bar)."""
        tab_bar = self.sender()
        if not isinstance(tab_bar, QtWidgets.QTabBar):
            return
        self.handle_tab_close(index, tab_bar)

    def _live_tool_dock(self, kind, projKey=None):
        """Return the still-alive single-instance dock for (kind, projKey).

        A dock can die outside our control (tab close, Close Project, Qt-side
        deletion), so a registry hit is verified with ``sip.isdeleted`` before
        being trusted; stale entries are dropped on the spot."""
        key = (kind, projKey)
        d = self._tool_docks.get(key)
        if d is None:
            return None
        try:
            if sip.isdeleted(d):
                self._tool_docks.pop(key, None)
                return None
        except Exception:
            self._tool_docks.pop(key, None)
            return None
        return d

    def _register_tool_dock(self, kind, projKey, dock_widget, tool_widget):
        """Record (kind, projKey) -> dock and stash the inner tool widget on
        the dock for reuse-time actions."""
        dock_widget._tool_widget = tool_widget
        self._tool_docks[(kind, projKey)] = dock_widget

    def _focus_dock(self, dock_widget):
        """Bring an existing (possibly tabified) dock to the front."""
        dock_widget.setVisible(True)
        dock_widget.raise_()
        dock_widget.setFocus()

    def _forget_dock(self, child):
        """Drop every reference eSim keeps to a dock so closing a tab cannot
        leave a zombie member behind (which would corrupt the saved layout)."""
        keys_to_delete = [k for k, v in self._docks.items() if v is child]
        for k in keys_to_delete:
            del self._docks[k]
        for k in [k for k, v in self._tool_docks.items() if v is child]:
            del self._tool_docks[k]
        try:
            self.active_plotting_docks.discard(child)
        except Exception:
            pass
        # Drop any waveform tab bound to this source dock (and vice-versa).
        try:
            for src in [s for s, w in self._wave_docks.items()
                        if w is child or s is child]:
                del self._wave_docks[src]
        except Exception:
            pass
        for docks in self.obj_appconfig.dock_dict.values():
            if child in docks:
                docks.remove(child)

    def _destroy_dock(self, child):
        """Close, unparent and schedule deletion of a dock + forget it.

        Honours a vetoed close: an editor window with unsaved changes can
        reject its ``closeEvent``, and such a widget is left intact rather than
        force-deleted out from under the user. Returns True when the dock was
        actually torn down."""
        if not child.close():
            return False
        try:
            self.removeDockWidget(child)
        except Exception:
            pass
        self._forget_dock(child)
        child.deleteLater()
        return True

    def handle_tab_close(self, index, tab_bar):
        """Close the dock behind the clicked tab, tearing it fully down rather
        than just hiding it.

        The tab is matched to its dock by an *exact* windowTitle compare. Tab
        text is never elided (see enable_tab_close_buttons) and dock titles are
        unique by their ``-<self._count>`` suffix, so a prefix/startswith match --
        which could close ``Simulation-RLC-21`` when the user clicked
        ``Simulation-RLC-2`` -- is neither needed nor safe."""
        tab_text = tab_bar.tabText(index).replace('&', '').strip()

        # Welcome is the permanent home tab -- never destroy it.
        if tab_text == 'Welcome':
            return

        for child in self.findChildren(QtWidgets.QDockWidget):
            if not child.isVisible():
                continue
            title = child.windowTitle().replace('&', '').strip()
            if title == tab_text:
                self._destroy_dock(child)
                return

        # No dock carries that title. Nothing to close, but say so rather than
        # leaving a dead-looking X with no trace anywhere.
        self.obj_appconfig.print_warning(
            'Close: no open panel named "%s".' % tab_text)

    def get_main_view_reference(self):
        """Get reference to the MainView widget."""
        parent = self.parent()
        while parent:
            if hasattr(parent, 'collapse_console_area'):
                return parent
            parent = parent.parent()
        return None

    def on_dock_activated(self, dock_widget):
        """Handle when any dock becomes active. The console is on-demand now
        (the status bar carries the latest line), so we only auto-collapse for
        plotting docks and never force it back open."""
        main_view = self.get_main_view_reference()
        if not main_view:
            return

        if dock_widget in self.active_plotting_docks:
            main_view.collapse_console_area()

    @staticmethod
    def _scrollable(widget):
        """Put a tool panel behind a scroll viewport.

        A panel's layout minimum is a hard floor on the whole application:
        QMainWindow cannot shrink below the sum of its docks' minimums, so a
        tall fixed-metric page (the NGHDL VHDL builder is the worst, at
        720x385) forces the eSim window taller than a short workspace -- on a
        1920x1080 laptop at 150% Windows scaling there are only 672 logical
        pixels of desktop -- and the bottom rows end up under the screen edge,
        unreachable and un-resizable. Behind a viewport the panel keeps its
        natural size and scrolls instead of pushing the window off-screen.

        ``setWidgetResizable(True)`` means the panel still gets the full
        viewport whenever there is room, so nothing changes on a large display;
        scrollbars appear only when the dock is genuinely too small.
        """
        area = QtWidgets.QScrollArea()
        area.setObjectName("dockScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        # The card behind it paints the surface; a viewport with its own
        # background would sit as an opaque rectangle on top of the theme.
        area.viewport().setAutoFillBackground(False)
        area.setStyleSheet("QScrollArea#dockScroll { background: transparent; }")
        area.setWidget(widget)
        return area

    def apply_fullscreen_feature(self, dock_widget, original_widget):
        """Mount a dock's content inside a rounded Aurora card.

        Fullscreen is no longer dock chrome at all: it is a small per-panel
        control living in each working panel's own header (see
        frontEnd.FullScreen.FullScreenToggle). Here we wrap the tool content in
        a ``#dockCard`` frame (themed surface + 16px radius) sitting inside a
        thin holder whose margins reveal the darker dock base around it, so a
        docked tool reads as a raised floating card.

        The holder is the dock's *direct* child, so FullScreenToggle (which
        reparents the dock's direct child) carries the whole card in and out of
        fullscreen and the look survives the round-trip. The card is a plain
        QFrame with no graphics effect, so QWebEngineView tools (Makerchip)
        keep rendering."""
        if not dock_widget.objectName():
            dock_widget.setObjectName(dock_widget.windowTitle() or "dock")

        card = QtWidgets.QFrame()
        card.setObjectName("dockCard")
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(self._scrollable(original_widget))

        holder = QtWidgets.QWidget()
        holder_layout = QtWidgets.QVBoxLayout(holder)
        holder_layout.setContentsMargins(10, 8, 10, 10)
        holder_layout.setSpacing(0)
        holder_layout.addWidget(card)

        dock_widget.setWidget(holder)

        # Kill the dock's title bar ("Netlist-IC1-3", "Makerchip-1", ...). The
        # docks are tabified, so the bottom tab already names each panel and
        # carries its own close button -- the title strip just duplicated that
        # name and ate vertical space. An empty title-bar widget removes the
        # strip while keeping windowTitle intact (the tab still reads it).
        dock_widget.setTitleBarWidget(QtWidgets.QWidget())

        # Freshly-mounted tool content carries its own buttons; re-install the
        # Aurora hover/press glow so they animate too (gated inside motion — a
        # no-op when the user has motion off).
        try:
            from frontEnd.motion import install_button_motion
            install_button_motion(self)
        except Exception:
            pass

    def createTestEditor(self):
        """This function create widget for Library Editor"""

        self.testWidget = QtWidgets.QWidget()
        self.testArea = QtWidgets.QTextEdit()
        self.testLayout = QtWidgets.QVBoxLayout()
        self.testLayout.addWidget(self.testArea)

        # Adding to main Layout
        self.testWidget.setLayout(self.testLayout)
        self._docks['Tips-' + str(self._count)] = \
            QtWidgets.QDockWidget('Tips-' + str(self._count))
        self.apply_fullscreen_feature(
            self._docks['Tips-' + str(self._count)], self.testWidget)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea,
                           self._docks['Tips-' + str(self._count)])
        self.tabifyDockWidget(
            self._docks['Welcome'], self._docks['Tips-' + str(self._count)])

        self._docks['Tips-' + str(self._count)].setVisible(True)
        self._docks['Tips-' + str(self._count)].setFocus()

        self._docks['Tips-' + str(self._count)].raise_()

        temp = self.obj_appconfig.current_project['ProjectName']
        if temp:
            self.obj_appconfig.dock_dict.setdefault(temp, []).append(
                self._docks['Tips-' + str(self._count)]
            )
        self._count = self._count + 1

    def plottingEditor(self):
        """This function create widget for interactive PythonPlotting."""
        # Deferred: first plot pays the matplotlib import, not app startup.
        from ngspiceSimulation.plot_window import plotWindow
        self.projDir = self.obj_appconfig.current_project["ProjectName"]
        self.projName = self.obj_appconfig.get_proj_stem() \
            or os.path.basename(self.projDir)
        dockName = f'Plotting-{self.projName}-'
        # self.project = os.path.join(self.projDir, self.projName)

        # One plot dock per project: a re-click (or a fresh simulation) reloads
        # the existing viewer with the latest plot_data instead of stacking
        # another matplotlib canvas per click.
        existing = self._live_tool_dock('plotting', self.projDir)
        if existing is not None:
            try:
                existing._tool_widget.load_simulation_data()
                existing._tool_widget.refresh_plot()
            except Exception:
                # Data reload failing (e.g. plot files deleted) must not lose
                # the tab; the user still lands on the viewer.
                pass
            self._focus_dock(existing)
            main_view = self.get_main_view_reference()
            if main_view:
                QtCore.QTimer.singleShot(100, main_view.collapse_console_area)
            return

        self.plottingWidget = QtWidgets.QWidget()

        plot_widget = plotWindow(self.projDir, self.projName)
        self.plottingLayout = QtWidgets.QVBoxLayout()
        self.plottingLayout.addWidget(plot_widget)

        # Adding to main Layout
        self.plottingWidget.setLayout(self.plottingLayout)
        self._docks[dockName + str(self._count)
             ] = QtWidgets.QDockWidget(dockName
                                       + str(self._count))
        self.apply_fullscreen_feature(
            self._docks[dockName + str(self._count)], self.plottingWidget)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea,
                           self._docks[dockName + str(self._count)])
        self.tabifyDockWidget(self._docks['Welcome'],
                              self._docks[dockName + str(self._count)])
        
        # Track this as a plotting dock (the activation slot is wired once in
        # __init__, not per plot).
        self.active_plotting_docks.add(self._docks[dockName + str(self._count)])
        self._register_tool_dock(
            'plotting', self.projDir,
            self._docks[dockName + str(self._count)], plot_widget)

        self._docks[dockName + str(self._count)].setVisible(True)
        self._docks[dockName + str(self._count)].setFocus()
        self._docks[dockName + str(self._count)].raise_()

        # Collapse console immediately
        main_view = self.get_main_view_reference()
        if main_view:
            QtCore.QTimer.singleShot(100, main_view.collapse_console_area)

        temp = self.obj_appconfig.current_project['ProjectName']
        if temp:
            self.obj_appconfig.dock_dict.setdefault(temp, []).append(
                self._docks[dockName + str(self._count)]
            )
        self._count = self._count + 1

    def ngspiceEditor(self, projName, netlist, simEndSignal, plotFlag):
        """ This function creates widget for Ngspice window."""
        from ngspiceSimulation.NgspiceWidget import NgspiceWidget

        # One simulation console per project: a re-run replaces the previous
        # run's dock (terminating its ngspice via the widget teardown) instead
        # of stacking Simulation-<proj>-N tabs. A fresh NgspiceWidget per run
        # is still required -- it owns the QProcess for *this* netlist -- so
        # this is destroy-then-recreate, not reuse. A vetoed close just falls
        # through to opening a new dock alongside.
        old = self._live_tool_dock('simulation', projName)
        if old is not None:
            self._destroy_dock(old)

        self.ngspiceWidget = QtWidgets.QWidget()

        ngspice_widget = NgspiceWidget(netlist, simEndSignal, plotFlag)
        self.ngspiceLayout = QtWidgets.QVBoxLayout()
        self.ngspiceLayout.addWidget(ngspice_widget)

        # Adding to main Layout
        self.ngspiceWidget.setLayout(self.ngspiceLayout)
        dockName = f'Simulation-{projName}-'
        self._docks[dockName + str(self._count)
             ] = QtWidgets.QDockWidget(dockName
                                       + str(self._count))
        self.apply_fullscreen_feature(
            self._docks[dockName + str(self._count)], self.ngspiceWidget)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea,
                           self._docks[dockName + str(self._count)])
        self.tabifyDockWidget(self._docks['Welcome'],
                              self._docks[dockName
                                   + str(self._count)])

        self._register_tool_dock(
            'simulation', projName,
            self._docks[dockName + str(self._count)], ngspice_widget)

        self._docks[dockName + str(self._count)].setVisible(True)
        self._docks[dockName + str(self._count)].setFocus()
        self._docks[dockName + str(self._count)].raise_()

        temp = self.obj_appconfig.current_project['ProjectName']
        if temp:
            self.obj_appconfig.dock_dict.setdefault(temp, []).append(
                self._docks[dockName + str(self._count)]
            )
        self._count = self._count + 1

    def eSimConverter(self):
        """This function creates a widget for eSimConverter."""
        # Single instance: the converter holds only pick-a-file state, so a
        # re-click resurfaces the open tab (preserving the chosen path).
        existing = self._live_tool_dock('esim-converter')
        if existing is not None:
            self._focus_dock(existing)
            return

        from converter.pspiceToKicad import PspiceConverter
        from converter.ltspiceToKicad import LTspiceConverter
        from converter.LtspiceLibConverter import LTspiceLibConverter
        from converter.libConverter import PspiceLibConverter
        from converter.browseSchematic import browse_path

        dockName = 'Schematic Converter-'

        self.pspice_converter = PspiceConverter(self)
        self.ltspice_converter = LTspiceConverter(self)
        self.pspiceLib_converter = PspiceLibConverter(self)
        self.ltspiceLib_converter = LTspiceLibConverter(self)

        # ── Root: full-bleed layout that fills the whole dock.
        # The old version capped the content at 920px and centred it, so it sat
        # in a compressed island with dead margins all around. Here the content
        # spans the panel's full width and the working area (convert actions +
        # about) stretches to claim the vertical space down to the dock floor.
        self.eConWidget = QtWidgets.QWidget()
        col = QVBoxLayout(self.eConWidget)
        col.setContentsMargins(28, 24, 28, 24)
        col.setSpacing(18)

        # ── Header ───────────────────────────────────────────────────────
        title = QLabel("Schematic Converter")
        title.setProperty("cssClass", "title")
        col.addWidget(title)

        subtitle = QLabel(
            "Bring PSpice and LTspice designs into eSim — converted to KiCad "
            "schematics and libraries, ready to simulate and lay out."
        )
        subtitle.setProperty("cssClass", "muted")
        subtitle.setWordWrap(True)
        col.addWidget(subtitle)

        # ── Source file picker (full width) ──────────────────────────────
        source_group = QtWidgets.QGroupBox("Source file")
        source_group.setProperty("cssClass", "themedGroupBox")
        source_layout = QHBoxLayout(source_group)
        source_layout.setSpacing(10)

        from frontEnd.theme_utils import zoom_px
        file_path_text_box = QLineEdit()
        file_path_text_box.setMinimumHeight(zoom_px(38))
        file_path_text_box.setClearButtonEnabled(True)
        file_path_text_box.setPlaceholderText(
            "Choose a PSpice (.sch, .lib) or LTspice (.asc, .asy) file…"
        )
        file_path_text_box.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        source_layout.addWidget(file_path_text_box, 1)

        browse_button = QPushButton("Browse…")
        browse_button.setProperty("cssClass", "primary")
        browse_button.setMinimumHeight(zoom_px(38))
        browse_button.clicked.connect(
            lambda: browse_path(self, file_path_text_box))
        source_layout.addWidget(browse_button, 0)

        col.addWidget(source_group)

        # ── Convert actions, grouped by source format ────────────────────
        # Tiles that grow to fill the panel. The format lives in the group
        # title so the captions stay short (they used to clip, e.g. "onvert
        # Pspice schemat"), and the buttons expand in both axes so the action
        # area owns the dock's free space instead of leaving a big blank below
        # a cramped row.
        def _convert_btn(text, handler):
            btn = QPushButton(text)
            btn.setMinimumHeight(zoom_px(64))
            btn.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )
            btn.clicked.connect(handler)
            return btn

        pspice_lib_btn = _convert_btn(
            "Library",
            lambda: self.pspiceLib_converter.upload_file_Pspice(
                file_path_text_box.text()))
        pspice_sch_btn = _convert_btn(
            "Schematic",
            lambda: self.pspice_converter.upload_file_Pspice(
                file_path_text_box.text()))
        ltspice_lib_btn = _convert_btn(
            "Library",
            lambda: self.ltspiceLib_converter.upload_file_LTspice(
                file_path_text_box.text()))
        ltspice_sch_btn = _convert_btn(
            "Schematic",
            lambda: self.ltspice_converter.upload_file_LTspice(
                file_path_text_box.text()))

        pspice_group = QtWidgets.QGroupBox("PSpice")
        pspice_group.setProperty("cssClass", "themedGroupBox")
        pspice_row = QHBoxLayout(pspice_group)
        pspice_row.setSpacing(10)
        pspice_row.addWidget(pspice_lib_btn)
        pspice_row.addWidget(pspice_sch_btn)

        ltspice_group = QtWidgets.QGroupBox("LTspice")
        ltspice_group.setProperty("cssClass", "themedGroupBox")
        ltspice_row = QHBoxLayout(ltspice_group)
        ltspice_row.setSpacing(10)
        ltspice_row.addWidget(ltspice_lib_btn)
        ltspice_row.addWidget(ltspice_sch_btn)

        # Left rail of the body: the two format groups stacked, each taking an
        # equal share of the vertical space so the tiles fill the height.
        actions_col = QVBoxLayout()
        actions_col.setSpacing(16)
        actions_col.addWidget(pspice_group, 1)
        actions_col.addWidget(ltspice_group, 1)

        # ── About + how-it-works (right rail) ────────────────────────────
        # Themed rich-text, not the old white box with a 4px black border and a
        # blue outset bezel that fought the Aurora surface underneath it.
        about_group = QtWidgets.QGroupBox("About")
        about_group.setProperty("cssClass", "themedGroupBox")
        about_layout = QVBoxLayout(about_group)
        about_layout.setSpacing(14)

        self.description_label = QLabel(
            "<p><b>PSpice&nbsp;→&nbsp;eSim</b> converts PSpice schematic and "
            "library files to KiCad, mapping components and wiring so a design "
            "simulated in PSpice can go straight to a PCB layout in KiCad.</p>"
            "<p><b>LTspice&nbsp;→&nbsp;eSim</b> converts LTspice symbols and "
            "schematics to KiCad — design and simulate in LTspice, then carry "
            "the circuit into KiCad for the PCB.</p>"
        )
        self.description_label.setTextFormat(Qt.TextFormat.RichText)
        self.description_label.setWordWrap(True)
        about_layout.addWidget(self.description_label)

        steps_label = QLabel(
            "<p style='margin-bottom:0'><b>How it works</b><br/>"
            "1&nbsp;&nbsp;Choose a source file above.<br/>"
            "2&nbsp;&nbsp;Pick its format — PSpice or LTspice.<br/>"
            "3&nbsp;&nbsp;Convert it to a KiCad library or schematic.</p>"
        )
        steps_label.setTextFormat(Qt.TextFormat.RichText)
        steps_label.setProperty("cssClass", "muted")
        steps_label.setWordWrap(True)
        about_layout.addWidget(steps_label)
        about_layout.addStretch(1)

        # Body row fills the rest of the dock: actions on the left, about on the
        # right. Added with a stretch factor so it expands to the bottom edge.
        body_row = QHBoxLayout()
        body_row.setSpacing(18)
        body_row.addLayout(actions_col, 3)
        body_row.addWidget(about_group, 2)
        col.addLayout(body_row, 1)

        # Empty state: nothing to convert until a file is picked, so the four
        # actions stay disabled and light up together once the field is filled.
        convert_buttons = [
            pspice_lib_btn, pspice_sch_btn, ltspice_lib_btn, ltspice_sch_btn]

        def _sync_actions(text):
            enabled = bool(text.strip())
            for b in convert_buttons:
                b.setEnabled(enabled)

        file_path_text_box.textChanged.connect(_sync_actions)
        _sync_actions("")

        self._docks[dockName + str(self._count)] = QtWidgets.QDockWidget(dockName + str(self._count))
        self.apply_fullscreen_feature(
            self._docks[dockName + str(self._count)], self.eConWidget)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, self._docks[dockName + str(self._count)])
        self.tabifyDockWidget(self._docks['Welcome'], self._docks[dockName + str(self._count)])

        self._register_tool_dock(
            'esim-converter', None,
            self._docks[dockName + str(self._count)], self.eConWidget)

        self._docks[dockName + str(self._count)].setVisible(True)
        self._docks[dockName + str(self._count)].setFocus()
        self._docks[dockName + str(self._count)].raise_()

        # Register with the project so Close Project destroys it too; without
        # this the Schematic Converter dock (and its four sub-converters) leaked
        # for the whole session.
        temp = self.obj_appconfig.current_project['ProjectName']
        if temp:
            self.obj_appconfig.dock_dict.setdefault(temp, []).append(
                self._docks[dockName + str(self._count)]
            )
        self._count = self._count + 1

    def modelEditor(self):
        """This function defines UI for model editor."""
        print("in model editor")

        projDir = self.obj_appconfig.current_project["ProjectName"]
        if projDir is None:
            """ when projDir is None that is clicking on subcircuit icon
                without any project selection """
            self.msg = Dialogs.make_error_message(self)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Error Message")
            self.msg.showMessage(
                'Please select the project first.'
                ' You can either create new project or open existing project'
            )
            self.msg.exec()
            return
        from modelEditor.ModelEditor import ModelEditorclass
        projName = os.path.basename(projDir)
        dockName = f'Model Editor-{projName}-'

        # Single instance per project: a re-click lands back on the open
        # editor (with whatever the user had in progress) instead of a new tab.
        existing = self._live_tool_dock('model-editor', projDir)
        if existing is not None:
            self._focus_dock(existing)
            return

        self.modelwidget = QtWidgets.QWidget()

        model_editor_widget = ModelEditorclass()
        self.modellayout = QtWidgets.QVBoxLayout()
        # No wrapper margins — the editor manages its own padding and should
        # fill the dock edge to edge rather than sit inside a dead border.
        self.modellayout.setContentsMargins(0, 0, 0, 0)
        self.modellayout.addWidget(model_editor_widget)

        # Adding to main Layout
        self.modelwidget.setLayout(self.modellayout)

        self._docks[dockName +
             str(self._count)] = QtWidgets.QDockWidget(dockName
                                                 + str(self._count))
        self.apply_fullscreen_feature(
            self._docks[dockName + str(self._count)], self.modelwidget)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea,
                           self._docks[dockName + str(self._count)])
        self.tabifyDockWidget(self._docks['Welcome'],
                              self._docks[dockName + str(self._count)])

        self._register_tool_dock(
            'model-editor', projDir,
            self._docks[dockName + str(self._count)], model_editor_widget)

        self._docks[dockName + str(self._count)].setVisible(True)
        self._docks[dockName + str(self._count)].setFocus()
        self._docks[dockName + str(self._count)].raise_()

        # Register with the project so Close Project reaps the Model Editor dock.
        temp = self.obj_appconfig.current_project['ProjectName']
        if temp:
            self.obj_appconfig.dock_dict.setdefault(temp, []).append(
                self._docks[dockName + str(self._count)]
            )
        self._count = self._count + 1

    def _closeExistingConverters(self):
        """Tear down any open KiCad-to-Ngspice converter dock.

        The converter uses module-level globals and class-level TrackWidget
        state as its data bus, so two live converter docks would clobber each
        other -- silently writing one project's circuit into another's
        .cir.out. Enforce the single-consumer invariant the converter was
        written against by destroying any existing converter dock before
        opening a new one. Also stops the module `dock` dict from leaking a
        fresh entry on every open.
        """
        for key in [k for k in self._docks if k.startswith('Netlist-')]:
            d = self._docks.pop(key, None)
            if d is None:
                continue
            # Drop it from per-project bookkeeping so closing the project
            # later cannot double-free an already-deleted dock.
            for docks in self.obj_appconfig.dock_dict.values():
                if d in docks:
                    docks.remove(d)
            try:
                self.removeDockWidget(d)
                d.setParent(None)
                d.deleteLater()
            except RuntimeError:
                # Already deleted on the Qt side; nothing to do.
                pass

    def kicadToNgspiceEditor(self, clarg1, clarg2=None,
                             projDir=None, projName=None, label=None):
        """
        This function is creating Editor UI for Kicad to Ngspice conversion.

        ``projDir``/``projName`` carry the project CAPTURED when a background
        netlist export began (see Kicad.openKicadToNgspice). Synchronous callers
        (subcircuit convert) pass neither and fall back to the live project.

        ``label`` names the tab when what is being converted is not the project
        itself. A subcircuit conversion belongs to the open project for cleanup
        purposes -- closing the project must still reap the tab -- but the tab
        has to say which *subcircuit* it is rebuilding, or the user is looking
        at a converter titled after a circuit it will not touch.
        """

        from kicadtoNgspice.KicadtoNgspice import MainWindow
        # Keep at most one converter live; see _closeExistingConverters.
        self._closeExistingConverters()

        # Fall back to the live project only for callers that captured nothing.
        if projDir is None:
            projDir = self.obj_appconfig.current_project["ProjectName"]
        # The captured project was closed during the export: don't crash on
        # os.path.basename(None) -- tell the user the conversion was abandoned.
        if projDir is None:
            Dialogs.information(
                self, "Project Closed",
                'The project was closed before its netlist conversion could '
                'open. Re-open the project and convert again.')
            return
        if projName is None:
            projName = os.path.basename(projDir)
        dockName = f'Netlist-{label or projName}-'

        self.kicadToNgspiceWidget = QtWidgets.QWidget()
        self.kicadToNgspiceLayout = QtWidgets.QVBoxLayout()
        self.kicadToNgspiceLayout.addWidget(MainWindow(clarg1, clarg2))

        self.kicadToNgspiceWidget.setLayout(self.kicadToNgspiceLayout)
        self._docks[dockName + str(self._count)] = \
            QtWidgets.QDockWidget(dockName + str(self._count))
        self.apply_fullscreen_feature(
            self._docks[dockName + str(self._count)], self.kicadToNgspiceWidget)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea,
                           self._docks[dockName + str(self._count)])
        self.tabifyDockWidget(self._docks['Welcome'],
                              self._docks[dockName + str(self._count)])


        self._docks[dockName + str(self._count)].setVisible(True)
        self._docks[dockName + str(self._count)].setFocus()
        self._docks[dockName + str(self._count)].raise_()
        self._docks[dockName + str(self._count)].activateWindow()

        # Register under the CAPTURED project so Close Project reaps this dock
        # even if the live project changed during the background export.
        if projDir:
            self.obj_appconfig.dock_dict.setdefault(projDir, []).append(
                self._docks[dockName + str(self._count)]
            )
        self._count = self._count + 1

    def subcircuiteditor(self):
        """This function creates a widget for different subcircuit options."""
        from subcircuit.Subcircuit import Subcircuit

        projDir = self.obj_appconfig.current_project["ProjectName"]

        """ Checks projDir variable has valid value 
        & is not None before calling os.path.basename """

        if projDir is not None:
            projName = os.path.basename(projDir)
            dockName = f'Subcircuit-{projName}-'

            # Single instance per project: re-click raises the open tab.
            existing = self._live_tool_dock('subcircuit', projDir)
            if existing is not None:
                self._focus_dock(existing)
                return

            self.subcktWidget = QtWidgets.QWidget()
            subcircuit_widget = Subcircuit(self)
            self.subcktLayout = QtWidgets.QVBoxLayout()
            self.subcktLayout.addWidget(subcircuit_widget)

            self.subcktWidget.setLayout(self.subcktLayout)
            self._docks[dockName +
                str(self._count)] = QtWidgets.QDockWidget(dockName
                                                    + str(self._count))
            self.apply_fullscreen_feature(
                self._docks[dockName + str(self._count)], self.subcktWidget)
            self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea,
                            self._docks[dockName + str(self._count)])
            self.tabifyDockWidget(self._docks['Welcome'],
                                self._docks[dockName + str(self._count)])

            self._register_tool_dock(
                'subcircuit', projDir,
                self._docks[dockName + str(self._count)], subcircuit_widget)

            self._docks[dockName + str(self._count)].setVisible(True)
            self._docks[dockName + str(self._count)].setFocus()
            self._docks[dockName + str(self._count)].raise_()

            # Register so Close Project reaps the Subcircuit dock too.
            temp = self.obj_appconfig.current_project['ProjectName']
            if temp:
                self.obj_appconfig.dock_dict.setdefault(temp, []).append(
                    self._docks[dockName + str(self._count)]
                )
            self._count = self._count + 1

        else:
            """ when projDir is None that is clicking on subcircuit icon
                without any project selection """
            self.msg = Dialogs.make_error_message(self)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Error Message")
            self.msg.showMessage(
                'Please select the project first.'
                ' You can either create new project or open existing project'
            )
            self.msg.exec()

    def show_welcome(self):
        """Bring the permanent Welcome (home) tab to the front.

        Backs the top-toolbar Home button: from anywhere in the app the user
        lands back on the Welcome dashboard to navigate out again.
        """
        welcome = self._docks.get('Welcome')
        if welcome is not None:
            welcome.setVisible(True)
            welcome.raise_()
            welcome.setFocus()

    def makerchip(self, select_vhdl=False):
        """This function creates a widget for different subcircuit options.

        ``select_vhdl`` opens the Flow Navigator straight on the VHDL / NGHDL
        path (backs the dedicated NGHDL launcher) instead of the default
        Verilog Author stage.
        """

        projDir = self.obj_appconfig.current_project["ProjectName"]
        if projDir is None:
            """ when projDir is None that is clicking on subcircuit icon
                without any project selection """
            self.msg = Dialogs.make_error_message(self)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Error Message")
            self.msg.showMessage(
                'Please select the project first.'
                ' You can either create new project or open existing project'
            )
            self.msg.exec()
            return
        projName = os.path.basename(projDir)
        # Tab/dock label, matching the launcher action "Model Creation
        # (Verilog / VHDL)" and the sibling docks' "<Tool>-<proj>-<n>" form
        # (Simulation-RLC-2, Plotting-RLC-3).
        dockName = f'Model Creation-{projName}-'

        # Single instance per project: both launchers (Makerchip and NGHDL)
        # share the one Flow Navigator dock -- a re-click raises it and puts it
        # back on that launcher's path (NGHDL -> VHDL, Makerchip -> Verilog),
        # so the two toolbar buttons keep switching sides once the dock is up.
        existing = self._live_tool_dock('model-creation', projDir)
        if existing is not None:
            try:
                existing._tool_widget.flow._select_mode(
                    "vhdl" if select_vhdl else "verilog")
            except Exception:
                pass
            self._focus_dock(existing)
            return

        # Local import: shadows this method's name inside its own scope only.
        from maker.makerchip import makerchip
        self.makerWidget = QtWidgets.QWidget()
        self.makerLayout = QtWidgets.QVBoxLayout()
        maker = makerchip(self)
        # NGHDL launcher: jump the Flow Navigator to the VHDL / NGHDL path so the
        # user lands on the digital-model stage directly.
        if select_vhdl:
            try:
                maker.flow._select_mode("vhdl")
            except Exception:
                pass
        self.makerLayout.addWidget(maker)

        self.makerWidget.setLayout(self.makerLayout)
        self._docks[dockName +
             str(self._count)] = QtWidgets.QDockWidget(dockName
                                                 + str(self._count))
        self.apply_fullscreen_feature(
            self._docks[dockName + str(self._count)], self.makerWidget)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea,
                           self._docks[dockName + str(self._count)])
        self.tabifyDockWidget(self._docks['Welcome'],
                              self._docks[dockName + str(self._count)])

        # Verify-stage waveforms open as their own full-width eSim tab next to
        # this Model Creation dock. Bind the source dock + its navigator so
        # "Back to Verify" (and tab-close) return to the exact instance that
        # produced the plot, even with several Model Creation docks open.
        source_dock = self._docks[dockName + str(self._count)]
        self._register_tool_dock('model-creation', projDir, source_dock, maker)
        maker.flow.waveformRequested.connect(
            lambda plot, src=source_dock, flow=maker.flow:
            self._show_waveform_dock(plot, src, flow))

        # No generic '.QWidget' box here: the legacy rounded-grey border boxed
        # every plain QWidget inside the panel (notably FlowNavigator's stage
        # tab strip, strangling the Author/Verify/Convert selector). The
        # FlowNavigator supplies its own header styling, so the panel sits
        # edge-to-edge with zero margins.
        self.makerLayout.setContentsMargins(0, 0, 0, 0)
        self.makerLayout.setSpacing(0)

        self._docks[dockName + str(self._count)].setVisible(True)
        self._docks[dockName + str(self._count)].setFocus()
        self._docks[dockName + str(self._count)].raise_()

        # Register with the project so Close Project reaps the Model Creation
        # dock like every sibling opener. Without this the dock (its Flow
        # Navigator + DesignBus watchdog thread) survived Close Project bound to
        # a closed project, and each open/close cycle leaked an OS observer
        # thread. Teardown of the watch runs off FlowNavigator's
        # destroyed signal (dock destruction skips closeEvent).
        if projDir:
            self.obj_appconfig.dock_dict.setdefault(projDir, []).append(
                self._docks[dockName + str(self._count)]
            )
        self._count = self._count + 1

    def _show_waveform_dock(self, plot, source_dock, flow):
        """Host a Verilog simulation waveform as its own full-width eSim tab.

        A re-simulate reuses the source dock's existing waveform tab (swapping
        in the new plot) instead of stacking tabs -- matching how Vivado /
        ModelSim keep a single waveform viewer that updates. The tab carries a
        "Back to Verify" control; that button and closing the tab both return to
        the Verify stage that produced the plot.

        If the Verify panel was fullscreen when the run finished, the waveform
        takes that fullscreen window over -- the window itself is never torn
        down (see FullScreen.handover), so the screen is not uncovered for even
        a frame. Simply adding the tab put it *behind* the fullscreen window,
        so the simulation looked like it had produced nothing and the user had
        to leave fullscreen and hunt for the tab.
        """
        from frontEnd.FullScreen import (FullScreenToggle, exit_fullscreen,
                                         go_fullscreen, handover,
                                         is_fullscreen, transfer)

        def take_fullscreen(target):
            """Move the editor's fullscreen window onto ``target``, seamlessly
            if possible and by a visible exit+enter only as a fallback."""
            if handover(source_dock, target):
                return
            exit_fullscreen(source_dock)
            go_fullscreen(target)

        # The user asked for a fullscreen work surface; the waveform is now
        # that surface, so it inherits the state rather than opening behind it.
        was_full = is_fullscreen(source_dock)

        existing = self._wave_docks.get(source_dock)
        if existing is not None:
            # Swap the plot inside the live tab and bring it forward. If that
            # tab is ITSELF the fullscreen panel (re-simulate from a second
            # screen), the swap happens inside the fullscreen window and there
            # is nothing else to do.
            old = existing._wave_plot
            if old is not None:
                existing._wave_layout.removeWidget(old)
                old.deleteLater()
            existing._wave_layout.addWidget(plot, 1)
            existing._wave_plot = plot
            # The outgoing plot carries the FullScreenToggle that OWNS the
            # fullscreen window (the button lives in the plot's own toolbar),
            # so deleting it above would strand the window on a deleted owner:
            # its close path raises, and the user is left staring at an empty
            # fullscreen rectangle they cannot dismiss. Hand the window to the
            # incoming plot's button before that can happen.
            new_toggle = plot.findChild(FullScreenToggle)
            if new_toggle is not None:
                transfer(existing, new_toggle)
            existing.setVisible(True)
            existing.raise_()
            if was_full and not is_fullscreen(existing):
                take_fullscreen(existing)
            return

        wave_dock = WaveformDock("Waveform-" + source_dock.windowTitle(), self)

        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # A slim header with the single round-trip control back to the editor.
        # objectName + selector so the band reliably paints (a bare-property
        # sheet on a plain QWidget often does not) and matches the Flow
        # Navigator's own header palette.
        header = QtWidgets.QWidget()
        header.setObjectName("waveHeader")
        # Theme-aware: #waveHeader is styled in style_{dark,light}.qss so it
        # tracks the active theme instead of the old hard-coded light palette.
        hrow = QtWidgets.QHBoxLayout(header)
        hrow.setContentsMargins(10, 6, 10, 6)
        back_btn = QtWidgets.QPushButton("← Back to Verify")
        back_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        back_btn.setProperty("cssClass", "secondary")
        back_btn.clicked.connect(
            lambda: self._return_to_verify(source_dock, flow, wave_dock))
        hrow.addWidget(back_btn)
        hrow.addStretch(1)
        layout.addWidget(header)
        layout.addWidget(plot, 1)

        # Remember the swappable plot + its layout for reuse on re-simulate.
        wave_dock._wave_plot = plot
        wave_dock._wave_layout = layout

        self.apply_fullscreen_feature(wave_dock, container)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea,
                           wave_dock)
        self.tabifyDockWidget(self._docks['Welcome'], wave_dock)

        self._wave_docks[source_dock] = wave_dock

        # Closing the tab drops the mapping and returns to Verify; the dock
        # deletes itself (WA_DeleteOnClose), so nothing leaks across cycles.
        def _on_closed():
            if self._wave_docks.get(source_dock) is wave_dock:
                del self._wave_docks[source_dock]
            self._return_to_verify(source_dock, flow, wave_dock)
        wave_dock.closed.connect(_on_closed)

        wave_dock.setVisible(True)
        wave_dock.setFocus()
        wave_dock.raise_()
        if was_full:
            take_fullscreen(wave_dock)

    def _return_to_verify(self, source_dock, flow, wave_dock=None):
        """Bring the Model Creation dock that owns this plot forward and select
        its Verify stage.

        The wave tab outlives its source dock: closing Model Creation deletes
        that dock (WA_DeleteOnClose) while the plot tab it spawned stays open,
        still holding this reference. Closing the plot afterwards -- or hitting
        "Back to Verify" -- would then touch a freed QDockWidget, so check the
        dock is still alive first, exactly as _live_tool_dock does.

        Fullscreen is handed back the same way it was handed over -- the same
        window, its content swapped, so the round trip has no flash in either
        direction. Without any of this, "Back to Verify" pressed on a
        fullscreen waveform raised the editor *behind* the fullscreen window:
        the click worked, and nothing appeared to happen.

        The decision reads the CURRENT state and nothing else: fullscreen
        waveform -> fullscreen editor, docked waveform -> docked editor. An
        earlier version remembered how the waveform tab was first opened, which
        went stale the moment the user pressed Esc -- a later docked run then
        threw the editor into fullscreen on the way back, out of nowhere."""
        from frontEnd.FullScreen import (exit_fullscreen, go_fullscreen,
                                         handover, is_fullscreen)

        source_alive = source_dock is not None and not sip.isdeleted(source_dock)
        wave_alive = wave_dock is not None and not sip.isdeleted(wave_dock)
        wave_is_full = wave_alive and is_fullscreen(wave_dock)

        # Select the stage first: the panel is about to be shown either way,
        # and switching it while it is off-screen avoids a visible re-layout.
        if source_alive:
            try:
                flow.goto_verify()
            except Exception:
                pass

        handed = False
        if wave_is_full:
            if source_alive:
                handed = handover(wave_dock, source_dock)
            if not handed:
                exit_fullscreen(wave_dock)

        if not source_alive:
            return
        source_dock.setVisible(True)
        source_dock.raise_()
        if wave_is_full and not handed:
            go_fullscreen(source_dock)

    def modelicaEditor(self, projDir):
        """This function sets up the UI for ngspice to modelica conversion."""
        from ngspicetoModelica.ModelicaUI import OpenModelicaEditor

        projName = os.path.basename(projDir)
        dockName = f'Modelica-{projName}-'

        # Single instance per project: re-click raises the open tab.
        existing = self._live_tool_dock('modelica', projDir)
        if existing is not None:
            self._focus_dock(existing)
            return

        self.modelicaWidget = QtWidgets.QWidget()
        modelica_widget = OpenModelicaEditor(projDir)
        self.modelicaLayout = QtWidgets.QVBoxLayout()
        self.modelicaLayout.addWidget(modelica_widget)

        self.modelicaWidget.setLayout(self.modelicaLayout)
        self._docks[dockName + str(self._count)
             ] = QtWidgets.QDockWidget(dockName + str(self._count))
        self.apply_fullscreen_feature(
            self._docks[dockName + str(self._count)], self.modelicaWidget)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea,
                           self._docks[dockName
                                + str(self._count)])
        self.tabifyDockWidget(self._docks['Welcome'], self._docks[dockName
                                                    + str(self._count)])

        self._register_tool_dock(
            'modelica', projDir,
            self._docks[dockName + str(self._count)], modelica_widget)

        self._docks[dockName + str(self._count)].setVisible(True)
        self._docks[dockName + str(self._count)].setFocus()
        self._docks[dockName + str(self._count)].raise_()

        temp = self.obj_appconfig.current_project['ProjectName']
        if temp:
            self.obj_appconfig.dock_dict.setdefault(temp, []).append(
                self._docks[dockName + str(self._count)]
            )

        self._count = self._count + 1

    def closeDock(self):
        """
        Destroy (not hide) every dock registered to the current project.

        Hiding a dock (the old ``close()``) left its whole widget tree alive
        for the rest of the session -- plot canvases + refresh timers,
        QWebEngineViews, QScintilla editors, the verifier's DesignBus watchdog
        thread -- still parented and still registered in ``dock_dict``. Repeated
        open/close cycles therefore piled up heavy widgets and leaked OS
        threads. Each dock is now torn down through ``_destroy_dock`` so its own
        ``closeEvent`` runs (matplotlib figures/timers closed, watchdog
        observers stopped, verifier tmpdirs reaped), and the per-project bucket
        is dropped.

        The list is copied because ``_destroy_dock`` -> ``_forget_dock`` mutates
        the same bucket as it goes.
        """
        self.temp = self.obj_appconfig.current_project['ProjectName']
        for dockwidget in list(
                self.obj_appconfig.dock_dict.get(self.temp, [])):
            try:
                self._destroy_dock(dockwidget)
            except RuntimeError:
                # Wrapper already deleted on the Qt side; nothing to do.
                pass
        # _forget_dock already removed each torn-down dock from the bucket;
        # drop the bucket entirely only if nothing survived (e.g. an editor
        # vetoed its close to protect unsaved changes).
        if not self.obj_appconfig.dock_dict.get(self.temp):
            self.obj_appconfig.dock_dict.pop(self.temp, None)
