"""Pytest bootstrap for the ngspicetoModelica suite: put eSim's ``src`` tree on
sys.path so ``import ngspicetoModelica...`` works regardless of the invocation
directory."""
import os
import sys

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
