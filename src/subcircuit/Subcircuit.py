import os

from PyQt6 import QtCore, QtGui, QtWidgets
from configuration.Appconfig import Appconfig
from configuration import Dialogs
from projManagement.Validation import Validation
from subcircuit.newSub import NewSub
from subcircuit.openSub import openSub
from subcircuit.convertSub import convertSub
from subcircuit.uploadSub import UploadSub


# This class creates Subcircuit GUI.
class Subcircuit(QtWidgets.QWidget):
    """
    Creates buttons for New project, Edit existing project and
    Kicad Netlist to Ngspice Netlist converter and link them with the
    methods defined for it in other files.

        - New Project(NewSub method of newSub).
        - Open Project(openSub method of openSub).
        - Kicad to Ngspice convertor(convertSub of convertSub).
    """

    def __init__(self, parent=None):
        # ONE initialiser. This used to call super().__init__() and then
        # QtWidgets.QWidget.__init__(self) again: on PyQt the second call
        # constructs a FRESH C++ QWidget and rebinds this Python wrapper to it,
        # abandoning the first one. The orphan stays registered as a top-level
        # widget with no live owner, so every open of the Subcircuit tab left
        # one behind -- and anything that walks
        # QApplication.topLevelWidgets() (theme repolish, and _app_teardown at
        # exit, which calls findChildren on each) eventually touches freed
        # memory. That is an 0xc0000005 with no Python traceback.
        super(Subcircuit, self).__init__()
        self.obj_appconfig = Appconfig()
        self.obj_validation = Validation()
        self.obj_dockarea = parent

        # ── Root: full-bleed column that fills the whole dock.
        # The old version dropped four fixed-size buttons into a single row
        # pinned to the top-left, leaving the rest of the panel as dead space.
        # Here the content spans the panel width and the action tiles stretch
        # to claim the vertical space down to the dock floor, mirroring the
        # Schematic Converter tab so the two panels read as one design.
        col = QtWidgets.QVBoxLayout(self)
        col.setContentsMargins(28, 24, 28, 24)
        col.setSpacing(18)

        # ── Header ───────────────────────────────────────────────────────
        title = QtWidgets.QLabel("Subcircuit Builder")
        title.setProperty("cssClass", "title")
        col.addWidget(title)

        subtitle = QtWidgets.QLabel(
            "Build reusable subcircuit blocks for your schematics — draw them "
            "in KiCad, convert the netlist to ngspice, or import an existing "
            "subcircuit."
        )
        subtitle.setProperty("cssClass", "muted")
        subtitle.setWordWrap(True)
        col.addWidget(subtitle)

        # ── Selection strip ──────────────────────────────────────────────
        # Which subcircuit the next Convert will rebuild. Before this existed
        # the panel showed nothing at all: the only name on screen belonged to
        # the open *project*, which the Subcircuit Builder never touches, so
        # there was no way to tell what Convert was about to act on -- or that
        # anything was selected at all.
        self.selection_label = QtWidgets.QLabel()
        self.selection_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.selection_label.setWordWrap(True)
        self.selection_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self.selection_label)

        # ── Action tiles ─────────────────────────────────────────────────
        # Each tile is a real button with two lines of its own: a bold action
        # title and a muted one-line caption. That gives the box something to
        # hold, so it can stay a sane fixed height instead of ballooning to
        # fill the dock with one tiny word marooned in the middle.
        # Fonts are set with setFont (not stylesheet font-size): a stylesheet
        # font doesn't update the label's sizeHint, so the layout would reserve
        # default-font height while painting the bigger font — clipping
        # descenders (g/p/y) and overlapping the caption. setFont keeps metrics
        # and paint in sync.
        # 16px/12px are the design sizes at 100% zoom; the padding below is in
        # design pixels too. Both go through theme_utils so the tiles zoom with
        # the rest of the UI -- and because the height is derived from the
        # scaled font metrics, the box grows to fit the text rather than
        # clipping it.
        from frontEnd.theme_utils import scale_font_px, zoom_px

        title_font = QtGui.QFont()
        title_font.setPixelSize(scale_font_px(16))
        title_font.setWeight(QtGui.QFont.Weight.DemiBold)
        cap_font = QtGui.QFont()
        cap_font.setPixelSize(scale_font_px(12))

        # A QPushButton ignores its child layout when computing its own height,
        # so a hardcoded minHeight is fragile: the real app's QSS adds more
        # button padding than a bare stylesheet, and the caption's bottom gets
        # clipped. Derive the height from the actual font metrics plus generous
        # slack for whatever padding/border the theme applies.
        _top_pad = _bot_pad = zoom_px(14)
        _gap = zoom_px(4)
        _side_pad = zoom_px(18)
        _tile_min_h = (
            _top_pad + _bot_pad + _gap + zoom_px(16)
            + QtGui.QFontMetrics(title_font).height()
            + QtGui.QFontMetrics(cap_font).height()
        )

        def _tile(title, caption, tooltip, handler, primary=False):
            btn = QtWidgets.QPushButton()
            btn.setToolTip(tooltip)
            # The height MUST be set via an inline stylesheet, not
            # setMinimumHeight(): the app QSS carries `QPushButton
            # { min-height: 32px }`, and Qt's stylesheet engine clobbers a
            # Python-set minimum with the QSS one. A widget-level stylesheet
            # outranks the app QSS, so this min-height actually sticks and the
            # tile grows tall enough to hold both text lines without clipping.
            btn.setStyleSheet("QPushButton { min-height: %dpx; }" % _tile_min_h)
            btn.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

            inner = QtWidgets.QVBoxLayout(btn)
            inner.setContentsMargins(_side_pad, _top_pad, _side_pad, _bot_pad)
            inner.setSpacing(_gap)

            title_lbl = QtWidgets.QLabel(title)
            title_lbl.setFont(title_font)
            # Non-primary tiles inherit the theme's QLabel colour so the text
            # stays visible in dark mode; only the solid-blue primary tile
            # needs a forced white.
            if primary:
                title_lbl.setStyleSheet("color:#ffffff;background:transparent;")
            else:
                title_lbl.setStyleSheet("background:transparent;")

            cap_lbl = QtWidgets.QLabel(caption)
            cap_lbl.setFont(cap_font)
            cap_lbl.setWordWrap(True)
            if primary:
                cap_lbl.setStyleSheet(
                    "color:rgba(255,255,255,0.82);background:transparent;")
            else:
                # Themed muted colour via the shared QSS class.
                cap_lbl.setProperty("cssClass", "muted")
                cap_lbl.setStyleSheet("background:transparent;")

            if primary:
                btn.setProperty("cssClass", "primary")
            for lbl in (title_lbl, cap_lbl):
                lbl.setAttribute(
                    QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            # Centre the two lines vertically so they sit balanced in the tile
            # instead of hugging the top with a gap beneath.
            inner.addStretch(1)
            inner.addWidget(title_lbl)
            inner.addWidget(cap_lbl)
            inner.addStretch(1)

            btn.clicked.connect(handler)
            return btn

        self.newbtn = _tile(
            "New", "Start a blank subcircuit schematic",
            '<b>To create new Subcircuit Schematic</b>', self.newsch,
            primary=True)
        self.editbtn = _tile(
            "Edit", "Open an existing subcircuit",
            '<b>To edit existing Subcircuit Schematic</b>', self.editsch)
        self.convertbtn = _tile(
            "Convert to Ngspice", "KiCad netlist → ngspice .sub model",
            '<b>To convert Subcircuit Kicad Netlist to Ngspice Netlist</b>',
            self.convertsch)
        self.uploadbtn = _tile(
            "Upload", "Import a .sub you already have",
            '<b>Add an existing .sub file to the eSim Subcircuit Library</b>'
            '<br/>No schematic is drawn and nothing is converted -- use this '
            'for a model you wrote by hand or received from someone else.',
            self.uploadSub)

        schematic_group = QtWidgets.QGroupBox("Schematic")
        schematic_group.setProperty("cssClass", "themedGroupBox")
        schematic_row = QtWidgets.QHBoxLayout(schematic_group)
        schematic_row.setSpacing(12)
        schematic_row.addWidget(self.newbtn)
        schematic_row.addWidget(self.editbtn)

        netlist_group = QtWidgets.QGroupBox("Netlist")
        netlist_group.setProperty("cssClass", "themedGroupBox")
        netlist_row = QtWidgets.QHBoxLayout(netlist_group)
        netlist_row.setSpacing(12)
        netlist_row.addWidget(self.convertbtn)
        netlist_row.addWidget(self.uploadbtn)

        # Left rail: the two groups stacked at their natural height near the
        # top — no vertical stretch, so the tiles stay compact.
        actions_col = QtWidgets.QVBoxLayout()
        actions_col.setSpacing(16)
        actions_col.addWidget(schematic_group)
        actions_col.addWidget(netlist_group)
        actions_col.addStretch(1)

        # ── About + how-it-works (right rail) ────────────────────────────
        about_group = QtWidgets.QGroupBox("About")
        about_group.setProperty("cssClass", "themedGroupBox")
        about_layout = QtWidgets.QVBoxLayout(about_group)
        about_layout.setSpacing(14)

        description_label = QtWidgets.QLabel(
            "<p>A <b>subcircuit</b> is a reusable block you can drop into any "
            "eSim schematic — model it once, wire it in many times.</p>"
            "<p><b>New / Edit</b> open a KiCad schematic for the subcircuit's "
            "internals. <b>Convert to Ngspice</b> turns that KiCad netlist "
            "into an ngspice <code>.sub</code> model. <b>Upload</b> imports an "
            "existing subcircuit file into your library.</p>"
        )
        description_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        description_label.setWordWrap(True)
        about_layout.addWidget(description_label)

        steps_label = QtWidgets.QLabel(
            "<p style='margin-bottom:0'><b>How it works</b><br/>"
            "1&nbsp;&nbsp;Create or edit the subcircuit schematic.<br/>"
            "2&nbsp;&nbsp;Convert its KiCad netlist to ngspice.<br/>"
            "3&nbsp;&nbsp;Reuse it — or upload one someone else built.</p>"
        )
        steps_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        steps_label.setWordWrap(True)
        about_layout.addWidget(steps_label)
        about_layout.addStretch(1)

        # Keep About at its natural height at the top of the right rail.
        about_col = QtWidgets.QVBoxLayout()
        about_col.addWidget(about_group)
        about_col.addStretch(1)

        # ── Body: actions (left) + about (right) ─────────────────────────
        # No stretch weight on the body itself — the trailing stretch below
        # lets the whole block sit compactly near the top like a launcher,
        # instead of being pulled down to fill the dock floor.
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(18)
        body.addLayout(actions_col, 3)
        body.addLayout(about_col, 2)
        col.addLayout(body)
        col.addStretch(1)

        # Selection is per-panel, not per-application. Appconfig keeps it in a
        # CLASS attribute shared by every instance, so two projects each with a
        # Subcircuit tab open used to share one selection: work in project A,
        # switch to B, hit Convert, and B's panel rebuilt A's subcircuit. The
        # panel owns its own selection and re-asserts it whenever it is the one
        # on screen (see showEvent).
        self._folder = None
        self._stem = None
        self.obj_convertsubcircuit = None
        self._adopt_existing_selection()
        self._refresh_selection()

    # -- selection ----------------------------------------------------------

    def _adopt_existing_selection(self):
        """Inherit a selection made before this panel existed.

        Keeps a reopened tab (and any code path that set the selection without
        going through this widget) showing what is actually active instead of
        claiming nothing is selected.
        """
        folder = self.obj_appconfig.current_subcircuit.get("SubcircuitName")
        if folder and os.path.isdir(str(folder)):
            self._folder = folder
            self._stem = self.obj_appconfig.get_subcircuit_stem()

    def _select(self, folder, stem):
        """Record the subcircuit this panel is working on."""
        self._folder = folder
        self._stem = stem
        self.obj_appconfig.set_current_subcircuit(folder, stem)
        self._refresh_selection()

    def _refresh_selection(self):
        """Repaint the selection strip and gate Convert on having a target."""
        if self._folder and self._stem:
            self.selection_label.setText(
                "Working on <b>%s</b> &nbsp;<span>%s</span>"
                % (self._stem, self._folder))
        else:
            self.selection_label.setText(
                "<i>No subcircuit selected — start one with <b>New</b>, "
                "or open an existing one with <b>Edit</b>.</i>")
        ready = bool(self._folder and self._stem)
        self.convertbtn.setEnabled(ready)
        self.convertbtn.setToolTip(
            '<b>To convert Subcircuit Kicad Netlist to Ngspice Netlist</b>'
            if ready else
            '<b>Select a subcircuit first</b><br/>Use <b>New</b> or '
            '<b>Edit</b>; Convert then rebuilds that subcircuit&#39;s '
            '<code>.sub</code> model.')

    def showEvent(self, event):
        """Make the visible panel's selection the active one.

        Subcircuit tabs are per project and tabbed together with everything
        else; raising one has to hand the shared selection back to it, or
        Convert would act on whatever another tab last touched.
        """
        super(Subcircuit, self).showEvent(event)
        if self._folder and self._stem:
            self.obj_appconfig.set_current_subcircuit(
                self._folder, self._stem)
        self._refresh_selection()

    # -- actions ------------------------------------------------------------

    def newsch(self):
        text, ok = QtWidgets.QInputDialog.getText(
            self, 'New Schematic', 'Enter Schematic Name:'
        )
        if ok:
            if not text:
                print("Schematic name cannot be empty")
                print("==================")
                Dialogs.critical(
                    self, "Error Message",
                    'The schematic name cannot be empty')
                return

            self.schematic_name = (str(text))
            self.subcircuit = NewSub()
            self.subcircuit.createSubcircuit(self.schematic_name)
            self._sync_from_appconfig()

        else:
            print("Sub circuit creation cancelled")

    def editsch(self):
        self.obj_opensubcircuit = openSub()
        stem = self.obj_opensubcircuit.body()
        if stem:
            self._select(self.obj_opensubcircuit.editfile, stem)

    def convertsch(self):
        # One converter per panel, reused. Netlist generation runs on a worker
        # thread now, so the guard against a second click while the first is
        # still exporting has to live on an object that survives the click.
        if self.obj_convertsubcircuit is None:
            self.obj_convertsubcircuit = convertSub(self.obj_dockarea)
        self.obj_convertsubcircuit.createSub()

    def uploadSub(self):
        self.obj_uploadsubcircuit = UploadSub()
        self.obj_uploadsubcircuit.upload()

    def _sync_from_appconfig(self):
        """Adopt whatever the helper widget just selected.

        New/Edit run in their own objects and record the selection through
        Appconfig; this pulls it back so the panel's own copy -- the one
        showEvent re-asserts -- cannot drift from it.
        """
        folder = self.obj_appconfig.current_subcircuit.get("SubcircuitName")
        if folder and folder != self._folder:
            self._folder = folder
            self._stem = self.obj_appconfig.get_subcircuit_stem()
        self._refresh_selection()
