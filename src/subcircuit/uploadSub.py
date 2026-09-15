from PyQt6 import QtWidgets, QtCore
from configuration.Appconfig import Appconfig
from configuration import paths
from configuration import Dialogs
from projManagement.Validation import Validation
import os
import shutil


class UploadSub(QtWidgets.QWidget):
    """
    This class contain function for uploading subcircuits
    in SubcircuitLibrary present in src folder.
    A folder is created in library/SubcircuitLibrary
    and desired file is moved to that folder.
    """

    def __init__(self):
        super(UploadSub, self).__init__()
        self.obj_validation = Validation()
        self.obj_appconfig = Appconfig()

    def upload(self):
        """
        This method opens a dialog box when Upload subcircuit button is
        clicked and after entering folder name, it opens directory system
        to chose file for folder, it only shows file with extension .sub
        and with the name of project entered earlier as folder name.

            It then validates file if it is in proper format or not, for it
            the file is passed to the function **validateSub** and it returns
            true if file has valid format or else it shows an error message.
        """

        editfile = QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getOpenFileName(
                self, "Upload Subcircuit File",
                os.path.expanduser("~"), "*.sub"
            )[0]
        )

        if not editfile:
            return

        upload = os.path.basename(editfile)
        create_subcircuit, ext = os.path.splitext(upload)

        if ext != '.sub':
            Dialogs.critical(
                self, "Error Message",
                "Please ensure that filename ends with .sub")
            print("Invalid filename")
            return

        valid = self.obj_validation.validateSubcir(editfile, create_subcircuit)
        if not valid:
            Dialogs.critical(
                self, "Error Message",
                "Content of file does not meet the required format. " +
                "Please ensure that file starts with **.subckt " +
                create_subcircuit + " ** and ends with **.ends " +
                create_subcircuit + " **")
            print("Invalid file format")
            return

        subcircuit_path = paths.library_path(
            'SubcircuitLibrary', create_subcircuit
        )

        reply = self.obj_validation.validateNewproj(subcircuit_path)

        if reply == "VALID":
            print("Validated: Creating subcircuit directory")
            subcircuit = os.path.join(subcircuit_path, upload)
            # The SubcircuitLibrary lives in the install tree, which is
            # read-only on a Program Files / system install — the makedirs and
            # copy used to raise PermissionError onto the crash net. Surface a
            # clear dialog instead.
            try:
                os.makedirs(subcircuit_path)

                print("===================")
                print("Current path of subcircuit file is " + editfile)
                print("Selected file is " + upload)
                print("Final path of file is " + subcircuit)
                print("===================")
                shutil.copy(editfile, subcircuit)
            except OSError as e:
                Dialogs.critical(
                    self, "Error Message",
                    "Could not add the subcircuit to the eSim library. The "
                    "library folder may be read-only (e.g. a Program Files "
                    "install).\n\n" + str(e))
                print("Could not write subcircuit: " + str(e))
                return

        elif reply == "CHECKEXIST":
            print("Project name already exists.")
            print("==========================")
            Dialogs.critical(
                self, "Error Message",
                "The project already exist. Please select "
                "a different name or delete existing project")

        elif reply == "CHECKNAME":
            print("Name can not contain space between them")
            print("===========================")
            Dialogs.critical(
                self, "Error Message",
                'The project name should not contain space between them')
