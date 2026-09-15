"""Inline SVG icons used across eSim's UI.

Qt rasterises SVGs via QSvgRenderer. We expose them as QIcon()
factories so the same icons work in both QSS and toolbar slots, on
light and dark backgrounds.
"""
from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets


def _theme_icon_color(role="text"):
    app = QtWidgets.QApplication.instance()
    dark = True
    if app:
        dark = app.palette().color(QtGui.QPalette.ColorRole.Window).lightness() < 128
    if role == "accent":
        return "#53D7FF" if dark else "#0077A8"
    if role == "danger":
        return "#FB7185" if dark else "#E11D48"
    return "#F8FBFF" if dark else "#142033"


def _svg_icon(svg: str, size: int = 16, role="text") -> QtGui.QIcon:
    """Build a QIcon from inline SVG markup with theme-aware coloring.

    The SVG is rasterised at 256px rather than at its 24px viewBox: the
    toolbars ask for icons at ``28 * zoom`` px, which at 300% zoom is 84px --
    upscaling a 24px pixmap to that is visibly mushy, while downscaling a
    256px one stays crisp at every zoom level.
    """
    svg_colored = svg.replace("currentColor", _theme_icon_color(role))
    data = QtCore.QByteArray(svg_colored.encode('utf-8'))

    px = 256
    pixmap = QtGui.QPixmap(px, px)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    renderer = QtSvg.QSvgRenderer(data)
    if renderer.isValid():
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
    else:
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    icon = QtGui.QIcon()
    icon.addPixmap(pixmap)
    return icon


_REFRESH_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <polyline points="23 4 23 10 17 10"/>
  <polyline points="1 20 1 14 7 14"/>
  <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
</svg>
""".strip()


def refresh_icon(size: int = 16) -> QtGui.QIcon:
    return _svg_icon(_REFRESH_SVG, size)


_FULLSCREEN_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <polyline points="4 14 4 20 10 20"/>
  <polyline points="20 10 20 4 14 4"/>
  <line x1="4" y1="20" x2="11" y2="13"/>
  <line x1="13" y1="11" x2="20" y2="4"/>
</svg>
""".strip()


def fullscreen_icon(size: int = 14) -> QtGui.QIcon:
    return _svg_icon(_FULLSCREEN_SVG, size)


_DOCK_BACK_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <polyline points="10 4 4 4 4 10"/>
  <polyline points="14 20 20 20 20 14"/>
  <line x1="4" y1="4" x2="11" y2="11"/>
  <line x1="13" y1="13" x2="20" y2="20"/>
</svg>
""".strip()


def dock_back_icon(size: int = 14) -> QtGui.QIcon:
    return _svg_icon(_DOCK_BACK_SVG, size)


_COPY_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <rect x="9" y="9" width="11" height="11" rx="2" ry="2"/>
  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
</svg>
""".strip()


def copy_icon(size: int = 14) -> QtGui.QIcon:
    return _svg_icon(_COPY_SVG, size)


_CLOSE_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <line x1="6" y1="6" x2="18" y2="18"/>
  <line x1="18" y1="6" x2="6" y2="18"/>
</svg>
""".strip()


def close_icon(size: int = 14) -> QtGui.QIcon:
    return _svg_icon(_CLOSE_SVG, size, role="danger")


_WORKSPACE_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
  <line x1="8" y1="21" x2="16" y2="21"/>
  <line x1="12" y1="17" x2="12" y2="21"/>
</svg>
""".strip()


def workspace_icon(size: int = 16) -> QtGui.QIcon:
    return _svg_icon(_WORKSPACE_SVG, size)


_BACKUP_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
  <polyline points="17 21 17 13 7 13 7 21"/>
  <polyline points="7 3 7 8 15 8"/>
</svg>
""".strip()


def backup_icon(size: int = 16) -> QtGui.QIcon:
    return _svg_icon(_BACKUP_SVG, size)


_TIMELINE_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="10"/>
  <polyline points="12 6 12 12 16 14"/>
</svg>
""".strip()


def timeline_icon(size: int = 16) -> QtGui.QIcon:
    return _svg_icon(_TIMELINE_SVG, size)


_CLOSE_PROJ_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>
  <line x1="9" x2="15" y1="13" y2="13"/>
</svg>
""".strip()


def close_proj_icon(size: int = 16) -> QtGui.QIcon:
    return _svg_icon(_CLOSE_PROJ_SVG, size)


_HELP_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="10"/>
  <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
  <line x1="12" x2="12.01" y1="17" y2="17"/>
</svg>
""".strip()


def help_icon(size: int = 16) -> QtGui.QIcon:
    return _svg_icon(_HELP_SVG, size)


_DEV_DOCS_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <polyline points="16 18 22 12 16 6"/>
  <polyline points="8 6 2 12 8 18"/>
</svg>
""".strip()


def dev_docs_icon(size: int = 16) -> QtGui.QIcon:
    return _svg_icon(_DEV_DOCS_SVG, size)


_SETTINGS_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
  <circle cx="12" cy="12" r="3"/>
</svg>
""".strip()


def settings_icon(size: int = 16) -> QtGui.QIcon:
    return _svg_icon(_SETTINGS_SVG, size)


_HOME_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>
</svg>
""".strip()


def home_icon(size: int = 16) -> QtGui.QIcon:
    return _svg_icon(_HOME_SVG, size)


_THEME_TOGGLE_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="10"/>
  <path d="M12 2a10 10 0 0 1 0 20z" fill="currentColor" stroke="none"/>
</svg>
""".strip()


def theme_toggle_icon(size: int = 16) -> QtGui.QIcon:
    return _svg_icon(_THEME_TOGGLE_SVG, size)


_FOLDER_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>
</svg>
""".strip()


def folder_icon(size: int = 16) -> QtGui.QIcon:
    """Project-folder icon. Replaces SP_DirIcon, which resolves to the OS
    shell folder (yellow Explorer folder on Windows, icon-theme folder on
    Linux) and so never matched the design on either platform."""
    return _svg_icon(_FOLDER_SVG, size, role="accent")


_FILE_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
  <polyline points="14 2 14 8 20 8"/>
</svg>
""".strip()


def file_icon(size: int = 16) -> QtGui.QIcon:
    """Plain file icon. Replaces the platform-divergent SP_FileIcon."""
    return _svg_icon(_FILE_SVG, size)


_TRASH_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <polyline points="3 6 5 6 21 6"/>
  <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
  <line x1="10" y1="11" x2="10" y2="17"/>
  <line x1="14" y1="11" x2="14" y2="17"/>
</svg>
""".strip()


def trash_icon(size: int = 16) -> QtGui.QIcon:
    """Delete/remove icon. Replaces the platform-divergent SP_TrashIcon."""
    return _svg_icon(_TRASH_SVG, size, role="danger")


_SNAPSHOT_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/>
  <circle cx="12" cy="13" r="4"/>
</svg>
""".strip()


def snapshot_icon(size: int = 16) -> QtGui.QIcon:
    """Snapshot (camera) icon. Replaces SP_DriveHDIcon, which showed the OS
    hard-drive glyph and read as 'disk', not 'snapshot'."""
    return _svg_icon(_SNAPSHOT_SVG, size)
