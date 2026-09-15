"""Tests for the shared dialogs.ask_ngspice_plots helper.

Application.plotFlagPopBox and TerminalUi._resolveNgspicePlotChoice were
verbatim copies of the same Yes/No popup + "remember my choice" persistence.
They now both delegate to dialogs.ask_ngspice_plots. These exercise the
remember-short-circuit path, which returns without ever popping a dialog, so
the shared helper's stored-answer behaviour is asserted directly.
"""
import pytest

from frontEnd import dialogs


class _FakeSettings:
    """Minimal QSettings stand-in backed by a dict."""

    def __init__(self, store):
        self._store = store

    def value(self, key, default=False, type=bool):
        return self._store.get(key, default)

    def setValue(self, key, val):
        self._store[key] = val


@pytest.fixture
def fake_settings(monkeypatch):
    store = {}

    def factory(*_args, **_kwargs):
        return _FakeSettings(store)

    monkeypatch.setattr(dialogs.QtCore, "QSettings", factory)
    return store


def test_remembered_yes_returns_true_without_dialog(qapp, fake_settings):
    fake_settings[dialogs.NGSPICE_REMEMBER_KEY] = True
    fake_settings[dialogs.NGSPICE_FLAG_KEY] = True
    assert dialogs.ask_ngspice_plots(None) is True


def test_remembered_no_returns_false_without_dialog(qapp, fake_settings):
    fake_settings[dialogs.NGSPICE_REMEMBER_KEY] = True
    fake_settings[dialogs.NGSPICE_FLAG_KEY] = False
    assert dialogs.ask_ngspice_plots(None) is False
