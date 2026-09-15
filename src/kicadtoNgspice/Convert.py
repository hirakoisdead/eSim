import os
import shutil
from xml.etree import ElementTree as ET

from configuration import Dialogs

from . import TrackWidget
from maker import CosimConfig
from maker.CosimLogger import CosimLog


def _star_encode(path):
    """Wrap every uppercase char as ``*C**`` to protect it from the netlist
    lowercasing (the decoder on the ngspice/nghdl side expects this framing).

    A single linear pass -- the old code called ``path.index(c)`` which returns
    the *first* occurrence, so a path with a repeated uppercase letter (e.g.
    ``/home/U/ADC/ADC.hex``) computed the wrong insertion point and corrupted.
    """
    return ''.join('*' + c + '**' if c.isupper() else c for c in path)


class Convert:
    """
    - This class has all the necessary function required to convert \
      kicad netlist to ngspice netlist.
    - Method List
        - addDeviceLibrary
        - addModelParameter
        - addSourceParameter
        - addSubcircuit
        - analysisInsertor
        - converttosciform
        - defaultvalue
    """

    def __init__(self, sourcelisttrack, source_entry_var,
                 schematicInfo, clarg1, track=None):
        self.sourcelisttrack = sourcelisttrack
        self.schematicInfo = schematicInfo
        self.entry_var = source_entry_var
        self.sourcelistvalue = []
        self.clarg1 = clarg1
        self.errors = []
        # The converter's shared data bus, injected by the converter window so
        # every tab and this Convert read/write the same instance. A standalone
        # construction (e.g. tests exercising a single method) falls back to a
        # private instance.
        self.obj_track = track if track is not None else \
            TrackWidget.TrackWidget()

    def _record_error(self, component, exc):
        """Collect one component failure so conversion can abort as a unit."""
        message = f"{component}: {exc}"
        self.errors.append(message)
        print("Conversion error:", message)

    def raise_for_errors(self):
        """Abort before output is written when any component was incomplete."""
        if self.errors:
            details = "\n".join(f"- {error}" for error in self.errors)
            raise RuntimeError(
                "Some components could not be converted:\n" + details
            )

    def addSourceParameter(self):
        """
        - This function extracts the source details to schematicInfo
        - keywords recognised and parsed -
            - sine
            - pulse
            - pwl
            - ac
            - dc
            - exp
        - Return updated schematic
        """

        self.start = 0
        self.end = 0

        for compline in self.sourcelisttrack:
            self.index = compline[0]
            self.addline = self.schematicInfo[self.index]
            if compline[1] == 'sine':
                try:
                    self.start = compline[2]
                    self.end = compline[3]
                    vo_val = str(self.entry_var[self.start].text()) if len(
                        str(self.entry_var[self.start].text())) > 0 else '0'
                    va_val = str(
                        self.entry_var[self.start + 1].text()
                    ) if len(
                        str(self.entry_var[self.start + 1].text())) \
                        > 0 else '0'
                    freq_val = str(self.entry_var[self.start + 2].text()) \
                        if len(
                        str(self.entry_var[self.start + 2].text())) > \
                        0 else '0'
                    td_val = str(self.entry_var[self.start + 3].text()) if len(
                        str(self.entry_var[self.start + 3].text())) > \
                        0 else '0'
                    theta_val = str(self.entry_var[self.end].text()) if len(
                        str(self.entry_var[self.end].text())) > 0 else '0'
                    self.addline = self.addline.partition(
                        '(')[0] + "(" + vo_val + " " + va_val + " " + \
                        freq_val + " " + td_val + " " + theta_val + ")"
                    self.sourcelistvalue.append([self.index, self.addline])
                except Exception as exc:
                    self._record_error(self.addline, exc)

            elif compline[1] == 'pulse':
                try:
                    self.start = compline[2]
                    self.end = compline[3]
                    v1_val = str(self.entry_var[self.start].text()) if len(
                        str(self.entry_var[self.start].text())) > 0 else '0'
                    v2_val = str(self.entry_var[self.start + 1].text()) if len(
                        str(self.entry_var[self.start + 1].text())) > \
                        0 else '0'
                    td_val = str(self.entry_var[self.start + 2].text()) \
                        if len(
                        str(self.entry_var[self.start + 2].text())) > \
                        0 else '0'
                    tr_val = str(self.entry_var[self.start + 3].text()) if len(
                        str(self.entry_var[self.start + 3].text())) > \
                        0 else '0'
                    tf_val = str(self.entry_var[self.start + 4].text()) if len(
                        str(self.entry_var[self.start + 4].text())) > \
                        0 else '0'
                    pw_val = str(self.entry_var[self.start + 5].text()) if len(
                        str(self.entry_var[self.start + 5].text())) > \
                        0 else '0'
                    tp_val = str(self.entry_var[self.end].text()) if len(
                        str(self.entry_var[self.end].text())) > 0 else '0'

                    self.addline = self.addline.partition(
                        '(')[0] + "(" + v1_val + " " + v2_val + " " + \
                        td_val + " " + tr_val + " " + tf_val + " " + \
                        pw_val + " " + tp_val + ")"
                    self.sourcelistvalue.append([self.index, self.addline])
                except Exception as exc:
                    self._record_error(self.addline, exc)

            elif compline[1] == 'pwl':
                try:
                    self.start = compline[2]
                    self.end = compline[3]
                    t_v_val = str(self.entry_var[self.start].text()) if len(
                        str(self.entry_var[self.start].text())) > 0 else '0 0'
                    self.addline = self.addline.partition(
                        '(')[0] + "(" + t_v_val + ")"
                    self.sourcelistvalue.append([self.index, self.addline])
                except Exception as exc:
                    self._record_error(self.addline, exc)

            elif compline[1] == 'ac':
                try:
                    self.start = compline[2]
                    self.end = compline[3]
                    va_val = str(self.entry_var[self.start].text()) if len(
                        str(self.entry_var[self.start].text())) > 0 else '0'
                    ph_val = str(self.entry_var[self.start + 1].text()) if len(
                        str(self.entry_var[self.start + 1].text())) > \
                        0 else '0'
                    self.addline = ' '.join(self.addline.split())
                    self.addline = self.addline.partition(
                        'ac')[0] + " " + 'ac' + " " + va_val + " " + ph_val
                    self.sourcelistvalue.append([self.index, self.addline])
                except Exception as exc:
                    self._record_error(self.addline, exc)

            elif compline[1] == 'dc':
                try:
                    self.start = compline[2]
                    self.end = compline[3]
                    v1_val = str(self.entry_var[self.start].text()) if len(
                        str(self.entry_var[self.start].text())) > 0 else '0'
                    self.addline = ' '.join(self.addline.split())
                    self.addline = self.addline.partition(
                        'dc')[0] + " " + 'dc' + " " + v1_val
                    self.sourcelistvalue.append([self.index, self.addline])
                except Exception as exc:
                    self._record_error(self.addline, exc)

            elif compline[1] == 'exp':
                try:
                    self.start = compline[2]
                    self.end = compline[3]
                    v1_val = str(self.entry_var[self.start].text()) if len(
                        str(self.entry_var[self.start].text())) > 0 else '0'
                    v2_val = str(self.entry_var[self.start + 1].text()) if len(
                        str(self.entry_var[self.start + 1].text())) > \
                        0 else '0'
                    td1_val = str(self.entry_var[self.start + 2].text()) \
                        if len(
                        str(self.entry_var[self.start + 2].text())) > \
                        0 else '0'
                    tau1_val = str(self.entry_var[self.start + 3].text()) \
                        if len(
                        str(self.entry_var[self.start + 3].text())) > \
                        0 else '0'
                    td2_val = str(self.entry_var[self.start + 4].text()) \
                        if len(
                        str(self.entry_var[self.start + 4].text())) > \
                        0 else '0'
                    tau2_val = str(self.entry_var[self.end].text()) if len(
                        str(self.entry_var[self.end].text())) > 0 else '0'

                    self.addline = self.addline.partition(
                        '(')[0] + "(" + v1_val + " " + v2_val + " " + \
                        td1_val + " " + tau1_val + " " + td2_val + \
                        " " + tau2_val + ")"
                    self.sourcelistvalue.append([self.index, self.addline])
                except Exception as exc:
                    self._record_error(self.addline, exc)

        # Updating Schematic with source value
        for item in self.sourcelistvalue:
            del self.schematicInfo[item[0]]
            self.schematicInfo.insert(item[0], item[1])

        return self.schematicInfo

    def analysisInsertor(self, ac_entry_var, dc_entry_var, tran_entry_var,
                         set_checkbox, ac_parameter, dc_parameter,
                         tran_parameter, ac_type, op_check):
        """
        This function creates an analysis file in current project
        """
        self.ac_entry_var = ac_entry_var
        self.dc_entry_var = dc_entry_var
        self.tran_entry_var = tran_entry_var
        self.set_checkbox = set_checkbox
        self.ac_parameter = ac_parameter
        self.dc_parameter = dc_parameter
        self.trans_parameter = tran_parameter
        self.ac_type = ac_type
        self.op_check = op_check
        self.no = 0

        self.variable = self.set_checkbox
        self.direct = self.clarg1
        (filepath, filemname) = os.path.split(self.direct)
        self.Fileopen = os.path.join(filepath, "analysis")
        print("======================================================")
        print("FILEOPEN CONVERT ANALYS", self.Fileopen)
        # Write inside a `with` so an indexing error mid-build can never leave
        # the analysis file truncated-and-leaked -- a stale/empty analysis file
        # would silently make the next run mis-detect as Transient.
        with open(self.Fileopen, "w") as self.writefile:
            if self.variable == 'AC':
                self.no = 0
                self.writefile.write(".ac" +
                                     ' ' +
                                     self.ac_type +
                                     ' ' +
                                     str(self.defaultvalue(
                                         self.ac_entry_var[self.no + 2].text())) +
                                     ' ' +
                                     str(self.defaultvalue(
                                         self.ac_entry_var[self.no].text())) +
                                     self.ac_parameter[self.no] +
                                     ' ' +
                                     str(self.defaultvalue(
                                         self.ac_entry_var[self.no + 1].text())) +
                                     self.ac_parameter[self.no +
                                                       1])

            elif self.variable == 'DC':
                # op_check can be empty if the DC widgets were never populated;
                # default to a .dc sweep instead of raising IndexError on [-1].
                op_flag = self.op_check[-1] if self.op_check else 0
                if op_flag == 1:
                    self.no = 0
                    self.writefile.write(".op")
                elif op_flag == 0 or op_flag == '0':
                    self.no = 0
                    self.writefile.write(".dc" +
                                         ' ' +
                                         str(self.dc_entry_var[self.no].text()) +
                                         ' ' +
                                         str(self.defaultvalue(
                                             self.dc_entry_var[self.no +
                                                               1].text())) +
                                         self.converttosciform(
                                             self.dc_parameter[self.no]) +
                                         ' ' +
                                         str(self.defaultvalue(
                                             self.dc_entry_var[self.no +
                                                               3].text())) +
                                         self.converttosciform(
                                             self.dc_parameter[self.no +
                                                               2]) +
                                         ' ' +
                                         str(self.defaultvalue(
                                             self.dc_entry_var[self.no +
                                                               2].text())) +
                                         self.converttosciform(
                                             self.dc_parameter[self.no +
                                                               1]))

                    if self.dc_entry_var[self.no + 4].text():
                        self.writefile.write(' ' +
                                             str(self.defaultvalue(
                                                 self.dc_entry_var[self.no +
                                                                   4].text())) +
                                             ' ' +
                                             str(self.defaultvalue(
                                                 self.dc_entry_var[self.no +
                                                                   5].text())) +
                                             self.converttosciform(
                                                 self.dc_parameter[self.no +
                                                                   3]) +
                                             ' ' +
                                             str(self.defaultvalue(
                                                 self.dc_entry_var[self.no +
                                                                   7].text())) +
                                             self.converttosciform(
                                                 self.dc_parameter[self.no +
                                                                   5]) +
                                             ' ' +
                                             str(self.defaultvalue(
                                                 self.dc_entry_var[self.no +
                                                                   6].text())) +
                                             self.converttosciform(
                                                 self.dc_parameter[self.no +
                                                                   4]))

            elif self.variable == 'TRAN':
                self.no = 0
                self.writefile.write(".tran" +
                                     ' ' +
                                     str(self.defaultvalue(
                                         self.tran_entry_var[self.no +
                                                             1].text())) +
                                     self.converttosciform(
                                         self.trans_parameter[self.no +
                                                              1]) +
                                     ' ' +
                                     str(self.defaultvalue(
                                         self.tran_entry_var[self.no +
                                                             2].text())) +
                                     self.converttosciform(
                                         self.trans_parameter[self.no +
                                                              2]) +
                                     ' ' +
                                     str(self.defaultvalue(
                                         self.tran_entry_var[self.no].text())) +
                                     self.converttosciform(
                                         self.trans_parameter[self.no]))

            else:
                pass

    def converttosciform(self, string_obj):
        """
        This function is used for scientific conversion.
        """
        self.string_obj = string_obj
        if not self.string_obj:
            return "e-00"
        if self.string_obj[0] == 'm':
            return "e-03"
        elif self.string_obj[0] == 'u':
            return "e-06"
        elif self.string_obj[0] == 'n':
            return "e-09"
        elif self.string_obj[0] == 'p':
            return "e-12"
        else:
            return "e-00"

    def defaultvalue(self, value):
        """
        This function select default value as 0
        if Analysis widget do not hold any value.
        """
        self.value = value
        if self.value == '':
            return 0
        else:
            return self.value

    def addModelParameter(self, schematicInfo):
        """
        This function adds the Ngspice Model details to schematicInfo
        """

        # List to store model line
        addmodelLine = []
        modelParamValue = []

        for line in self.obj_track.modelTrack:
            # print "Model Track :",line
            if line[6] == "NgVeriCosim":
                cosimLine = self._cosim_model_line(line)
                if cosimLine:
                    modelParamValue.append([line[0], cosimLine, line[4]])
                continue
            if line[2] == 'transfo':
                try:
                    start = line[7]
                    # end = line[8]
                    num_turns = str(
                        self.obj_track.model_entry_var[start + 1].text())

                    if num_turns == "":
                        num_turns = "310"
                    h_array = "H_array = [ "
                    b_array = "B_array = [ "
                    h1 = str(self.obj_track.model_entry_var[start].text())
                    b1 = str(self.obj_track.model_entry_var[start + 5].text())

                    if len(h1) != 0 and len(b1) != 0:
                        h_array = h_array + h1 + " "
                        b_array = b_array + b1 + " "
                        bh_array = h_array + " ] " + b_array + " ]"
                    else:
                        bh_array = "H_array = [-1000 -500 -375 -250 -188 -125 \
                         -63 0 63 125 188 250 375 500 \
                         1000] B_array = [-3.13e-3 -2.63e-3 -2.33e-3 -1.93e-3\
                          -1.5e-3 -6.25e-4 -2.5e-4 0 2.5e-4 6.25e-4 \
                          1.5e-3 1.93e-3 2.33e-3 2.63e-3 3.13e-3]"
                    area = str(
                        self.obj_track.model_entry_var[start + 2].text())
                    length = str(
                        self.obj_track.model_entry_var[start + 3].text())
                    if area == "":
                        area = "1"
                    if length == "":
                        length = "0.01"
                    num_turns2 = str(
                        self.obj_track.model_entry_var[start + 4].text())
                    if num_turns2 == "":
                        num_turns2 = "620"
                    addmodelLine = ".model " + \
                                   line[3] + \
                                   "_primary lcouple (num_turns= " + \
                                   num_turns + ")"
                    modelParamValue.append(
                        [line[0], addmodelLine, "*primary lcouple"])
                    addmodelLine = ".model " + \
                                   line[3] + "_iron_core core (" + bh_array + \
                                   " area = " + area + " length =" + length + \
                                   ")"
                    modelParamValue.append(
                        [line[0], addmodelLine, "*iron core"])
                    addmodelLine = ".model " + \
                                   line[3] + \
                                   "_secondary lcouple (num_turns =" + \
                                   num_turns2 + ")"
                    modelParamValue.append(
                        [line[0], addmodelLine, "*secondary lcouple"])
                except Exception as exc:
                    self._record_error(line[1], exc)

            elif line[2] == 'ic':
                try:
                    start = line[7]
                    # end = line[8]
                    for key, value in line[9].items():
                        initVal = str(
                            self.obj_track.model_entry_var[value].text())
                        if initVal == "":
                            initVal = "0"
                        # Extracting node from model line
                        node = line[1].split()[1]
                        addmodelLine = ".ic v(" + node + ")=" + initVal
                        modelParamValue.append(
                            [line[0], addmodelLine, line[4]])
                except Exception as exc:
                    self._record_error(line[1], exc)

            else:
                try:
                    start = line[7]
                    # end = line[8]
                    addmodelLine = ".model " + line[3] + " " + line[2] + "("
                    for key, value in line[9].items():
                        # Checking for default value and accordingly assign
                        # param and default.
                        if ':' in key:
                            key = key.split(':')
                            param = key[0]
                            default = key[1]
                        else:
                            param = key
                            default = 0
                        # Checking if value is iterable.its for vector
                        if (
                                not isinstance(value, str) and
                                hasattr(value, '__iter__')
                        ):
                            addmodelLine += param + "=["
                            for lineVar in value:
                                if str(
                                        self.obj_track.model_entry_var
                                        [lineVar].text()) == "":
                                    paramVal = default
                                else:
                                    paramVal = str(
                                        self.obj_track.model_entry_var
                                        [lineVar].text())
                                addmodelLine += paramVal + " "
                            addmodelLine += "] "
                        else:
                            if str(
                                    self.obj_track.model_entry_var
                                    [value].text()) == "":
                                paramVal = default
                            else:
                                paramVal = str(
                                    self.obj_track.model_entry_var
                                    [value].text())

                            addmodelLine += param + "=" + paramVal + " "

                    addmodelLine += ") "
                    modelParamValue.append([line[0], addmodelLine, line[4]])
                except Exception as exc:
                    self._record_error(line[1], exc)

        # Adding it to schematic
        for item in modelParamValue:
            if ".ic" in item[1]:
                schematicInfo.insert(0, item[1])
                schematicInfo.insert(0, item[2])
            else:
                schematicInfo.append(item[2])  # Adding Comment
                schematicInfo.append(item[1])  # Adding model line

        return schematicInfo

    def _cosim_model_line(self, line):
        """Build the d_cosim ".model" line for an NgVeriCosim block and stage
        its compiled Icarus vvp into the project directory.

        Emits, e.g.:  .model u5 d_cosim simulation="ivlng" sim_args=["adder"]
        where u5 is the schematic instance (line[3]) and "adder" is the Verilog
        model name (line[2]) == the vvp basename ngspice's ivlng adapter loads.
        ivlng resolves sim_args relative to the ngspice working directory (the
        project dir), so the vvp is copied next to the netlist. The vvp source
        path is derived once, from the nghdl config, via CosimConfig -- the same
        helper the build step used, so there is a single source of truth.
        """
        comp_name = line[3]
        model_name = line[2]
        proj_dir = os.path.dirname(self.clarg1)

        log = CosimLog()  # no GUI here: terminal + ~/.esim/dcosim.log only
        vvp_src = CosimConfig.cosim_vvp_path(model_name)
        try:
            if vvp_src and os.path.isfile(vvp_src):
                dst = os.path.join(proj_dir, model_name)
                shutil.copy(vvp_src, dst)
                log.info('d_cosim: staged vvp for "%s" -> %s' %
                         (model_name, dst))
            else:
                log.error('d_cosim: compiled model "%s" not found at %s'
                          % (model_name, vvp_src))
                log.fix('Rebuild the model in the NgVeri tab ("Add Verilog '
                        '(d_cosim)") before running the simulation.')
        except OSError as e:
            log.error('d_cosim: could not stage vvp for "%s": %s'
                      % (model_name, str(e)))

        # On Windows, ivlng's default VPI-module location is its compile-time
        # NGSPICELIBDIR -- a build-machine path that does not exist on user
        # installs. ivlng does add_module_path(".") (the project dir, ngspice's
        # cwd), so stage ivlng.vpi next to the netlist like the vvp above and
        # point lib_args[1] at the bare module name. lib_args[0] must be a
        # non-empty value (ngspice drops empty strings from the vector,
        # shifting the args); "libvvp" = ivlng's own default, resolved via the
        # OS loader path the launcher already sets. Both names are relative,
        # so the netlist stays machine-portable.
        lib_args = ''
        if os.name == 'nt':
            cmdir = CosimConfig.ngspice_codemodel_dir()
            vpi_src = os.path.join(cmdir, 'ivlng.vpi') if cmdir else None
            try:
                if vpi_src and os.path.isfile(vpi_src):
                    shutil.copy(vpi_src, os.path.join(proj_dir, 'ivlng.vpi'))
                    lib_args = 'lib_args=["libvvp", "ivlng"] '
                else:
                    log.error('d_cosim: ivlng.vpi not found at %s'
                              % str(vpi_src))
            except OSError as e:
                log.error('d_cosim: could not stage ivlng.vpi: %s' % str(e))

        return ('.model ' + comp_name + ' d_cosim simulation="ivlng" '
                + lib_args + 'sim_args=["' + model_name + '"] ')

    def addMicrocontrollerParameter(self, schematicInfo):
        """
        This function adds the Microcontroller Model details to schematicInfo
        """

        # List to store model line
        addmodelLine = []
        modelParamValue = []

        for line in self.obj_track.microcontrollerTrack:
            # print "Model Track :",line
            try:
                start = line[7]
                # end = line[8]
                addmodelLine = ".model " + line[3] + " " + line[2] + "("
                z = 0
                for key, value in line[9].items():
                    # Checking for default value and accordingly assign
                    # param and default.
                    if ':' in key:
                        key = key.split(':')
                        param = key[0]
                        default = key[1]
                    else:
                        param = key
                        default = 0
                    # Checking if value is iterable.its for vector
                    if (
                            not isinstance(value, str) and
                            hasattr(value, '__iter__')
                    ):
                        addmodelLine += param + "=["
                        for lineVar in value:
                            if str(
                                    self.obj_track.microcontroller_var
                                    [lineVar].text()) == "":
                                paramVal = default
                            else:
                                paramVal = str(
                                    self.obj_track.microcontroller_var
                                    [lineVar].text())
                            # Checks For 5th Parameter(Hex File Path)
                            if z == 4:
                                paramVal = "\"" + _star_encode(paramVal) + "\""

                            addmodelLine += paramVal + " "
                            z = z + 1
                        addmodelLine += "] "
                    else:
                        if str(
                                self.obj_track.microcontroller_var
                                [value].text()) == "":
                            paramVal = default
                        else:
                            paramVal = str(
                                self.obj_track.microcontroller_var
                                [value].text())
                        # Checks For 5th Parameter(Hex File Path)
                        if z == 4:
                            paramVal = "\"" + _star_encode(paramVal) + "\""
                        z = z + 1
                        addmodelLine += param + "=" + paramVal + " "

                addmodelLine += ") "
                modelParamValue.append([line[0], addmodelLine, line[4]])
            except Exception as exc:
                self._record_error(line[1], exc)

        # Adding it to schematic
        for item in modelParamValue:
            if ".ic" in item[1]:
                schematicInfo.insert(0, item[1])
                schematicInfo.insert(0, item[2])
            else:
                schematicInfo.append(item[2])  # Adding Comment
                schematicInfo.append(item[1])  # Adding model line

        return schematicInfo

    def addDeviceLibrary(self, schematicInfo, kicadFile):
        """
        This function add the library details to schematicInfo
        """

        (projpath, filename) = os.path.split(kicadFile)

        deviceLibList = self.obj_track.deviceModelTrack
        deviceLine = {}
        # Key:Index, Value:with its updated line in the form of list
        includeLine = []  # All .include line list

        if not deviceLibList:
            print("No library added in the schematic")
        else:
            for eachline in schematicInfo:
                words = eachline.split()
                if words[0] in deviceLibList:
                    # print("Found Library line")
                    index = schematicInfo.index(eachline)
                    completeLibPath = deviceLibList[words[0]]

                    # Handle IHP components
                    # Detection: ihp prefix, sg13/npn13 in model, or known IHP device names
                    model_name = words[-1].lower() if len(words) > 1 else ""
                    ihp_known_devices = ['rppd', 'rhigh', 'rsil', 'ptap1', 'ntap1', 
                                        'dantenna', 'dpantenna', 'isolbox', 'pnpmpa',
                                        'nmoscl_2', 'nmoscl_4', 'cparasitic', 'dpwdnw', 'ddnwpsub']
                    is_ihp_device = (
                        eachline[0:3] == 'ihp' or
                        'sg13' in model_name or
                        'npn13' in model_name or
                        model_name.startswith('cap_') or
                        model_name in ihp_known_devices
                    )
                    
                    if is_ihp_device and eachline[0:7] != 'ihpmode':
                        # Parse the per-device tracking data: lib_path:corner:params
                        ihp_parts = completeLibPath.split(':')
                        ihp_lib_path = ihp_parts[0] if len(ihp_parts) > 0 else ""
                        ihp_corner = ihp_parts[1] if len(ihp_parts) > 1 else "mos_tt"
                        ihp_params = ihp_parts[2] if len(ihp_parts) > 2 else ""
                        
                        print("==============================================")
                        print(f"IHP Device: {words[0]}")
                        print(f"  Library: {ihp_lib_path}")
                        print(f"  Corner: {ihp_corner}")
                        print(f"  Params: {ihp_params}")
                        
                        # Add .lib include for this device's corner
                        if ihp_lib_path and os.path.exists(ihp_lib_path):
                            lib_include = f'.lib "{ihp_lib_path}" {ihp_corner}'
                            if lib_include not in includeLine:
                                includeLine.append(lib_include)
                                print(f"  Added: {lib_include}")
                        
                        # Convert ihp prefix to xihp and add params
                        words[0] = words[0].replace('ihp', 'xihp')
                        if ihp_params:
                            words.append(ihp_params)
                        deviceLine[index] = words
                        print("==============================================")
                        continue
                    
                    # Legacy ihpmode handling (for backward compatibility)
                    if eachline[0:7] == 'ihpmode':
                        deviceLine[index] = "*ihpmode (legacy)"
                        continue
                    
                    # Standard processing for non-IHP components
                    (libpath, libname) = os.path.split(completeLibPath)
                    # print("Library Path :", libpath)
                    # Copying library from devicemodelLibrary to Project Path
                    # Special case for MOSFET
                    tempStr = libname.split(':')
                    libname = tempStr[0]
                    libAbsPath = os.path.join(libpath, libname)

                    if eachline[0] == 'm':
                        # For mosfet library name come along with MOSFET
                        # dimension information. A model-track entry without
                        # the ":W=.. L=.." suffix used to IndexError here
                        # surface it as a readable error instead.
                        if len(tempStr) < 2:
                            raise ValueError(
                                "MOSFET '" + words[0] + "' has no W/L "
                                "dimensions — reopen its device model and set "
                                "the dimensions before converting.")
                        dimension = tempStr[1]
                        # Replace last word with library name
                        # words[-1] = libname.split('.')[0]
                        words[-1] = self.getReferenceName(libname, libpath)
                        # Appending Dimension of MOSFET
                        words.append(dimension)
                        deviceLine[index] = words
                        includeLine.append(".include " + libname)

                        # A library file that was moved/renamed/unplugged
                        # between selection and Convert used to raise a raw
                        # FileNotFoundError; surface it clearly.
                        try:
                            shutil.copy2(libAbsPath, projpath)
                        except OSError as copy_err:
                            raise FileNotFoundError(
                                "Device-model library '" + libname +
                                "' could not be copied from " + libpath +
                                " — it may have been moved, renamed or is on "
                                "an unavailable drive. (" +
                                str(copy_err) + ")"
                            ) from copy_err

                    elif eachline[0:6] == 'scmode':
                        (filepath, filemname) = os.path.split(self.clarg1)
                        self.Fileopen = os.path.join(filepath, ".spiceinit")
                        print("==============================================")
                        print("Writing to the .spiceinit file to " +
                              "make ngspice SKY130 compatible")
                        # `with` so the handle is closed even on write error;
                        # num_threads from the actual CPU count, not a hardcoded 8.
                        num_threads = os.cpu_count() or 4
                        with open(self.Fileopen, "w") as self.writefile:
                            self.writefile.write('''
set ngbehavior=hsa     ; set compatibility for reading PDK libs
set ng_nomodcheck      ; don't check the model parameters
set num_threads={0}      ; CPU hardware threads available
option noinit          ; don't print operating point data
optran 0 0 0 100p 2n 0 ; don't use dc operating point, but transient op)
'''.format(num_threads))
                        print("==============================================")

                        libs = '''
sky130_fd_pr__model__diode_pd2nw_11v0.model.spice
sky130_fd_pr__model__diode_pw2nd_11v0.model.spice
sky130_fd_pr__model__inductors.model.spice
sky130_fd_pr__model__linear.model.spice
sky130_fd_pr__model__pnp.model.spice
sky130_fd_pr__model__r+c.model.spice
'''
                        corner = tempStr[1] if len(tempStr) > 1 else "tt"
                        includeLine.append(
                            ".lib \"" + libAbsPath + "\" " + corner)
                        for i in libs.split():
                            includeLine.append(
                                ".include \"" + libAbsPath.replace(
                                    "sky130.lib.spice", i) + "\"")
                        deviceLine[index] = "*scmode"
                        # words.append(completeLibPath)
                        # deviceLine[index] = words

                    elif eachline[0:2] == 'sc' and eachline[0:6] != 'scmode':
                        words[0] = words[0].replace('sc', 'xsc')
                        words.append(completeLibPath)
                        deviceLine[index] = words

                    else:
                        # Replace last word with library name
                        # words[-1] = libname.split('.')[0]
                        words[-1] = self.getReferenceName(libname, libpath)
                        deviceLine[index] = words
                        includeLine.append(".include " + libname)

                        try:
                            shutil.copy2(completeLibPath, projpath)
                        except OSError as copy_err:
                            raise FileNotFoundError(
                                "Device-model library '" +
                                os.path.basename(completeLibPath) +
                                "' could not be copied — it may have been "
                                "moved, renamed or is on an unavailable "
                                "drive. (" + str(copy_err) + ")"
                            ) from copy_err

            # Adding device line to schematicInfo
            for index, value in deviceLine.items():
                # Update the device line
                strLine = " ".join(str(item) for item in value)
                schematicInfo[index] = strLine

            # This has to be second i.e after deviceLine details
            # Adding .include line to Schematic Info at the start of line
            for item in list(set(includeLine)):
                schematicInfo.insert(0, item)

        return schematicInfo

    def addSubcircuit(self, schematicInfo, kicadFile):
        """
        This function add the subcircuit to schematicInfo
        """
        (projpath, filename) = os.path.split(kicadFile)

        subList = self.obj_track.subcircuitTrack
        subLine = {}
        # Key:Index, Value:with its updated line in the form of list
        includeLine = []  # All .include line list

        if len(self.obj_track.subcircuitList) != len(
                self.obj_track.subcircuitTrack):
            self.msg = Dialogs.make_error_message(None)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Error Message")
            self.msg.showMessage(
                "Conversion failed. Please add all Subcircuits.")
            self.msg.exec()
            raise Exception('All subcircuit directories need to be specified.')
        elif not subList:
            print("No Subcircuit Added in the schematic")
        else:
            for eachline in schematicInfo:
                words = eachline.split()
                if words[0] in subList:
                    print("Found Subcircuit line")
                    index = schematicInfo.index(eachline)
                    completeSubPath = subList[words[0]]
                    (subpath, subname) = os.path.split(completeSubPath)
                    print("Library Path :", subpath)
                    # Copying library from devicemodelLibrary to Project Path

                    # Replace last word with library name
                    words[-1] = subname.split('.')[0]
                    subLine[index] = words
                    includeLine.append(".include " + subname + ".sub")

                    src = completeSubPath
                    dst = projpath
                    # A subcircuit directory that was moved/renamed/unplugged
                    # between selection and Convert used to raise a raw
                    # FileNotFoundError from os.listdir; surface it.
                    try:
                        sub_files = os.listdir(src)
                    except OSError as list_err:
                        raise FileNotFoundError(
                            "Subcircuit directory '" + src + "' is not "
                            "available — it may have been moved, renamed or "
                            "is on an unavailable drive. (" +
                            str(list_err) + ")"
                        ) from list_err
                    print(sub_files)
                    for files in sub_files:
                        if os.path.isfile(os.path.join(src, files)):
                            if files != "analysis":
                                try:
                                    shutil.copy2(
                                        os.path.join(src, files), dst)
                                except OSError as copy_err:
                                    raise FileNotFoundError(
                                        "Subcircuit file '" + files +
                                        "' could not be copied from " + src +
                                        ". (" + str(copy_err) + ")"
                                    ) from copy_err

            # Adding subcircuit line to schematicInfo
            for index, value in subLine.items():
                # Update the subcircuit line
                strLine = " ".join(str(item) for item in value)
                schematicInfo[index] = strLine

            # This has to be second i.e after subcircuitLine details
            # Adding .include line to Schematic Info at the start of line
            for item in list(set(includeLine)):
                schematicInfo.insert(0, item)

        return schematicInfo

    def getReferenceName(self, libname, libpath):
        libname = libname.replace('.lib', '.xml')
        library = os.path.join(libpath, libname)
        fallback = os.path.splitext(libname)[0]

        # Extracting Value from XML
        try:
            libtree = ET.parse(library)
            for child in libtree.iter():
                if child.tag == 'ref_model' and child.text:
                    return child.text
            raise ValueError("ref_model is missing or empty")
        except Exception as exc:
            self._record_error(library, exc)
            return fallback
