# =========================================================================
#          FILE: Validation.py
#
#         USAGE: ---
#
#   DESCRIPTION: This module is use to create validation for openProject,
#                newProject and other activity.
#
#       OPTIONS: ---
#  REQUIREMENTS: ---
#          BUGS: ---
#         NOTES: ---
#        AUTHOR: Fahim Khan, fahim.elex@gmail.com
#      MODIFIED: Rahul Paknikar, rahulp@iitb.ac.in
#  ORGANIZATION: eSim team at FOSSEE, IIT Bombay.
#       CREATED: Wednesday 12 February 2015
#      REVISION: Friday 14 February 2020
# =========================================================================

import os
import re
import shutil

from .projectPaths import find_anchors, resolve_stem


class Validation:
    """
    This is Validation class use for validating Project.
    e.g if .proj is present in project directory
    or if new project name is already exist in workspace etc
    """

    def __init__(self):
        pass

    def validateOpenproj(self, projDir):
        """
        Takes as input the path of the project and checks if
        projName.proj file exists or not

        @params
            :projDir    => contains the path of the project selected to open

        @return
            True        => If the folder contains the projName.proj file
            False       => If the folder doesn't contain projName.proj file
        """
        print("Function: Validating Open Project Information")
        # A folder is a valid project if it contains any .proj anchor file,
        # regardless of whether its name matches the folder name. The exact
        # stem is resolved separately (see projectPaths.resolve_stem).
        return len(find_anchors(str(projDir), 'proj')) >= 1

    def validateNewproj(self, projDir):
        """
        Validate new project created

        @params
            :projDir        => Contains path of the new projDir created

        @return
            :"CHECKEXIST"   => If smae project name folder exists
            :"CHECKNAME"    => If space is there in name
            :"VALID"        => If valid project name given
        """
        print("Function: Validating New Project Information")

        projDir = str(projDir)
        projName = os.path.basename(os.path.normpath(projDir))

        # Checking existence of project with same name
        projName = os.path.basename(projDir)
        if os.path.exists(projDir):
            return "CHECKEXIST"  # Project with name already exist
        else:
            # Check Proper name for project. It should not have space
            projName = os.path.basename(str(projDir))
            if re.search(r"\s", projName):
                return "CHECKNAME"
            else:
                return "VALID"

    def validateKicad(self, projDir):
        """
        Validate if projDir is set appropriately in the function calling file
        and if Kicad components are present

        @params
            :projDir    => the path of the project directory, passed from
                           the calling function

        @return
            True
            False
        """
        print("Function : Validating for Kicad components")
        if projDir is None:
            return False
        else:
            return True

    def validateCir(self, projDir, stem=None):
        """
        Validate if the project's .cir netlist is present.

        @params
            :projDir    => the path to the project directory
            :stem        => resolved project stem; if omitted it is resolved
                            from the .proj anchor instead of the folder name

        @return
            True
            False
        """
        if stem is None:
            stem, _status = resolve_stem(str(projDir), 'proj')
        lookCir = os.path.join(str(projDir), str(stem) + ".cir")
        # Check existence of project
        if os.path.exists(lookCir):
            return True
        else:
            return False

    def validateSub(self, subDir, givenNum):
        """
        This function checks if ".sub" file is present.
        Also, if subckt file is present check for ports and check if equal

        @params
            :subDir    => the path of the subcircuit directory
            :giveNum   => the number of port calculated and passed for\
                validation

        @return
            "True"     => a matching .subckt with the expected port count
            "PORT"     => .subckt found but port count differs
            "DIREC"    => no .sub file in the directory
            "NOSUBCKT" => .sub file exists but contains no .subckt line
        """
        # Resolve the subcircuit stem from its .sub anchor, not the folder name.
        subName, _status = resolve_stem(str(subDir), 'sub')
        lookSub = os.path.join(str(subDir), str(subName) + ".sub")
        # Read the .sub directly instead of exists()-then-open: the anchor can
        # vanish (sync client / manual delete) or lock in the gap between the
        # check and the open, which used to raise FileNotFoundError
        # on the GUI thread. A missing / unreadable anchor degrades to the same
        # "no .sub here" terminal code the callers already handle.
        try:
            with open(lookSub) as f:
                data = f.read()
        except OSError:
            return "DIREC"
        netlist = data.splitlines()
        for eachline in netlist:
            eachline = eachline.strip()
            if len(eachline) < 1:
                continue
            words = eachline.split()
            if words[0] == '.subckt':
                # The number of ports is specified in this line
                # eg. '.subckt ua741 6 7 3' has 3 ports (6, 7 and 3).
                numPorts = len(words) - 2
                print("Looksub : ", lookSub)
                print("Given Number of ports : ", givenNum)
                print("Actual Number of ports :", numPorts)
                if numPorts != givenNum:
                    return "PORT"
                else:
                    return "True"
        # .sub file exists but no ".subckt" line was found — an explicit
        # terminal value beats falling off the end returning None (which
        # callers string-compare into a confusing wrong-branch message).
        return "NOSUBCKT"

    def validateCirOut(self, projDir, stem=None):
        """This function checks if ".cir.out" file is present."""
        if stem is None:
            stem, _status = resolve_stem(str(projDir), 'proj')
        lookCirOut = os.path.join(str(projDir), str(stem) + ".cir.out")
        # Check existence of project
        if os.path.exists(lookCirOut):
            return True
        else:
            return False

    def validateTool(self, toolName):
        """This function check if tool is present in the system."""
        return shutil.which(toolName) is not None

    def validateSubcir(self, projDir, fileName):
        """
        This function checks for valid format of .sub file.
            Correct format of file is:
                - File should start with **.subckt <filename>**
                - End with **.ends <filename>**
        Function is passed with the file of path it checks the
        file line by line untill it get .subckt as its first word
        and then check for second word is it <fileName> or not.

        Then it checks for second last line if it is ".ends
        <filename>" it return True if conditions satisfy else
        return False.

        """

        first = True
        last_line = []

        # os.stat / open / read on a path that vanished or locked between the
        # caller's exists-check and here raises on the GUI thread.
        # Treat an unreadable / missing / disappearing file as an invalid
        # subcircuit (return False) — the same terminal the format checks below
        # already use — instead of crashing into the excepthook.
        try:
            # Checks if file is empty or not.
            if os.stat(projDir).st_size == 0:
                print("File is empty")
                return False

            with open(projDir, 'r') as f:
                for line in f:
                    word = line.split()
                    if len(word) == 0 or word[0][0] == "*":
                        continue
                    if first:
                        if (len(word) >= 2 and word[0] == ".subckt"
                                and word[1] == fileName):
                            first = False
                        else:
                            print("First line not found:", word)
                            return False
                    else:
                        last_line = word
        except OSError as e:
            print("Cannot read subcircuit file:", e)
            return False

        if first is True:
            print("First line not found")
            return False

        if len(last_line) >= 2 and last_line[0] == ".ends" and \
                last_line[1] == fileName:
            return True

        print("Last line not found:", last_line)
        return False
