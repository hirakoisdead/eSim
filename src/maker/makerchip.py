# =========================================================================
#             FILE: makerchip.py
#
#            USAGE: ---
#
#      DESCRIPTION: Entry widget for eSim's HDL -> ngspice-block subsystem.
#                   Hosts the Flow Navigator (Author -> Verify -> Convert ->
#                   Place, with a VHDL/NGHDL path) that replaced the old flat
#                   Makerchip / NgVeri / NGHDL tab strip.
#
#          OPTIONS: ---
#     REQUIREMENTS: ---
#             BUGS: ---
#            NOTES: ---
#           AUTHOR: Sumanto Kar, sumantokar@iitb.ac.in, FOSSEE, IIT Bombay
# ACKNOWLEDGEMENTS: Rahul Paknikar, rahulp@iitb.ac.in, FOSSEE, IIT Bombay
#                Digvijay Singh, digvijay.singh@iitb.ac.in, FOSSEE, IIT Bombay
#                Prof. Maheswari R. and Team, VIT Chennai
#     GUIDED BY: Steve Hoover, Founder Redwood EDA
#                Kunal Ghosh, VLSI System Design Corp.Pvt.Ltd
#                Anagha Ghosh, VLSI System Design Corp.Pvt.Ltd
# OTHER CONTRIBUTERS:
#                Prof. Madhuri Kadam, Shree L. R. Tiwari College of Engineering
#                Rohinth Ram, Madras Institue of Technology
#                Charaan S., Madras Institue of Technology
#                Nalinkumar S., Madras Institue of Technology
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
#       CREATED: Monday 29, November 2021
#      REVISION: Tuesday 25, January 2022
# =========================================================================

# importing the files and libraries
import os
import sys
from PyQt6 import QtWidgets
from .FlowNavigator import FlowNavigator

# The NGHDL GUI lives in-repo at <repo>/nghdl/src and uses flat imports, just
# like its standalone `nghdl` entry point. Put that directory on sys.path so it
# can be imported and embedded as the VHDL stage. Mutating sys.path is
# acceptable here because the names it exposes (ngspice_ghdl, Appconfig,
# model_generation, createKicadLibrary) do not collide with any eSim module.
_NGHDL_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'nghdl', 'src'))
if os.path.isdir(_NGHDL_SRC) and _NGHDL_SRC not in sys.path:
    sys.path.append(_NGHDL_SRC)

# filecount is used to count the number of windows created
filecount = 0


class makerchip(QtWidgets.QWidget):
    '''
        Hosts the Flow Navigator for the HDL -> ngspice-block workflow.
    '''

    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self)
        print("==================================")
        print("Makerchip and Verilog to Ngspice Converter")
        print("==================================")
        self.createMainWindow()

    def createMainWindow(self):
        self.vbox = QtWidgets.QVBoxLayout()
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.addWidget(self.createWidget())
        self.setLayout(self.vbox)
        self.setWindowTitle("Makerchip and Verilog to Ngspice Converter")

    def createWidget(self):
        global filecount
        self.flow = FlowNavigator(filecount, self)
        # incrementing filecount for every new window
        filecount = filecount + 1
        return self.flow
