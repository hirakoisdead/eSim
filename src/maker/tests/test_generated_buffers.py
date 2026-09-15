"""Generated-C buffer sizing on the maker (Verilator) side.

``sim_main_<model>.h`` used to declare ``int <model>_temp_<port>[1024]`` for
every port and ``sim_main_<model>.cpp`` an instance array of a fixed 1024,
whatever the model actually needs. A port wider than 1024 bits therefore
overflowed a C array in the generated model with no diagnostic anywhere, and
the instance array was indexed by ngspice's instance_id with no bound check.

The generator knows every width (the ifspec pins ``Vector_Bounds`` to
``[width width]``, so ngspice connects exactly that many bits), so the arrays
are now sized from it; the one bound it cannot know — the instance count — is
checked in the emitted C instead of being written past.
"""
import os

from maker import ModelGeneration


def _generate(tmp_path, inputs, outputs, stem="counter"):
    """Run sim_main_header + sim_main for a made-up port list and return the
    (.h, .cpp) text. __new__ bypasses the Qt/config-heavy constructor: these
    two writers only read model_stem/modelpath/input_port/output_port."""
    cls = ModelGeneration.ModelGeneration
    mg = cls.__new__(cls)
    mg.model_stem = stem
    mg.modelpath = str(tmp_path) + os.sep
    mg.input_port = list(inputs)
    mg.output_port = list(outputs)
    mg.sim_main_header()
    mg.sim_main()
    with open(os.path.join(str(tmp_path), "sim_main_" + stem + ".h")) as fh:
        header = fh.read()
    with open(os.path.join(str(tmp_path), "sim_main_" + stem + ".cpp")) as fh:
        cpp = fh.read()
    return header, cpp


def test_port_arrays_are_sized_from_the_port_width(tmp_path):
    header, cpp = _generate(
        tmp_path, ["clk:1", "data_in:2048"], ["q:8"])

    for text in (header, cpp):
        assert "counter_temp_clk[1]" in text
        assert "counter_temp_data_in[2048]" in text
        assert "counter_temp_q[8]" in text
        # No port array is left at the old blanket size.
        assert "_temp_clk[1024]" not in text
        assert "_temp_data_in[1024]" not in text
        assert "_temp_q[1024]" not in text


def test_header_and_cpp_agree_on_every_width(tmp_path):
    """The .h owns the definitions and the .cpp re-declares them extern "C";
    a mismatch is a link-time or (worse) a silent-corruption bug."""
    ports = ["a:3", "b:17"], ["y:5"]
    header, cpp = _generate(tmp_path, *ports)
    for name, width in (("a", 3), ("b", 17), ("y", 5)):
        decl = "counter_temp_%s[%d]" % (name, width)
        assert header.count(decl) == 1
        assert ('extern "C" int ' + decl) in cpp


def test_unparsable_width_falls_back_to_one_bit(tmp_path):
    """A malformed entry must not emit ``[0]`` (a zero-length array every loop
    would then overrun) or crash mid-generation."""
    header, _ = _generate(tmp_path, ["odd:", "zero:0"], ["q:1"])
    assert "counter_temp_odd[1]" in header
    assert "counter_temp_zero[1]" in header
    assert "[0]" not in header


def test_instance_array_is_bounded_and_checked(tmp_path):
    _, cpp = _generate(tmp_path, ["clk:1"], ["q:1"])

    # The array is still a compile-time bound (instance_id is a run-time value)
    # but it is named and, crucially, checked before it is indexed.
    assert "#define counter_MAX_INSTANCES 1024" in cpp
    assert "static Vcounter* counter[counter_MAX_INSTANCES];" in cpp
    assert "counter[1024]" not in cpp

    guard = "if (count < 0 || count >= counter_MAX_INSTANCES)"
    assert guard in cpp
    # The guard must sit between the decrement and the first use of count.
    assert cpp.index("count--;") < cpp.index(guard) < cpp.index("if (init==0)")
    assert "return -1;" in cpp[cpp.index(guard):cpp.index("if (init==0)")]
