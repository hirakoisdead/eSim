"""Put every d_cosim block on a schematic into ONE Icarus simulation.

ivlng loads Icarus's ``libvvp``, whose engine state is process-global and
single-shot. A netlist carrying two d_cosim devices therefore prints

    This VVP simulation has already run and can not be reused

and then ngspice dies with SIGSEGV, leaving no output file and no diagnostic.
Loading a renamed second copy of libvvp does not help: ``ivlng.vpi`` imports
the first copy by name, so the second engine's VPI callbacks run against the
first.

The limit is one *engine* per process, not one *block* per schematic. So the
converter compiles all the blocks into a single artifact -- one generated
wrapper module instantiating each design, one vvp, one d_cosim device whose
``d_in``/``d_out`` vectors are the blocks' vectors concatenated -- and the
schematic can carry as many Verilog blocks as the user likes. The blocks still
talk to each other, and to the analog half, through SPICE nodes exactly as
before; the wrapper never sees the connections.

This is d_cosim's own machinery. It runs only when a d_cosim block is present,
which no eSim 2.5 schematic can be, so nothing that worked before can change.
"""
import os
import shutil

from . import CosimConfig
from .hdl import icarus
from .ModelGeneration import (
    COSIM_TOP_MODULE,
    cosim_wrapper_source,
    declared_timescale,
    normalise_timescale,
    parse_connection_info,
)

#: Basename of the merged artifact, staged next to the netlist. ivlng resolves
#: sim_args relative to ngspice's working directory, which is the project dir.
MERGED_VVP = 'esim_cosim_merged'


class MergeError(Exception):
    """A merge that cannot produce a correct netlist.

    Raised rather than papered over: every alternative -- dropping a block,
    guessing a port width -- ends in a simulation that runs and is wrong, which
    is the failure mode this whole area exists to remove.
    """


def model_dir(model_name):
    """Where build_cosim left a model's sources, or None if unconfigured."""
    vvp = CosimConfig.cosim_vvp_path(model_name)
    return os.path.dirname(vvp) if vvp else None


def model_ports(model_name):
    """``[(name, direction, bits), ...]`` for a built d_cosim model."""
    folder = model_dir(model_name)
    if not folder:
        raise MergeError(
            'The digital model library is not configured, so the ports of '
            '"%s" cannot be read.' % model_name)
    path = os.path.join(folder, 'connection_info.txt')
    try:
        with open(path) as fh:
            ports = parse_connection_info(fh.read())
    except OSError as exc:
        raise MergeError(
            'Cannot read the port list for "%s" (%s). Rebuild the model in '
            'the NgVeri tab ("Add Verilog (d_cosim)").'
            % (model_name, exc)) from exc
    if not ports:
        raise MergeError(
            'The port list for "%s" is empty. Rebuild the model in the '
            'NgVeri tab ("Add Verilog (d_cosim)").' % model_name)
    return ports


def model_source(model_name):
    """The design file build_cosim compiled, or None if it is missing."""
    folder = model_dir(model_name)
    if not folder:
        return None
    for suffix in ('.v', '.sv', '.V', '.SV'):
        candidate = os.path.join(folder, model_name + suffix)
        if os.path.isfile(candidate):
            return candidate
    return None


def _prepare(text):
    """The source as build_cosim would compile it: a `timescale present, and
    its precision fine enough for ivlng to advance a tick per SPICE step."""
    if '`timescale' not in text:
        return '`timescale 1ns/1ps\n' + text
    return normalise_timescale(text)[0]


def build_merged_vvp(blocks, workdir, log=None):
    """Compile ``blocks`` into one vvp in ``workdir``; return its path.

    ``blocks`` is ``[(label, model_name, ports), ...]``. ``label`` is the
    schematic instance (``u2``), which is what disambiguates two placements of
    the same Verilog model.
    """
    iverilog = CosimConfig.iverilog_binary()
    if not iverilog or not CosimConfig.has_iverilog():
        raise MergeError(
            'This schematic has %d Verilog co-simulation blocks, which are '
            'combined into one simulation at conversion time -- but Icarus '
            'Verilog was not found. %s'
            % (len(blocks), CosimConfig.missing_reason() or ''))

    build = os.path.join(workdir, '.esim_cosim_build')
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(build, exist_ok=True)

    # One prepared copy of each distinct design. Two instances of the same
    # model share a source; compiling it twice is a duplicate-module error.
    sources, libdirs, timescale = [], [], None
    for _label, model_name, _ports in blocks:
        if any(os.path.basename(s).startswith(model_name + '.')
               for s in sources):
            continue
        src = model_source(model_name)
        if not src:
            raise MergeError(
                'The Verilog source for "%s" is missing from the model '
                'library, so it cannot be merged with the other blocks. '
                'Rebuild it in the NgVeri tab ("Add Verilog (d_cosim)").'
                % model_name)
        with open(src) as fh:
            prepared = _prepare(fh.read())
        if timescale is None:
            timescale = declared_timescale(prepared)
        copy = os.path.join(build, os.path.basename(src))
        with open(copy, 'w') as fh:
            fh.write(prepared)
        sources.append(copy)
        folder = model_dir(model_name)
        if folder and folder not in libdirs:
            libdirs.append(folder)

    wrapper = os.path.join(build, COSIM_TOP_MODULE + '.v')
    with open(wrapper, 'w') as fh:
        fh.write(cosim_wrapper_source(blocks, timescale
                                      or '`timescale 1ns/1ps'))

    # -y per model dir so each design's own dependency files still resolve,
    # exactly as they do in the single-block build.
    extra_flags = []
    for folder in libdirs:
        extra_flags += ['-y', folder, '-I', folder]
    extra_flags += ['-Y', '.sv']

    out = os.path.join(workdir, MERGED_VVP)
    if log:
        log.info('Merging %d d_cosim block(s) into one simulation: %s'
                 % (len(blocks), ', '.join(b[0] for b in blocks)))
    res = icarus.run_iverilog(
        iverilog, [wrapper] + sources, out,
        extra_flags=extra_flags, cwd=build, timeout=300)
    if log:
        log.output(res.stdout, 'stdout')
        log.output(res.stderr, 'stderr')
    if not res.ok or not os.path.isfile(out):
        raise MergeError(
            'Compiling the %d co-simulation blocks into one simulation '
            'failed:\n%s' % (len(blocks), (res.output or '').strip()))
    return out


def merged_nodes(blocks, instances):
    """``(in_nodes, out_nodes)`` for the single merged device.

    ``instances`` maps a label to its ``([in nodes], [out nodes])`` as the
    schematic wired them. The concatenation order is inputs of every block in
    schematic order, then outputs of every block -- the same order
    :func:`cosim_wrapper_source` declares the wrapper's ports in, and the order
    ivlng assigns bit positions in (``vpi.c`` ``start_cb``).
    """
    ins, outs = [], []
    for label, model_name, ports in blocks:
        block_in, block_out = instances[label]
        want_in = sum(b for _n, d, b in ports if d == 'input')
        want_out = sum(b for _n, d, b in ports if d == 'output')
        if len(block_in) != want_in or len(block_out) != want_out:
            raise MergeError(
                'Block %s ("%s") is wired to %d input and %d output nodes, '
                'but the built model has %d and %d. The symbol on the '
                'schematic is out of date -- rebuild the model, then delete '
                'and replace the block.'
                % (label, model_name, len(block_in), len(block_out),
                   want_in, want_out))
        ins.extend(block_in)
        outs.extend(block_out)
    return ins, outs
