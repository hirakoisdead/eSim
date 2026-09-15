from PyQt6 import QtWidgets
from projManagement.Validation import Validation
from configuration.Appconfig import Appconfig
from configuration import paths
from configuration import Dialogs
from projManagement import Worker
import os
import shlex


# This class is called when User creates new Project.
class NewSub(QtWidgets.QWidget):
    """
    Contains functions to check :
    - Name of project should not be blank.
    - Name should not contain space between them.
    - Name does not match with existing project.
    """

    def __init__(self):
        super(NewSub, self).__init__()
        self.obj_validation = Validation()
        self.obj_appconfig = Appconfig()

    def createSubcircuit(self, subName):
        """
        - This function create workspace for subcircuit.
        - It also validate file names for Subcircuits:
            - File name should not contain space.
            - Name can not be empty.
            - File name already exists.
        """

        self.create_schematic = subName
        # Checking if Workspace already exist or not
        self.schematic_path = paths.library_path(
            'SubcircuitLibrary', self.create_schematic)

        # Validation for new subcircuit
        if self.schematic_path == "":
            self.reply = "NONE"
        else:
            self.reply = self.obj_validation.validateNewproj(
                str(self.schematic_path))

        # Checking Validations Response
        if self.reply == "VALID":
            print("Validated : Creating subcircuit directory")
            try:
                os.mkdir(self.schematic_path)
                self.schematic = os.path.join(
                    self.schematic_path, self.create_schematic)
                # New KiCad v6 file extension
                self.cmd = (
                    "eeschema "
                    + shlex.quote(self.schematic + ".kicad_sch")
                )
                self.obj_workThread = Worker.WorkerThread(self.cmd)
                self.obj_workThread.start()
                self.close()
            except Exception:
                Dialogs.critical(
                    self, "Error Message",
                    'Unable to create subcircuit. Please make sure ' +
                    'you have write permission on ' + self.schematic_path)
                # Selection stays where it was: pointing the builder at a
                # folder that was never created makes the next Convert fail
                # with a netlist error instead of the permission problem the
                # user actually hit.
                return

            # A brand-new subcircuit has no .sub yet -- that file is the
            # OUTPUT of Convert -- so the stem is the name just entered.
            self.obj_appconfig.set_current_subcircuit(
                self.schematic_path, self.create_schematic)
            self.obj_appconfig.print_info(
                'New subcircuit created : ' + self.create_schematic)

        elif self.reply == "CHECKEXIST":
            Dialogs.critical(
                self, "Error Message",
                'The subcircuit "' + self.create_schematic +
                '" already exist.Please select the different name or delete' +
                'existing subcircuit')

        elif self.reply == "CHECKNAME":
            Dialogs.critical(
                self, "Error Message",
                'The subcircuit name should not contain space between them')

        elif self.reply == "NONE":
            Dialogs.critical(
                self, "Error Message",
                'The subcircuit name cannot be empty')
