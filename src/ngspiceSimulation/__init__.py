# ngspiceSimulation/__init__.py
"""
NGSpice Simulation Module

This package provides NGSpice simulation integration including:
- NgspiceWidget: Widget for running NGSpice simulations
- plotWindow: Window for plotting and analyzing simulation results
"""

__all__ = ['NgspiceWidget', 'plotWindow']
__version__ = '1.0.0'


# PEP 562 lazy exports: plot_window drags in matplotlib.pyplot + numpy, which
# dominates eSim's import time (worst on a cold Windows start, where Defender
# scans every native module on first load). Deferring it until a plot is
# actually opened keeps `import ngspiceSimulation` (and through it DockArea /
# Application startup) off that path entirely.
def __getattr__(name):
    if name == 'plotWindow':
        from .plot_window import plotWindow
        return plotWindow
    if name == 'NgspiceWidget':
        from .NgspiceWidget import NgspiceWidget
        return NgspiceWidget
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
