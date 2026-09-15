"""Qt-free core for eSim's HDL -> ngspice-block subsystem.

Everything in this package is pure Python (no PyQt) so it can be unit-tested
without a display and reused by every front end (the Verilog Simulator IDE, the
NgVeri convert flow, and the future Flow Navigator). UI code lives elsewhere;
this package only knows about strings, files and toolchains.
"""
