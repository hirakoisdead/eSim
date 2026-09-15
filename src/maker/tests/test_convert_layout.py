"""The Convert stage must fit its dock, because a scrolled Convert stage hides
the one thing the user is waiting for.

The page is mounted behind a QScrollArea (FlowNavigator._scroll). A panel's
layout minimum is a hard floor: once it exceeds the dock's height the page
scrolls, and the build progress bar -- which lives under the console -- goes
below the fold. Someone who has just pressed Convert then sees nothing move,
has no reason to suspect this page scrolls at all, and concludes the click did
nothing. (Scrolling with the wheel over the console scrolls the console
instead, which makes it worse.)

So the floor is tested directly, at the smallest dock height eSim is expected
to survive: 1080p at 150% Windows scaling leaves ~672 logical pixels of
desktop, and the dock gets a fraction of that.
"""
import pytest

from PyQt6 import QtWidgets

#: The convert page must fit in this, with the dock chrome and the eSim menu /
#: toolbar / status bar already taken out of a 672px-tall workspace.
MAX_MIN_HEIGHT = 460


@pytest.fixture
def convert(qapp):
    from maker import NgVeri
    w = NgVeri.NgVeri(0)
    yield w
    w.close()
    w.deleteLater()


def test_the_page_fits_a_short_dock_without_scrolling(convert, qapp):
    convert.resize(700, MAX_MIN_HEIGHT)
    floor = convert.minimumSizeHint().height()
    assert floor <= MAX_MIN_HEIGHT, (
        "the convert page needs %dpx but only %dpx is guaranteed -- it will "
        "scroll, and the build progress bar goes below the fold"
        % (floor, MAX_MIN_HEIGHT))


def test_the_method_explainer_is_folded_away_by_default(convert, qapp):
    """It is a paragraph in a 210px column: ~250px of MINIMUM height, which is
    what made the page scroll. Folded, it costs one row and is one click from
    being read."""
    # isHidden(), not isVisible(): the page itself is not on screen in a test,
    # which would make isVisible() False either way and assert nothing.
    assert convert.convertHintToggle.isChecked() is False
    assert convert.convertHint.isHidden() is True


def test_expanding_the_explainer_shows_it(convert, qapp):
    convert.convertHintToggle.setChecked(True)
    assert convert.convertHint.isHidden() is False
    convert.convertHintToggle.setChecked(False)
    assert convert.convertHint.isHidden() is True


def test_the_subject_line_shares_the_heading_row(convert, qapp):
    """One row, not three: the heading and what-will-be-built sit side by
    side."""
    heading = None
    for label in convert.optionsbox.findChildren(QtWidgets.QLabel):
        if label.text() == "Convert Verilog to Ngspice":
            heading = label
            break
    assert heading is not None
    assert convert.subjectLabel.parentWidget() is heading.parentWidget()


def test_starting_a_build_scrolls_the_progress_bar_into_view(convert, qapp):
    """Belt and braces for the dock sizes where it cannot fit: the bar brings
    itself into view rather than relying on the user to find it."""
    area = QtWidgets.QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(convert)
    area.resize(700, 200)
    area.show()
    qapp.processEvents()

    convert._show_build_progress(True, "Building…")
    qapp.processEvents()

    bar_top = convert.buildBar.mapTo(convert, convert.buildBar.rect().topLeft())
    viewport = area.viewport().rect()
    visible_top = area.verticalScrollBar().value()
    assert convert.buildBar.isVisible()
    assert bar_top.y() + convert.buildBar.height() <= \
        visible_top + viewport.height() + 1
    area.close()
    area.deleteLater()
