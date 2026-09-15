# ==============================================================================
#  ModelGroupWidget.py -- a collapsible "assign once, override per instance"
#  group card for the Device Modeling and Subcircuits tabs.
#
#  One ModelGroupWidget represents all instances that share a model (e.g. the
#  five eSim_NPN transistors). It shows:
#
#      > eSim_NPN  Transistor  (q1 · q2 · q5)  [ /lib/bc547.lib  ] [Browse]
#          q1   (follows group)
#          q2   (follows group)
#          q5   [ /lib/bc547_alt.lib ] [Browse]  overridden  [Reset]
#
#  The group path field fans its value out to every instance that is still
#  "inheriting"; editing one instance's field (or its Browse) detaches just that
#  instance ("override") so later group changes leave it alone, and Reset
#  re-attaches it.
#
#  Design / why it is shaped this way:
#    * The per-instance QLineEdit handed in (InstanceRow.path_edit) is the SAME
#      widget the converter already registers in TrackWidget (entry_var) and
#      that three consumers read per instance (Convert -> netlist, callConvert ->
#      Previous_Values.xml, tab reload). This widget never replaces that storage;
#      it only arranges those edits and drives them. So grouping stays a pure
#      view/controller layer and the downstream netlist is byte-for-byte
#      unchanged.
#    * Override is detected with QLineEdit.textEdited (user keystrokes only),
#      never textChanged, so the programmatic setText() used for fan-out does NOT
#      look like a manual override.
#    * resolve_fn(ref, path) is the single hook back to the tab; the tab uses it
#      to validate and update its deviceModelTrack / subcircuitTrack entry, i.e.
#      exactly what trackLibraryWithoutButton already does.
#
#  The disclosure (expand/collapse) is built on three rules:
#    1. CLIP, DON'T SQUASH. The instance rows live in `_content`, a widget that
#       always keeps its full natural height, inside `_ClipBox`, whose height is
#       what the animation drives. Animating the height of the widget that OWNS
#       the rows -- the previous shape -- re-ran the row layout on every frame
#       and squeezed each QLineEdit down toward zero, so the rows visibly
#       reflowed and jittered instead of sliding into view.
#    2. ONE animation object, restarted from wherever it currently is. Building
#       a fresh QPropertyAnimation per click left the previous one running (it
#       was parented, so dropping the Python reference did not stop it): two
#       animations then drove the same height in opposite directions, which is
#       what made a quick double-click stutter and land at the wrong size.
#    3. Every path settles synchronously in `_settle`. Motion off, widget not on
#       screen (headless tests, construction before the tab is shown), or the
#       animation finishing -- all end in the same place, so the body's final
#       visibility never depends on a callback that may not fire.
#    4. An OPEN body is a hard floor on the card's height (_ClipBox.
#       minimumSizeHint), because the tab divides its height between the cards
#       (finish_group_layout) and would otherwise shrink an open card below its
#       own rows -- which the clip does not report, it just cuts them off. Qt
#       bounds a minimumSizeHint by maximumSize, so the cap the slide drives
#       still lets the box collapse to zero while it is animating.
# ==============================================================================
import re

from PyQt6 import QtCore, QtGui, QtWidgets


class InstanceRow:
    """One instance inside a model group.

    ref       : reference designator (q1, x1, ...)
    path_edit : the canonical per-instance QLineEdit (a TrackWidget entry_var).
    browse_fn : optional zero-arg callable that opens a file dialog and returns
                the chosen path (or '' / None if cancelled).
    extras    : optional list of (label_text, QWidget) shown after the path on
                this instance's row -- used for MOSFET W/L/M, which are always
                per-instance and never inherited.
    """

    def __init__(self, ref, path_edit, browse_fn=None, extras=None):
        self.ref = ref
        self.path_edit = path_edit
        self.browse_fn = browse_fn
        self.extras = extras or []
        self.overridden = False
        # Populated by the widget when it builds this row:
        self._marker = None
        self._reset_btn = None


class ModelGroupWidget(QtWidgets.QGroupBox):
    """Collapsible group of instances that share one model/library."""

    def __init__(self, title, instance_rows, resolve_fn=None,
                 group_browse_fn=None, parent=None):
        super().__init__(parent)
        self._rows = list(instance_rows)
        self._resolve_fn = resolve_fn or (lambda ref, path: None)
        self._group_browse_fn = group_browse_fn

        refs = [r.ref for r in self._rows]
        self._title_text = title
        self.setTitle("")           # custom header row instead of the box title
        self.setProperty("cssClass", "modelGroup")
        # Cards divide the tab between them (see finish_group_layout), so a
        # card takes whatever height its share gives it and centres its content
        # in that. Expanding one grows its minimum, which squeezes the others.
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred,
                           QtWidgets.QSizePolicy.Policy.Preferred)

        outer = QtWidgets.QVBoxLayout()
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(0)
        self.setLayout(outer)
        # Equal stretch above and below the header+body block: the block sits
        # in the middle of a card with room to spare, and the two stretches
        # collapse to nothing once the card is packed, so a full tab looks the
        # same as it would with no centring at all.
        outer.addStretch(1)

        # -- header: disclosure button + group path + group Browse -------------
        header = QtWidgets.QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setHorizontalSpacing(10)

        self._toggle = _GroupHeader(title, refs)
        self._toggle.clicked.connect(self._on_toggle)
        header.addWidget(self._toggle, 0, 0)

        self._group_edit = QtWidgets.QLineEdit()
        self._group_edit.setPlaceholderText(
            "Assign one file for all %d instances" % len(self._rows))
        self._group_edit.editingFinished.connect(
            lambda: self.set_group_path(self._group_edit.text()))
        header.addWidget(self._group_edit, 0, 1)

        group_browse = QtWidgets.QPushButton("Browse")
        group_browse.setProperty("cssClass", "secondary")
        group_browse.clicked.connect(self._on_group_browse)
        header.addWidget(group_browse, 0, 2)

        # Proportional columns, not content-driven ones: every group on the tab
        # is its own layout, so only a shared ratio can line their path fields
        # and Browse buttons up into columns. The header button elides its own
        # text, so a long model name cannot push the ratio around.
        header.setColumnStretch(0, 4)
        header.setColumnStretch(1, 6)
        header.setColumnStretch(2, 0)
        outer.addLayout(header)

        # -- collapsible body: one row per instance ----------------------------
        self._content = QtWidgets.QWidget()
        content_box = QtWidgets.QVBoxLayout()
        content_box.setContentsMargins(4, 5, 4, 4)
        content_box.setSpacing(8)
        self._content.setLayout(content_box)
        content_box.addWidget(_Hairline())

        body_grid = QtWidgets.QGridLayout()
        body_grid.setContentsMargins(22, 0, 0, 0)
        body_grid.setVerticalSpacing(5)
        body_grid.setHorizontalSpacing(8)
        content_box.addLayout(body_grid)

        for r, row in enumerate(self._rows):
            ref_label = QtWidgets.QLabel(row.ref)
            ref_label.setProperty("cssClass", "muted")
            ref_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                                   | QtCore.Qt.AlignmentFlag.AlignVCenter)
            body_grid.addWidget(ref_label, r, 0)
            row.path_edit.setPlaceholderText("follows the group above")
            body_grid.addWidget(row.path_edit, r, 1)

            row_browse = QtWidgets.QPushButton("Browse")
            row_browse.setProperty("cssClass", "tertiary")
            row_browse.clicked.connect(self._make_row_browse(row))
            body_grid.addWidget(row_browse, r, 2)

            row._marker = QtWidgets.QLabel("")
            row._marker.setProperty("cssClass", "muted")
            body_grid.addWidget(row._marker, r, 3)

            row._reset_btn = QtWidgets.QPushButton("Reset")
            row._reset_btn.setProperty("cssClass", "tertiary")
            row._reset_btn.setToolTip(
                "Follow the group path again instead of this instance's own")
            row._reset_btn.setVisible(False)
            row._reset_btn.clicked.connect(self._make_row_reset(row))
            body_grid.addWidget(row._reset_btn, r, 4)

            # MOSFET-style per-instance extras (W/L/M); never inherited.
            col = 5
            for label_text, widget in row.extras:
                extra_label = QtWidgets.QLabel(label_text)
                extra_label.setProperty("cssClass", "muted")
                body_grid.addWidget(extra_label, r, col)
                body_grid.addWidget(widget, r, col + 1)
                col += 2

            # User keystrokes (not programmatic setText) => override this row.
            row.path_edit.textEdited.connect(self._make_row_edited(row))

        # Same 4:6 split as the header row, so an instance's path field sits
        # (near enough) under the group field it inherits from.
        body_grid.setColumnStretch(0, 4)
        body_grid.setColumnStretch(1, 6)

        self._clip = _ClipBox(self._content)
        outer.addWidget(self._clip)
        outer.addStretch(1)
        self._clip.setVisible(False)

        # Fade the rows in with the slide. The effect is created once and only
        # ENABLED while an animation runs: a disabled QGraphicsEffect costs
        # nothing at rest, and never deleting it keeps this off the
        # freed-effect-touched-by-a-live-animation path that theme repolishing
        # has to guard against elsewhere.
        self._fade = QtWidgets.QGraphicsOpacityEffect(self._content)
        self._fade.setOpacity(1.0)
        self._fade.setEnabled(False)
        self._content.setGraphicsEffect(self._fade)

        self._anim = QtCore.QParallelAnimationGroup(self)
        self._height_anim = QtCore.QPropertyAnimation(
            self._clip, b"maximumHeight", self)
        self._fade_anim = QtCore.QPropertyAnimation(
            self._fade, b"opacity", self)
        self._arrow_anim = QtCore.QPropertyAnimation(
            self._toggle, b"rotation", self)
        for a in (self._height_anim, self._fade_anim, self._arrow_anim):
            self._anim.addAnimation(a)
        self._anim.finished.connect(self._on_anim_finished)

        self._derive_initial()

    # -- public API (also the unit-test surface) -------------------------------

    def set_group_path(self, path):
        """Set the group default and push it to every inheriting instance."""
        if self._group_edit.text() != path:
            self._group_edit.setText(path)
        for row in self._rows:
            if not row.overridden:
                self._apply(row, path)

    def override(self, ref, path):
        """Detach one instance and give it its own path."""
        row = self._row(ref)
        row.path_edit.setText(path)
        self._set_overridden(row, True)
        self._resolve_fn(row.ref, path)

    def reset_row_by_ref(self, ref):
        """Re-attach one instance to the group default."""
        self._reset(self._row(ref))

    def resolved(self):
        """Return {ref: current path text} -- what each instance would convert
        with right now. Mirrors the per-instance entries the tab tracks."""
        return {r.ref: r.path_edit.text() for r in self._rows}

    def group_path(self):
        return self._group_edit.text()

    def is_overridden(self, ref):
        return self._row(ref).overridden

    def is_expanded(self):
        # Tracked via the toggle's checked state, not body.isVisible(): a widget
        # only reports visible once it and all ancestors are shown, which is
        # false in headless tests and before the tab is displayed.
        return self._toggle.isChecked()

    def set_expanded(self, expanded):
        self._toggle.setChecked(expanded)
        self._on_toggle()

    # -- internals -------------------------------------------------------------

    def _row(self, ref):
        for r in self._rows:
            if r.ref == ref:
                return r
        raise KeyError(ref)

    def _apply(self, row, path):
        if row.path_edit.text() != path:
            row.path_edit.setText(path)
        self._resolve_fn(row.ref, path)

    def _reset(self, row):
        self._set_overridden(row, False)
        path = self._group_edit.text()
        if row.path_edit.text() != path:
            row.path_edit.setText(path)
        self._resolve_fn(row.ref, path)

    def _set_overridden(self, row, value):
        row.overridden = value
        if row._marker is not None:
            row._marker.setText("overridden" if value else "")
        if row._reset_btn is not None:
            row._reset_btn.setVisible(value)
        self._toggle.set_override_count(
            sum(1 for r in self._rows if r.overridden))
        # Showing/hiding Reset changes the rows' natural height, so the clip
        # has to re-measure or the last row would be cut off while open.
        self._clip.sync()

    def _derive_initial(self):
        """Set the starting group/override state from whatever the instance
        edits already hold (e.g. values restored from Previous_Values.xml).

        Rule: if every instance carries the same non-empty value, that becomes
        the group default and all instances inherit. Otherwise the group is left
        blank and any instance that has a value is shown as an override (and the
        group is expanded so the user sees them). This never calls resolve_fn --
        restored values are already tracked.
        """
        vals = [r.path_edit.text() for r in self._rows]
        nonempty = [v for v in vals if v]
        uniform = bool(nonempty) and all(v == nonempty[0] for v in vals)
        if uniform:
            self._group_edit.setText(nonempty[0])
            for row in self._rows:
                self._set_overridden(row, False)
        else:
            self._group_edit.setText("")
            any_override = False
            for row in self._rows:
                has_val = bool(row.path_edit.text())
                self._set_overridden(row, has_val)
                any_override = any_override or has_val
            if any_override:
                self.set_expanded(True)

    # -- Qt signal adapters ----------------------------------------------------

    def _on_toggle(self):
        self._animate_body(self._toggle.isChecked())

    def _animate_body(self, expanded):
        """Slide the instance list open/closed instead of snapping it.

        Falls back to a plain show/hide when motion is off or the widget is not
        on screen (headless tests, pre-display construction) -- an animation
        never advances there, so the body must reach its final state
        synchronously."""
        if not _motion_enabled() or not self.isVisible():
            self._settle(expanded)
            return

        clip = self._clip
        # The fade effect is only ever enabled while a slide runs, so this is
        # also the "were we interrupted mid-slide?" flag -- read it before the
        # stop below, because that is what the fade has to resume from.
        mid_slide = self._fade.isEnabled()
        self._anim.stop()               # never leave a second animation running

        # Start from where the body actually is, so a toggle mid-slide reverses
        # smoothly from that point instead of jumping to 0 / full height first.
        start = clip.maximumHeight()
        if start >= _UNCAPPED:
            start = clip.height() if clip.isVisible() else 0
        target = clip.content_height() if expanded else 0
        if start == target:
            self._settle(expanded)
            return

        clip.setMaximumHeight(start)
        if expanded:
            clip.setVisible(True)

        duration = _duration(abs(target - start), expanded)
        self._height_anim.setDuration(duration)
        self._height_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._height_anim.setStartValue(start)
        self._height_anim.setEndValue(target)

        # The rows finish fading in a little before the slide stops (and fade
        # out a little before it closes), so the eye never catches the last
        # couple of clipped pixels.
        fade_from = self._fade.opacity() if mid_slide \
            else (0.0 if expanded else 1.0)
        self._fade.setOpacity(fade_from)
        self._fade.setEnabled(True)
        self._fade_anim.setDuration(max(80, int(duration * 0.7)))
        self._fade_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._fade_anim.setStartValue(fade_from)
        self._fade_anim.setEndValue(1.0 if expanded else 0.0)

        self._arrow_anim.setDuration(duration)
        self._arrow_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._arrow_anim.setStartValue(self._toggle.rotation)
        self._arrow_anim.setEndValue(_OPEN_ANGLE if expanded else 0.0)

        self._anim.start()

    def _on_anim_finished(self):
        # Read the toggle rather than a captured flag: whatever it says now is
        # the state the user asked for, even if they clicked again mid-slide.
        self._settle(self._toggle.isChecked())

    def _settle(self, expanded):
        """Put the body in its final, un-animated state. Every path ends here."""
        self._fade.setOpacity(1.0)
        self._fade.setEnabled(False)
        self._clip.setMaximumHeight(_UNCAPPED)
        self._clip.setVisible(expanded)
        self._clip.sync()
        self._toggle.rotation = _OPEN_ANGLE if expanded else 0.0

    def _on_group_browse(self):
        if not self._group_browse_fn:
            return
        path = self._group_browse_fn()
        if path:
            self.set_group_path(path)

    def _make_row_browse(self, row):
        def handler():
            if not row.browse_fn:
                return
            path = row.browse_fn()
            if path:
                self.override(row.ref, path)
        return handler

    def _make_row_reset(self, row):
        return lambda: self._reset(row)

    def _make_row_edited(self, row):
        def handler(text):
            self._set_overridden(row, True)
            self._resolve_fn(row.ref, text)
        return handler


class _ClipBox(QtWidgets.QWidget):
    """A height-limited window onto a widget that keeps its natural size.

    The content is deliberately NOT in a layout. It is given its full sizeHint
    height on every resize and this box simply clips what does not fit, so an
    animation on ``maximumHeight`` reveals finished rows instead of re-laying
    them out (and squashing every QLineEdit toward zero) once per frame.
    """

    def __init__(self, content, parent=None):
        super().__init__(parent)
        self._content = content
        content.setParent(self)
        content.installEventFilter(self)

    def content_height(self):
        return self._content.sizeHint().height()

    def sizeHint(self):
        return self._content.sizeHint()

    def minimumSizeHint(self):
        # Ask for the content in full. Qt bounds a minimumSizeHint by the
        # widget's maximumSize, so while the slide is capping that this still
        # lets the box shrink all the way to zero -- but once it is open and
        # uncapped, the card can no longer be squeezed below its own rows by a
        # layout dividing the tab up, which would silently cut rows off inside
        # the clip instead of letting the tab scroll.
        return QtCore.QSize(self._content.minimumSizeHint().width(),
                            self.content_height())

    def sync(self):
        """Re-measure after the content's own size requirements changed."""
        self.updateGeometry()
        self._lay_out_content()

    def resizeEvent(self, event):
        self._lay_out_content()
        super().resizeEvent(event)

    def eventFilter(self, obj, event):
        if obj is self._content \
                and event.type() == QtCore.QEvent.Type.LayoutRequest:
            self.sync()
        return False

    def _lay_out_content(self):
        width = max(self.width(), self._content.minimumSizeHint().width())
        self._content.setGeometry(0, 0, width, self.content_height())


class _Hairline(QtWidgets.QWidget):
    """A one-pixel divider at the text colour, heavily faded.

    A QFrame HLine draws from the palette's shadow/light roles, which under
    both eSim sheets lands far brighter than anything else on the card; this
    keeps the separator at the weight the rest of the chrome uses and needs no
    per-theme wiring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Fixed)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        color = QtGui.QColor(
            self.palette().color(QtGui.QPalette.ColorRole.WindowText))
        color.setAlpha(38)
        painter.fillRect(self.rect(), color)
        painter.end()


class _GroupHeader(QtWidgets.QAbstractButton):
    """The disclosure control: chevron + model name + kind + instance chip.

    Painted rather than assembled from a QToolButton so that (a) the chevron
    can rotate continuously with the slide instead of swapping between two
    fixed arrow bitmaps, (b) the title can elide itself, which is what lets the
    header columns stay a fixed ratio and line up across every group on the
    tab, and (c) the whole strip is one hit target. All colours come from the
    palette, so it follows a light/dark switch with no extra wiring.
    """

    _PAD_X = 9
    _GAP = 9
    _CHEVRON = 13

    def __init__(self, title, refs, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Fixed)
        self._name, self._kind = _split_title(title)
        self._refs = list(refs)
        self._chip = _chip_text(self._refs)
        self._override_count = 0
        self._rotation = 0.0
        self._hovered = False
        self.setText(title)              # accessible name / findChild by text
        self._refresh_tooltip()

    # -- animated chevron ------------------------------------------------------

    def _get_rotation(self):
        return self._rotation

    def _set_rotation(self, value):
        value = float(value)
        if value != self._rotation:
            self._rotation = value
            self.update()

    rotation = QtCore.pyqtProperty(float, _get_rotation, _set_rotation)

    # -- state -----------------------------------------------------------------

    def set_override_count(self, count):
        if count != self._override_count:
            self._override_count = count
            self._refresh_tooltip()
            self.update()

    def _refresh_tooltip(self):
        tip = "%s — %d instance%s: %s" % (
            self._name, len(self._refs), "" if len(self._refs) == 1 else "s",
            ", ".join(self._refs))
        if self._override_count:
            tip += "\n%d with their own path" % self._override_count
        self.setToolTip(tip)

    # -- geometry --------------------------------------------------------------

    def _row_height(self):
        return max(self.fontMetrics().height() + 12, 28)

    def sizeHint(self):
        fm = self.fontMetrics()
        width = (self._PAD_X * 2 + self._CHEVRON + self._GAP
                 + fm.horizontalAdvance(self._name)
                 + self._GAP + fm.horizontalAdvance(self._kind)
                 + self._GAP + self._chip_width())
        return QtCore.QSize(width, self._row_height())

    def minimumSizeHint(self):
        fm = self.fontMetrics()
        return QtCore.QSize(
            self._PAD_X * 2 + self._CHEVRON + self._GAP
            + fm.horizontalAdvance("MMMMMMMM…"),
            self._row_height())

    def _chip_font(self):
        font = QtGui.QFont(self.font())
        size = font.pointSizeF()
        if size > 0:
            font.setPointSizeF(max(6.5, size - 1.0))
        return font

    def _chip_width(self):
        if not self._chip:
            return 0
        fm = QtGui.QFontMetrics(self._chip_font())
        return fm.horizontalAdvance(self._chip) + 16

    # -- hover / paint ---------------------------------------------------------

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        palette = self.palette()
        accent = palette.color(QtGui.QPalette.ColorRole.Highlight)
        text_color = palette.color(QtGui.QPalette.ColorRole.WindowText)
        lit = self._hovered or self.isChecked() or self.hasFocus()

        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isDown():
            fill_alpha = 46
        elif self._hovered:
            fill_alpha = 30
        elif self.isChecked():
            fill_alpha = 16
        else:
            fill_alpha = 0
        if fill_alpha:
            fill = QtGui.QColor(accent)
            fill.setAlpha(fill_alpha)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 9, 9)
        if self.hasFocus():
            ring = QtGui.QColor(accent)
            ring.setAlpha(150)
            painter.setPen(QtGui.QPen(ring, 1.0))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 9, 9)

        self._paint_chevron(painter, rect, accent, text_color, lit)

        right = rect.right() - self._PAD_X
        right = self._paint_chip(painter, rect, right, accent)

        left = rect.left() + self._PAD_X + self._CHEVRON + self._GAP
        self._paint_title(painter, rect, left, right, text_color)
        painter.end()

    def _paint_chevron(self, painter, rect, accent, text_color, lit):
        cx = rect.left() + self._PAD_X + self._CHEVRON / 2.0
        cy = rect.center().y()
        arm = self._CHEVRON * 0.30
        color = QtGui.QColor(accent if lit else text_color)
        color.setAlpha(235 if lit else 150)
        pen = QtGui.QPen(color, 1.7)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._rotation)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        path = QtGui.QPainterPath()
        path.moveTo(-arm * 0.7, -arm * 1.25)
        path.lineTo(arm * 0.8, 0.0)
        path.lineTo(-arm * 0.7, arm * 1.25)
        painter.drawPath(path)
        painter.restore()

    def _paint_chip(self, painter, rect, right, accent):
        """Right-aligned pill listing the instances. Returns the new right edge
        available to the title."""
        if not self._chip:
            return right
        font = self._chip_font()
        fm = QtGui.QFontMetrics(font)
        width = self._chip_width()
        height = fm.height() + 5
        pill = QtCore.QRectF(right - width, rect.center().y() - height / 2.0,
                             width, height)
        overridden = self._override_count > 0
        bg = QtGui.QColor(accent)
        bg.setAlpha(48 if overridden else 26)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(pill, height / 2.0, height / 2.0)
        fg = QtGui.QColor(accent)
        fg.setAlpha(255 if overridden else 210)
        painter.setFont(font)
        painter.setPen(fg)
        painter.drawText(pill, int(QtCore.Qt.AlignmentFlag.AlignCenter),
                         self._chip)
        return right - width - self._GAP

    def _paint_title(self, painter, rect, left, right, text_color):
        available = max(0.0, right - left)
        name_font = QtGui.QFont(self.font())
        name_font.setBold(True)
        name_fm = QtGui.QFontMetrics(name_font)
        kind_fm = QtGui.QFontMetrics(self.font())
        kind_width = (kind_fm.horizontalAdvance(self._kind) + self._GAP
                      if self._kind else 0)

        name = name_fm.elidedText(
            self._name, QtCore.Qt.TextElideMode.ElideMiddle,
            int(max(0.0, available - kind_width)))
        painter.setFont(name_font)
        painter.setPen(text_color)
        name_width = name_fm.horizontalAdvance(name)
        painter.drawText(
            QtCore.QRectF(left, rect.top(), name_width, rect.height()),
            int(QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter),
            name)

        if not self._kind:
            return
        kind_left = left + name_width + self._GAP
        if kind_left + kind_fm.horizontalAdvance(self._kind) > right:
            return
        muted = QtGui.QColor(text_color)
        muted.setAlpha(140)
        painter.setFont(self.font())
        painter.setPen(muted)
        painter.drawText(
            QtCore.QRectF(kind_left, rect.top(), right - kind_left,
                          rect.height()),
            int(QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter),
            self._kind)


def finish_group_layout(layout):
    """Divide the whole tab between the group cards.

    Both tabs live in a QScrollArea with widgetResizable(True), so the tab
    widget is always at least as tall as the viewport. Giving every card row an
    equal stretch hands that height out card by card instead of letting it
    collect as one dead band at the bottom: each card is an outlined box that
    fills its share, with its header (and rows, when open) centred inside.

    Rows are sized as minimum-plus-an-equal-slice-of-what-is-left, so opening
    one card -- which raises that row's minimum -- squeezes the others to make
    way, and once the cards no longer fit, every row is already at its minimum
    and the tab simply scrolls."""
    for row in range(layout.rowCount()):
        layout.setRowStretch(row, 1)


# QWIDGETSIZE_MAX -- the "no cap" value to restore on QWidget.maximumHeight once
# the open animation finishes.
_UNCAPPED = 16777215

# Chevron travel: '>' when closed, 'v' when open.
_OPEN_ANGLE = 90.0

_KIND_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")


def _split_title(title):
    """'eSim_NPN  (Transistor)' -> ('eSim_NPN', 'Transistor'). The tabs already
    build the title this way; splitting it here lets the model name carry the
    weight and the kind sit back as a subtitle."""
    match = _KIND_RE.match(title or "")
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return (title or "").strip(), ""


def _chip_text(refs):
    """Short instance summary for the header pill. Long groups are truncated
    rather than allowed to shove the path field around -- the tooltip always
    lists every reference."""
    if not refs:
        return ""
    if len(refs) <= 4:
        return " · ".join(refs)
    return "%s · +%d" % (" · ".join(refs[:3]), len(refs) - 3)


def _duration(distance, expanding):
    """Scale the slide to the distance travelled.

    A fixed duration over a one-row span leaves the decelerating tail of
    OutCubic moving well under a pixel per frame, so the integer height holds
    for several frames and then jumps -- visible stutter. Tying the duration to
    the distance keeps every frame moving. Collapsing runs slightly quicker
    than expanding: closing something is an acknowledgement, not a reveal."""
    ceiling = 190 if expanding else 150
    return max(110, min(ceiling, int(60 + distance * 0.55)))


def _motion_enabled():
    """True only when the app's motion preference is on. Defaults to False (no
    animation, plain show/hide) if frontEnd isn't importable -- keeps headless
    tests on the synchronous path."""
    try:
        from frontEnd.motion import motion_enabled
        return motion_enabled()
    except Exception:
        return False
