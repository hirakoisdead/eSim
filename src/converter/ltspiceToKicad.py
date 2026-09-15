import os
import sys
import subprocess
import shutil
from PyQt6.QtWidgets import QMessageBox
from configuration import Dialogs
from configuration import paths

class LTspiceConverter:
    def __init__(self, parent):
        self.parent = parent

    def get_workspace_directory(self):
        # read_workspace splits on the first space only, so a workspace path
        # containing spaces survives (the old split()[-1] returned only the
        # last token).
        workspace_file_path = paths.esim_config_path('workspace.txt')
        if not os.path.exists(workspace_file_path):
            return None
        _check, workspace_directory = paths.read_workspace()
        return workspace_directory

    def convert(self, file_path):
        
        # Get the base name of the file without the extension
        filename = os.path.splitext(os.path.basename(file_path))[0]
        conPath = os.path.dirname(file_path)

        # getsize on a path the user typed, or on a file a sync client removed
        # between the file-dialog pick and now, raises FileNotFoundError on the
        # GUI thread (excepthook dialog). Read the size defensively so a
        # missing / unreadable source degrades to a clear dialog instead.
        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            Dialogs.critical(
                self.parent, "File not found",
                "The selected file could not be read:\n\n" + str(e))
            return

        # Check if the file is not empty
        if file_size > 0:
            # Get the absolute path of the current script's directory
            script_dir = os.path.dirname(os.path.abspath(__file__))

            # Define the relative path to parser.py from the current script's directory
            # Check the current operating system
            if os.name == 'nt':  # Windows
                relative_parser_path = "LTSpiceToKiCadConverter/src/Windows"
            else:
                relative_parser_path = "LTSpiceToKiCadConverter/src/Ubuntu"

            # Construct the full path to parser.py
            parser_path = os.path.join(script_dir, relative_parser_path)
            
            # sys.executable (not "python3", absent on Windows); arg list, no
            # shell. The vendored script appends its own extension handling --
            # it is invoked with cwd=conPath and the bare filename by design.
            command = [sys.executable,
                       f"{parser_path}/sch_LTspice2Kicad.py", f"{filename}.asc"]

            try:
                subprocess.run(command, check=True, cwd=conPath,
                               capture_output=True, text=True,
                               creationflags=getattr(
                                   subprocess, 'CREATE_NO_WINDOW', 0))
                # Message box with the conversion success message
                msg_box = Dialogs.make_message_box(self.parent)
                msg_box.setIcon(QMessageBox.Icon.Information)
                msg_box.setWindowTitle("Conversion Successful")
                newFile = str(conPath + "/LTspice_" + filename)
                workspace_directory = self.get_workspace_directory()
                if workspace_directory:
                        print(f"Workspace directory found: {workspace_directory}")
                        try:
                            shutil.copytree(
                                newFile,
                                os.path.join(workspace_directory,
                                             "LTspice_" + filename),
                                dirs_exist_ok=True,
                                copy_function=shutil.copy2)
                            msg_box.setText(f"The file has been converted successfully.  Saved in {workspace_directory}.  Open the Project manually.")
                            print("File added under the project explorer.")
                        except OSError as e:
                            # Conversion itself succeeded; only the copy into the
                            # workspace failed (locked by a sync client, read-only
                            # target, or the tree vanished). Report the copy
                            # failure without throwing away the converted output.
                            print("Copy to workspace failed:", e)
                            msg_box.setIcon(QMessageBox.Icon.Warning)
                            msg_box.setText(
                                "Converted, but the result could not be copied "
                                f"into the workspace:\n\n{e}\n\nCopy it manually "
                                f"from {newFile}.")
                else:
                        print("Workspace directory not found.")
                result = msg_box.exec()
                print("Conversion of LTspice to eSim schematic Successful")

            except subprocess.CalledProcessError as e:
                # Surface the parser failure that was invisible before.
                detail = (e.stderr or e.stdout or str(e)).strip()
                print("Error:", detail)
                Dialogs.critical(
                    self.parent, "Conversion failed",
                    "LTspice to eSim conversion failed:\n\n"
                    + "\n".join(detail.splitlines()[:15]))
        else:
            print("File is empty. Cannot perform conversion.")
            # A message box indicating that the file is empty
            msg_box = Dialogs.make_message_box(self.parent)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("Empty File")
            msg_box.setText("The selected file is empty. Conversion cannot be performed.")
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.exec()

    def upload_file_LTspice(self, file_path):
        if file_path:
            # Check if the file path contains spaces
            if ' ' in file_path:
                # Show a message box indicating that spaces are not allowed
                msg_box = Dialogs.make_message_box(self.parent)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Invalid File Path")
                msg_box.setText("Spaces are not allowed in the file path.")
                msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg_box.exec()
                return
            
            if ".asc" in file_path:
                print(file_path)
                self.convert(file_path)
            else:
                msg_box = Dialogs.make_message_box(self.parent)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Invalid File Path")
                msg_box.setText("Only .asc file can be converted.")
                msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg_box.exec()
                return

        else:
            print("No file selected.")

            # Message box indicating that no file is selected
            msg_box = Dialogs.make_message_box(self.parent)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("No File Selected")
            msg_box.setText("Please select a file before uploading.")
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.exec()
