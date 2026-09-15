# =========================================================================
#          FILE: newProject.py
#
#         USAGE: ---
#
#   DESCRIPTION: It is called whenever new project is being called.
#
#       OPTIONS: ---
#  REQUIREMENTS: ---
#          BUGS: ---
#         NOTES: ---
#        AUTHOR: Fahim Khan, fahim.elex@gmail.com
#      MODIFIED: Rahul Paknikar, rahulp@iitb.ac.in
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
#       CREATED: Wednesday 12 February 2015
#      REVISION: Sunday 26 July 2020
# =========================================================================

from PyQt6 import QtWidgets
from .Validation import Validation
from .projectPaths import canonical_path, save_project_explorer
from configuration.Appconfig import Appconfig
from configuration import Dialogs
import os
import shutil


class NewProjectInfo(QtWidgets.QWidget):
    """
    This class is called when User create new Project.
    """

    def __init__(self):
        super(NewProjectInfo, self).__init__()
        self.obj_validation = Validation()
        self.obj_appconfig = Appconfig()

    def createProject(self, projName):
        """
        This function create Project related directories and files.
        Before creating also validates using the `Validation` class

        Validation codes

        - VALID
        - CHECKEXIST
        - CHECKNAME
        - NONE

         @params
            :projName   => name of the project created passed from
                        frontEnd/Application new_project()
         @return
            :dirs        => The directories inside the project folder
            :filelist    => The files inside the project folder

         @params
            :projName   => name of the project created passed from
                        frontEnd/Application new_project()
         @return
            :dirs        => The directories inside the project folder
            :filelist    => The files inside the project folder

        """
        self.projName = projName
        self.workspace = self.obj_appconfig.default_workspace['workspace']
        # self.projName = self.projEdit.text()
        # Remove leading and trailing space
        # self.projName = str(self.projName).rstrip().lstrip()
        # Remove leading and trailing spaces AND replace internal spaces with underscores
        self.projName = str(self.projName).strip().replace(" ", "_")

        self.projDir = os.path.join(self.workspace, str(self.projName))

        # Validation for newProject
        if self.projName == "":
            self.reply = "NONE"
        else:
            self.reply = self.obj_validation.validateNewproj(str(self.projDir))

        # Checking Validations Response
        if self.reply == "VALID":
            newprojlist = [self.projName + '.proj']
            # Canonicalise the folder to its identity key (see
            # projectPaths.canonical_path) before it becomes the
            # project_explorer/current_project key, so a project is registered
            # under one form -- matching what openProject and the project tree
            # compare against.
            canonicalDir = canonical_path(self.projDir)

            # One guarded region over EVERY disk/registry write: the .proj write
            # and the registry save used to sit OUTSIDE the try, so a disk-full
            # or a workspace turning read-only between the probe and the write
            # raised a raw excepthook dialog and left a half-created project on
            # disk. Anything that fails now rolls the whole thing back.
            try:
                os.mkdir(self.projDir)
                self.projFile = os.path.join(
                    self.projDir, self.projName + ".proj")
                # New KiCad v6 file extension
                with open(self.projFile, "w") as f:
                    f.write("schematicFile " + self.projName + ".kicad_sch\n")

                self.obj_appconfig.project_explorer[canonicalDir] = newprojlist
                save_project_explorer(
                    self.obj_appconfig.dictPath["path"],
                    self.obj_appconfig.project_explorer)
            except Exception:
                # Leave the workspace exactly as it was: drop the folder (and any
                # empty .proj) and the in-memory entry, and do NOT switch to it.
                shutil.rmtree(self.projDir, ignore_errors=True)
                self.obj_appconfig.project_explorer.pop(canonicalDir, None)
                Dialogs.critical(
                    self, "Error Message",
                    'Unable to create project. Please make sure you have ' +
                    'write permission on ' + self.workspace)
                return None, None

            # Committed on disk + in the registry: only now switch to it.
            self.projDir = canonicalDir
            self.obj_appconfig.current_project['ProjectName'] = self.projDir
            self.close()

            self.obj_appconfig.print_info(
                'New project created : ' + self.projName)
            self.obj_appconfig.print_info(
                'Current project is : ' + self.projDir)
            return self.projDir, newprojlist

        elif self.reply == "CHECKEXIST":
            Dialogs.critical(
                self, "Error Message",
                'The project "' + self.projName +
                '" already exist.Please select the different name or delete' +
                ' existing project')
            return None, None

        elif self.reply == "CHECKNAME":
            Dialogs.critical(
                self, "Error Message",
                'The project name should not contain space between them')
            return None, None

        elif self.reply == "NONE":
            Dialogs.critical(
                self, "Error Message", 'The project name cannot be empty')
            return None, None

    def cancelProject(self):
        self.close()
