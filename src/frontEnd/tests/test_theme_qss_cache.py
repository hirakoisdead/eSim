"""The resolved stylesheet is cached per input tuple.

Toggling theme back and forth (or the OS colorScheme signal firing repeatedly)
must not re-read the .qss file and re-run the token-replace / rgba-recolor /
px-scale regex passes every time. build_qss memoizes on
(qss_name, accent, secondary, internal, zoom).
"""
from frontEnd import theme_utils


def _clear():
    theme_utils._QSS_CACHE.clear()


def test_repeat_build_hits_cache_and_is_identical():
    _clear()
    a = theme_utils.build_qss('style_dark.qss', True, 'default', 'system',
                              'system', 100)
    assert a  # the dark sheet is non-empty
    assert len(theme_utils._QSS_CACHE) == 1

    b = theme_utils.build_qss('style_dark.qss', True, 'default', 'system',
                              'system', 100)
    # Same object returned from cache (not merely equal) -- proves no rebuild.
    assert a is b
    assert len(theme_utils._QSS_CACHE) == 1


def test_distinct_inputs_are_cached_separately():
    _clear()
    dark = theme_utils.build_qss('style_dark.qss', True, 'default', 'system',
                                 'system', 100)
    light = theme_utils.build_qss('style_light.qss', False, 'default',
                                  'system', 'system', 100)
    zoomed = theme_utils.build_qss('style_dark.qss', True, 'default', 'system',
                                   'system', 150)

    assert dark != light
    assert dark != zoomed          # px metrics scaled
    assert len(theme_utils._QSS_CACHE) == 3


def test_accent_substitution_still_applies():
    _clear()
    default = theme_utils.build_qss('style_dark.qss', True, 'default',
                                    'system', 'system', 100)
    accented = theme_utils.build_qss('style_dark.qss', True, '#FF00AA',
                                     'system', 'system', 100)
    # A custom accent must change the sheet and be cached under its own key.
    assert accented != default
    assert '#FF00AA' in accented
    assert len(theme_utils._QSS_CACHE) == 2


def test_apply_theme_sets_base_style_only_once(qapp, monkeypatch):
    """setStyle() re-polishes every widget in the app, so calling it on every
    theme toggle doubles the repolish cost (the 2-3s toggle freeze). apply_theme
    must install the base style once per QApplication and never again.

    The style it installs is ComboPopupStyle rather than the bare "Fusion" key:
    a QProxyStyle over Fusion that turns off the menu-flavoured combo popup.
    """
    calls = []
    monkeypatch.setattr(
        qapp, "setStyle", lambda *a, **k: calls.append(a), raising=False)
    if hasattr(qapp, "_esim_base_style_set"):
        del qapp._esim_base_style_set

    theme_utils.apply_theme(qapp)
    assert len(calls) == 1
    (installed,) = calls[0]
    assert isinstance(installed, theme_utils.ComboPopupStyle)
    assert installed.baseStyle().objectName() == "fusion"

    theme_utils.apply_theme(qapp)
    theme_utils.apply_theme(qapp)
    assert len(calls) == 1


def test_missing_qss_file_caches_empty():
    _clear()
    out = theme_utils.build_qss('does_not_exist.qss', True, 'default',
                                'system', 'system', 100)
    assert out == ""
    # Cached so a repeated miss does not re-stat the filesystem each toggle.
    assert theme_utils._QSS_CACHE[
        ('does_not_exist.qss', 'default', 'system', 'system', 100)] == ""
