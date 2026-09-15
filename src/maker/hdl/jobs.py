"""Tiny QThread wrapper for running a blocking backend call off the GUI thread.

This is the ONLY Qt-aware module in hdl/. It keeps the long iverilog/vvp work
(hdl.icarus) from freezing the UI: the widget starts a :class:`BackgroundJob`,
gets ``succeeded``/``failed`` on the GUI thread, and can hand the job an
``icarus.CancelToken`` to support a Cancel button.
"""
from PyQt6 import QtCore


class BackgroundJob(QtCore.QThread):
    """Run ``fn(*args, **kwargs)`` on a worker thread.

    Emits ``succeeded(result)`` with the return value, or ``failed(str)`` if the
    callable raised. The result is delivered via a queued signal, so the slot
    runs back on the GUI thread and may safely touch widgets.

    ``progress(kind, text)`` is the same story for *interim* news -- a phase
    change, a line of simulator output -- so a long run can say what it is
    doing instead of presenting a frozen-looking panel. A callable that wants
    it declares a first parameter literally named ``report`` and is handed a
    ``report(kind, text)`` bound to that signal; every other callable is
    invoked exactly as before.

    The opt-in is by parameter NAME, not by arity: a bound method with one
    defaulted argument (``build_cosim(self, engine="icarus")``) has the same
    arity as an opt-in worker, and handing it the reporter would silently pass
    a callable where it expected a string.
    """

    succeeded = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(str, str)

    def __init__(self, fn, *args, parent=None, **kwargs):
        super().__init__(parent)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def _wants_report(self):
        """True when ``fn``'s first parameter is named ``report``."""
        import inspect
        try:
            params = list(inspect.signature(self._fn).parameters)
        except (TypeError, ValueError):
            return False
        return bool(params) and params[0] == 'report'

    def run(self):
        args = self._args
        if self._wants_report():
            args = (self.progress.emit,) + tuple(args)
        try:
            result = self._fn(*args, **self._kwargs)
        except Exception as exc:  # surfaced to the UI as a failed signal
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)
