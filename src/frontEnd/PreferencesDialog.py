import os
from PyQt6 import QtWidgets, QtGui, QtCore

from configuration.Appconfig import Appconfig


class PreferencesDialog(QtWidgets.QDialog):
    """User-facing application preferences.

    Deliberately minimal — a focused settings surface, not a customization
    playground:

        * **General** — display mode (Auto / Light / Dark), interface
          animation toggle, and the Ngspice simulation-plot prompt.
        * **About**   — product blurb.

    Theme colors (accent, window/panel tints) and editor fonts are intentionally
    NOT user-configurable: the app ships one carefully-tuned light and dark
    palette. The persisted accent/surface keys are pinned to their defaults so
    the shared theme engine (``theme_utils`` / ngspice ``_palette``) keeps
    resolving them to the built-in colors.

    Live updates: changes apply to the running app immediately; Cancel reverts
    to the snapshot taken when the dialog opened.
    """

    def __init__(self, parent=None):
        super().__init__(None)
        self.appconfig = Appconfig()
        self.prefs = self.appconfig.load_preferences()
        # Snapshot for Cancel revert (live-apply changes the running theme).
        self._orig_prefs = dict(self.prefs)

        self.setWindowTitle("Preferences")
        self.setWindowFlags(
            QtCore.Qt.WindowType.Dialog
            | QtCore.Qt.WindowType.WindowTitleHint
            | QtCore.Qt.WindowType.WindowCloseButtonHint
        )

        icon_path = self._find_icon()
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QtGui.QIcon(icon_path))

        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.setObjectName('preferencesDialog')

        self._build_ui()
        self._load_into_widgets()

        from frontEnd.motion import install_button_motion
        install_button_motion(self)

    def changeEvent(self, event):
        """Re-tint the header gear when the theme changes under an open dialog.

        This dialog is the theme switch itself, so applying a new theme with it
        still open must not leave the baked-color gear behind (settings_icon()
        renders the SVG at the theme color once).
        """
        super().changeEvent(event)
        # Deferred by a tick: rasterising the SVG inside the handler re-enters
        # the polish that delivered the event (theme_utils.defer_restyle).
        if event.type() == QtCore.QEvent.Type.PaletteChange \
                and getattr(self, "_icon_label", None) is not None:
            from frontEnd.theme_utils import defer_restyle
            defer_restyle(self, self._retint_header_icon)

    def _retint_header_icon(self):
        """Deferred body of the PaletteChange branch of changeEvent."""
        try:
            from frontEnd.icon_paths import settings_icon
            self._icon_label.setPixmap(settings_icon(28).pixmap(28, 28))
        except Exception:
            pass

    # ------------------------------------------------------------------ build
    def _build_ui(self):
        self.setMinimumSize(600, 460)
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 20, 20, 20)

        # Header (themed gear icon + solid-colour title).
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        # Held on self so changeEvent can re-tint it: settings_icon() bakes the
        # theme color into the SVG once, and this dialog is itself the theme
        # switch — applying a new theme with the dialog still open would leave a
        # stale-colored gear otherwise.
        self._icon_label = QtWidgets.QLabel()
        # Same themed SVG gear as the Preferences action in the top toolbar so
        # the header icon matches the toolbar and tracks the theme colour.
        try:
            from frontEnd.icon_paths import settings_icon
            self._icon_label.setPixmap(settings_icon(28).pixmap(28, 28))
        except Exception:
            icon_path = self._find_icon()
            if icon_path and os.path.exists(icon_path):
                pixmap = QtGui.QPixmap(icon_path).scaled(
                    32, 32,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                self._icon_label.setPixmap(pixmap)
        header = QtWidgets.QLabel("Preferences")
        header.setProperty("cssClass", "title")
        header_layout.addWidget(self._icon_label)
        header_layout.addWidget(header)
        header_layout.addStretch()
        root.addLayout(header_layout)

        # Body: left nav rail + stacked pages (settings-app pattern).
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(14)
        self.nav = QtWidgets.QListWidget()
        self.nav.setObjectName('prefsNav')
        # Fixed width + a font that grows with zoom = clipped category names.
        from frontEnd.theme_utils import zoom_px
        self.nav.setFixedWidth(zoom_px(150))
        self.nav.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        for label in ("General", "About"):
            QtWidgets.QListWidgetItem(label, self.nav)

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self._build_general_page())
        self.stack.addWidget(self._build_about_page())
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        # Re-validate drop-shadow effects when a page is re-shown, otherwise
        # buttons on a previously-hidden page can paint blank (until hovered)
        # after a stack switch while the dialog is maximized/fullscreen.
        self.stack.currentChanged.connect(self._on_pref_page_changed)
        self.nav.setCurrentRow(0)

        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        # Footer — live-apply means a single primary 'Done'. Reset is the one
        # power-user affordance on the left.
        footer = QtWidgets.QHBoxLayout()
        self.btn_reset = QtWidgets.QPushButton("Reset to Defaults")
        self.btn_reset.setProperty("cssClass", "tertiary")
        self.btn_reset.setToolTip("Restore every preference to its factory default.")
        self.btn_reset.clicked.connect(self._reset_to_defaults_live)

        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.setProperty("cssClass", "secondary")
        self.btn_cancel.setToolTip("Discard changes made in this session.")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_done = QtWidgets.QPushButton("Done")
        self.btn_done.setDefault(True)
        self.btn_done.setToolTip("Keep changes and close.")
        self.btn_done.clicked.connect(self._save_and_close)

        footer.addWidget(self.btn_reset)
        footer.addStretch()
        footer.addWidget(self.btn_cancel)
        footer.addWidget(self.btn_done)
        root.addLayout(footer)

    def _on_pref_page_changed(self, idx):
        """Refresh graphics effects on the newly shown page (and once more on
        the next tick, after layout/expose settles) so buttons never render
        blank after a stack switch in maximized/fullscreen state."""
        try:
            from frontEnd.elevation import refresh_effects
            page = self.stack.widget(idx)
            refresh_effects(page)
            QtCore.QTimer.singleShot(
                0, lambda p=page: refresh_effects(p))
        except Exception:
            pass

    def _build_general_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        v = QtWidgets.QVBoxLayout(page)
        v.setSpacing(16)
        v.setContentsMargins(8, 16, 8, 8)

        # ── Section: Appearance ──────────────────────────────────────
        theme_group = QtWidgets.QGroupBox("Appearance")
        theme_group.setProperty("cssClass", "themedGroupBox")
        theme_gl = QtWidgets.QVBoxLayout(theme_group)
        theme_gl.setSpacing(6)

        # Hidden combo retained as the data model so the segment logic
        # (findData/currentData) stays simple; the visible UI is a segmented
        # control.
        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.setVisible(False)
        for label, key in [
            ("Follow operating system", "System"),
            ("Always light",           "Light"),
            ("Always dark",            "Dark"),
        ]:
            self.theme_combo.addItem(label, key)

        from frontEnd.theme_utils import zoom_px
        seg = QtWidgets.QWidget()
        segh = QtWidgets.QHBoxLayout(seg)
        segh.setContentsMargins(0, 0, 0, 0)
        segh.setSpacing(0)
        self._theme_btns = {}
        for key, lbl in [("System", "Auto"), ("Light", "Light"), ("Dark", "Dark")]:
            b = QtWidgets.QPushButton(lbl)
            b.setCheckable(True)
            b.setProperty("cssClass", "segmentBtn")
            b.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            b.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed,
                            QtWidgets.QSizePolicy.Policy.Fixed)
            b.setMinimumWidth(zoom_px(96))
            b.clicked.connect(lambda _c=False, k=key: self._set_theme_mode(k))
            self._theme_btns[key] = b
            segh.addWidget(b)
        # Trailing stretch so the segment stays a compact group on the left
        # instead of each button expanding to fill (and overflowing) the row.
        segh.addStretch(1)

        theme_help = QtWidgets.QLabel(
            "eSim will automatically match your OS theme, or you can force "
            "light or dark."
        )
        theme_help.setProperty("cssClass", "subtle")
        theme_help.setWordWrap(True)
        theme_gl.addWidget(seg)
        theme_gl.addWidget(self.theme_combo)
        theme_gl.addWidget(theme_help)
        v.addWidget(theme_group)

        # ── Section: Interface Animation ─────────────────────────────
        motion_group = QtWidgets.QGroupBox("Interface Animation")
        motion_group.setProperty("cssClass", "themedGroupBox")
        motion_gl = QtWidgets.QVBoxLayout(motion_group)
        motion_gl.setSpacing(10)
        self.motion_checkbox = QtWidgets.QCheckBox(
            "Enable button glow animations")
        self.motion_checkbox.setToolTip(
            "Animated hover/press glows on buttons and dialogs. Turn off to "
            "reduce motion or save power; takes effect the next time a dialog "
            "opens.")
        motion_gl.addWidget(self.motion_checkbox)
        v.addWidget(motion_group)

        # ── Section: Simulation ──────────────────────────────────────
        # The "Do you want Ngspice plots?" popup shown before every simulation
        # can be silenced from its own checkbox; this toggle is the documented
        # way to bring it back.
        sim_group = QtWidgets.QGroupBox("Simulation")
        sim_group.setProperty("cssClass", "themedGroupBox")
        sim_gl = QtWidgets.QVBoxLayout(sim_group)
        sim_gl.setSpacing(10)
        self.ngspice_prompt_checkbox = QtWidgets.QCheckBox(
            "Ask before generating Ngspice plots")
        self.ngspice_prompt_checkbox.setToolTip(
            "Show the \"Do you want Ngspice plots?\" popup before each "
            "simulation. Untick to stop asking and reuse your last answer.")
        sim_gl.addWidget(self.ngspice_prompt_checkbox)
        v.addWidget(sim_group)

        v.addStretch(1)

        wrapper = QtWidgets.QVBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(scroll)
        container = QtWidgets.QWidget()
        container.setLayout(wrapper)
        return container

    def _build_about_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(8, 16, 8, 8)
        v.setSpacing(14)

        # Reuse the About dialog's calm, on-brand header (neutral logo chip,
        # thin accent rule, wordmark) so both About surfaces match — no loud
        # gradient, no coin-on-cyan clash.
        try:
            from frontEnd import dialogs
            c = dialogs._about_palette(self)
            icon_path = self._logo_icon_path()
            header = dialogs._about_header(icon_path, c, rounded=True)
            v.addWidget(header)

            version = QtWidgets.QLabel(f"Version {dialogs.ESIM_VERSION}")
            version.setStyleSheet(
                f"color: {c['pill_fg']}; background: {c['pill_bg']}; "
                f"border-radius: 10px; padding: 4px 12px; font-weight: 700;")
            version.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum,
                                  QtWidgets.QSizePolicy.Policy.Fixed)
            v.addWidget(version, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass

        info = QtWidgets.QLabel(
            "Circuit design, simulation, analysis and PCB layout in a single "
            "integrated environment — built on KiCad and ngspice.\n\n"
            "FOSSEE, IIT Bombay · esim.fossee.in"
        )
        info.setWordWrap(True)
        info.setProperty("cssClass", "muted")
        v.addWidget(info)
        v.addStretch(1)
        return page

    def _logo_icon_path(self):
        here = os.path.dirname(os.path.abspath(__file__))
        p = os.path.normpath(os.path.join(here, "..", "..", "images", "logo.png"))
        return p

    # ------------------------------------------------------------------ helpers
    def _find_icon(self):
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "..", "..", "images", "preferences.png"),
            os.path.abspath("images/preferences.png"),
        ]
        for p in candidates:
            p = os.path.normpath(p)
            if os.path.exists(p):
                return p
        return None

    # ------------------------------------------------------------------ theme segment
    def _set_theme_mode(self, key):
        idx = self.theme_combo.findData(key)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self._sync_theme_segment()
        self._live_apply()

    def _sync_theme_segment(self):
        if not hasattr(self, "_theme_btns"):
            return
        cur = self.theme_combo.currentData()
        for k, b in self._theme_btns.items():
            b.setChecked(k == cur)

    # ------------------------------------------------------------------ live apply
    def _live_apply(self):
        """Debounced re-theme so the running app updates as the user tweaks."""
        if not hasattr(self, "_live_timer"):
            self._live_timer = QtCore.QTimer(self)
            self._live_timer.setSingleShot(True)
            self._live_timer.setInterval(160)
            self._live_timer.timeout.connect(self._apply_preferences)
        self._live_timer.start()

    def _reset_to_defaults_live(self):
        self._reset_to_defaults()
        self._sync_theme_segment()
        self._live_apply()

    def reject(self):
        """Cancel reverts to the snapshot taken when the dialog opened.

        If nothing actually changed during the session (the common "open then
        immediately close/X" case), DON'T re-apply the theme: a needless
        re-polish nudges the toolbars slightly larger. Only revert + re-theme
        when the live preview actually diverged from the opening snapshot.
        """
        try:
            from configuration import paths
            path = paths.esim_config_path("preferences.json")
            try:
                with open(path, "r") as f:
                    current = json_load(f)
            except Exception:
                current = {}
            keys = ("theme_mode", "accent_color", "secondary_accent_color",
                    "internal_bg_color", "enable_motion")
            # Compare only keys actually present on disk: _orig_prefs is the
            # normalized (defaults-filled) snapshot, while the file holds only
            # explicitly-saved keys, so a plain compare would see phantom diffs.
            changed = any(k in current and current.get(k) != self._orig_prefs.get(k)
                          for k in keys)
            if changed:
                self.appconfig.save_preferences(
                    self._orig_prefs.get("theme_mode", "System"),
                    self._orig_prefs.get("accent_color", "default"),
                    self._orig_prefs.get("secondary_accent_color", "system"),
                    self._orig_prefs.get("internal_bg_color", "system"),
                )
                with open(path, "r") as f:
                    existing = json_load(f)
                existing.update(self._orig_prefs)
                with open(path, "w") as f:
                    json_dump(existing, f)
                app = QtWidgets.QApplication.instance()
                fn = getattr(app, "apply_theme", None)
                if callable(fn):
                    fn()
        except Exception as exc:
            print("Preferences cancel-revert failed:", exc)
        super().reject()

    # ------------------------------------------------------------------ loaders
    def _load_into_widgets(self):
        mode = self.prefs.get("theme_mode", "System")
        idx = self.theme_combo.findData(mode)
        if idx < 0:
            idx = 0
        self.theme_combo.setCurrentIndex(idx)
        self._sync_theme_segment()

        self.motion_checkbox.setChecked(
            bool(self.prefs.get("enable_motion", True)))
        # Persist the motion toggle; install happens next dialog open.
        self.motion_checkbox.toggled.connect(lambda *_: self._live_apply())

        # "Ask before generating Ngspice plots" lives in the shared QSettings
        # store (same keys TerminalUi reads), not preferences.json — checked
        # means "keep asking" (i.e. the remember flag is NOT set).
        sim_settings = QtCore.QSettings('eSim', 'eSim')
        self.ngspice_prompt_checkbox.setChecked(
            not sim_settings.value('ngspicePlots/remember', False, type=bool))
        self.ngspice_prompt_checkbox.toggled.connect(
            self._on_ngspice_prompt_toggled)

    def _on_ngspice_prompt_toggled(self, ask):
        """Sync the Ngspice-plot prompt preference into the shared QSettings.

        Checked  → clear the remember flag so the popup is shown every run.
        Unchecked→ set remember so later runs reuse the saved answer (keeping
        any answer the user already stored; defaults to no extra plots).
        """
        settings = QtCore.QSettings('eSim', 'eSim')
        if ask:
            settings.setValue('ngspicePlots/remember', False)
        else:
            settings.setValue('ngspicePlots/remember', True)
            if settings.value('ngspicePlots/flag', None) is None:
                settings.setValue('ngspicePlots/flag', False)

    # ------------------------------------------------------------------ actions
    def _reset_to_defaults(self):
        self.theme_combo.setCurrentIndex(self.theme_combo.findData("System"))
        self.motion_checkbox.setChecked(True)
        # Clear the "remember my answer" flag so plots prompt every run again.
        self.ngspice_prompt_checkbox.setChecked(True)

    def _collect_prefs(self) -> dict:
        # Accent + surface colors are no longer user-configurable; pin them to
        # the sentinels the theme engine resolves to the built-in palette. This
        # also normalizes away any custom colors left over from older versions.
        return {
            "theme_mode":             self.theme_combo.currentData(),
            "accent_color":           "default",
            "secondary_accent_color": "system",
            "internal_bg_color":      "system",
            "enable_motion":          self.motion_checkbox.isChecked(),
        }

    def _apply_preferences(self):
        prefs = self._collect_prefs()
        self.appconfig.save_preferences(
            prefs["theme_mode"],
            prefs["accent_color"],
            prefs["secondary_accent_color"],
            prefs["internal_bg_color"],
        )
        try:
            from configuration import paths
            path = paths.esim_config_path("preferences.json")
            existing = {}
            if os.path.exists(path):
                with open(path, "r") as f:
                    existing = json_load(f)
            existing.update(prefs)
            paths.write_json_atomic(path, existing)
        except Exception:
            pass

        # enable_motion just changed on disk; drop motion's cached read so the
        # theme re-apply below wires (or skips) glows per the new value.
        try:
            from frontEnd.motion import invalidate_motion_cache
            invalidate_motion_cache()
        except Exception:
            pass

        app = QtWidgets.QApplication.instance()
        fn = getattr(app, "apply_theme", None)
        if callable(fn):
            try:
                fn()
            except Exception as exc:
                print("apply_theme failed:", exc)

        for w in QtWidgets.QApplication.topLevelWidgets():
            if hasattr(w, "update_theme_styles"):
                try:
                    w.update_theme_styles()
                except Exception:
                    pass

    def _save_and_close(self):
        self._apply_preferences()
        self.accept()


import json as _json


def json_load(fp):
    return _json.load(fp)


def json_dump(data, fp):
    return _json.dump(data, fp, indent=2)
