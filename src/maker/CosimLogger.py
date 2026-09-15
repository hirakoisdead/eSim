# =========================================================================
# FILE: CosimLogger.py
#
# PURPOSE: Structured, dual-sink logging for the d_cosim (Icarus Verilog)
#          flow -- build, netlist staging and simulation run.
#
#   Before this module the d_cosim flow logged in two disconnected ways:
#     * build_cosim() appended raw HTML to the NgVeri GUI terminal only, and
#     * the netlist stager / run path used bare print()/logger calls that went
#       only to the OS terminal (and, with no logging config, often nowhere).
#   So no single audience ever saw the whole story, nothing was timestamped or
#   severity-tagged, and the exact compiler command / return code were hidden.
#
#   CosimLog fixes that: every event is emitted to BOTH
#     1. the Python 'esim.dcosim' logger -> the OS terminal eSim was launched
#        from AND a rotating ~/.esim/dcosim.log file (timestamped, severity-
#        tagged, grep-able for developers), and
#     2. an optional GUI QTextEdit (the NgVeri tab terminal) as a severity-
#        colored line, so an end user reading the GUI sees the same events.
#
# Developed for the eSim ubuntu-26.04-support fork.
# =========================================================================

import os
import sys
import logging
from html import escape

# Parent logger for the whole d_cosim flow. Module loggers can be children
# (e.g. 'esim.dcosim.build') and inherit these handlers.
_ROOT_NAME = 'esim.dcosim'
_CONFIGURED = False


def configure_logging():
    '''
        Idempotently attach a console + rotating-file handler to the
        'esim.dcosim' logger. Safe to call many times (guards against
        duplicate handlers). Honors ESIM_DEBUG=1 for verbose console output;
        the logfile is always DEBUG-level.
    '''
    global _CONFIGURED
    if _CONFIGURED:
        return

    console_level = logging.DEBUG if os.environ.get('ESIM_DEBUG') \
        else logging.INFO
    fmt = logging.Formatter(
        '%(asctime)s %(levelname)-7s %(name)s: %(message)s',
        datefmt='%H:%M:%S')

    root = logging.getLogger(_ROOT_NAME)
    # Root gates first, so keep it at the most verbose level any handler wants
    # and let each handler filter; otherwise the file handler never sees DEBUG.
    root.setLevel(logging.DEBUG)
    # Don't double-print through the application's root logger.
    root.propagate = False

    # Console -> the OS terminal eSim was launched from.
    if not any(getattr(h, '_esim_console', False) for h in root.handlers):
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        ch.setLevel(console_level)
        ch._esim_console = True
        root.addHandler(ch)

    # Rotating logfile -> persistent, always-verbose record under ~/.esim.
    if not any(getattr(h, '_esim_file', False) for h in root.handlers):
        try:
            from logging.handlers import RotatingFileHandler
            logdir = os.path.join(os.path.expanduser('~'), '.esim')
            os.makedirs(logdir, exist_ok=True)
            fh = RotatingFileHandler(
                os.path.join(logdir, 'dcosim.log'),
                maxBytes=1_000_000, backupCount=3)
            fh.setFormatter(fmt)
            fh.setLevel(logging.DEBUG)
            fh._esim_file = True
            root.addHandler(fh)
        except OSError:
            # Read-only HOME etc. -- console logging still works.
            pass

    _CONFIGURED = True


class CosimLog:
    '''
        Severity-aware logger that fans every message out to the Python
        'esim.dcosim' logger (terminal + file) and, when given one, to a GUI
        QTextEdit (the NgVeri terminal) as a colored HTML line.

        param termedit: optional QTextEdit whose .append() renders HTML; pass
                        None for non-GUI contexts (netlist staging, sim run)
                        where only terminal+file output is wanted.
        param sink:     optional callable(html) used INSTEAD of termedit.append
                        as the GUI sink. Pass a queued-signal emit (e.g. a
                        pyqtSignal(str).emit connected to the terminal) when the
                        logger may be driven from a worker thread, so GUI writes
                        cross back to the GUI thread instead of touching the
                        QTextEdit off-thread.
    '''

    # GUI line colors. None means "emit no color at all" so the line inherits
    # the QTextEdit palette -- which is what the active theme sets. A
    # hardcoded #000000 renders black-on-black and is INVISIBLE on the dark
    # theme; ModelGeneration.termtext/termtitle already took exactly this fix,
    # but CosimLog paints the whole d_cosim build story into the same terminal
    # and kept the light-theme values. Only lines whose color carries MEANING
    # keep one, and those reuse the theme-tested values shared with the rest of
    # the maker UI. A phase header is already distinguished by size+weight, so
    # it needs no color either.
    _COLOR = {
        'info': None,               # body text -> palette
        'ok': '#00AA00',
        'warn': '#E07B00',
        'error': '#FF0000',
        'phase': None,              # marked by size/weight, not color
        'detail': '#666666',        # deliberately dim on both themes
        'fix': '#B30086',
        'stdout': None,             # verbatim tool output -> palette
        # Same two values ModelGeneration._emit_stderr classifies into. This
        # sink is used for messages that ARE already known to be failures, so
        # unlike the raw tool stream it does not re-classify.
        'stderr': '#FF0000',
    }

    def __init__(self, termedit=None, name=_ROOT_NAME, sink=None):
        configure_logging()
        self.termedit = termedit
        # Prefer an explicit sink (typically a queued signal.emit so the logger
        # is safe to drive from a worker thread); else fall back to appending
        # straight to the QTextEdit.
        if sink is not None:
            self._sink = sink
        elif termedit is not None:
            self._sink = termedit.append
        else:
            self._sink = None
        self.logger = logging.getLogger(name)

    # -- internal GUI sink --------------------------------------------------
    def _gui(self, html):
        if self._sink is not None:
            self._sink(html)

    @staticmethod
    def _color_css(color):
        '''"color:<c>;" for a semantic color, "" for None -- an omitted color
           inherits the widget palette, i.e. follows the active theme.'''
        return ('color:%s;' % color) if color else ''

    def _span(self, msg, color, size=12, weight=500):
        self._gui(
            '<span style="font-size:%dpt; font-weight:%d;%s">%s</span>'
            % (size, weight, self._color_css(color), escape(msg)))

    # -- public API ---------------------------------------------------------
    def phase(self, title):
        '''Bold blue section header marking a new step of the flow.'''
        self.logger.info('=== %s ===', title)
        self._gui(
            '<span style="font-size:14pt; font-weight:800;%s">'
            '<br>&#9654;&nbsp;%s</span>'
            % (self._color_css(self._COLOR['phase']), escape(title)))

    def info(self, msg):
        '''Normal progress line (INFO).'''
        self.logger.info(msg)
        self._span(msg, self._COLOR['info'])

    def detail(self, msg):
        '''Low-priority diagnostic: DEBUG on terminal/file, dim grey in GUI.'''
        self.logger.debug(msg)
        self._span(msg, self._COLOR['detail'], size=11)

    def ok(self, msg):
        '''Success line (green).'''
        self.logger.info(msg)
        self._span(msg, self._COLOR['ok'], weight=600)

    def warn(self, msg):
        '''Warning line (orange).'''
        self.logger.warning(msg)
        self._span(msg, self._COLOR['warn'], weight=600)

    def error(self, msg):
        '''Failure line (red).'''
        self.logger.error(msg)
        self._span(msg, self._COLOR['error'], weight=700)

    def fix(self, msg):
        '''Actionable remediation hint shown after an error.'''
        self.logger.error('Fix: %s', msg)
        self._span('Fix: ' + msg, self._COLOR['fix'], weight=600)

    def output(self, text, stream='stdout'):
        '''
            Echo a captured subprocess stream block verbatim in a monospace
            box. stream='stderr' is logged at WARNING and rendered red.
        '''
        text = (text or '').rstrip()
        if not text:
            return
        if stream == 'stderr':
            self.logger.warning('[iverilog stderr]\n%s', text)
        else:
            self.logger.info('[iverilog stdout]\n%s', text)
        self._gui(
            '<pre style="margin:2px 0; font-size:11pt;%s">%s</pre>'
            % (self._color_css(self._COLOR[stream]), escape(text)))
