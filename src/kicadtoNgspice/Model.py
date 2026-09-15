#!/usr/bin/python
# -*- coding: utf-8 -*-
from xml.etree import ElementTree as ET
from PyQt6 import QtWidgets

from . import TrackWidget
from projManagement.projectPaths import previous_values_path


class Model(QtWidgets.QWidget):
    """
    - This class creates Model Tab of KicadtoNgspice window.
      The widgets are created dynamically in the Model Tab.
    """
    def __init__(
            self,
            schematicInfo,
            modelList,
            clarg1,
            track=None,
    ):

        QtWidgets.QWidget.__init__(self)

        # Processing for getting previous values
        kicadFile = clarg1
        check = 1
        # Pre-bind the restore node so ``root`` is always defined even when the
        # prev-values XML is missing or has no <model> child; the restore loops
        # below then simply skip. Previously ``root`` was only bound inside the
        # try, so a bare access outside the swallowing try/except would raise
        # UnboundLocalError.
        root = None
        try:
            f = open(
                previous_values_path(kicadFile),
                "r",
            )
            tree = ET.parse(f)
            parent_root = tree.getroot()
            for child in parent_root:
                if child.tag == "model":
                    root = child
        except Exception:
            check = 0

        # Shared per-conversion data bus, injected by the converter window; a
        # standalone construction falls back to its own instance.
        self.obj_trac = track if track is not None else \
            TrackWidget.TrackWidget()

        # for increasing row and counting/tracking line edit widget
        self.nextrow = 0
        self.nextcount = 0

        # for storing line edit details position details
        self.start = 0
        self.end = 0
        self.entry_var = []
        self.hex_btns = []
        self.text = ""

        # Creating GUI dynamically for Model tab
        self.grid = QtWidgets.QGridLayout()
        self.setLayout(self.grid)

        for line in modelList:
            # print "ModelList Item:",line
            # Adding title label for model
            # Key: Tag name,Value:Entry widget number

            tag_dict = {}
            modelbox = QtWidgets.QGroupBox()
            modelgrid = QtWidgets.QGridLayout()
            modelbox.setTitle(line[5])
            self.start = self.nextcount
            self.model_name = line[2]

            # line[7] is parameter dictionary holding parameter tags.
            i = 0
            for (key, value) in line[7].items():
                print(value)
                print(key)

                # VECTOR parameters
                if not isinstance(value, str) and hasattr(value, "__iter__"):
                    temp_tag = []
                    for item in value:
                        lbl = QtWidgets.QLabel(item)
                        modelgrid.addWidget(lbl, self.nextrow, 0)

                        # create & store one QLineEdit
                        le = QtWidgets.QLineEdit()
                        self.obj_trac.model_entry_var[self.nextcount] = le
                        le.setText("")

                        # load any previous XML value
                        try:
                            for child in root if root is not None else []:
                                if child.text == line[2] and child.tag == line[3]:
                                    le.setText(child[i].text)
                                    i += 1
                        except Exception:
                            pass

                        # add exactly one widget per row
                        modelgrid.addWidget(le, self.nextrow, 1)

                        temp_tag.append(self.nextcount)
                        self.nextcount += 1
                        self.nextrow   += 1

                    tag_dict[key] = temp_tag

                # SCALAR parameters
                else:
                    lbl = QtWidgets.QLabel(value)
                    modelgrid.addWidget(lbl, self.nextrow, 0)

                    le = QtWidgets.QLineEdit()
                    self.obj_trac.model_entry_var[self.nextcount] = le
                    le.setText("")

                    try:
                        for child in root if root is not None else []:
                            if child.text == line[2] and child.tag == line[3]:
                                le.setText(child[i].text)
                                i += 1
                    except Exception:
                        pass

                    modelgrid.addWidget(le, self.nextrow, 1)

                    tag_dict[key]   = self.nextcount
                    self.nextcount  += 1
                    self.nextrow    += 1

            self.end = self.nextcount - 1
            modelbox.setLayout(modelgrid)

            # CSS
            modelbox.setStyleSheet(
                " \
            QGroupBox { border: 1px solid gray; border-radius: \
            9px; margin-top: 0.5em; } \
            QGroupBox::title { subcontrol-origin: margin; left:\
             10px; padding: 0 3px 0 3px; } \
            "
            )

            self.grid.addWidget(modelbox)

            # This keeps the track of Model Tab Widget
            lst = [
                line[0],
                line[1],
                line[2],
                line[3],
                line[4],
                line[5],
                line[6],
                self.start,
                self.end,
                tag_dict,
            ]
            check = 0
            for itr in self.obj_trac.modelTrack:
                if itr == lst:
                    check = 1
            if check == 0:
                self.obj_trac.modelTrack.append(lst)
