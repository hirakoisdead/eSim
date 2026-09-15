"""Unit tests for ngspiceSimulation.math_utils.

These are the pure numeric helpers behind the Plot Function feature, the SI
formatting in cursor/stat readouts, and the digital-timing frequency detector.
No Qt or simulation data required.
"""
import numpy as np
import pytest

from ngspiceSimulation.math_utils import (
    _safe_eval, _canonical_expr, _format_measurement, _format_frequency,
    _detect_frequency,
)


# ── _safe_eval ────────────────────────────────────────────────────────────

def test_safe_eval_arithmetic():
    dm = {'a': np.array([1.0, 2.0, 3.0]), 'b': np.array([10.0, 10.0, 10.0])}
    np.testing.assert_allclose(_safe_eval('a + b', dm), [11, 12, 13])


def test_safe_eval_precedence_and_power():
    dm = {'a': np.array([2.0, 3.0])}
    np.testing.assert_allclose(_safe_eval('a ** 2 + 1', dm), [5, 10])


def test_safe_eval_whitelisted_functions():
    dm = {'a': np.array([1.0, 4.0, 9.0])}
    np.testing.assert_allclose(_safe_eval('sqrt(a)', dm), [1, 2, 3])


def test_safe_eval_unary_minus():
    dm = {'a': np.array([1.0, -2.0])}
    np.testing.assert_allclose(_safe_eval('-a', dm), [-1, 2])


def test_safe_eval_unknown_identifier_raises():
    with pytest.raises(ValueError):
        _safe_eval('a + c', {'a': np.array([1.0])})


def test_safe_eval_rejects_attribute_call():
    # np.sin(...) must be rejected — no attribute access is allowed.
    with pytest.raises(ValueError):
        _safe_eval('np.sin(a)', {'a': np.array([1.0])})


def test_safe_eval_rejects_unknown_function():
    with pytest.raises(ValueError):
        _safe_eval('atan(a)', {'a': np.array([1.0])})


def test_safe_eval_aligns_mismatched_lengths():
    dm = {'a': np.array([1.0, 2.0, 3.0]), 'b': np.array([1.0, 1.0])}
    out = _safe_eval('a + b', dm)
    assert len(out) == 2
    np.testing.assert_allclose(out, [2, 3])


def test_safe_eval_syntax_error_raises_valueerror():
    with pytest.raises(ValueError):
        _safe_eval('a +', {'a': np.array([1.0])})


# ── _canonical_expr ───────────────────────────────────────────────────────

def test_canonical_commutative_add_equal():
    assert _canonical_expr('a+b+c') == _canonical_expr('c+b+a')


def test_canonical_commutative_mult_equal():
    assert _canonical_expr('a*b') == _canonical_expr('b*a')


def test_canonical_subtraction_order_matters():
    assert _canonical_expr('a-b') != _canonical_expr('b-a')


def test_canonical_division_order_matters():
    assert _canonical_expr('a/b') != _canonical_expr('b/a')


# ── _format_measurement ───────────────────────────────────────────────────

@pytest.mark.parametrize("value,unit,suffix", [
    (2.0, 'V', 'V'),
    (0.005, 'V', 'mV'),
    (5e-6, 'V', 'µV'),
    (5e-9, 'V', 'nV'),
    (5e-12, 'V', 'pV'),
    (0.005, 'A', 'mA'),
    (5e-9, 'A', 'nA'),
])
def test_format_measurement_si_prefix(value, unit, suffix):
    assert _format_measurement(value, unit).endswith(suffix)


def test_format_measurement_negative_keeps_sign():
    assert _format_measurement(-0.005, 'V').startswith('-')


# ── _format_frequency ─────────────────────────────────────────────────────

@pytest.mark.parametrize("hz,suffix", [
    (50, 'Hz'),
    (1500, 'kHz'),
    (2e6, 'MHz'),
    (3e9, 'GHz'),
])
def test_format_frequency(hz, suffix):
    assert _format_frequency(hz).endswith(suffix)


# ── _detect_frequency ─────────────────────────────────────────────────────

def test_detect_frequency_square_wave():
    t = np.linspace(0, 1e-6, 2000)
    logic = (np.sin(2 * np.pi * 5e6 * t) > 0).astype(float)
    freq = _detect_frequency(t, logic)
    assert freq is not None
    assert abs(freq - 5e6) / 5e6 < 0.05


def test_detect_frequency_too_few_edges_returns_none():
    t = np.linspace(0, 1e-6, 1000)
    logic = np.concatenate([np.zeros(500), np.ones(500)])  # single rising edge
    assert _detect_frequency(t, logic) is None


def test_detect_frequency_non_periodic_returns_none():
    # Rising edges with wildly varying spacing → CV > 10% → rejected.
    t = np.array([0.0, 1.0, 1.1, 5.0, 5.1, 20.0, 20.1])
    logic = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0])
    assert _detect_frequency(t, logic) is None
