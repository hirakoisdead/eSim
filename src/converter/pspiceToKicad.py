import os
import sys
import subprocess
import shutil
from PyQt6.QtWidgets import QMessageBox
from configuration import Dialogs
from configuration import paths

class PspiceConverter:
    def __init__(self, parent):
        self.parent = parent

    def get_workspace_directory(self):
        # read_workspace splits on the first space only, so a workspace path
        # that itself contains spaces survives (the old split()[-1] returned
        # only the last token).
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
        # missing or unreadable source degrades to a clear dialog instead.
        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            Dialogs.critical(
                self.parent, "File not found",
                "The selected file could not be read:\n\n" + str(e))
            return

        # Checks if the file is not empty
        if file_size <= 0:
            print("File is empty. Cannot perform conversion.")
            # A message box indicating that the file is empty
            msg_box = Dialogs.make_message_box(self.parent)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("Empty File")
            msg_box.setText("The selected file is empty. Conversion cannot be performed.")
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.exec()
            return

        # Guard against a second Schematic click while an export is running.
        existing = getattr(self, '_convert_job', None)
        if existing is not None and existing.isRunning():
            print("PSpice conversion already in progress.")
            return

        # Get the absolute path of the current script's directory
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Define the relative path to parser.py from the current script's directory
        relative_parser_path = "schematic_converters/lib/PythonLib"

        # Construct the full path to parser.py
        parser_path = os.path.join(script_dir, relative_parser_path)
        # Pass args as a list (no shell) and run the parser with the same
        # interpreter running eSim (sys.executable) -- "python3" is absent
        # on Windows installs that expose only python.exe. A path with
        # spaces or shell metacharacters can no longer break or inject.
        command = [
            sys.executable, os.path.join(parser_path, "parser.py"),
            file_path, os.path.join(conPath, filename),
        ]

        # The parser can take many seconds on a large schematic; running it
        # with subprocess.run on the GUI thread froze eSim ("Not Responding")
        # for the whole parse. Run it on a BackgroundJob and finish on the GUI
        # thread via queued signals, mirroring the KiCad netlister
        # (projManagement/Kicad.py). No Qt parent + a reference held on the
        # instance keeps the thread alive without tying it to a dock that may
        # be closed mid-run.
        from maker.hdl.jobs import BackgroundJob
        job = BackgroundJob(self._run_parser, command)
        job.succeeded.connect(
            lambda res, cp=conPath, fn=filename:
                self._on_convert_done(cp, fn, res))
        job.failed.connect(self._on_convert_failed)
        job.finished.connect(job.deleteLater)
        self._convert_job = job
        job.start()

    @staticmethod
    def _run_parser(command):
        """Run the blocking parser subprocess on the BackgroundJob worker
        thread. Returns ``(returncode, stdout, stderr)``; a non-zero exit is
        reported through the tuple (not raised) so the GUI-thread slot decides
        how to surface it. An OSError launching the interpreter propagates and
        reaches ``_on_convert_failed`` via BackgroundJob.failed."""
        proc = subprocess.run(
            command, capture_output=True, text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return proc.returncode, proc.stdout, proc.stderr

    def _on_convert_done(self, conPath, filename, result):
        """Parser finished. Runs on the GUI thread (queued signal), so it may
        safely touch widgets."""
        returncode, stdout, stderr = result
        if returncode != 0:
            # The parser's failure output was invisible before; surface it.
            detail = (stderr or stdout
                      or f"parser exited with status {returncode}").strip()
            print("Error:", detail)
            Dialogs.critical(
                self.parent, "Conversion failed",
                "PSpice to eSim conversion failed:\n\n"
                + "\n".join(detail.splitlines()[:15]))
            return

        # Message box with the conversion success message
        msg_box = Dialogs.make_message_box(self.parent)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle("Conversion Successful")
        newFile = str(conPath + "/" + filename)
        workspace_directory = self.get_workspace_directory()

        if workspace_directory:
                print(f"Workspace directory found: {workspace_directory}")
                try:
                    shutil.copytree(
                        newFile, os.path.join(workspace_directory, filename),
                        dirs_exist_ok=True, copy_function=shutil.copy2)
                    msg_box.setText(f"The file has been converted successfully.  Saved in {workspace_directory}.  Open the Project manually.")
                    print("File added under the project explorer.")
                except OSError as e:
                    # Conversion itself succeeded; only the copy into the
                    # workspace failed (locked by a sync client, read-only
                    # target, or the tree vanished). Report the copy failure
                    # without throwing away the converted output.
                    print("Copy to workspace failed:", e)
                    msg_box.setIcon(QMessageBox.Icon.Warning)
                    msg_box.setText(
                        "Converted, but the result could not be copied into "
                        f"the workspace:\n\n{e}\n\nCopy it manually from "
                        f"{newFile}.")
        else:
                print("Workspace directory not found.")
        msg_box.exec()
        print("Conversion of Pspice to eSim schematic Successful")

    def _on_convert_failed(self, err):
        """The parser subprocess could not be launched (OSError). Runs on the
        GUI thread."""
        print("Error:", err)
        Dialogs.critical(
            self.parent, "Conversion failed",
            "PSpice to eSim conversion could not start:\n\n" + err)

    def upload_file_Pspice(self, file_path):
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
            
            if ".sch" in file_path:
                print(file_path)
                self.convert(file_path)
            else:
                msg_box = Dialogs.make_message_box(self.parent)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Invalid File Path")
                msg_box.setText("Only .sch file can be converted.")
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
