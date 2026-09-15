# =========================================================================
#          FILE: kicadtoNgspice.py
#
#         USAGE: ---
#
#   DESCRIPTION: This define all configuration used in Application.
#
#       OPTIONS: ---
#  REQUIREMENTS: ---
#          BUGS: ---
#         NOTES: ---
#        AUTHOR: Fahim Khan, fahim.elex@gmail.com
#      MODIFIED: Rahul Paknikar, rahulp@iitb.ac.in
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
#       CREATED: Wednesday 04 March 2015
#      REVISION: Tuesday 25 April 2023
# =========================================================================

import os
import re
import tempfile
import traceback
from xml.etree import ElementTree as ET

from PyQt6 import QtWidgets
from configuration import Dialogs
from configuration.Appconfig import Appconfig

from . import Analysis
from . import Convert
from . import DeviceModel
from . import Model
from . import Microcontroller
from . import Source
from . import SubcircuitTab
from . import TrackWidget
from .Processing import PrcocessNetlist
from projManagement.projectPaths import previous_values_path


def _model_types(schematic_info):
    """``{model card name: ngspice model type}`` for every ``.model`` line,
    e.g. ``{"u1": "adc_bridge", "u2": "d_cosim"}``. Both keys and values are
    lower-cased; the type is the token before the parameter parenthesis."""
    types = {}
    for line in schematic_info:
        s = str(line).strip()
        if s.lower().startswith('.model '):
            parts = s.split()
            if len(parts) >= 3:
                types[parts[1].lower()] = parts[2].split('(')[0].lower()
    return types


def _a_devices(schematic_info):
    """``(instance, model card name, [node lists])`` for every XSPICE a-device.

    ``a2 [in1 in2] [out1] u2`` yields
    ``("a2", "u2", [["in1", "in2"], ["out1"]])``.

    The instance name is carried because it is the only per-placement identity
    there is: two placements of one Verilog block share a single ``.model``
    card, so anything keyed by the card silently merges them."""
    devices = []
    for line in schematic_info:
        s = str(line).strip()
        if not s or s[0].lower() != 'a':
            continue
        groups = re.findall(r'\[([^\]]*)\]', s)
        if not groups:
            continue
        parts = s.split()
        devices.append((parts[0].lower(), parts[-1].lower(),
                        [g.split() for g in groups]))
    return devices


def _get_event_plot_nodes(schematic_info, plot_text):
    """Return ordered event (digital) node names that appear in plot_text.

    Scans schematic_info for .model lines (adc_bridge / d_cosim / dac_bridge)
    and a-device lines to decide which nodes are XSPICE event nodes, then keeps
    only those also requested in plot_text ("plot v(node)"). ngspice's `eprint`
    fails if handed a plain analog node, so the two sets must be intersected.
    """
    model_types = _model_types(schematic_info)

    event_nodes = set()
    for _inst, model, groups in _a_devices(schematic_info):
        mtype = model_types.get(model, '')
        if mtype == 'adc_bridge' and len(groups) >= 2:
            event_nodes.update(groups[1])
        elif mtype == 'd_cosim':
            for g in groups:
                event_nodes.update(g)
        elif mtype == 'dac_bridge' and len(groups) >= 1:
            event_nodes.update(groups[0])

    seen = set()
    result = []
    for item in plot_text:
        m = re.search(r'v\(([^),\s]+)\)', item)
        if m:
            node = m.group(1)
            if node in event_nodes and node not in seen:
                result.append(node)
                seen.add(node)
    return result


def dcosim_instance_count(schematic_info):
    """How many d_cosim blocks the netlist instantiates.

    Counted per a-device, not per ``.model`` card: two instances of the same
    Verilog block share one card and are still two co-simulations."""
    types = _model_types(schematic_info)
    return sum(1 for _inst, model, _g in _a_devices(schematic_info)
               if types.get(model) == 'd_cosim')


#: ``sim_args=["counter"]`` -- the vvp basename ivlng loads for a d_cosim card.
_SIM_ARGS_RE = re.compile(r'sim_args\s*=\s*\[\s*"([^"]+)"', re.IGNORECASE)
#: ``lib_args=["libvvp", "ivlng"]`` -- kept verbatim; on Windows it is what
#: points ivlng at the .vpi staged next to the netlist.
_LIB_ARGS_RE = re.compile(r'lib_args\s*=\s*\[[^\]]*\]', re.IGNORECASE)

#: Card name of the single device every d_cosim block is merged into.
MERGED_CARD = 'u_esim_cosim'


def dcosim_devices(schematic_info):
    """``[(instance, card, model, in_nodes, out_nodes), ...]`` for every
    d_cosim block, in netlist order.

    ``instance`` is the a-device name (``a2``) -- the only per-placement
    identity in the netlist. ``card`` is the ``.model`` it references and
    ``model`` the Verilog design behind it, and BOTH are shared when the same
    block is placed twice, so neither can key a per-block table."""
    types = _model_types(schematic_info)
    names = {}
    for line in schematic_info:
        s = str(line).strip()
        if not s.lower().startswith('.model '):
            continue
        parts = s.split()
        if len(parts) >= 3 and types.get(parts[1].lower()) == 'd_cosim':
            match = _SIM_ARGS_RE.search(s)
            if match:
                names[parts[1].lower()] = match.group(1)

    devices = []
    for inst, card, groups in _a_devices(schematic_info):
        if types.get(card) != 'd_cosim' or len(groups) < 2:
            continue
        devices.append((inst, card, names.get(card, card),
                        groups[0], groups[1]))
    return devices


#: ``in_low=1.5``, ``in_high = 2.0e0`` -- one adc_bridge threshold parameter.
def _param_re(name):
    return re.compile(
        r'\b' + name + r'\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)')


def merge_dcosim_blocks(schematic_info, project_dir, log=None):
    """Replace every d_cosim a-device with one device running all of them.

    Returns the rewritten netlist. A netlist with fewer than two d_cosim blocks
    is returned unchanged -- there is nothing to merge, and the per-model vvp
    the build already produced is used as-is.

    Icarus's engine is process-global and single-shot, so a second d_cosim
    device segfaults ngspice (docs/NGVERI_ACCURACY.md D2). One engine running a
    generated wrapper that instantiates every block lifts that to any number of
    blocks: see maker/cosim_merge.py. The blocks keep talking to each other
    through their SPICE nodes, so the schematic is unchanged in meaning.
    """
    from maker import cosim_merge

    devices = dcosim_devices(schematic_info)
    if len(devices) < 2:
        return list(schematic_info)

    # Keyed by INSTANCE: two placements of one block share a card and a model
    # name, and keying on either silently gives both copies the same nodes.
    ports = {}
    blocks, instances = [], {}
    for inst, _card, model, in_nodes, out_nodes in devices:
        if model not in ports:
            ports[model] = cosim_merge.model_ports(model)
        blocks.append((inst, model, ports[model]))
        instances[inst] = (in_nodes, out_nodes)

    ins, outs = cosim_merge.merged_nodes(blocks, instances)
    cosim_merge.build_merged_vvp(blocks, project_dir, log)

    cards = {card for _i, card, _m, _in, _out in devices}
    # Drop exactly the a-devices that went into the merge, by name. Matching
    # on the .model card instead would also delete a d_cosim a-line that
    # dcosim_devices skipped as malformed -- removing a block from the netlist
    # is the one outcome worse than refusing the conversion.
    merged = {inst for inst, _c, _m, _in, _out in devices}
    lib_args = ''
    netlist, placed = [], False
    for line in schematic_info:
        s = str(line)
        parts = s.strip().split()
        if not parts:
            netlist.append(line)
            continue

        if (len(parts) >= 3 and parts[0].lower() == '.model'
                and parts[1].lower() in cards):
            match = _LIB_ARGS_RE.search(s)
            if match and not lib_args:
                lib_args = match.group(0) + ' '
            continue

        if parts[0].lower() in merged:
            if not placed:                       # keep the first block's slot
                netlist.append('a_esim_cosim [%s] [%s] %s'
                               % (' '.join(ins), ' '.join(outs), MERGED_CARD))
                placed = True
            continue

        netlist.append(line)

    card_lines = [
        '* All Verilog co-simulation blocks run in one Icarus engine (%s)'
        % ', '.join(sorted(cards)),
        '.model %s d_cosim simulation="ivlng" %ssim_args=["%s"] '
        % (MERGED_CARD, lib_args, cosim_merge.MERGED_VVP)]

    # Before .control/.end if the caller handed over a complete netlist:
    # ngspice stops reading at .end, and a d_cosim a-device whose .model card
    # never got parsed does not fail -- it simulates, and its outputs are
    # whatever was left in memory. (createNetlistFile appends its control
    # block after this runs, so in the normal path either position works; the
    # point is not to depend on that.)
    cut = len(netlist)
    for index, line in enumerate(netlist):
        if str(line).strip().lower().split(' ')[0] in ('.control', '.end'):
            cut = index
            break
    return netlist[:cut] + card_lines + netlist[cut:]


#: ``.model`` categories whose blocks are an HDL simulation behind an XSPICE
#: shell -- Verilator (Ngveri), GHDL (Nghdl) and Icarus (NgVeriCosim). Each
#: reads its inputs as logic, and none of them wants an x from a voltage ramp.
HDL_MODEL_TYPES = ('Ngveri', 'Nghdl', 'NgVeriCosim')


def collapse_adc_band_for_hdl(schematic_info, hdl_cards=()):
    """PARKED -- not called by the converter. See docs/UPSTREAM_DECISIONS.md.

    Give every adc_bridge that feeds an HDL block a single switching
    threshold, and return ``(netlist, [(card, in_low, in_high, threshold)])``.

    This is kept, tested and deliberately unwired. It is a genuine fix for a
    genuine defect -- the measurements are in docs/NGVERI_ACCURACY.md D1/D5 --
    but it rewrites a netlist parameter eSim has emitted unchanged since 2.5,
    so it can move the numbers of a schematic the user already considers
    working. That call belongs to the eSim maintainers. The d_cosim backend
    reaches the same behaviour without touching the netlist, by reading x as 1
    the way NgVeri's generated C already does
    (``ModelGeneration.cosim_wrapper_source``).

    XSPICE's adc_bridge is a THREE-state converter: below ``in_low`` it emits
    0, above ``in_high`` it emits 1, and **in between it emits x**. Dumping the
    digital node for a 0-5 V clock with the stock 1.0/2.0 band shows four
    events per period, not two::

        0.000321 ms  U        <- crossed in_low going up
        0.000448 ms  1        <- crossed in_high
        0.501701 ms  U        <- crossed in_high coming down
        0.501828 ms  0        <- crossed in_low

    What each backend does with that ``U`` differs, and both answers are wrong:

    * **Icarus (d_cosim)** is a real four-state simulator and, per IEEE 1364,
      counts a transition to a *higher* value as a posedge -- so ``0->U`` and
      ``U->1`` are **both** posedges and the design is clocked twice per analog
      edge. Measured on a probe design: a ``posedge`` counter and a ``negedge``
      counter each advance 2 per period, and an ``always @(clk)`` counter
      advances 4.
    * **Verilator (Ngveri) and GHDL (Nghdl)** are spared the double edge only
      by accident: both generators emit
      ``if (INPUT_STATE(p) == ZERO) 0; else 1;``, so x is silently read as a
      logic 1. They see one edge -- but taken at ``in_low`` on the way up *and*
      on the way down, so the edge is early on one side and late on the other,
      and a genuinely undefined input reads as a confident 1.

    A logic input has one switching threshold; the ``in_low``/``in_high`` pair
    describes a *static* datasheet guarantee, not a dynamic behaviour, and
    applying it to a ramping clock is the modelling error. Collapsing the band
    to its midpoint keeps the user's intent (the centre of the band they asked
    for) and removes the ``U`` window entirely.

    ``hdl_cards`` names the ``.model`` cards known to be Ngveri/Nghdl blocks.
    They cannot be recognised from the netlist alone -- a generated model's
    type token is just the HDL entity name -- so the caller passes them in from
    the parsed model list. d_cosim blocks are self-identifying and are always
    included. Doing all three uniformly is what keeps a backend swap an
    apples-to-apples comparison: the analog half of the netlist must not change
    under the schematic just because the block behind it was rebuilt.
    """
    types = _model_types(schematic_info)
    devices = _a_devices(schematic_info)
    hdl = {str(c).lower() for c in hdl_cards}

    hdl_inputs = set()
    for _inst, model, groups in devices:
        if (types.get(model) == 'd_cosim' or model in hdl) and groups:
            hdl_inputs.update(groups[0])
    if not hdl_inputs:
        return list(schematic_info), []

    feeders = set()
    for _inst, model, groups in devices:
        if (types.get(model) == 'adc_bridge' and len(groups) >= 2
                and hdl_inputs.intersection(groups[1])):
            feeders.add(model)

    low_re, high_re = _param_re('in_low'), _param_re('in_high')
    collapsed = []
    netlist = []
    for line in schematic_info:
        s = str(line)
        parts = s.strip().split()
        if not (len(parts) >= 3 and parts[0].lower() == '.model'
                and parts[1].lower() in feeders
                and parts[2].split('(')[0].lower() == 'adc_bridge'):
            netlist.append(line)
            continue

        low, high = low_re.search(s), high_re.search(s)
        if not (low and high):
            netlist.append(line)
            continue
        try:
            lo, hi = float(low.group(1)), float(high.group(1))
        except ValueError:
            netlist.append(line)
            continue
        if hi <= lo:                    # already a single threshold
            netlist.append(line)
            continue

        mid = '%.10g' % ((lo + hi) / 2.0)
        s = low_re.sub('in_low=' + mid, s, count=1)
        s = high_re.sub('in_high=' + mid, s, count=1)
        netlist.append(s)
        collapsed.append((parts[1], lo, hi, mid))

    return netlist, collapsed


class MainWindow(QtWidgets.QWidget):
    """
    - This class create KicadtoNgspice window.
    - And Call Convert function if convert button is pressed.
    - The convert function takes all the value entered by user and create
      a final netlist "*.cir.out".
    - This final netlist is compatible with Ngspice.
    - clarg1 is the path to the .cir file
    - clarg2 is either None or "sub" depending on the analysis type
    """

    def __init__(self, clarg1, clarg2=None):
        QtWidgets.QWidget.__init__(self)
        print("==================================")
        print("Kicad to Ngspice netlist converter")
        print("==================================")
        self.kicadFile = clarg1
        self.clarg1 = clarg1
        self.clarg2 = clarg2
        self.obj_appconfig = Appconfig()

        # The converter's data bus (parse results + per-tab entries) lives on
        # this instance; _loadNetlist (re)creates a fresh TrackWidget here for
        # each parse, and it is injected into every tab and into Convert so no
        # state is shared across converter windows.
        self.obj_track = None

        # Validity of the parsed-in-memory model and the mtime of the .cir it
        # came from. callConvert uses these to detect a schematic re-export
        # under an open window and reload instead of serializing stale data.
        self._netlistValid = False
        self._netlist_mtime = None

        # Parse the .cir off disk into the module globals the tabs read from.
        try:
            load_aborted = self._loadNetlist()
        except Exception as exc:
            self._surface_conversion_failure(
                exc,
                "Netlist load failed",
                "Correct the reported schematic or model-library problem, "
                "then open the converter again.",
            )
            return

        if load_aborted:
            return

        self.createMainWindow()

    def _surface_conversion_failure(self, exc, title, hint):
        """Log and show a converter failure without destroying user state."""
        details = traceback.format_exc()
        if details.strip() == "NoneType: None":
            details = str(exc)
        print(details)
        self.obj_appconfig.print_error(f"{title}: {exc}")
        Dialogs.critical(
            self,
            title,
            str(exc),
            informative_text=hint,
        )

    def _loadNetlist(self):
        """(Re)parse the .cir into the module globals the tabs read from.

        Returns True if an unknown/duplicate model aborted the load (no UI
        should be built), else False.
        """
        # A fresh data bus for this conversion run: starting from a new
        # TrackWidget is what clears any state accumulated by a previous parse
        # (the old class-level reset()).
        self.obj_track = TrackWidget.TrackWidget()

        # A (re)load starts invalid and is marked valid only once it completes
        # without an aborting model error, so callConvert can refuse to
        # serialize a half-parsed netlist. Stamp the source mtime now -- even
        # on a failed parse -- so a stale snapshot can never look "current".
        self._netlistValid = False
        try:
            self._netlist_mtime = os.path.getmtime(self.kicadFile)
        except OSError:
            self._netlist_mtime = None

        # Object of Processing
        obj_proc = PrcocessNetlist()

        # Read the netlist, ie the .cir file
        kicadNetlist = obj_proc.readNetlist(self.kicadFile)

        # An empty or comment-only .cir has no usable lines; bail out with a
        # clear message instead of letting preprocessNetlist index off the end.
        if not kicadNetlist:
            self.msg = Dialogs.make_error_message(self)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Empty netlist")
            self.msg.showMessage(
                "The netlist file is empty. Open Kicad to Ngspice again to "
                "regenerate it from the schematic before converting.")
            self.msg.exec()
            return True

        # Construct parameter information
        param = obj_proc.readParamInfo(kicadNetlist)

        # Replace parameter with values
        netlist, self.infoline = obj_proc.preprocessNetlist(
            kicadNetlist, param)

        # Separate option and schematic information
        self.optionInfo, self.schematicInfo = \
            obj_proc.separateNetlistInfo(netlist)

        # List for storing source and its value
        self.sourcelist = []
        self.sourcelisttrack = []
        self.schematicInfo, self.sourcelist = \
            obj_proc.insertSpecialSourceParam(
                self.schematicInfo, self.sourcelist)

        # List storing model detail
        self.modelList = []
        self.microcontrollerList = []
        self.outputOption = []
        self.plotText = []
        (
            self.schematicInfo,
            self.outputOption,
            self.modelList,
            unknownModelList,
            multipleModelList,
            self.plotText
        ) = obj_proc.convertICintoBasicBlocks(
            self.schematicInfo, self.outputOption, self.modelList,
            self.plotText
        )
        for line in self.modelList:
            if line[6] == "Nghdl":
                self.microcontrollerList.append(line)
                self.modelList.remove(line)

        """
        - Checking if any unknown model is used in schematic which is not
          recognized by Ngspice.
        - Also if the two model of same name is present under
          modelParamXML directory
        """
        if unknownModelList:
            print("Unknown Model List is : ", unknownModelList)
            self.msg = Dialogs.make_error_message(self)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Unknown Models")
            self.content = "Your schematic contain unknown model " + \
                           ', '.join(unknownModelList)
            self.msg.showMessage(self.content)
            self.msg.exec()
            return True

        elif multipleModelList:
            self.msg = Dialogs.make_error_message(self)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Multiple Models")
            self.mcontent = "Look like you have duplicate model in \
            modelParamXML directory " + \
                            ', '.join(multipleModelList[0])
            self.msg.showMessage(self.mcontent)
            self.msg.exec()
            return True

        self._netlistValid = True
        return False

    def createMainWindow(self):
        """
        - This function create main window of KiCad to Ngspice converter
        - Two components
            - createcreateConvertWidget
            - Convert button => callConvert
        """
        self.vbox = QtWidgets.QVBoxLayout()

        # Aurora description strip: a gradient header that orients the user
        # before the model/source/analysis tabs (#converterDescription supplies
        # the gradient surface + padding).
        self.descriptionFrame = QtWidgets.QFrame()
        self.descriptionFrame.setObjectName("converterDescription")
        descLayout = QtWidgets.QVBoxLayout(self.descriptionFrame)
        descLayout.setContentsMargins(0, 0, 0, 0)
        descLabel = QtWidgets.QLabel(
            "Assign each schematic device its SPICE model, source and analysis "
            "parameters, then convert to an Ngspice-ready netlist.")
        descLabel.setWordWrap(True)
        descLabel.setProperty("cssClass", "muted")
        descLayout.addWidget(descLabel)

        # The tab widget lives in its own container layout so reloadNetlist()
        # can swap in freshly-built tabs when the source .cir changes, without
        # touching the persistent Convert button below it.
        self.convertContainer = QtWidgets.QVBoxLayout()
        self.convertContainer.addWidget(self.createcreateConvertWidget())

        self.hbox = QtWidgets.QHBoxLayout()
        self.hbox.addStretch(1)
        self.convertbtn = QtWidgets.QPushButton("Convert")
        # Primary action of the converter dialog.
        self.convertbtn.setProperty("cssClass", "primary")
        self.convertbtn.clicked.connect(self.callConvert)
        self.hbox.addWidget(self.convertbtn)

        self.vbox.addWidget(self.descriptionFrame)
        self.vbox.addLayout(self.convertContainer)
        self.vbox.addLayout(self.hbox)

        self.setLayout(self.vbox)
        self.setWindowTitle("Kicad To NgSpice Converter")

    def createcreateConvertWidget(self):
        """
        - Contains the tabs for various convertor elements
            - Analysis            => obj_analysis
            => Analysis.Analysis(`path_to_projFile`)

            - Source Details      => obj_source
            => Source.Source(`sourcelist`,`sourcelisttrack`,`path_to_projFile`)

            - NgSpice Model       => obj_model
            => Model.Model(`schematicInfo`,`modelList`,`path_to_projFile`)

            - Device Modelling    => obj_devicemodel
            => DeviceModel.DeviceModel(`schematicInfo`,`path_to_projFile`)

            - Subcircuits         => obj_subcircuitTab
            => SubcircuitTab.SubcircuitTab(`schematicInfo`,`path_to_projFile`)

            - Microcontrollers         => obj_microcontroller
            => Model.Model(schematicInfo, microcontrollerList, self.clarg1)

        - Finally pass each of these objects, to widgets
        - convertWindow > mainLayout > tabWidgets > AnalysisTab, SourceTab ...
        """
        # Each tab shares this window's single TrackWidget data bus (self.
        # obj_track) so the tabs and Convert all read/write the same state.
        self.convertWindow = QtWidgets.QWidget()
        self.analysisTab = QtWidgets.QScrollArea()
        self.obj_analysis = Analysis.Analysis(
            self.clarg1, track=self.obj_track)
        self.analysisTab.setWidget(self.obj_analysis)
        # self.analysisTabLayout = \
        #       QtWidgets.QVBoxLayout(self.analysisTab.widget())
        self.analysisTab.setWidgetResizable(True)
        self.sourceTab = QtWidgets.QScrollArea()
        self.obj_source = Source.Source(
            self.sourcelist, self.sourcelisttrack, self.clarg1,
            track=self.obj_track)
        self.sourceTab.setWidget(self.obj_source)
        # self.sourceTabLayout = QtWidgets.QVBoxLayout(self.sourceTab.widget())
        self.sourceTab.setWidgetResizable(True)
        self.modelTab = QtWidgets.QScrollArea()
        self.obj_model = Model.Model(
            self.schematicInfo, self.modelList, self.clarg1,
            track=self.obj_track)
        self.modelTab.setWidget(self.obj_model)
        # self.modelTabLayout = QtWidgets.QVBoxLayout(self.modelTab.widget())
        self.modelTab.setWidgetResizable(True)
        self.deviceModelTab = QtWidgets.QScrollArea()
        self.obj_devicemodel = DeviceModel.DeviceModel(
            self.schematicInfo, self.clarg1, track=self.obj_track)
        self.deviceModelTab.setWidget(self.obj_devicemodel)
        self.deviceModelTab.setWidgetResizable(True)
        self.subcircuitTab = QtWidgets.QScrollArea()
        self.obj_subcircuitTab = SubcircuitTab.SubcircuitTab(
            self.schematicInfo, self.clarg1, track=self.obj_track)
        self.subcircuitTab.setWidget(self.obj_subcircuitTab)
        self.subcircuitTab.setWidgetResizable(True)
        self.microcontrollerTab = QtWidgets.QScrollArea()
        self.obj_microcontroller = Microcontroller.Microcontroller(
            self.schematicInfo, self.microcontrollerList, self.clarg1,
            track=self.obj_track)
        self.microcontrollerTab.setWidget(self.obj_microcontroller)
        self.microcontrollerTab.setWidgetResizable(True)

        self.tabWidget = QtWidgets.QTabWidget()
        # self.tabWidget.TabShape(QtWidgets.QTabWidget.Rounded)
        self.tabWidget.addTab(self.analysisTab, "Analysis")
        self.tabWidget.addTab(self.sourceTab, "Source Details")
        self.tabWidget.addTab(self.modelTab, "Ngspice Model")
        self.tabWidget.addTab(self.deviceModelTab, "Device Modeling")
        self.tabWidget.addTab(self.subcircuitTab, "Subcircuits")
        self.tabWidget.addTab(self.microcontrollerTab, "Microcontroller")
        # Contextual fullscreen toggle in the tab-bar corner (not a global
        # toolbar): fullscreen this converter panel and dock it back.
        from frontEnd.FullScreen import FullScreenToggle
        self.tabWidget.setCornerWidget(FullScreenToggle())
        self.mainLayout = QtWidgets.QVBoxLayout()
        self.mainLayout.addWidget(self.tabWidget)
        # self.mainLayout.addStretch(1)
        self.convertWindow.setLayout(self.mainLayout)
        # No show() here: convertWindow is parentless at this point, so
        # showing it opens a brief top-level window (the "flash" popup)
        # before addWidget() reparents it into the converter layout. The
        # caller's addWidget() makes it visible with its parent instead.

        return self.convertWindow

    def _sourceChangedOnDisk(self):
        """True if the .cir was re-exported since this window last parsed it.

        The converter parses the netlist once and caches it in the module
        globals the tabs read from; this mtime check is the cache-invalidation
        signal that tells callConvert the cache is dirty.
        """
        try:
            return os.path.getmtime(self.kicadFile) != self._netlist_mtime
        except OSError:
            return False

    def reloadNetlist(self):
        """Re-parse the .cir and rebuild the converter tabs in place.

        Called when the source schematic changed under an open window so the
        UI and the in-memory model both reflect the current netlist before any
        conversion. Field values that still apply are restored from
        *_Previous_Values.xml by the rebuilt tabs.

        Returns True if the reload aborted (unknown/duplicate/empty model), in
        which case the old tabs have already been torn down and the model is
        marked invalid.
        """
        # Drop the existing tab widget (and its child tabs) before reparsing.
        item = self.convertContainer.takeAt(0)
        if item is not None:
            old = item.widget()
            if old is not None:
                old.setParent(None)
                old.deleteLater()

        try:
            load_aborted = self._loadNetlist()
        except Exception as exc:
            self._surface_conversion_failure(
                exc,
                "Netlist reload failed",
                "Correct the reported schematic or model-library problem, "
                "then retry the conversion.",
            )
            return True

        if load_aborted:
            return True

        self.convertContainer.addWidget(self.createcreateConvertWidget())
        return False

    def callConvert(self):
        """
        - This function called when convert button clicked
        - Extracting data from the objs created above
        - Pushing this data to xml, and writing it finally
        - Written to the per-user ..._Previous_Values.xml cache under
          ~/.esim/prevvalues/ (see projectPaths.previous_values_path); the
          cache deliberately lives outside the shareable project folder
        - Finally, call createNetListFile, with the converted schematic
        """
        # self.analysisoutput is kept for reference; self.schematicInfo is
        # only read here (snapshotted below).

        # If the schematic was re-exported while this window stayed open, the
        # parse-once state is stale. Reload from disk (rebuilding the tabs)
        # rather than serializing the old snapshot, then let the user review
        # the refreshed fields and convert again. This is the root-cause fix
        # for "convert only works the first time in a tab".
        if self._sourceChangedOnDisk():
            if not self.reloadNetlist():
                Dialogs.information(
                    self, "Netlist refreshed",
                    "The schematic changed since this converter window was "
                    "opened, so it has been refreshed from the new netlist. "
                    "Review the fields and click Convert again.",
                    QtWidgets.QMessageBox.StandardButton.Ok
                )
            return

        # A reload may have aborted on a broken netlist; never serialize one.
        if not self._netlistValid:
            return

        store_schematicInfo = list(self.schematicInfo)
        check = 1

        try:
            # Close the handle before the os.replace() below: an open reader
            # on the same file makes the replace fail on Windows (WinError 5).
            with open(previous_values_path(self.kicadFile), 'r') as fr:
                temp_tree = ET.parse(fr)
            temp_root = temp_tree.getroot()
        except Exception:
            check = 0

        # Opening previous value file pertaining to the selected project
        fw = previous_values_path(self.kicadFile)

        if check == 0:
            attr_parent = ET.Element("KicadtoNgspice")
        if check == 1:
            attr_parent = temp_root

        for child in attr_parent:
            if child.tag == "analysis":
                attr_parent.remove(child)

        attr_analysis = ET.SubElement(attr_parent, "analysis")
        attr_ac = ET.SubElement(attr_analysis, "ac")

        if self.obj_analysis.Lin.isChecked():
            ET.SubElement(attr_ac, "field1", name="Lin").text = "true"
            ET.SubElement(attr_ac, "field2", name="Dec").text = "false"
            ET.SubElement(attr_ac, "field3", name="Oct").text = "false"
        elif self.obj_analysis.Dec.isChecked():
            ET.SubElement(attr_ac, "field1", name="Lin").text = "false"
            ET.SubElement(attr_ac, "field2", name="Dec").text = "true"
            ET.SubElement(attr_ac, "field3", name="Oct").text = "false"
        if self.obj_analysis.Oct.isChecked():
            ET.SubElement(attr_ac, "field1", name="Lin").text = "false"
            ET.SubElement(attr_ac, "field2", name="Dec").text = "false"
            ET.SubElement(attr_ac, "field3", name="Oct").text = "true"

        ET.SubElement(
            attr_ac, "field4", name="Start Frequency"
        ).text = str(self.obj_analysis.ac_entry_var[0].text())
        ET.SubElement(
            attr_ac, "field5", name="Stop Frequency"
        ).text = str(self.obj_analysis.ac_entry_var[1].text())
        ET.SubElement(
            attr_ac, "field6", name="No. of points"
        ).text = str(self.obj_analysis.ac_entry_var[2].text())
        ET.SubElement(
            attr_ac, "field7", name="Start Fre Combo"
        ).text = self.obj_analysis.ac_parameter[0]
        ET.SubElement(
            attr_ac, "field8", name="Stop Fre Combo"
        ).text = self.obj_analysis.ac_parameter[1]

        attr_dc = ET.SubElement(attr_analysis, "dc")

        ET.SubElement(
            attr_dc, "field1", name="Source 1"
        ).text = str(self.obj_analysis.dc_entry_var[0].text())
        ET.SubElement(
            attr_dc, "field2", name="Start"
        ).text = str(self.obj_analysis.dc_entry_var[1].text())
        ET.SubElement(
            attr_dc, "field3", name="Increment"
        ).text = str(self.obj_analysis.dc_entry_var[2].text())
        ET.SubElement(
            attr_dc, "field4", name="Stop"
        ).text = str(self.obj_analysis.dc_entry_var[3].text())
        # print("OBJ_ANALYSIS.CHECK -----", self.obj_track.op_check[-1])
        ET.SubElement(
            attr_dc, "field5", name="Operating Point"
        ).text = str(self.obj_track.op_check[-1]
                     if self.obj_track.op_check else '0')
        ET.SubElement(
            attr_dc, "field6", name="Start Combo"
        ).text = self.obj_analysis.dc_parameter[0]
        ET.SubElement(
            attr_dc, "field7", name="Increment Combo"
        ).text = self.obj_analysis.dc_parameter[1]
        ET.SubElement(
            attr_dc, "field8", name="Stop Combo"
        ).text = self.obj_analysis.dc_parameter[2]
        ET.SubElement(
            attr_dc, "field9", name="Source 2"
        ).text = str(self.obj_analysis.dc_entry_var[4].text())
        ET.SubElement(
            attr_dc, "field10", name="Start"
        ).text = str(self.obj_analysis.dc_entry_var[5].text())
        ET.SubElement(
            attr_dc, "field11", name="Increment"
        ).text = str(self.obj_analysis.dc_entry_var[6].text())
        ET.SubElement(
            attr_dc, "field12", name="Stop"
        ).text = str(self.obj_analysis.dc_entry_var[7].text())
        ET.SubElement(
            attr_dc, "field13", name="Start Combo"
        ).text = self.obj_analysis.dc_parameter[3]
        ET.SubElement(
            attr_dc, "field14", name="Increment Combo"
        ).text = self.obj_analysis.dc_parameter[4]
        ET.SubElement(
            attr_dc, "field15", name="Stop Combo"
        ).text = self.obj_analysis.dc_parameter[5]

        attr_tran = ET.SubElement(attr_analysis, "tran")
        ET.SubElement(
            attr_tran, "field1", name="Start Time"
        ).text = str(self.obj_analysis.tran_entry_var[0].text())
        ET.SubElement(
            attr_tran, "field2", name="Step Time"
        ).text = str(self.obj_analysis.tran_entry_var[1].text())
        ET.SubElement(
            attr_tran, "field3", name="Stop Time"
        ).text = str(self.obj_analysis.tran_entry_var[2].text())
        ET.SubElement(
            attr_tran, "field4", name="Start Combo"
        ).text = self.obj_analysis.tran_parameter[0]
        ET.SubElement(
            attr_tran, "field5", name="Step Combo"
        ).text = self.obj_analysis.tran_parameter[1]
        ET.SubElement(
            attr_tran, "field6", name="Stop Combo"
        ).text = self.obj_analysis.tran_parameter[2]
        # print("TRAN PARAMETER 2-----",self.obj_analysis.tran_parameter[2])

        # attr_source must always be bound before the serialization loop
        # below. A prevvalues cache that has no <source> node (corrupt or
        # from an older schematic revision) used to leave it unassigned ->
        # UnboundLocalError at "for child in attr_source".
        attr_source = None
        if check == 1:
            for child in attr_parent:
                if child.tag == "source":
                    attr_source = child
                    break
        if attr_source is None:
            attr_source = ET.SubElement(attr_parent, "source")

        count = 0
        grand_child_count = 0
        entry_var_keys = list(self.obj_source.entry_var.keys())

        for i in store_schematicInfo:
            tmp_check = 0
            words = i.split(' ')
            wordv = words[0]
            for child in attr_source:
                if child.tag == wordv and child.text == words[len(words) - 1]:
                    tmp_check = 1
                    for grand_child in child:
                        # Source-type drift (remembered XML carries more
                        # source fields than the live tab now has) used to
                        # index past entry_var_keys -> IndexError.
                        # Stop restoring once the live fields run out.
                        if grand_child_count >= len(entry_var_keys):
                            break
                        grand_child.text = \
                            str(self.obj_source.entry_var
                                [entry_var_keys[grand_child_count]].text())
                        grand_child_count += 1
            if tmp_check == 0:
                words = i.split(' ')
                wordv = words[0]
                if wordv[0] == "v" or wordv[0] == "i":
                    attr_var = ET.SubElement(
                        attr_source, words[0], name="Source type"
                    )
                    attr_var.text = words[len(words) - 1]
                    # ET.SubElement(
                    #     attr_ac, "field1", name="Lin").text = "true"
                if words[len(words) - 1] == "ac":
                    # attr_ac = ET.SubElement(attr_var, "ac")
                    ET.SubElement(
                        attr_var, "field1", name="Amplitude"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field2", name="Phase"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                elif words[len(words) - 1] == "dc":
                    # attr_dc = ET.SubElement(attr_var, "dc")
                    ET.SubElement(
                        attr_var, "field1", name="Value"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                elif words[len(words) - 1] == "sine":
                    # attr_sine = ET.SubElement(attr_var, "sine")
                    ET.SubElement(
                        attr_var, "field1", name="Offset Value"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field2", name="Amplitude"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field3", name="Frequency"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field4", name="Delay Time"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field5", name="Damping Factor"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                elif words[len(words) - 1] == "pulse":
                    # attr_pulse=ET.SubElement(attr_var,"pulse")
                    ET.SubElement(
                        attr_var, "field1", name="Initial Value"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field2", name="Pulse Value"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field3", name="Delay Time"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field4", name="Rise Time"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field5", name="Fall Time"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    # Was field5 for all three (Fall Time / Pulse width /
                    # Period), so two values collided under one tag. Restore
                    # reads children positionally, so old files stay readable.
                    ET.SubElement(
                        attr_var, "field6", name="Pulse width"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field7", name="Period"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                elif words[len(words) - 1] == "pwl":
                    # attr_pwl=ET.SubElement(attr_var,"pwl")
                    ET.SubElement(
                        attr_var, "field1", name="Enter in pwl format"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                elif words[len(words) - 1] == "exp":
                    # attr_exp=ET.SubElement(attr_var,"exp")
                    ET.SubElement(
                        attr_var, "field1", name="Initial Value"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field2", name="Pulsed Value"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field3", name="Rise Delay Time"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field4", name="Rise Time Constant"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field5", name="Fall Time"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1
                    ET.SubElement(
                        attr_var, "field6", name="Fall Time Constant"
                    ).text = str(self.obj_source.entry_var
                                 [entry_var_keys[count]].text())
                    count += 1

        if check == 0:
            attr_model = ET.SubElement(attr_parent, "model")
        if check == 1:
            for child in attr_parent:
                if child.tag == "model":
                    attr_model = child
        i = 0

        # tmp_check is a variable to check for duplicates in the xml file
        tmp_check = 0
        # tmp_i is the iterator in case duplicates are there;
        # then in that case we need to replace only the child node and
        # not create a new parent node

        for line in self.modelList:
            tmp_check = 0
            # Init before the scan: an unmatched modelTrack entry used to leave
            # start/end unbound -> NameError swallowed into a silent close.
            start = end = -1
            for rand_itr in self.obj_model.obj_trac.modelTrack:
                if rand_itr[2] == line[2] and rand_itr[3] == line[3]:
                    start = rand_itr[7]
                    end = rand_itr[8]
            if start == -1:
                continue

            i = start
            for child in attr_model:
                if child.text == line[2] and child.tag == line[3]:
                    for grand_child in child:
                        if i <= end and i < len(
                                self.obj_model.obj_trac.model_entry_var):
                            grand_child.text = \
                                str(self.obj_model.obj_trac.model_entry_var[
                                        i].text())
                            i = i + 1
                    tmp_check = 1

            if tmp_check == 0:
                attr_ui = ET.SubElement(attr_model, line[3], name="type")
                attr_ui.text = line[2]
                for key, value in line[7].items():
                    if (
                        hasattr(value, '__iter__') and
                        i <= end and not isinstance(value, str)
                    ):
                        for item in value:
                            # Guard the parallel index walk: a model whose
                            # tracked range outruns model_entry_var used to
                            # IndexError here. Stop at the live end.
                            if i >= len(
                                    self.obj_model.obj_trac.model_entry_var):
                                break
                            ET.SubElement(
                                attr_ui, "field" + str(i + 1), name=item
                            ).text = str(
                                self.obj_model.obj_trac.model_entry_var[i].text()
                            )
                            i = i + 1

                    elif i < len(self.obj_model.obj_trac.model_entry_var):
                        ET.SubElement(
                            attr_ui, "field" + str(i + 1), name=value
                        ).text = str(
                            self.obj_model.obj_trac.model_entry_var[i].text()
                        )
                        i = i + 1

        # Writing Device Model values
        if check == 0:
            attr_devicemodel = ET.SubElement(attr_parent, "devicemodel")
        if check == 1:
            for child in attr_parent:
                if child.tag == "devicemodel":
                    del child[:]
                    attr_devicemodel = child

        for device in self.obj_devicemodel.devicemodel_dict_beg:
            attr_var = ET.SubElement(attr_devicemodel, device)
            it = self.obj_devicemodel.devicemodel_dict_beg[device]
            end = self.obj_devicemodel.devicemodel_dict_end[device]

            while it <= end:
                widget = self.obj_devicemodel.entry_var[it]
                # Handle both QComboBox (uses currentText) and QLineEdit (uses text)
                if hasattr(widget, 'currentText'):
                    widget_text = str(widget.currentText())
                else:
                    widget_text = str(widget.text())
                ET.SubElement(attr_var, "field").text = widget_text
                it = it + 1

        # Writing Subcircuit values
        if check == 0:
            attr_subcircuit = ET.SubElement(attr_parent, "subcircuit")
        if check == 1:
            for child in attr_parent:
                if child.tag == "subcircuit":
                    del child[:]
                    attr_subcircuit = child

        for subckt in self.obj_subcircuitTab.subcircuit_dict_beg:
            attr_var = ET.SubElement(attr_subcircuit, subckt)
            it = self.obj_subcircuitTab.subcircuit_dict_beg[subckt]
            end = self.obj_subcircuitTab.subcircuit_dict_end[subckt]

            while it <= end:
                ET.SubElement(attr_var, "field").text = \
                    str(self.obj_subcircuitTab.entry_var[it].text())
                it = it + 1

        # Writing for Microcontroller
        if check == 0:
            attr_microcontroller = ET.SubElement(attr_parent,
                                                 "microcontroller")
        if check == 1:
            for child in attr_parent:
                if child.tag == "microcontroller":
                    attr_microcontroller = child
        i = 0

        # tmp_check is a variable to check for duplicates in the xml file
        tmp_check = 0
        # tmp_i is the iterator in case duplicates are there;
        # then in that case we need to replace only the child node and
        # not create a new parent node

        for line in self.microcontrollerList:
            tmp_check = 0
            start = end = -1
            for rand_itr in self.obj_microcontroller.obj_trac.microcontrollerTrack:
                if rand_itr[2] == line[2] and rand_itr[3] == line[3]:
                    start = rand_itr[7]
                    end = rand_itr[8]
            if start == -1:
                continue

            i = start
            for child in attr_microcontroller:
                if child.text == line[2] and child.tag == line[3]:
                    for grand_child in child:
                        if i <= end and i < len(
                                self.obj_microcontroller
                                .obj_trac.microcontroller_var):
                            grand_child.text = \
                                str(
                                    self.obj_microcontroller.
                                    obj_trac.microcontroller_var[i].text())
                            i = i + 1
                    tmp_check = 1

            if tmp_check == 0:
                attr_ui = ET.SubElement(attr_microcontroller, line[3],
                                        name="type")
                attr_ui.text = line[2]
                for key, value in line[7].items():
                    if (
                            hasattr(value, '__iter__') and
                            i <= end and not isinstance(value, str)
                    ):
                        for item in value:
                            if i >= len(
                                    self.obj_microcontroller
                                    .obj_trac.microcontroller_var):
                                break
                            ET.SubElement(
                                attr_ui, "field" + str(i + 1), name=item
                            ).text = str(
                                self.obj_microcontroller.
                                obj_trac.microcontroller_var[i].text()
                            )
                            i = i + 1
                    elif i < len(
                            self.obj_microcontroller
                            .obj_trac.microcontroller_var):
                        ET.SubElement(
                            attr_ui, "field" + str(i + 1), name=value
                        ).text = str(
                            self.obj_microcontroller.obj_trac.microcontroller_var[
                                i].text()
                        )
                        i = i + 1

        # xml written to previous value file for the project
        tree = ET.ElementTree(attr_parent)
        # Write atomically: a crash mid-write must not leave a half-written
        # (corrupt) cache that every reader then silently discards. Write to a
        # sibling temp file, then os.replace() it into place in one step.
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(fw), suffix='.xml.tmp')
        os.close(tmp_fd)
        try:
            tree.write(tmp_path)
            os.replace(tmp_path, fw)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        # print("=============================================================")
        # print("SOURCE LIST TRACK")
        # print(self.obj_track.sourcelisttrack["ITEMS"])
        # print("SOURCE ENTRY VAR")
        # print(self.obj_track.source_entry_var["ITEMS"])
        # print("SCHEMATIC INFO")
        # print(store_schematicInfo)
        # print("=============================================================")

        # Create Convert object with the source details & the schematic details
        self.obj_convert = Convert.Convert(
            self.obj_track.sourcelisttrack["ITEMS"],
            self.obj_track.source_entry_var["ITEMS"],
            store_schematicInfo, self.clarg1, track=self.obj_track
        )

        try:
            # Adding Source Value to Schematic Info
            store_schematicInfo = self.obj_convert.addSourceParameter()
            print("=========================================================")
            print("Netlist After Adding Source details :", store_schematicInfo)

            # Adding Model Value to store_schematicInfo
            store_schematicInfo = self.obj_convert.addModelParameter(
                store_schematicInfo)
            print("=========================================================")
            print("Netlist After Adding Ngspice Model :", store_schematicInfo)

            store_schematicInfo = self.obj_convert.addMicrocontrollerParameter(
                store_schematicInfo)
            print("=========================================================")
            print("Netlist After Adding Microcontroller Model :",
                  store_schematicInfo)

            # Adding Device Library to SchematicInfo
            store_schematicInfo = self.obj_convert.addDeviceLibrary(
                store_schematicInfo, self.kicadFile)
            print("=========================================================")
            print(
                "Netlist After Adding Device Model Library :",
                store_schematicInfo)

            # Adding Subcircuit Library to SchematicInfo
            store_schematicInfo = self.obj_convert.addSubcircuit(
                store_schematicInfo, self.kicadFile)
            print("=========================================================")
            print("Netlist After Adding subcircuits :", store_schematicInfo)

            # Per-component builders collect failures so the user sees every
            # bad field/model in one pass. Never emit a partially converted
            # netlist as a successful result.
            self.obj_convert.raise_for_errors()

            self.analysisoutput = self.obj_convert.analysisInsertor(
                self.obj_track.AC_entry_var["ITEMS"],
                self.obj_track.DC_entry_var["ITEMS"],
                self.obj_track.TRAN_entry_var["ITEMS"],
                self.obj_track.set_CheckBox["ITEMS"],
                self.obj_track.AC_Parameter["ITEMS"],
                self.obj_track.DC_Parameter["ITEMS"],
                self.obj_track.TRAN_Parameter["ITEMS"],
                self.obj_track.AC_type["ITEMS"],
                self.obj_track.op_check
            )
            print("=========================================================")
            print("Analysis OutPut ", self.analysisoutput)

            # Calling netlist file generation function
            print("=========================================================")
            print("STORE SCHEMATIC INFO")
            print(store_schematicInfo)
            print("=========================================================")
            self.createNetlistFile(store_schematicInfo, self.plotText)

            # Remember each model's chosen library across projects (a hint for
            # pre-filling the same model in future conversions). Best-effort:
            # a cache write must never fail a completed conversion.
            try:
                from projManagement import modelCache
                learned = {}
                learned.update(self.obj_devicemodel.remembered_models())
                learned.update(self.obj_subcircuitTab.remembered_models())
                modelCache.remember_many(learned)
            except Exception as cache_err:
                print("model_cache update skipped:", cache_err)

        except Exception as e:
            self._surface_conversion_failure(
                e,
                "Conversion failed",
                "Review the Analysis and model values, correct the reported "
                "problem, and click Convert again.",
            )
            return

        # Generate .sub file from .cir.out file if it is a subcircuit
        subPath = os.path.splitext(self.kicadFile)[0]

        # If sub argument passed, create subCircuit file as well.
        #
        # The report comes AFTER the .sub is written, and describes it. The
        # generic "conversion completed successfully!" used to fire first, so a
        # subcircuit whose schematic had no PORT element announced success and
        # then immediately raised an error about the file it had not written --
        # and on the way through, never said where the .sub landed or what
        # ports it ended up with, which is the entire deliverable.
        if self.clarg2 == "sub":
            # Read the OUTGOING model's port count before it is replaced: a
            # rebuild that changes it silently breaks every parent circuit
            # already wired to this subcircuit, and that is the one outcome
            # the user must not discover later (see _reportSubcircuitBuilt).
            previous = self._subcktPortCount(subPath + ".sub")
            if self.createSubFile(subPath):
                self._reportSubcircuitBuilt(subPath, previous)
            return

        self.msg = "The KiCad to Ngspice conversion completed "
        self.msg += "successfully!"
        Dialogs.information(
            self, "Information", self.msg,
            QtWidgets.QMessageBox.StandardButton.Ok
        )

    def _subcktHeader(self, sub_file):
        """The ``.subckt`` line of a ``.sub``, or '' when there is none."""
        try:
            with open(sub_file, errors='replace') as fh:
                for line in fh:
                    if line.strip().lower().startswith('.subckt'):
                        return line.strip()
        except OSError:
            pass
        return ""

    def _subcktPortCount(self, sub_file):
        """Number of ports an existing ``.sub`` declares, or None if there is
        no readable model there yet."""
        header = self._subcktHeader(sub_file)
        return len(header.split()) - 2 if header else None

    def _reportSubcircuitBuilt(self, subPath, previous_ports=None):
        """Tell the user what Convert actually produced.

        The ngspice model is the point of the whole Subcircuit Builder, and
        until now its creation was reported only to stdout. Name the file, and
        echo back the ``.subckt`` header so the port list can be checked
        against the parent circuit's symbol without opening anything.

        ``previous_ports`` is the port count of the model that was just
        replaced. When it changed, say so first and plainly: a subcircuit's
        port count is its interface, so every schematic that already
        instantiates this block is now mis-wired, and nothing else in eSim
        would tell them. It happens for real -- a handful of subcircuits in
        eSim's own library ship a ``.kicad_sch`` that is a different revision
        from the ``.cir``/``.sub`` beside it, so the first honest rebuild
        changes the interface.
        """
        outfile = subPath + ".sub"
        name = os.path.basename(outfile)
        header = self._subcktHeader(outfile)

        detail = outfile
        ports = header.split()[2:] if header else []
        if header:
            detail += "\n\n%s\n\n%d port%s: %s" % (
                header, len(ports), "" if len(ports) == 1 else "s",
                ", ".join(ports) if ports else "none")

        if header and previous_ports is not None \
                and previous_ports != len(ports):
            Dialogs.warning(
                self, "Subcircuit ports changed",
                "%s now has %d ports; it had %d."
                % (name, len(ports), previous_ports),
                informative_text=(
                    "Any schematic that already uses this subcircuit is wired "
                    "for the old interface and will need its symbol and "
                    "connections updated.\n\n" + detail))
            return

        Dialogs.information(
            self, "Subcircuit built", "Created " + name,
            informative_text=detail)

    def createNetlistFile(self, store_schematicInfo, plotText):
        """
        - Creating .cir.out file
        - If analysis file present uses that and extract
            - Simulator
            - Initial
            - Analysis
        - Finally add the following components to .cir.out file
            - SimulatorOption
            - InitialCondOption
            - Store_SchematicInfo
            - AnalysisOption
        - In the end add control statements and allv, alli, end statements
        """
        print("=============================================================")
        print("Creating Final netlist")

        # Two or more d_cosim blocks become ONE device running a generated
        # wrapper that instantiates all of them. Icarus's engine is
        # process-global and single-shot, so a second device would segfault
        # ngspice -- but the limit is one engine per process, not one block per
        # schematic. See merge_dcosim_blocks / maker/cosim_merge.py.
        if dcosim_instance_count(store_schematicInfo) > 1:
            from maker.CosimLogger import CosimLog
            from maker.cosim_merge import MergeError
            log = CosimLog()
            try:
                store_schematicInfo = merge_dcosim_blocks(
                    store_schematicInfo,
                    os.path.dirname(self.kicadFile), log)
            except MergeError as exc:
                log.error(str(exc))
                raise RuntimeError(str(exc)) from exc

        # NOTE: collapse_adc_band_for_hdl() is deliberately NOT called here.
        # It is measured, tested and parked -- see docs/UPSTREAM_DECISIONS.md
        # item 1. Rewriting in_low/in_high changes the numbers eSim 2.5
        # produced for a schematic that already worked, which is a decision for
        # the eSim maintainers, not for this branch. The netlist therefore
        # leaves every adc_bridge card exactly as 2.5 wrote it.
        #
        # The double-clocking this used to prevent is handled entirely inside
        # the d_cosim backend instead (ModelGeneration.cosim_wrapper_source),
        # by reading x as 1 the way NgVeri's generated C already does. To
        # evaluate the netlist-level fix, call it here.

        # To avoid writing optionInfo twice in final netlist
        store_optionInfo = list(self.optionInfo)
        # Work on a copy of the output options too: appending to the instance
        # list accumulated duplicate .save/.print/.plot lines on every reconvert
        # in the same window. createNetlistFile must stay a pure function of its
        # inputs.
        store_outputOption = list(self.outputOption)

        # checking if analysis files is present
        (projpath, filename) = os.path.split(self.kicadFile)
        analysisFileLoc = os.path.join(projpath, "analysis")

        if not os.path.exists(analysisFileLoc):
            raise RuntimeError(
                "Analysis file could not be created — check the Analysis tab "
                "values."
            )

        try:
            with open(analysisFileLoc) as analysis_file:
                data = analysis_file.read()
        except OSError as exc:
            raise RuntimeError(
                f"Analysis file could not be read: {analysisFileLoc}: {exc}"
            ) from exc

        # Adding analysis file info to optionInfo
        analysisData = data.splitlines()
        for eachline in analysisData:
            eachline = eachline.strip()
            if len(eachline) > 1:
                if eachline[0] == '.':
                    store_optionInfo.append(eachline)

        analysisOption = []
        initialCondOption = []
        simulatorOption = []
        # includeOption=[]  # Don't know why to use it
        # model = []      # Don't know why to use it

        for eachline in store_optionInfo:
            words = eachline.split()
            option = words[0]
            if (option == '.ac' or option == '.dc' or option ==
                    '.disto' or option == '.noise' or
                    option == '.op' or option == '.pz' or option ==
                    '.sens' or option == '.tf' or
                    option == '.tran'):
                analysisOption.append(eachline + '\n')

            elif (option == '.save' or option == '.print' or option ==
                  '.plot' or option == '.four'):
                eachline = eachline.strip('.')
                store_outputOption.append(eachline + '\n')
            elif (option == '.nodeset' or option == '.ic'):
                initialCondOption.append(eachline + '\n')
            elif option == '.option':
                simulatorOption.append(eachline + '\n')
            # elif (option=='.include' or option=='.lib'):
            #    includeOption.append(eachline+'\n')
            # elif (option=='.model'):
            #    model.append(eachline+'\n')
            elif option == '.end':
                continue

        # Start creating final netlist cir.out file
        outfile = self.kicadFile + ".out"
        out = open(outfile, "w")
        out.writelines(self.infoline)
        out.writelines('\n')
        # Verilog co-simulators loaded by the d_cosim code model (Icarus
        # ivlng/vvp) are one-shot: the vvp runs to completion once and cannot be
        # reset. With `ngspice -b`, an analysis *card* (.tran/.ac/...) is
        # auto-run, and a `.control` `run` runs it a second time -- that pass
        # reuses the finished vvp ("already run", 0 ports, mismatched counts).
        # For such netlists, run the analysis exactly once inside `.control` and
        # drop the analysis card. Non-d_cosim netlists are unchanged.
        uses_dcosim = any(
            'd_cosim' in str(line).lower() for line in store_schematicInfo)

        sections = [
            simulatorOption,
            initialCondOption,
            store_schematicInfo,
            analysisOption]

        for section in sections:
            if uses_dcosim and section is analysisOption:
                continue        # moved into .control below (single run)
            if len(section) == 0:
                continue
            else:
                for line in section:
                    out.writelines('\n')
                    out.writelines(line)

        out.writelines('\n* Control Statements \n')
        out.writelines('.control\n')
        out.writelines('set width=1000\n')
        if uses_dcosim:
            for line in analysisOption:
                # '.tran 1e-3 15e-3 0' -> 'tran 1e-3 15e-3 0' (runs once)
                out.writelines(line.strip().lstrip('.') + '\n')
        else:
            out.writelines('run\n')
        # out.writelines(store_outputOption)
        out.writelines('print allv > plot_data_v.txt\n')
        out.writelines('print alli > plot_data_i.txt\n')
        # `print allv` truncates column names to ~15 chars, so distinct long
        # node names (e.g. plot_vout_bit_10..31) collapse to the same string in
        # the plot legend. Also dump an ASCII rawfile, whose Variables section
        # keeps FULL names in the same column order; data_extraction uses it to
        # recover the real names (count-guarded, falls back if absent).
        out.writelines('set filetype=ascii\n')
        out.writelines('write plot_data.raw\n')
        if uses_dcosim:
            # A d_cosim netlist has no bare analysis card -- the .tran was
            # moved into .control above so the one-shot Icarus engine runs
            # exactly once. That also means ngspice's own `-r <project>.raw`
            # has no analysis left to run in the deck and writes nothing, so
            # the project rawfile that every other backend leaves behind was
            # simply absent after a co-simulation (and any rawfile from an
            # earlier run stayed there, stale, for gaw to pick up). Write it
            # from here instead, keeping the on-disk result of a run the same
            # whichever backend produced it. Relative name: ngspice's working
            # directory is the project directory, so the netlist stays
            # portable.
            out.writelines(
                'write %s.raw\n'
                % os.path.basename(os.path.splitext(self.kicadFile)[0]))
        event_nodes = _get_event_plot_nodes(store_schematicInfo, plotText)
        if event_nodes:
            out.writelines('eprint ' + ' '.join(event_nodes)
                           + ' > plot_data_event.txt\n')
        # eSim always launches ngspice with `-b`, where `plot` is unavailable --
        # every one of these emitted "Warning: command 'plot' is not available
        # during batch simulation, ignored!" into the user's console, once per
        # plotted node, on every single run. eSim draws the waveforms itself
        # from plot_data_v.txt / plot_data.raw, so the warnings bought nothing.
        # Keep the lines (a .cir.out is also meant to be runnable by hand) but
        # let only an interactive ngspice reach them: `-b` defines `batchmode`,
        # `-i` does not.
        if plotText:
            out.writelines('if $?batchmode = 0\n')
            for item in plotText:
                out.writelines('  ' + item + '\n')
            out.writelines('end\n')
        out.writelines('.endc\n')
        out.writelines('.end\n')
        out.close()

    def createSubFile(self, subPath):
        """
        - To create subcircuit file
        - Extract data from .cir.out file

        Returns True when the ``.sub`` was written, False when it could not be
        (missing ``.cir.out``, unreadable, or a schematic with no PORT). The
        caller reports the result, so it must be able to tell the difference --
        it used to announce success before this ran.
        """
        self.project = subPath
        self.projName = os.path.basename(self.project)
        cirOut = self.project + ".cir.out"
        if not os.path.exists(cirOut):
            Dialogs.critical(
                self, "Subcircuit creation failed",
                self.projName + ".cir.out does not exist. "
                "Please create a spice netlist first.")
            return False
        try:
            with open(cirOut) as f:
                data = f.read()
        except OSError as e:
            Dialogs.critical(
                self, "Subcircuit creation failed",
                "Error opening " + self.projName + ".cir.out: " + str(e))
            return False

        newNetlist = []
        subcktInfo = None
        netlist = iter(data.splitlines())
        for eachline in netlist:
            eachline = eachline.strip()
            if len(eachline) < 1:
                continue
            words = eachline.split()
            # The PORT element defines the subcircuit's interface, and it is
            # the ONE line here that is always commented out: PORT is not a
            # real spice device, so Processing.convertICintoBasicBlocks
            # rewrites every u-component it cannot expand as "* <line>" on its
            # way into the .cir.out. Matching on words[0] therefore never
            # fired -- it saw the "*" -- and every conversion ended in "No PORT
            # component found in the schematic", with no .sub produced. Drop a
            # leading comment marker before looking, so the line is recognised
            # in either form.
            port_words = words[1:] if words[0] == '*' else words
            if (len(port_words) > 2 and port_words[0].startswith('u')
                    and port_words[-1] == "port"):
                # Ports are the nets between the reference and the PORT value.
                # Indexing off the normalised tokens also fixes a latent
                # off-by-one: the old slice started at 2, which was right for
                # the commented line it never matched and would have dropped
                # the first net on an uncommented one.
                subcktInfo = ".subckt " + self.projName + " "
                for word in port_words[1:-1]:
                    subcktInfo += word + " "
                continue
            if (
                words[0] == ".end" or
                words[0] == ".ac" or
                words[0] == ".dc" or
                words[0] == ".tran" or
                words[0] == '.disto' or
                words[0] == '.noise' or
                words[0] == '.op' or
                words[0] == '.pz' or
                words[0] == '.sens' or
                words[0] == '.tf'
            ):
                continue
            elif words[0] == ".control":
                # Skip through the .control block. If .endc is missing
                # (hand-edited .cir.out), the shared iterator simply
                # exhausts and the outer for-loop ends — no StopIteration
                # escapes as it did with next().
                for ctrl_line in netlist:
                    ctrl_words = ctrl_line.strip().split()
                    if ctrl_words and ctrl_words[0] == ".endc":
                        break
            else:
                newNetlist.append(eachline)

        if subcktInfo is None:
            Dialogs.critical(
                self, "Subcircuit creation failed",
                "No PORT component found in the schematic — a subcircuit "
                "needs a port element.")
            return False

        outfile = self.project + ".sub"
        out = open(outfile, "w")
        out.writelines("* Subcircuit " + self.projName)
        out.writelines('\n')
        out.writelines(subcktInfo)
        out.writelines('\n')

        for i in range(len(newNetlist), 0, -1):
            newNetlist.insert(i, '\n')

        out.writelines(newNetlist)
        out.writelines('\n')

        out.writelines('.ends ' + self.projName)
        # print("=============================================================")
        print("The subcircuit has been written in " + self.projName + ".sub")
        return True
