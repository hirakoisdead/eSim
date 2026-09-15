"""Unit tests for ngspiceSimulation.data_extraction.

Covers the vectorized block parser, the rawfile node-name recovery, the
eprint event-file resampler, and a full openFile() round-trip over synthetic
ngspice output. DataExtraction pulls in Appconfig (Qt), so a QApplication is
required — provided by the session ``qapp`` fixture in conftest.
"""
import numpy as np
import pytest

from ngspiceSimulation.data_extraction import DataExtraction, _block_to_array


# ── _block_to_array (module-level, pure) ──────────────────────────────────

def test_block_to_array_transient():
    rows = [
        "0\t0.000000e+00\t0.0\t5.0\t\n",
        "1\t1.000000e-09\t1.0\t4.0\t\n",
        "2\t2.000000e-09\t2.0\t3.0\t\n",
    ]
    # usecols: time (col 1) + two node cols (2, 3).
    out = _block_to_array(rows, (1, 2, 3), is_ac=False)
    assert out.shape == (3, 3)
    np.testing.assert_allclose(out[:, 0], [0, 1e-9, 2e-9])
    np.testing.assert_allclose(out[:, 1], [0.0, 1.0, 2.0])
    np.testing.assert_allclose(out[:, 2], [5.0, 4.0, 3.0])


def test_block_to_array_ac_strips_real_part_comma():
    # AC rows carry "real,<tab>imag" per node; only the real part is kept.
    rows = [
        "0\t1.000000e+03\t9.96e+00,\t-4.50e+00\t\n",
        "1\t2.000000e+03\t8.00e+00,\t-3.00e+00\t\n",
    ]
    # n_nodes = 1 -> node real col is index 2; usecols = (freq col 1, 2).
    out = _block_to_array(rows, (1, 2), is_ac=True)
    assert out.shape == (2, 2)
    np.testing.assert_allclose(out[:, 0], [1e3, 2e3])
    np.testing.assert_allclose(out[:, 1], [9.96, 8.0])


def test_block_to_array_empty_rows():
    out = _block_to_array([], (1, 2), is_ac=False)
    assert out.shape == (0, 2)


def test_block_to_array_drops_ragged_rows():
    rows = [
        "0\t0.0\t1.0\t2.0\t\n",
        "1\t1.0\n",                 # malformed: too few fields
        "2\t2.0\t3.0\t4.0\t\n",
    ]
    out = _block_to_array(rows, (1, 2, 3), is_ac=False)
    assert out.shape == (2, 3)
    np.testing.assert_allclose(out[:, 0], [0.0, 2.0])


# ── _full_voltage_names (staticmethod, pure) ──────────────────────────────

def test_full_voltage_names_from_rawfile(tmp_path):
    raw = tmp_path / "plot_data.raw"
    raw.write_text(
        "Title: test\n"
        "Date: now\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tv(in)\tvoltage\n"
        "\t2\tv(out)\tvoltage\n"
        "\t3\ti(v1)\tcurrent\n"
        "Values:\n"
        "0\t0\t0\t0\t0\n"
    )
    names = DataExtraction._full_voltage_names(str(raw))
    assert names == ["in", "out"]


def test_full_voltage_names_missing_file():
    assert DataExtraction._full_voltage_names("/no/such/file.raw") == []


# ── _parse_event_file (instance method) ───────────────────────────────────

def test_parse_event_file_resamples(qapp, tmp_path):
    ev = tmp_path / "plot_data_event.txt"
    ev.write_text(
        "**** Results Data ****\n"
        "\n"
        "Time or Step\n"
        "d_out\n"
        "\n"
        "0.0\t0*\n"
        "1.0e-09\t1*\n"
        "2.0e-09\t0*\n"
        "**** Messages ****\n"
    )
    d = DataExtraction()
    tran_x = np.array([0.0, 0.5e-9, 1.5e-9, 2.5e-9])
    names, arrays = d._parse_event_file(str(ev), tran_x)
    assert names == ["d_out"]
    assert len(arrays) == 1
    # Step-hold: last state at/<= each sample. 0->0V, 1e-9->5V, 2e-9->0V.
    np.testing.assert_allclose(arrays[0], [0.0, 0.0, 5.0, 0.0])


def test_parse_event_file_empty_tran_axis(qapp, tmp_path):
    ev = tmp_path / "plot_data_event.txt"
    ev.write_text("**** Results Data ****\nTime or Step\nd\n0.0\t0*\n")
    d = DataExtraction()
    assert d._parse_event_file(str(ev), np.array([])) == ([], [])


# ── openFile round-trip ───────────────────────────────────────────────────

def _write_transient_project(d):
    (d / "analysis").write_text(".tran 1e-9 3e-9 0\n")
    (d / "plot_data_v.txt").write_text(
        "Title\n"
        "Transient Analysis  Mon\n"
        "--------------------------------------------------------------------\n"
        "Index   time   v(in)   v(out)\n"
        "--------------------------------------------------------------------\n"
        "0\t0.000000e+00\t0.0\t5.0\t\n"
        "1\t1.000000e-09\t1.0\t4.0\t\n"
        "2\t2.000000e-09\t2.0\t3.0\t\n"
    )
    (d / "plot_data_i.txt").write_text(
        "Title\n"
        "Transient Analysis  Mon\n"
        "--------------------------------------------------------------------\n"
        "Index   time   i(v1)\n"
        "--------------------------------------------------------------------\n"
        "0\t0.000000e+00\t1.000000e-03\t\n"
        "1\t1.000000e-09\t2.000000e-03\t\n"
        "2\t2.000000e-09\t3.000000e-03\t\n"
    )


def test_openfile_transient_roundtrip(qapp, tmp_path):
    _write_transient_project(tmp_path)
    d = DataExtraction()
    result = d.openFile(str(tmp_path))
    assert result == [DataExtraction.TRANSIENT_ANALYSIS, 0]
    assert d.NBList == ["v(in)", "v(out)", "i(v1)"]
    assert d.volts_length == 2
    np.testing.assert_allclose(d.x, [0.0, 1e-9, 2e-9])
    # y is parallel to NBList: 2 voltage arrays + 1 current array.
    assert len(d.y) == 3
    np.testing.assert_allclose(d.y[1], [5.0, 4.0, 3.0])
    np.testing.assert_allclose(d.y[2], [1e-3, 2e-3, 3e-3])
    # numVals -> [total, voltage_count]
    assert d.numVals() == [3, 2]


def test_detect_analysis_type_ac(qapp, tmp_path):
    (tmp_path / "analysis").write_text(".ac dec 10 1 1e6\n")
    d = DataExtraction()
    atype, dec = d._detect_analysis_type(str(tmp_path))
    assert atype == DataExtraction.AC_ANALYSIS
    assert dec == 1
