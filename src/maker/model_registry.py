# =========================================================================
#             FILE: model_registry.py
#
#      DESCRIPTION: Who owns a model name, and what to build under when the
#                   name is taken.
#
#                   eSim keys a block model on one thing: its name. The
#                   netlister resolves a schematic value to a model by
#                   filename alone (Processing.convertICintoBasicBlocks indexes
#                   library/modelParamXML/**/<value>.xml), so two libraries
#                   holding a <name>.xml make that lookup ambiguous and the
#                   convert fails with "multiple models". One name therefore
#                   means one backend, across NgVeri, d_cosim, NGHDL and the
#                   built-in primitives alike.
#
#                   That rule used to be enforced at the very END of a build,
#                   inside KiCad symbol creation -- after iverilog had compiled
#                   (d_cosim) or after verilator and a full ngspice rebuild
#                   (NgVeri). The user paid minutes for a refusal that was
#                   knowable up front, and the half-built model stayed on disk
#                   and in the remove-model dialog. These helpers let the
#                   decision be made BEFORE anything is written.
#
#                   Pure stdlib, no Qt: the ownership rules are unit-testable
#                   without a GUI.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# =========================================================================

import os

#: The two Verilog backends. A clash between these is not a clash at all --
#: NgVeri.py's _switch_backends_if_needed offers to move the name from one to
#: the other, which is a rebuild of the same design, not a collision with
#: someone else's model.
VERILOG_DIRS = ("Ngveri", "NgVeriCosim")

#: The VHDL backend. Its models are built by a different toolchain (GHDL) from
#: different sources, so eSim will not remove one on the Verilog side's behalf.
NGHDL_DIR = "Nghdl"


def _names_in(directory):
    """Lowercased model names with a param XML in ``directory``.

    Lists the directory rather than probing ``os.path.isfile``: Windows
    compares names case-insensitively, so an isfile() probe for "counter.xml"
    answers True for a "Counter.xml" that belongs to a differently-cased
    model."""
    try:
        entries = os.listdir(directory)
    except OSError:
        return set()
    return {n[:-4].lower() for n in entries if n.lower().endswith(".xml")}


def owner_of(xml_loc, name):
    """Which modelParamXML library already holds ``name``, or "".

    Returns the subdirectory name ("Ngveri", "NgVeriCosim", "Nghdl", "Digital",
    …) or "" for a model root itself (a built-in primitive whose XML sits
    directly in modelParamXML/). "" is also the answer when nothing owns the
    name.

    Deterministic precedence -- the Verilog backends first -- so a caller that
    treats a Verilog owner as "mine to switch" cannot be handed the VHDL owner
    of a name that (wrongly) exists in both.
    """
    low = str(name or "").strip().lower()
    if not low or not xml_loc:
        return ""
    for sub in VERILOG_DIRS + (NGHDL_DIR,):
        if low in _names_in(os.path.join(xml_loc, sub)):
            return sub
    if low in _names_in(xml_loc):
        return "__builtin__"
    try:
        subdirs = sorted(d for d in os.listdir(xml_loc)
                         if os.path.isdir(os.path.join(xml_loc, d)))
    except OSError:
        return ""
    for sub in subdirs:
        if sub in VERILOG_DIRS or sub == NGHDL_DIR:
            continue
        if low in _names_in(os.path.join(xml_loc, sub)):
            return sub
    return ""


def is_taken(xml_loc, name):
    """True when ANY library already holds ``name``."""
    return bool(owner_of(xml_loc, name))


def library_label(owner):
    """How to name ``owner`` to a user, who has never heard of a directory
    called NgVeriCosim."""
    return {
        "Ngveri": "NgVeri (Verilator)",
        "NgVeriCosim": "d_cosim (Icarus Verilog)",
        "Nghdl": "NGHDL (VHDL)",
        "__builtin__": "built-in eSim",
        "Analog": "built-in eSim analog",
        "Digital": "built-in eSim digital",
        "Hybrid": "built-in eSim hybrid",
    }.get(owner, owner)


def free_name(xml_loc, name, suffix="_v", limit=50):
    """A name near ``name`` that no library owns: ``<name>_v``, then
    ``<name>_v2``, ``_v3`` …

    Suffixing rather than prompting for a name is deliberate. The model name is
    NOT the module name -- ModelGeneration keeps them apart (``model_stem`` vs
    ``top_module``), so building as ``nand_gate_v`` neither edits nor renames
    the user's code; it only changes what the block is called in the schematic.
    That makes an automatic alternative safe to offer as the default action,
    where "go rename your module and start again" was the only way out before.

    Returns "" if ``name`` is blank, or if 50 candidates in a row are taken --
    at which point something is wrong that a 51st guess will not fix.
    """
    low = str(name or "").strip().lower()
    if not low:
        return ""
    for n in range(1, limit + 1):
        candidate = low + suffix + ("" if n == 1 else str(n))
        if not is_taken(xml_loc, candidate):
            return candidate
    return ""
