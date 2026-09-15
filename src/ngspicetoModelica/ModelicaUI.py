import os
import glob
import shlex
import shutil
import traceback
from PyQt6 import QtWidgets, QtCore
from configuration import Dialogs
from configuration.Appconfig import Appconfig
from projManagement import Worker
from projManagement.Validation import Validation
from projManagement.projectPaths import resolve_stem
from .NgspicetoModelica import NgMoConverter

BROWSE_LOCATION = os.path.expanduser('~')


class OpenModelicaEditor(QtWidgets.QWidget):

    def __init__(self, dir=None):
        QtWidgets.QWidget.__init__(self)
        self.obj_validation = Validation()
        self.obj_appconfig = Appconfig()
        self.projDir = dir
        # Resolve the stem from the .proj anchor, not the folder basename —
        # renamed/imported projects have folder name != file stem, and the
        # rest of the app already anchors on resolve_stem (cf. convertSub.py).
        if self.projDir:
            stem, _status = resolve_stem(str(self.projDir), 'proj')
            self.projName = stem or os.path.basename(self.projDir)
        else:
            self.projName = ''
        self.ngspiceNetlist = os.path.join(
            self.projDir, self.projName + ".cir.out")
        self.modelicaNetlist = os.path.join(self.projDir, "*.mo")
        self.map_json = Appconfig.modelica_map_json

        # ── Layout ────────────────────────────────────────────────────
        # Full-bleed two-pane workspace that uses the whole dock: a header
        # band across the top, the controls on the left, and a contextual
        # "How it works" panel on the right so the width is filled with
        # something useful instead of dead space. The body is centred
        # vertically so it never marroons at the top of a tall dock.
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.setSpacing(18)

        # Header band
        title = QtWidgets.QLabel("Ngspice → OpenModelica")
        title.setProperty("cssClass", "title")
        subtitle = QtWidgets.QLabel(
            "Convert an Ngspice netlist into a Modelica model, then open "
            "it in OMEdit."
        )
        subtitle.setProperty("cssClass", "muted")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        outer.addStretch(1)

        # Body — controls (left) beside guidance (right), spanning the dock.
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(24)

        controls = QtWidgets.QVBoxLayout()
        controls.setSpacing(18)

        # ── Step 1 · Convert netlist ──────────────────────────────────
        convertGroup = QtWidgets.QGroupBox("Step 1  ·  Convert netlist")
        convertForm = QtWidgets.QVBoxLayout(convertGroup)
        convertForm.setContentsMargins(16, 20, 16, 16)
        convertForm.setSpacing(8)

        convertForm.addWidget(QtWidgets.QLabel("Ngspice netlist (*.cir.out)"))

        self.FileEdit = QtWidgets.QLineEdit()
        self.FileEdit.setText(self.ngspiceNetlist)
        self.FileEdit.setPlaceholderText(
            "Path to the Ngspice netlist (*.cir.out)")
        self.FileEdit.setClearButtonEnabled(True)

        self.browsebtn = QtWidgets.QPushButton("Browse…")
        self.browsebtn.setProperty("cssClass", "secondary")
        self.browsebtn.clicked.connect(self.browseFile)

        netlistRow = QtWidgets.QHBoxLayout()
        netlistRow.setSpacing(8)
        netlistRow.addWidget(self.FileEdit, 1)
        netlistRow.addWidget(self.browsebtn)
        convertForm.addLayout(netlistRow)

        self.convertbtn = QtWidgets.QPushButton("Convert to Modelica")
        # Primary action of this converter — only one bold button per view.
        self.convertbtn.setProperty("cssClass", "primary")
        self.convertbtn.clicked.connect(self.callConverter)

        convertActions = QtWidgets.QHBoxLayout()
        convertActions.addStretch(1)
        convertActions.addWidget(self.convertbtn)
        convertForm.addSpacing(2)
        convertForm.addLayout(convertActions)

        controls.addWidget(convertGroup)

        # ── Step 2 · Open in OMEdit ───────────────────────────────────
        omGroup = QtWidgets.QGroupBox("Step 2  ·  Open in OMEdit")
        omForm = QtWidgets.QVBoxLayout(omGroup)
        omForm.setContentsMargins(16, 20, 16, 16)
        omForm.setSpacing(8)

        omForm.addWidget(QtWidgets.QLabel("OpenModelica install folder"))

        self.OMPathtext = QtWidgets.QLineEdit()
        self.OMPathtext.setText("")
        self.OMPathtext.setPlaceholderText(
            "Folder that contains the OMEdit executable")
        self.OMPathtext.setClearButtonEnabled(True)

        self.OMPathbrowsebtn = QtWidgets.QPushButton("Browse…")
        self.OMPathbrowsebtn.setProperty("cssClass", "secondary")
        self.OMPathbrowsebtn.clicked.connect(self.OMPathbrowseFile)

        omRow = QtWidgets.QHBoxLayout()
        omRow.setSpacing(8)
        omRow.addWidget(self.OMPathtext, 1)
        omRow.addWidget(self.OMPathbrowsebtn)
        omForm.addLayout(omRow)

        self.loadOMbtn = QtWidgets.QPushButton("Load OMEdit")
        self.loadOMbtn.clicked.connect(self.callOMEdit)

        omActions = QtWidgets.QHBoxLayout()
        omActions.addStretch(1)
        omActions.addWidget(self.loadOMbtn)
        omForm.addSpacing(2)
        omForm.addLayout(omActions)

        controls.addWidget(omGroup)
        controls.addStretch(1)

        # ── Guidance pane (right) ─────────────────────────────────────
        # Genuine help that also lets the workspace fill the dock width
        # instead of a marooned column.
        guideGroup = QtWidgets.QGroupBox("How it works")
        guide = QtWidgets.QVBoxLayout(guideGroup)
        guide.setContentsMargins(16, 20, 16, 16)
        guide.setSpacing(12)

        for step in (
            "1.  Choose your Ngspice netlist (*.cir.out).",
            "2.  Convert to Modelica — a .mo model is written next to "
            "the netlist.",
            "3.  Point to your OpenModelica folder, then Load OMEdit to "
            "open the model.",
        ):
            lbl = QtWidgets.QLabel(step)
            lbl.setWordWrap(True)
            guide.addWidget(lbl)

        guide.addSpacing(6)
        note = QtWidgets.QLabel(
            "The generated .mo file is saved in the same folder as the "
            "selected netlist."
        )
        note.setProperty("cssClass", "muted")
        note.setWordWrap(True)
        guide.addWidget(note)

        link = QtWidgets.QLabel(
            "Don’t have OpenModelica? Download it from "
            "<a href=\"https://openmodelica.org/download/download-linux\">"
            "openmodelica.org</a>."
        )
        link.setProperty("cssClass", "muted")
        link.setWordWrap(True)
        link.setOpenExternalLinks(True)
        link.setTextFormat(QtCore.Qt.TextFormat.RichText)
        guide.addWidget(link)
        guide.addStretch(1)

        body.addLayout(controls, 3)
        body.addWidget(guideGroup, 2)

        outer.addLayout(body)
        outer.addStretch(1)


    def OMPathbrowseFile(self):
        temp = QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getExistingDirectory(
                self, "Open OpenModelica Directory", BROWSE_LOCATION
            )
        )

        if temp:
            self.OMPath = temp
            self.OMPathtext.setText(self.OMPath)

    def browseFile(self):
        temp = QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getOpenFileName(
                self, 'Open Ngspice Netlist', BROWSE_LOCATION
            )[0]
        )

        if temp:
            self.ngspiceNetlist = temp
            self.FileEdit.setText(self.ngspiceNetlist)

    def callConverter(self):

        dir_name = os.path.dirname(os.path.realpath(self.ngspiceNetlist))
        # file_basename = os.path.basename(self.ngspiceNetlist)

        # No os.chdir: the converter is passed dir_name explicitly and writes
        # the .mo via absolute paths, so mutating the process CWD here bought
        # nothing and raced with any concurrent CWD-relative code on the GUI
        # thread (the map_json is absolute too).
        try:
            obj_NgMoConverter = NgMoConverter(self.map_json)
            # Getting all the require information
            lines = obj_NgMoConverter.readNetlist(self.ngspiceNetlist)
            # print("Complete Lines of Ngspice netlist : " +
            # "lines ---------------->", lines)
            optionInfo, schematicInfo = \
                obj_NgMoConverter.separateNetlistInfo(lines)

            # An empty or comment-only netlist parses cleanly all the way down
            # to a bare skeleton .mo with no components, which then reported a
            # false "successfully converted" result and wrote an empty model.
            # schematicInfo holds every device / source / subckt-instance line;
            # if it is empty there is nothing to convert -- report it and write
            # no output file instead of pretending success.
            if not schematicInfo:
                self.msg = Dialogs.make_error_message(self)
                self.msg.setModal(True)
                self.msg.setWindowTitle("Conversion Error")
                self.msg.showMessage(
                    'The Ngspice netlist has no circuit elements to convert. '
                    'Generate the netlist first (Convert KiCad to Ngspice), '
                    'then retry.'
                )
                return
            # print("All option details like analysis,subckt,.ic,.model  :" +
            # "OptionInfo------------------->", optionInfo)
            # print("Schematic connection info :schematicInfo", schematicInfo)
            modelName, modelInfo, subcktName, paramInfo, transInfo,\
                inbuiltModelDict = (
                    obj_NgMoConverter.addModel(optionInfo)
                )
            # print("Name of Model : " +
            # "modelName-------------------->", modelName)
            # print("Model Information : " +
            # "modelInfo--------------------->", modelInfo)
            # print("Subcircuit Name : " +
            # "subcktName------------------------>", subcktName)
            # print("Parameter Information : " +
            # "paramInfo---------------------->", paramInfo)
            # print("InBuilt Model ---------------------->", inbuiltModelDict)

            modelicaParamInit = obj_NgMoConverter.processParam(paramInfo)
            # print("Make modelicaParamInit from paramInfo : " +
            # "processParamInit------------->", modelicaParamInit)
            compInfo, plotInfo = obj_NgMoConverter.separatePlot(schematicInfo)
            # print("Plot info like plot,print etc :plotInfo",plotInfo)
            IfMOS = '0'

            for eachline in compInfo:
                # words = eachline.split()
                if eachline[0] == 'm':
                    IfMOS = '1'
                    break

            node, nodeDic, pinInit, pinProtectedInit = \
                obj_NgMoConverter.nodeSeparate(
                    compInfo, '0', [], subcktName, []
                )
            # print("All nodes in the netlist :node---------------->", node)
            # print("NodeDic which will be used for modelica :" +
            # "nodeDic------------->", nodeDic)
            # print("PinInit-------------->", pinInit)
            # print("pinProtectedInit----------->", pinProtectedInit)

            modelicaCompInit, numNodesSub = obj_NgMoConverter.compInit(
                compInfo,
                node,
                modelInfo,
                subcktName,
                dir_name,
                transInfo,
                inbuiltModelDict
            )
            # print("ModelicaComponents :" +
            # "modelicaCompInit----------->", modelicaCompInit)
            # print("SubcktNumNodes :" +
            # "numNodesSub---------------->", numNodesSub)

            connInfo = obj_NgMoConverter.connectInfo(
                compInfo, node, nodeDic, numNodesSub, subcktName)

            # print("ConnInfo------------------>", connInfo)

            # After Sub Ckt Func
            if len(subcktName) > 0:
                data, subOptionInfo, subSchemInfo, subModel, subModelInfo,\
                    subsubName, subParamInfo, modelicaSubCompInit,\
                    modelicaSubParam, nodeSubInterface, nodeSub, nodeDicSub,\
                    pinInitSub, connSubInfo = (
                        obj_NgMoConverter.procesSubckt(
                            subcktName, numNodesSub, dir_name
                        )
                    )  # Adding 'numNodesSub' by Fahim

            # Creating Final Output file
            fileDir = os.path.dirname(self.ngspiceNetlist)
            newfile = os.path.basename(self.ngspiceNetlist)
            newfilename = os.path.join(fileDir, newfile.split('.')[0])
            outfile = newfilename + ".mo"

            out = open(outfile, "w")
            out.writelines('model ' + os.path.basename(newfilename))
            out.writelines('\n')
            if IfMOS == '0':
                out.writelines('import Modelica.Electrical.*;')
            elif IfMOS == '1':
                out.writelines('import BondLib.Electrical.*;')
                # out.writelines('import Modelica.Electrical.*;')
            out.writelines('\n')

            for eachline in modelicaParamInit:
                if len(paramInfo) == 0:
                    continue
                else:
                    out.writelines(eachline)
                    out.writelines('\n')
            for eachline in modelicaCompInit:
                if len(compInfo) == 0:
                    continue
                else:
                    out.writelines(eachline)
                    out.writelines('\n')

            out.writelines('protected')
            out.writelines('\n')
            out.writelines(pinInit)
            out.writelines('\n')
            out.writelines('equation')
            out.writelines('\n')

            for eachline in connInfo:
                if len(connInfo) == 0:
                    continue
                else:
                    out.writelines(eachline)
                    out.writelines('\n')

            out.writelines('end ' + os.path.basename(newfilename) + ';')
            out.writelines('\n')

            out.close()

            base_msg = ("Ngspice netlist successfully converted to "
                        "OpenModelica netlist")
            skipped = getattr(obj_NgMoConverter, "skipped", [])
            self.msg = Dialogs.make_message_box(self)
            if skipped:
                # Do not pretend the model is complete: some parameters had no
                # Modelica equivalent and were left out. Name them so the user
                # can check the .mo instead of discovering the gap in OMEdit.
                preview = ", ".join(skipped[:12])
                if len(skipped) > 12:
                    preview += ", …"
                detail = ("%s, with %d unsupported parameter(s) skipped: %s"
                          % (base_msg, len(skipped), preview))
                self.msg.setText(detail)
                self.obj_appconfig.print_warning(detail)
            else:
                self.msg.setText(base_msg)
                self.obj_appconfig.print_info(base_msg)
            self.msg.exec()

        except Exception as e:
            traceback.print_exc()
            print("================")
            self.msg = Dialogs.make_error_message(self)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Conversion Error")
            self.msg.showMessage(
                'Unable to convert Ngspice netlist to Modelica netlist. ' +
                'Check the netlist : ' + repr(e)
            )

    def callOMEdit(self):

        try:
            modelFiles = glob.glob(self.modelicaNetlist)
            # Resolve the OMEdit binary from the user-supplied folder, else
            # from PATH. Quote every path (binary + each .mo) so folders or
            # files containing spaces don't shatter into bogus args when the
            # WorkerThread shlex.split()s the command.
            ompath = self.OMPathtext.text().strip()
            if ompath:
                ombin = os.path.join(ompath, "OMEdit")
            else:
                ombin = shutil.which("OMEdit")
            if not ombin:
                raise FileNotFoundError("OMEdit executable not found")
            self.cmd2 = " ".join(
                [shlex.quote(ombin)] + [shlex.quote(f) for f in modelFiles]
            )
            print(self.cmd2)
            self.obj_workThread2 = Worker.WorkerThread(self.cmd2)
            self.obj_workThread2.start()
            print("OMEdit called")
            self.obj_appconfig.print_info("OMEdit called")

        except Exception as e:
            traceback.print_exc()
            self.msg = Dialogs.make_message_box(self)
            self.msgContent = (
                "There was an error while opening OMEdit.<br/>"
                "Please make sure OpenModelica is installed in your"
                " system.<br/>"
                "To install it on Linux : Go to <a href="
                "https://www.openmodelica.org/download/download-linux"
                ">OpenModelica Linux</a> and install nightly build"
                " release.<br/>"
                "To install it on Windows : Go to <a href="
                "https://www.openmodelica.org/download/download-windows"
                ">OpenModelica Windows</a> and install latest version.<br/>"
                )
            self.msg.setTextFormat(QtCore.Qt.TextFormat.RichText)
            self.msg.setText(self.msgContent)
            self.msg.setWindowTitle("Missing OpenModelica")
            self.obj_appconfig.print_info(
                self.msgContent + " [" + repr(e) + "]")
            self.msg.exec()
