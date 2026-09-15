from PyQt6 import QtWidgets, QtGui, QtCore
import os


def _prepare_msg(msg, kind):
    msg.setObjectName("esimMessageBox")
    msg.setProperty("messageKind", kind)
    try:
        from frontEnd.motion import apply_popup_depth
        apply_popup_depth(msg)
    except Exception:
        pass


def show_error(parent, title, message):
    msg = QtWidgets.QMessageBox(parent)
    msg.setIcon(QtWidgets.QMessageBox.Icon.Critical)
    msg.setWindowTitle(title)
    msg.setText(message)
    _prepare_msg(msg, "error")
    msg.exec()


def show_warning(parent, title, message):
    msg = QtWidgets.QMessageBox(parent)
    msg.setIcon(QtWidgets.QMessageBox.Icon.Warning)
    msg.setWindowTitle(title)
    msg.setText(message)
    _prepare_msg(msg, "warning")
    msg.exec()


def show_info(parent, title, message):
    msg = QtWidgets.QMessageBox(parent)
    msg.setIcon(QtWidgets.QMessageBox.Icon.Information)
    msg.setWindowTitle(title)
    msg.setText(message)
    _prepare_msg(msg, "info")
    msg.exec()


def ask_question(parent, title, message):
    # Build the box the same way show_warning/show_info do (QMessageBox(parent)
    # + _prepare_msg) rather than the static QMessageBox.question() — the
    # static call is a parentless top-level window and is banned by the
    # dialog-hygiene guard (configuration/tests/test_dialog_hygiene.py).
    msg = QtWidgets.QMessageBox(parent)
    msg.setIcon(QtWidgets.QMessageBox.Icon.Question)
    msg.setWindowTitle(title)
    msg.setText(message)
    msg.setStandardButtons(
        QtWidgets.QMessageBox.StandardButton.Yes
        | QtWidgets.QMessageBox.StandardButton.No)
    msg.setDefaultButton(QtWidgets.QMessageBox.StandardButton.No)
    _prepare_msg(msg, "question")
    return msg.exec() == QtWidgets.QMessageBox.StandardButton.Yes


# Persisted across runs in the shared QSettings store. When the user ticks
# "Remember my choice" the popup is skipped on every later simulation and the
# saved answer is reused. It can be re-enabled from Preferences ▸ Simulation
# ("Ask before generating Ngspice plots").
NGSPICE_REMEMBER_KEY = "ngspicePlots/remember"
NGSPICE_FLAG_KEY = "ngspicePlots/flag"


def ask_ngspice_plots(parent):
    """Return whether to also generate native ngspice plots for this run.

    If the user previously chose "Remember my choice", reuse the stored answer
    silently. Otherwise show the Yes/No popup (with a remember checkbox) and
    persist the decision when the box is ticked. Shared by
    Application.plotFlagPopBox and TerminalUi's redo path so the popup and its
    QSettings keys live in exactly one place.
    """
    settings = QtCore.QSettings('eSim', 'eSim')
    if settings.value(NGSPICE_REMEMBER_KEY, False, type=bool):
        return settings.value(NGSPICE_FLAG_KEY, False, type=bool)

    msg_box = QtWidgets.QMessageBox(parent)
    msg_box.setWindowTitle("Ngspice Plots")
    msg_box.setText("Do you want Ngspice plots?")
    # Widen the message label so the window title is not clipped behind the
    # close/minimise/maximise buttons on tight window managers. QMessageBox
    # ignores setMinimumWidth, so size via the label.
    msg_box.setStyleSheet("QLabel { min-width: 360px; }")

    remember_cb = QtWidgets.QCheckBox(
        "Remember my choice (re-enable in Preferences ▸ Simulation)")
    msg_box.setCheckBox(remember_cb)

    yes_button = msg_box.addButton(
        "Yes", QtWidgets.QMessageBox.ButtonRole.YesRole)
    msg_box.addButton("No", QtWidgets.QMessageBox.ButtonRole.NoRole)

    msg_box.exec()
    flag = msg_box.clickedButton() == yes_button

    if remember_cb.isChecked():
        settings.setValue(NGSPICE_REMEMBER_KEY, True)
        settings.setValue(NGSPICE_FLAG_KEY, flag)

    return flag


ESIM_VERSION = "2.6.0"


def _about_palette(parent):
    """Theme-aware colour set for the About surfaces. Restrained, on-brand —
    a single quiet accent, neutral chip for the (warm bronze) logo, no loud
    full-saturation gradient."""
    dark = parent.palette().color(
        QtGui.QPalette.ColorRole.Window).lightness() < 128
    if dark:
        return dict(
            dark=True,
            page="#0E1728", header="#121E33",
            chip="#0A1220", chip_border="rgba(255,255,255,0.10)",
            title="#F4F8FF", muted="#9FB1CC", subtle="#6C7F99",
            accent="#53D7FF", link="#8BEAFF",
            sep="rgba(255,255,255,0.08)",
            pill_bg="rgba(83,215,255,0.14)", pill_fg="#8BEAFF",
        )
    return dict(
        dark=False,
        page="#FFFFFF", header="#F5F8FC",
        chip="#FFFFFF", chip_border="rgba(20,32,51,0.12)",
        title="#142033", muted="#5A6E89", subtle="#9AAABE",
        accent="#0077A8", link="#0077A8",
        sep="rgba(20,32,51,0.08)",
        pill_bg="rgba(0,119,168,0.10)", pill_fg="#0077A8",
    )


def _logo_chip(icon_path, c, size=76, logo_px=48):
    """Bronze eSim coin inside a clean neutral rounded chip so its warm tone
    reads cleanly on any theme — fixes the coin-on-cyan clash + opaque band."""
    from frontEnd.theme_utils import zoom_px
    size, logo_px = zoom_px(size), zoom_px(logo_px)
    chip = QtWidgets.QLabel()
    chip.setFixedSize(size, size)
    chip.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    chip.setStyleSheet(
        f"background: {c['chip']}; border: 1px solid {c['chip_border']}; "
        f"border-radius: {size // 2}px;")
    if os.path.exists(icon_path):
        pix = QtGui.QPixmap(icon_path).scaled(
            logo_px, logo_px, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation)
        chip.setPixmap(pix)
    return chip


def _about_header(icon_path, c, rounded=False):
    """Quiet header band: thin accent hairline, logo chip, wordmark, tagline.
    No gradient — structure comes from a subtle raised surface + accent rule.
    ``rounded`` frames it as a standalone card (used in the Preferences tab)."""
    header = QtWidgets.QWidget()
    header.setObjectName("aboutHeader")
    if rounded:
        header.setStyleSheet(
            f"#aboutHeader {{ background: {c['header']}; "
            f"border: 1px solid {c['sep']}; border-radius: 12px; }}")
    else:
        header.setStyleSheet(
            f"#aboutHeader {{ background: {c['header']}; "
            f"border-bottom: 1px solid {c['sep']}; }}")
    outer = QtWidgets.QVBoxLayout(header)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    rule = QtWidgets.QWidget()
    rule.setFixedHeight(3)
    rule.setStyleSheet(f"background: {c['accent']};")
    outer.addWidget(rule)

    body = QtWidgets.QVBoxLayout()
    body.setContentsMargins(28, 22, 28, 20)
    body.setSpacing(8)
    body.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)

    chip = _logo_chip(icon_path, c)
    body.addWidget(chip, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

    # Sizes here are *design* sizes at 100%; scale_font takes them through the
    # same text curve the stylesheet uses, so the About card zooms with the
    # rest of the UI instead of staying frozen at 22pt/9pt.
    from frontEnd.theme_utils import scale_font

    title = QtWidgets.QLabel("eSim")
    title.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
    tf = title.font()
    tf.setPointSize(22)
    tf.setWeight(QtGui.QFont.Weight.Black)
    title.setFont(scale_font(tf))
    title.setStyleSheet(f"color: {c['title']}; background: transparent;")
    body.addWidget(title)

    tagline = QtWidgets.QLabel("Open Source EDA for Circuit Design")
    tagline.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
    gf = tagline.font()
    gf.setPointSize(9)
    tagline.setFont(scale_font(gf))
    tagline.setStyleSheet(f"color: {c['muted']}; background: transparent;")
    body.addWidget(tagline)

    outer.addLayout(body)
    return header


def show_about_dialog(parent):
    """About eSim — a calm, on-brand card: neutral logo chip, quiet accent
    header (no loud gradient), correct version, product blurb and credits."""
    from frontEnd.theme_utils import zoom_px
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("About eSim")
    # A *fixed* size has to move with zoom or the card simply crops its own
    # contents at anything above 100%.
    dlg.setFixedSize(zoom_px(440), zoom_px(500))
    dlg.setObjectName("aboutDialog")

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    icon_path = os.path.join(base_dir, 'images', 'logo.png')
    if os.path.exists(icon_path):
        dlg.setWindowIcon(QtGui.QIcon(icon_path))

    c = _about_palette(parent)
    dlg.setStyleSheet(f"#aboutDialog {{ background: {c['page']}; }}")

    root = QtWidgets.QVBoxLayout(dlg)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    root.addWidget(_about_header(icon_path, c))

    # ── Content ──────────────────────────────────────────────────
    content = QtWidgets.QWidget()
    content_layout = QtWidgets.QVBoxLayout(content)
    content_layout.setContentsMargins(28, 22, 28, 20)
    content_layout.setSpacing(12)

    version = QtWidgets.QLabel(f"Version {ESIM_VERSION}")
    version.setStyleSheet(
        f"color: {c['pill_fg']}; background: {c['pill_bg']}; "
        f"border-radius: 10px; padding: 4px 12px; font-weight: 700;")
    version.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum,
                          QtWidgets.QSizePolicy.Policy.Fixed)
    content_layout.addWidget(version, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

    desc = QtWidgets.QLabel(
        "Circuit design, simulation, analysis and PCB layout in a single "
        "integrated environment — built on KiCad and ngspice.")
    desc.setWordWrap(True)
    desc.setStyleSheet(f"color: {c['muted']}; font-size: 13px;")
    content_layout.addWidget(desc)

    content_layout.addSpacing(2)

    sep = QtWidgets.QWidget()
    sep.setFixedHeight(1)
    sep.setStyleSheet(f"background: {c['sep']};")
    content_layout.addWidget(sep)

    content_layout.addSpacing(2)

    org = QtWidgets.QLabel("FOSSEE, IIT Bombay")
    org.setStyleSheet(
        f"color: {c['title']}; font-size: 14px; font-weight: 650; "
        "background: transparent;")
    content_layout.addWidget(org)

    website = QtWidgets.QLabel(
        f'<a href="https://esim.fossee.in" '
        f'style="color: {c["link"]}; text-decoration: none;">esim.fossee.in</a>')
    website.setOpenExternalLinks(True)
    website.setStyleSheet("font-size: 12px; background: transparent;")
    content_layout.addWidget(website)

    content_layout.addSpacing(4)

    credits = QtWidgets.QLabel(
        "Originally created by Fahim Khan\n"
        "Maintained by the eSim team at FOSSEE")
    credits.setWordWrap(True)
    credits.setStyleSheet(
        f"color: {c['subtle']}; font-size: 11px; background: transparent;")
    content_layout.addWidget(credits)

    content_layout.addStretch()

    btn_row = QtWidgets.QHBoxLayout()
    btn_row.addStretch()
    close_btn = QtWidgets.QPushButton("Close")
    close_btn.setProperty("cssClass", "secondary")
    close_btn.setFixedWidth(zoom_px(100))
    close_btn.clicked.connect(dlg.accept)
    btn_row.addWidget(close_btn)
    content_layout.addLayout(btn_row)

    root.addWidget(content, 1)

    for fn in ("apply_popup_depth", "install_button_motion"):
        try:
            mod = __import__("frontEnd.motion", fromlist=[fn])
            getattr(mod, fn)(dlg)
        except Exception:
            pass

    dlg.exec()
