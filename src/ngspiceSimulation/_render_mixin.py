from typing import List, Optional, Tuple
import matplotlib
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, ScalarFormatter
from .data_extraction import DataExtraction
from .trace import Trace
from .constants import (LEGEND_FONT_SIZE, THRESHOLD_ALPHA,
                        TIME_UNIT_THRESHOLD_PS, TIME_UNIT_THRESHOLD_NS,
                        TIME_UNIT_THRESHOLD_US, TIME_UNIT_THRESHOLD_MS,
                        REFRESH_DEBOUNCE_MS, STACKED_REFRESH_DEBOUNCE_MS,
                        DECIMATION_MIN_POINTS, DECIMATION_BINS,
                        MAX_STACKED_GAP_RATIO)
from .math_utils import (_format_measurement, _format_frequency, _detect_frequency, _trapz,
                         minmax_decimate)


class _RenderMixin:
    def _schedule_refresh(self) -> None:
        """Coalesce rapid visibility toggles into a single deferred refresh.

        Restarting the single-shot timer on each call means a burst of clicks
        collapses to one refresh_plot once the user stops. Used by every
        waveform/func-trace visibility toggle; direct refresh_plot calls
        (view-mode change, autoscale, etc.) cancel any pending tick via the
        stop() at the top of refresh_plot so they never double-rebuild.

        The window is mode-aware: a stacked toggle restructures panes and
        redraws the whole (tall) canvas — cheap since the incremental stacked
        path, but still the priciest toggle — so a wider window collapses a
        human-paced click burst into one restructure. Normal view toggles
        take the cheapest incremental path and stay snappy at 80ms. The list
        item icon/text update synchronously either way, so clicks always feel
        instant; only the plot redraw is deferred.
        """
        self._refresh_timer.setInterval(
            STACKED_REFRESH_DEBOUNCE_MS if self.radio_stacked.isChecked()
            else REFRESH_DEBOUNCE_MS)
        self._refresh_timer.start()

    # ── Draw-time decimation ─────────────────────────────────────────────
    # Long traces are drawn as a per-bin min/max envelope (peak-preserving,
    # pixel-identical at screen scale) so matplotlib transforms/rasterises a
    # few thousand points instead of the full array — the dominant per-pane
    # cost once several long transients are stacked. The raw arrays stay on
    # the artist and the view is re-sliced+re-decimated after zoom/pan, so
    # zooming in always recovers full sample resolution.

    def _add_decimated_line(self, ax, x, y, kind: str = 'plot', **kwargs) -> Line2D:
        """Plot one line, decimated when large. kind: 'plot'|'step'|'semilogx'.

        Only monotonic-x lines are decimated (Lissajous-style function traces
        plot verbatim — index bins would scramble their path).
        """
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        n = min(len(x), len(y))
        x, y = x[:n], y[:n]
        xd, yd = x, y
        if n > DECIMATION_MIN_POINTS and bool(np.all(np.diff(x) >= 0)):
            xd, yd = minmax_decimate(x, y, DECIMATION_BINS)
        if kind == 'step':
            line, = ax.step(xd, yd, where='post', **kwargs)
        elif kind == 'semilogx':
            line, = ax.semilogx(xd, yd, **kwargs)
        else:
            line, = ax.plot(xd, yd, **kwargs)
        if len(xd) < n:
            line._esim_raw_xy = (x, y)
            line._esim_decim_span = (0, n)
            self._decim_registry.append(line)
        return line

    def _connect_xlim_watch(self) -> None:
        """Arm xlim_changed → deferred re-decimation on every pane.

        Connected per-pane because matplotlib propagates shared-x limit
        changes to siblings with emit=False — a zoom on pane 3 never fires
        pane 0's callback. The single-shot timer coalesces the per-pane burst
        into one _redecimate_visible pass.
        """
        for ax in self.panes:
            if not getattr(ax, '_esim_xlim_watch', False):
                ax.callbacks.connect(
                    'xlim_changed', lambda _ax: self._schedule_redecimate())
                ax._esim_xlim_watch = True

    def _schedule_redecimate(self) -> None:
        if self._decim_registry:
            self._decim_timer.start()

    def _redecimate_visible(self) -> None:
        """Re-slice each decimated line's raw data to the current x-view.

        Skipped mid-drag: divider drag swaps line data itself, and the cursor
        blit snapshot would be invalidated by a data change. Both end with a
        full draw/refresh, and the next zoom re-arms the timer anyway.
        """
        if self._divider_drag is not None or self._blit_background is not None:
            return
        fig_axes = self.fig.axes
        live = [ln for ln in self._decim_registry
                if ln.axes is not None and ln.axes in fig_axes]
        self._decim_registry = live
        changed = False
        for ln in live:
            x, y = ln._esim_raw_xy
            xlo, xhi = ln.axes.get_xlim()
            if xlo > xhi:
                xlo, xhi = xhi, xlo
            i0 = max(0, int(np.searchsorted(x, xlo, side='left')) - 1)
            i1 = min(len(x), int(np.searchsorted(x, xhi, side='right')) + 1)
            if i1 - i0 < 2 or (i0, i1) == ln._esim_decim_span:
                continue
            xd, yd = minmax_decimate(x[i0:i1], y[i0:i1], DECIMATION_BINS)
            ln.set_data(xd, yd)
            ln._esim_decim_span = (i0, i1)
            changed = True
        if changed:
            self.canvas.draw_idle()

    def _composition_signature(self, mode: str) -> tuple:
        """Fingerprint of everything that determines the pane/artist structure.

        When this is unchanged between two refreshes, the existing axes and
        Line2D objects are already correct (trace data is static after load),
        so refresh_plot can skip the full fig.clear() teardown.

        Per mode it captures only what is *structural* for that mode:

        - normal: one shared Axes regardless of how many traces are visible,
          so the visible set is deliberately EXCLUDED — visibility toggles are
          handled incrementally via set_visible. What IS structural: the
          analysis path (plot vs semilogx vs step), which traces use steps
          (changes the artist type), the visible function-overlay set, and
          whether the legend is shown.
        - stacked: one pane per visible trace, so the visible set + per-trace
          steps flag + visible func panes + stats overlay are all structural.
        - timing: rows are laid out by the visible set; threshold and spacing
          change every row's geometry.

        Changes the signature cannot see (pane reorder, divider resize, lock
        toggle, rename) set self._force_full_refresh instead.
        """
        vis_func = tuple(i for i in range(len(self._func_traces))
                         if i < len(self._func_visible) and self._func_visible[i])
        if mode == 'normal':
            steps = tuple(sorted(i for i, t in self.traces.items()
                                 if t.style == 'steps-post'))
            return ('normal', self._current_analysis_type, steps, vis_func,
                    self.legend_check.isChecked())
        if mode == 'stacked':
            vis = self.visible_traces
            return ('stacked',
                    tuple(t.index for t in vis),
                    tuple(t.style == 'steps-post' for t in vis),
                    vis_func,
                    self.stats_check.isChecked())
        # timing
        return ('timing',
                tuple(t.index for t in self.visible_traces),
                vis_func,
                self.threshold_spinbox.value(),
                self.vertical_spacing)

    def refresh_plot(self) -> None:
        # Cancel any pending debounced refresh — this call supersedes it, so a
        # queued timer tick must not fire a second redundant rebuild afterwards.
        self._refresh_timer.stop()
        force_full = self._force_full_refresh
        self._force_full_refresh = False

        next_mode = ('timing' if self.radio_timing.isChecked()
                     else 'stacked' if self.radio_stacked.isChecked()
                     else 'normal')
        new_sig = self._composition_signature(next_mode)

        # ── Incremental fast path ────────────────────────────────────────
        # Taken only when the pane composition is provably unchanged from what
        # is currently drawn: same mode, matching signature, live panes, and no
        # caller-forced full rebuild. Then the axes + lines already exist and
        # are correct, so we avoid fig.clear() entirely.
        if (not force_full and self.panes
                and self._drawn_signature is not None
                and new_sig == self._drawn_signature
                and self._current_view_mode == next_mode):
            if next_mode == 'normal':
                # Normal view keeps ALL prior limits/cursors; only line
                # visibility may differ. 0-visible needs the placeholder text,
                # so fall through to the full rebuild for that case.
                if self.visible_traces:
                    self._incremental_refresh_normal()
                    return
            else:
                # Stacked/timing: identical composition + static data means the
                # rendered figure is already correct. Just redraw.
                for ax in self.panes:
                    ax.grid(self.grid_check.isChecked())
                self.canvas.draw_idle()
                return

        # ── Incremental stacked path ─────────────────────────────────────
        # A visibility toggle in stacked view only adds/removes panes; the
        # untouched panes' axes, lines, titles, and user zoom are already
        # correct. Reusing them turns an O(all panes) fig.clear() rebuild
        # into O(changed panes) — the difference between stutter and snappy
        # once many waveforms are stacked.
        if (not force_full and next_mode == 'stacked'
                and self._current_view_mode == 'stacked'
                and self._try_incremental_stacked(new_sig)):
            self._drawn_signature = new_sig
            return

        # ── Full rebuild ─────────────────────────────────────────────────
        # Preserve zoom when autoscale is off.
        # Capture only when staying in the SAME ylim-meaningful mode: timing
        # uses [0..N] normalized space, stacked uses per-trace SI units —
        # restoring one across modes would clip signals or scramble panes.
        capture_state = (not self.autoscale_check.isChecked()
                         and self._current_view_mode == next_mode
                         and next_mode in ('normal', 'stacked')
                         and bool(self.panes))
        if capture_state:
            self._capture_view_state()

        # Re-enable constrained_layout before rebuilding: a previous stacked
        # refresh may have frozen it (engine off + pinned positions). The new
        # panes must be solved once by CL; _freeze_layout re-freezes at the end
        # for multi-pane stacked. Cheap single-pane modes stay CL-managed.
        self.fig.set_layout_engine('constrained')

        self._func_line = None  # fig.clear() below wipes all artists
        self._empty_placeholder = None
        self.timing_annotations.clear()
        # Any in-progress cursor drag and the blit snapshot become invalid
        # once fig.clear() tears down the figure.  Reset them here so the
        # restore path that follows starts from a clean state.
        self._drag_cursor_idx = None
        self._blit_background = None
        self.fig.clear()
        # All artists died with the figure; drop decimation + pane-identity
        # records so the incremental paths never touch dead objects.
        self._decim_registry = []
        self._stacked_pane_keys = []
        # Hover-cache held references to the old Axes; invalidate before
        # _build_panes hands out fresh ones.
        self._last_hover_axes = None
        self._last_hover_anchor = None
        for t in self.traces.values():
            t.line_object = None
        # Set view mode BEFORE plot path runs so callees (update_timing_tick_colors,
        # legend handling, etc.) can branch on the new mode instead of the prior one.
        self._current_view_mode = next_mode
        if next_mode == 'timing':
            self._build_panes(1)
            self.plot_timing_diagram()
        elif next_mode == 'stacked':
            self.plot_stacked_diagram()
        else:
            if self.plot_type[0] == DataExtraction.AC_ANALYSIS:
                if self.plot_type[1] == 1:
                    self.on_push_decade()
                else:
                    self.on_push_ac()
            elif self.plot_type[0] == DataExtraction.TRANSIENT_ANALYSIS:
                self.on_push_trans()
            else:
                self.on_push_dc()
        if self.panes:
            for ax in self.panes:
                ax.grid(self.grid_check.isChecked())
            # Restore unconditionally: capture_state fills saved_pane_ylims
            # for the preserve-zoom path, AND lock-Y entries persist there
            # independently. _restore_view_state is a no-op when both are
            # empty, so calling it is always safe.
            self._restore_view_state()
            if self.legend_check.isChecked():
                self.position_legend()
        self._restore_cursors()
        self._connect_xlim_watch()
        # Record what we just drew so the next refresh can skip the rebuild if
        # nothing structural changed. Recomputed rather than reusing new_sig:
        # the normal-mode signature reads _current_analysis_type, which the
        # plot path above sets. Storing the pre-plot value would mismatch on
        # the next refresh and force one spurious full rebuild.
        self._drawn_signature = self._composition_signature(next_mode)
        # Arm the free post-draw freeze for multi-pane stacked: the draw below
        # solves CL once, then _on_draw_event pins the result and drops the
        # engine so later draws skip the solver. Doing this inline (an extra
        # synchronous layout pass) is what made rapid toggling lag, so we let
        # the draw we already need do the work. Single-pane modes keep CL on —
        # cheap there, and it keeps tick-label margins adaptive.
        self._pending_freeze = (self._current_view_mode == 'stacked'
                                and len(self.panes) > 1)
        self.canvas.draw_idle()

    def _incremental_refresh_normal(self) -> None:
        """Update the shared-axes normal view in place — no fig.clear().

        Used when the composition signature is unchanged but trace visibility
        may have toggled. Reconciles each trace's Line2D (lazily creating one
        for a newly-visible trace, hiding rather than destroying one that was
        switched off), then re-fits/legends/cursors exactly as a full rebuild
        would, all without tearing the figure down.
        """
        # The empty-state text was drawn by a rebuild that saw zero visible
        # traces. This path is only entered with ≥1 visible (refresh_plot falls
        # through to a full rebuild otherwise), so it is always stale here —
        # and nothing else clears it, since there is no fig.clear() on this path.
        if self._empty_placeholder is not None:
            self._empty_placeholder.remove()
            self._empty_placeholder = None

        for idx, t in self.traces.items():
            if t.visible:
                if t.line_object is None:
                    self._draw_normal_trace_line(t)
                else:
                    t.line_object.set_visible(True)
            elif t.line_object is not None:
                # Keep the artist for cheap re-show; just hide it.
                t.line_object.set_visible(False)

        # Re-fit only when autoscale is on; otherwise leave the user's zoom.
        # visible_only=True excludes the hidden (kept) lines from the bounds.
        if self.autoscale_check.isChecked():
            self.axes.relim(visible_only=True)
            self.axes.autoscale_view()

        first_visible = next((i for i in sorted(self.traces)
                              if self.traces[i].visible), None)
        if first_visible is not None:
            self.axes.set_ylabel('Voltage (V)' if first_visible < self.volts_length
                                 else 'Current (A)')

        if self.legend_check.isChecked():
            # legend() replaces any existing legend; ≥1 visible is guaranteed
            # by the caller, so position_legend always has a handle to draw.
            self.position_legend()

        # Cursor axvlines persist on the live axes (no fig.clear), so they need
        # no re-creation — but the sidebar readouts depend on the visible set,
        # which just changed, so refresh those.
        if any(p is not None for p in self.cursor_positions):
            self._refresh_cursor_readouts()

        self.canvas.draw_idle()

    def _on_draw_event(self, event) -> None:
        """Freeze the layout for FREE, right after a stacked rebuild's draw.

        The CL solver (~60% of a stacked draw's Python time) re-runs on every
        draw — even when pane geometry is unchanged. We can't avoid the one
        solve that the rebuild's own draw performs, but we CAN stop it repeating
        on subsequent zoom/pan/cursor draws: this fires after that draw has
        already solved CL, so we snapshot the EXACT solved positions (margins
        match CL by construction — rotated y-labels, stats titles included) and
        drop the engine. No extra layout pass, so rapid toggling stays cheap.
        """
        if not (self.panes and self._current_view_mode == 'stacked'):
            return
        if self._pending_freeze and len(self.panes) > 1:
            self._pending_freeze = False
            positions = [ax.get_position().frozen() for ax in self.panes]
            self.fig.set_layout_engine('none')   # stop the solver
            for ax, pos in zip(self.panes, positions):
                ax.set_position(pos)             # pin the CL-solved geometry

    def position_legend(self) -> None:
        if not (self.panes and self.legend_check.isChecked()):
            return
        # Stacked view: each pane already has a single-trace caption (set by
        # the stacked plot path), so a combined legend on the top pane would
        # be redundant noise.
        if self._current_view_mode == 'stacked':
            return
        handles, labels = [], []
        for idx in sorted(self.traces.keys()):
            t = self.traces[idx]
            if t.visible and t.line_object:
                handles.append(t.line_object)
                labels.append(t.name)
        if not handles:
            return
        ncol = max(1, min(4, len(handles)))
        legend = self.axes.legend(
            handles, labels,
            loc='best',
            ncol=ncol,
            frameon=True,
            fancybox=False,
            shadow=False,
            framealpha=0.95,
            columnspacing=1.2,
            handlelength=1.5,
        )
        # Frame colors from the live palette, not hardcoded light literals: a
        # baked 'white'/'#E0E0E0' frame is a white box on dark theme even on a
        # fresh render (rcParams legend.facecolor/edgecolor already track the
        # palette; these overrides used to fight it). _retheme_canvas re-applies
        # these same tokens on a live theme toggle.
        legend.get_frame().set_facecolor(self._palette['legend_face'])
        legend.get_frame().set_edgecolor(self._palette['legend_edge'])
        legend.get_frame().set_linewidth(1)

    def _get_transient_start_idx(self, time_data: "np.ndarray") -> int:
        """Return the index into time_data where the .tran start time begins, or 0."""
        if self._tran_start_time > 0:
            return int(np.searchsorted(time_data, self._tran_start_time))
        return 0

    def plot_timing_diagram(self) -> None:
        """Plot digital timing diagram with normalized trace heights."""
        self.timing_annotations.clear()

        if self.plot_type[0] != DataExtraction.TRANSIENT_ANALYSIS:
            _msg = self.axes.text(
                0.5, 0.5, 'Digital timing view is only\navailable for transient analysis.',
                ha='center', va='center', transform=self.axes.transAxes,
                color=self._palette['info_text'])
            # Tag as chrome so _retheme_canvas recolors it on a live theme
            # toggle (rcParams don't touch an already-created Text artist).
            _msg.set_gid('esim-chrome')
            self.axes.set_yticks([])
            self.axes.set_yticklabels([])
            return

        visible_indices = [t.index for t in self.visible_traces]
        if not visible_indices:
            self.axes.text(0.5, 0.5, 'Select a waveform to display',
                           ha='center', va='center', transform=self.axes.transAxes)
            self.axes.set_yticks([])
            self.axes.set_yticklabels([])
            return

        self.logic_thresholds = {}

        # Build local float arrays for all traces — never touch obj_dataext
        time_data = np.asarray(self.obj_dataext.x, dtype=float)
        y_data = {i: np.asarray(self.obj_dataext.y[i], dtype=float)
                  for i in range(len(self.obj_dataext.y))}

        if self.plot_type[0] == DataExtraction.TRANSIENT_ANALYSIS:
            start_idx = self._get_transient_start_idx(time_data)
            if 0 < start_idx < len(time_data):
                time_data = time_data[start_idx:]
                y_data = {i: arr[start_idx:] for i, arr in y_data.items()}

        # Fit the threshold spin box to the actual voltage span of the visible
        # traces, so its range/step/Auto-midpoint are meaningful. The old fixed
        # -100..100 range made the single step out of Auto jump to a useless
        # extreme threshold (everything reads logic-high → waveforms vanish).
        spans = [y_data[i] for i in visible_indices if i in y_data and len(y_data[i])]
        if spans:
            self._sync_threshold_range(float(min(np.min(a) for a in spans)),
                                       float(max(np.max(a) for a in spans)))

        manual_threshold = (None if self.threshold_spinbox.value() == self.threshold_spinbox.minimum()
                            else self.threshold_spinbox.value())
        if manual_threshold is None:
            self.threshold_spinbox.setSpecialValueText("Auto (midpoint)")

        # Each trace occupies exactly 1.0 normalized unit of y-space.
        # spacing = vertical_spacing (e.g. 1.2 → 20% gap between traces).
        # This guarantees uniform height for all signals regardless of voltage domain.
        spacing = self.vertical_spacing
        yticks, ylabels = [], []

        for rank, idx in enumerate(visible_indices[::-1]):
            raw_data = y_data[idx]

            # Safety clamp — guards against malformed simulation output where a
            # y array is shorter or longer than the time axis. Use a local
            # trace_time so time_data is never mutated across iterations.
            n = min(len(raw_data), len(time_data))
            raw_data = raw_data[:n]
            trace_time = time_data[:n]

            # An empty trace (header-only / all-rows-dropped run) makes
            # np.min/np.max raise "zero-size array to reduction" — skip it
            # so the Timing view still renders the remaining traces.
            if n == 0:
                continue

            trace_vmin, trace_vmax = np.min(raw_data), np.max(raw_data)
            trace_unit = "V" if idx < self.obj_dataext.volts_length else "A"

            if trace_vmax - trace_vmin < 1e-10:
                # Constant (DC) signal — state indeterminate, park at 0.5.
                # No threshold line drawn (nothing to threshold against).
                logic_normalized = np.full(n, 0.5)
            else:
                # Per-trace threshold: midpoint of its own swing (CMOS VDD/2 convention).
                # Manual override applies the user's voltage, normalized into [0,1] for
                # this trace so the axhline always sits within the trace bounds.
                threshold = (manual_threshold if manual_threshold is not None
                             else (trace_vmin + trace_vmax) / 2.0)
                logic_normalized = np.where(raw_data > threshold, 1.0, 0.0)
                threshold_norm = float(np.clip(
                    (threshold - trace_vmin) / (trace_vmax - trace_vmin), 0.0, 1.0
                ))
                self.logic_thresholds[idx] = threshold_norm

            logic_offset = logic_normalized + rank * spacing

            t = self.traces[idx]
            line = self._add_decimated_line(
                self.axes, trace_time, logic_offset, kind='step',
                linewidth=t.thickness, color=t.color, label=t.name)
            t.line_object = line

            # y_center is always rank * spacing + 0.5 in normalized space.
            y_center = rank * spacing + 0.5
            yticks.append(y_center)
            ylabels.append(t.name)

            ann = []
            xform = self.axes.get_yaxis_transform()
            if trace_vmax - trace_vmin < 1e-10:
                ann.append(self.axes.text(
                    1.01, y_center,
                    f"DC: {_format_measurement(float(trace_vmax), trace_unit)}",
                    transform=xform, va='center', ha='left',
                    color=t.color, clip_on=False))
            else:
                ann.append(self.axes.text(
                    1.01, rank * spacing + 0.82,
                    f"H: {_format_measurement(float(trace_vmax), trace_unit)}",
                    transform=xform, va='center', ha='left',
                    color=t.color, clip_on=False))
                ann.append(self.axes.text(
                    1.01, rank * spacing + 0.18,
                    f"L: {_format_measurement(float(trace_vmin), trace_unit)}",
                    transform=xform, va='center', ha='left',
                    color=t.color, clip_on=False))
                freq = _detect_frequency(trace_time, logic_normalized)
                if freq is not None:
                    ann.append(self.axes.text(
                        1.01, y_center, _format_frequency(freq),
                        transform=xform, va='center', ha='left',
                        color=t.color, alpha=0.75, clip_on=False))
            self.timing_annotations[idx] = ann

        # Func traces as additional timing channels — normalized same as sim signals.
        n_sim = len(visible_indices)
        vis_func = [
            (f_idx, self._func_traces[f_idx])
            for f_idx in range(len(self._func_traces))
            if f_idx < len(self._func_visible) and self._func_visible[f_idx]
        ]
        xform = self.axes.get_yaxis_transform()
        for func_slot, (f_idx, (flabel, fx, fy, fcolor, fthickness, _fs)) in enumerate(vis_func):
            rank = n_sim + func_slot
            n_pts = min(len(fx), len(fy))
            if n_pts < 2:
                continue
            fy_arr = np.asarray(fy[:n_pts], dtype=float)
            fx_arr = np.asarray(fx[:n_pts], dtype=float)
            fmin, fmax = float(np.min(fy_arr)), float(np.max(fy_arr))
            y_center = rank * spacing + 0.5
            if fmax - fmin < 1e-10:
                logic = np.full(n_pts, 0.5)
                self.axes.text(1.01, y_center, f"DC: {fmax:.4g}",
                               transform=xform, va='center', ha='left',
                               color=fcolor, clip_on=False,
                               fontsize=max(7, LEGEND_FONT_SIZE - 1))
            else:
                logic = np.where(fy_arr > (fmin + fmax) / 2.0, 1.0, 0.0)
                self.axes.text(1.01, rank * spacing + 0.82, f"H: {fmax:.4g}",
                               transform=xform, va='center', ha='left',
                               color=fcolor, clip_on=False,
                               fontsize=max(7, LEGEND_FONT_SIZE - 1))
                self.axes.text(1.01, rank * spacing + 0.18, f"L: {fmin:.4g}",
                               transform=xform, va='center', ha='left',
                               color=fcolor, clip_on=False,
                               fontsize=max(7, LEGEND_FONT_SIZE - 1))
                freq = _detect_frequency(fx_arr, logic)
                if freq is not None:
                    self.axes.text(1.01, y_center, _format_frequency(freq),
                                   transform=xform, va='center', ha='left',
                                   color=fcolor, alpha=0.75, clip_on=False,
                                   fontsize=max(7, LEGEND_FONT_SIZE - 1))
            self._add_decimated_line(
                self.axes, fx_arr, logic + rank * spacing, kind='step',
                color=fcolor, linewidth=fthickness, label=flabel)
            yticks.append(y_center)
            ylabels.append(f'ƒ {flabel}')

        # Y-axis bounds: total count includes func trace slots.
        total_count = n_sim + len(vis_func)
        total_height = max(total_count - 1, 0) * spacing + 1.0
        margin = 0.15 * spacing
        self.axes.set_ylim(-margin, total_height + margin)
        self.axes.set_yticks(yticks)
        self.axes.set_yticklabels(ylabels)

        self.update_timing_tick_colors()
        self.set_time_axis_label(time_data)

        # Threshold lines for sim signals only.
        for rank, idx in enumerate(visible_indices[::-1]):
            if idx in self.logic_thresholds:
                self.axes.axhline(y=self.logic_thresholds[idx] + rank * spacing,
                                  color='red', linestyle=':', alpha=THRESHOLD_ALPHA, linewidth=0.8)

    def _render_pane_stats(self, ax, group: List[int],
                           x_arr: "np.ndarray") -> None:
        """Draw a min/max/p-p/RMS (+ freq for periodic transient) overlay.

        One text row per trace in the group, anchored top-right via axes
        fraction so it survives pane resize / zoom. Skipped silently when
        the group has no plottable traces.
        """
        if not group:
            return
        rows: List[str] = []
        for trace_idx in group:
            t = self.traces.get(trace_idx)
            if t is None:
                continue
            # Sim data is static per load, so the stats line for a given
            # (trace, x-window, analysis) never changes — cache it. This is
            # O(points) work per trace per rebuild otherwise, and with stats
            # on it ran on every stacked visibility toggle. '' = computed but
            # skipped (too few points / degenerate axis).
            cache_key = (trace_idx, len(x_arr), self._current_analysis_type)
            row = self._stats_cache.get(cache_key)
            if row is None:
                row = self._compute_trace_stats_row(trace_idx, x_arr)
                self._stats_cache[cache_key] = row
            if row:
                rows.append(row)
        if not rows:
            return
        # No bbox — stats are in the title margin above the spine, no waveform
        # behind them, so a white background box is unnecessary and its padding
        # would straddle the spine into the axes area.
        ax.set_title("\n".join(rows), loc='right',
                     fontsize=max(7, LEGEND_FONT_SIZE - 1),
                     color=self._palette['stats_text'], pad=4)

    def _compute_trace_stats_row(self, trace_idx: int,
                                 x_arr: "np.ndarray") -> str:
        """One trace's p-p/DC/RMS (+freq) stats line; '' when not computable."""
        y_arr = np.asarray(self.obj_dataext.y[trace_idx], dtype=float)
        n_pts = min(len(y_arr), len(x_arr))
        if n_pts < 2:
            return ''
        y = y_arr[:n_pts]
        x = x_arr[:n_pts]
        unit = 'V' if trace_idx < self.obj_dataext.volts_length else 'A'
        ymin = float(np.min(y))
        ymax = float(np.max(y))
        pp = ymax - ymin
        # Trapezoid integration is correct for adaptive-timestep ngspice
        # output where sample spacing is non-uniform (up to 200x ratio).
        # Simple mean/mean² gives wrong DC and RMS on such data.
        T = float(x[-1] - x[0])
        # Degenerate axis (all-equal x) → integration window is zero; skip
        # the DC/RMS row instead of dividing by zero into inf/nan. Matches
        # the guard in _render_func_pane_stats.
        if T <= 0:
            return ''
        dc = float(_trapz(y, x) / T)
        rms_total_sq = float(_trapz(y * y, x) / T)
        # AC RMS = sqrt(RMS² - DC²) — signal amplitude without DC offset.
        rms_ac = float(np.sqrt(max(0.0, rms_total_sq - dc * dc)))
        # Drop min/max (already visible from Y-axis ticks) and name
        # (already the left title). Keep only the high-value stats.
        parts = [f"p-p={_format_measurement(pp, unit)}",
                 f"DC={_format_measurement(dc, unit)}",
                 f"RMS={_format_measurement(rms_ac, unit)}"]
        if self._current_analysis_type == 'transient' and pp > 1e-12:
            mid = (ymin + ymax) / 2.0
            logic = np.where(y > mid, 1.0, 0.0)
            freq = _detect_frequency(x, logic)
            if freq is not None:
                parts.append(f"f={_format_frequency(freq)}")
        return "  ".join(parts)

    def _render_func_pane_stats(self, ax, fx: "np.ndarray", fy: "np.ndarray") -> None:
        x = np.asarray(fx, dtype=float)
        y = np.asarray(fy, dtype=float)
        n = min(len(x), len(y))
        if n < 2:
            return
        x, y = x[:n], y[:n]
        ymin, ymax = float(np.min(y)), float(np.max(y))
        pp = ymax - ymin
        T = float(x[-1] - x[0])
        if T <= 0:
            return
        dc = float(_trapz(y, x) / T)
        rms_ac = float(np.sqrt(max(0.0, float(_trapz(y * y, x) / T) - dc * dc)))

        def _fmt(v: float) -> str:
            a = abs(v)
            if a >= 1:      return f"{v:.3g}"
            if a >= 1e-3:   return f"{v * 1e3:.3g}m"
            if a >= 1e-6:   return f"{v * 1e6:.3g}µ"
            if a >= 1e-9:   return f"{v * 1e9:.3g}n"
            return f"{v:.3g}"

        parts = [f"p-p={_fmt(pp)}", f"DC={_fmt(dc)}", f"RMS={_fmt(rms_ac)}"]
        if self._current_analysis_type == 'transient' and pp > 1e-12:
            freq = _detect_frequency(x, np.where(y > (ymin + ymax) / 2.0, 1.0, 0.0))
            if freq is not None:
                parts.append(f"f={_format_frequency(freq)}")
        ax.set_title("  ".join(parts), loc='right',
                     fontsize=max(7, LEGEND_FONT_SIZE - 1),
                     color=self._palette['stats_text'], pad=4)

    def _style_stacked_pane_bottom(self, ax, is_last: bool) -> None:
        """Bottom-edge treatment for a stacked pane.

        Inner panes hide their x tick labels and paint the bottom spine gray
        as a row-divider hint; the bottom pane keeps normal labels and the
        theme's spine. Idempotent both ways so the incremental path can
        re-style a kept pane whose stack position changed.
        """
        if is_last:
            ax.tick_params(labelbottom=True)
            ax.spines['bottom'].set_color(matplotlib.rcParams['axes.edgecolor'])
            ax.spines['bottom'].set_linewidth(matplotlib.rcParams['axes.linewidth'])
        else:
            ax.tick_params(labelbottom=False)
            # Visible separator hint: muted bottom spine reads as a row
            # divider in the strip chart. Palette token (spine_separator) so it
            # stays legible on dark theme; _retheme_canvas re-applies it on
            # toggle for the inner (non-last) stacked panes.
            ax.spines['bottom'].set_color(self._palette['spine_separator'])
            ax.spines['bottom'].set_linewidth(1.0)

    def _plot_stacked_trace_pane(self, ax, trace_idx: int,
                                 x_data: "np.ndarray") -> None:
        """Draw one signal into its stacked pane: line, title, unit axis,
        fitted ylim, and (when enabled) the stats overlay. Shared by the full
        rebuild and the incremental add-pane path so both produce identical
        panes."""
        t = self.traces[trace_idx]
        is_transient = self.plot_type[0] == DataExtraction.TRANSIENT_ANALYSIS
        is_ac = self.plot_type[0] == DataExtraction.AC_ANALYSIS
        is_log = is_ac and self.plot_type[1] == 1
        is_dc = self.plot_type[0] == DataExtraction.DC_ANALYSIS

        raw_y = np.asarray(self.obj_dataext.y[t.index], dtype=float)
        n_pts = min(len(raw_y), len(x_data))
        if n_pts == 0:
            ax.set_ylim(-1, 1)
            return
        y = raw_y[:n_pts]
        trace_x = x_data[:n_pts]

        plot_style = '-' if t.style == 'steps-post' else t.style
        if is_log:
            line = self._add_decimated_line(
                ax, trace_x, y, kind='semilogx', color=t.color,
                linewidth=t.thickness, linestyle=plot_style)
        elif t.style == 'steps-post' and (is_transient or is_dc):
            line = self._add_decimated_line(
                ax, trace_x, y, kind='step', color=t.color,
                linewidth=t.thickness)
        else:
            line = self._add_decimated_line(
                ax, trace_x, y, color=t.color,
                linewidth=t.thickness, linestyle=plot_style)
        t.line_object = line

        ax.set_title(t.name, loc='left', color=t.color,
                     fontsize=LEGEND_FONT_SIZE, fontweight='bold', pad=3)

        unit = 'V' if t.index < self.obj_dataext.volts_length else 'A'
        # No standalone 'V'/'A' axis label here: the formatter below writes the
        # unit into every tick ('1 V', '500 mV', '16.3 µA'), so a separate one
        # only restates it — and it has nowhere to sit. Inside the figure there
        # are ~5px between the numbers and the canvas edge (the roomy-looking
        # gutter left of the plot is Qt widget padding, outside the canvas), so
        # the label either overlapped the numbers or bought its gap by pushing
        # the plot area right, since constrained_layout sizes the left margin
        # from the axes' tight bbox. Dropping it removes the overlap and gives
        # the margin back to the plot.
        ax.yaxis.set_major_formatter(FuncFormatter(
            lambda v, _pos, _u=unit: _format_measurement(float(v), _u)))

        ymin = float(np.min(y))
        ymax = float(np.max(y))
        if abs(ymax - ymin) < 1e-12:
            center = (ymin + ymax) / 2.0
            ax.set_ylim(center - 1.0, center + 1.0)
        else:
            margin = 0.1 * (ymax - ymin)
            ax.set_ylim(ymin - margin, ymax + margin)

        if self.stats_check.isChecked():
            self._render_pane_stats(ax, [trace_idx], x_data)

    def _plot_stacked_func_pane(self, ax, f_idx: int) -> None:
        """Draw one function trace into its stacked pane (see trace variant)."""
        label, fx, fy, color, thickness, style = self._func_traces[f_idx]
        plot_style = '-' if style == 'steps-post' else style
        if style == 'steps-post':
            self._add_decimated_line(ax, fx, fy, kind='step',
                                     color=color, linewidth=thickness)
        else:
            self._add_decimated_line(ax, fx, fy, color=color,
                                     linewidth=thickness, linestyle=plot_style)
        ax.set_title(label, loc='left', color=color,
                     fontsize=LEGEND_FONT_SIZE, fontweight='bold', pad=3)
        if len(fy):
            ymin = float(np.min(fy))
            ymax = float(np.max(fy))
            if abs(ymax - ymin) < 1e-12:
                center = (ymin + ymax) / 2.0
                ax.set_ylim(center - 1.0, center + 1.0)
            else:
                margin = 0.1 * (ymax - ymin)
                ax.set_ylim(ymin - margin, ymax + margin)
        if self.stats_check.isChecked():
            self._render_func_pane_stats(ax, fx, fy)

    def plot_stacked_diagram(self) -> None:
        """Stacked-pane view: one pane per visible trace + one per func trace.

        Each entry in self._pane_groups is a single-element list containing
        the trace.index of that pane's signal. Function panes follow at the
        bottom. Heights, lock-Y, stats, and pane-name anchor live on the
        first (and only) trace in the group.

        Function traces (set by plot_function while stacked is active) tail
        at the bottom as one extra pane each.
        """
        # Bring _pane_groups in line with the current visibility set
        self._sync_pane_groups_to_visible()

        if not self._pane_groups and not self._func_traces:
            self._build_panes(1)
            self._stacked_pane_keys = []
            self.axes.text(0.5, 0.5, 'Select a waveform to display',
                           ha='center', va='center',
                           transform=self.axes.transAxes)
            self.axes.set_yticks([])
            self.axes.set_yticklabels([])
            return

        is_transient = self.plot_type[0] == DataExtraction.TRANSIENT_ANALYSIS
        is_ac        = self.plot_type[0] == DataExtraction.AC_ANALYSIS

        x_data = np.asarray(self.obj_dataext.x, dtype=float)
        if is_transient:
            start_idx = self._get_transient_start_idx(x_data)
            if 0 < start_idx < len(x_data):
                x_data = x_data[start_idx:]

        n_groups = len(self._pane_groups)
        # Only visible func traces get their own pane.
        _vis_func = [i for i in range(len(self._func_traces))
                     if i < len(self._func_visible) and self._func_visible[i]]
        n = n_groups + len(_vis_func)
        self._build_panes(n)

        keys: List[tuple] = []
        for pane_idx, group in enumerate(self._pane_groups):
            ax = self.panes[pane_idx]
            if not group or group[0] not in self.traces:
                ax.set_ylim(-1, 1)
                keys.append(('none', pane_idx))
            else:
                self._plot_stacked_trace_pane(ax, group[0], x_data)
                keys.append(('t', group[0]))
            self._style_stacked_pane_bottom(ax, pane_idx == n - 1)

        # Trailing function-trace panes. _vis_func holds the original indices
        # into _func_traces so labels and colours stay correct after partial
        # hide/show.
        for pane_slot, f_idx in enumerate(_vis_func):
            pane_offset = n_groups + pane_slot
            if pane_offset >= len(self.panes):
                break
            ax = self.panes[pane_offset]
            self._plot_stacked_func_pane(ax, f_idx)
            keys.append(('f', f_idx))
            self._style_stacked_pane_bottom(ax, pane_offset == n - 1)
        self._stacked_pane_keys = keys

        # Bottom-pane X label / formatter. Existing helpers already target
        # self.panes[-1], so the multi-pane case is free.
        if is_ac:
            self.set_freq_axis_label()
        elif is_transient:
            self.set_time_axis_label(x_data)
        else:  # DC sweep
            self._reset_x_axis_scaling()
            self.panes[-1].set_xlabel('Voltage Sweep (V)')

    def _try_incremental_stacked(self, new_sig: tuple) -> bool:
        """Restructure the stacked view in place after a visibility toggle.

        Reuses every pane whose signal stays visible — axes, plotted line,
        title, and the user's per-pane zoom survive untouched — deletes the
        panes of hidden signals, and creates+plots panes only for newly shown
        ones. Returns False (caller falls back to the fig.clear() rebuild)
        whenever anything beyond the pane set changed: stats toggle, a kept
        trace's step-style flag, a placeholder state on either side, or no
        reusable pane at all.
        """
        old_sig = self._drawn_signature
        if (old_sig is None or old_sig[0] != 'stacked'
                or not self.panes
                or len(self._stacked_pane_keys) != len(self.panes)):
            return False
        if old_sig[4] != new_sig[4]:  # stats overlay toggled → every pane changes
            return False
        # A kept trace whose steps-post flag flipped needs a different artist
        # type — that pane would have to be re-plotted, so take the full path.
        old_steps = dict(zip(old_sig[1], old_sig[2]))
        new_steps = dict(zip(new_sig[1], new_sig[2]))
        if any(old_steps[i] != new_steps[i]
               for i in old_steps.keys() & new_steps.keys()):
            return False

        self._sync_pane_groups_to_visible()
        if any(not g or g[0] not in self.traces for g in self._pane_groups):
            return False
        vis_func = [i for i in range(len(self._func_traces))
                    if i < len(self._func_visible) and self._func_visible[i]]
        target = ([('t', g[0]) for g in self._pane_groups]
                  + [('f', i) for i in vis_func])
        old_keys = self._stacked_pane_keys
        if not target or target == old_keys:
            return False
        old_map = dict(zip(old_keys, self.panes))
        kept = [k for k in target if k in old_map]
        if not kept:
            return False

        # The bottom pane owns the x label; remember it before panes move.
        xlabel = self.panes[-1].get_xlabel()

        # Snapshot the frozen-layout envelope (outer extents + inter-pane gap)
        # while the old panes still hold their solved positions. Re-slotting
        # the new pane set inside this envelope by height ratio — exactly what
        # the divider drag does live — skips the constrained_layout solve,
        # which even after the align-group fix is the single biggest cost of
        # a toggle (every solve iteration re-lays-out all panes' ticks).
        envelope = None
        if len(self.panes) >= 2:
            pos = [ax.get_position() for ax in self.panes]
            total_gap = sum(max(0.0, pos[i].y0 - pos[i + 1].y1)
                            for i in range(len(pos) - 1))
            envelope = {
                'top': pos[0].y1, 'bottom': pos[-1].y0,
                'x0': pos[0].x0, 'width': pos[0].x1 - pos[0].x0,
                'gap': total_gap / (len(pos) - 1),
            }

        # Geometry is about to change: hover cache and blit snapshot are stale.
        self._blit_background = None
        self._last_hover_axes = None
        self._last_hover_anchor = None

        target_set = set(target)
        for k, ax in zip(old_keys, self.panes):
            if k in target_set:
                continue
            self.fig.delaxes(ax)
            if k[0] == 't' and k[1] in self.traces:
                self.traces[k[1]].line_object = None

        x_data = np.asarray(self.obj_dataext.x, dtype=float)
        if self.plot_type[0] == DataExtraction.TRANSIENT_ANALYSIS:
            start_idx = self._get_transient_start_idx(x_data)
            if 0 < start_idx < len(x_data):
                x_data = x_data[start_idx:]

        n = len(target)
        gridspec_kw = {'hspace': 0.08}
        if self._pane_heights and all(h > 0 for h in self._pane_heights):
            heights = list(self._pane_heights)
            while len(heights) < n:
                heights.append(1.0)
            gridspec_kw['height_ratios'] = heights[:n]
        gs = self.fig.add_gridspec(n, 1, **gridspec_kw)

        anchor_ax = old_map[kept[0]]
        grid_on = self.grid_check.isChecked()
        new_panes = []
        for i, k in enumerate(target):
            ax = old_map.get(k)
            if ax is not None:
                ax.set_subplotspec(gs[i])
                # The post-draw freeze pinned this pane via set_position,
                # which excludes it from layout managers; re-admit it so the
                # constrained solve below can place the new geometry.
                ax.set_in_layout(True)
            else:
                ax = self.fig.add_subplot(gs[i], sharex=anchor_ax)
                if k[0] == 't':
                    self._plot_stacked_trace_pane(ax, k[1], x_data)
                else:
                    self._plot_stacked_func_pane(ax, k[1])
                # Match the kept panes' x formatter (raw SI → display scale).
                if self._x_unit:
                    ax.xaxis.set_major_formatter(FuncFormatter(
                        lambda v, _pos, _s=self._x_scale: f"{v * _s:g}"))
                else:
                    ax.xaxis.set_major_formatter(ScalarFormatter())
                ax.grid(grid_on)
            new_panes.append(ax)

        self.panes = new_panes
        self.axes = new_panes[0]
        self._stacked_pane_keys = target

        for i, ax in enumerate(new_panes):
            self._style_stacked_pane_bottom(ax, i == n - 1)
            ax.set_xlabel('')
        new_panes[-1].set_xlabel(xlabel)

        # Locked panes must keep their pinned ylim even on a brand-new axes;
        # one-shot snapshots are empty on this path so this is lock-only.
        self._restore_view_state()

        # Cursor axvlines: cheapest correct move is recreate on every pane.
        for pane_lines in self.cursor_lines:
            for line in pane_lines:
                if line is None:
                    continue
                try:
                    line.remove()
                except (ValueError, NotImplementedError):
                    pass
        self.cursor_lines = []
        self._restore_cursors()

        self._connect_xlim_watch()
        resize_scale = self._set_canvas_height_for_panes(n)

        # Prune decimation entries whose axes were just deleted.
        fig_axes = self.fig.axes
        self._decim_registry = [ln for ln in self._decim_registry
                                if ln.axes is not None and ln.axes in fig_axes]

        # Position the new pane set. Preferred path: redistribute the frozen
        # envelope by height ratio with the solver kept off — no constrained
        # solve at all. New panes inherit the shared left margin; SI-formatted
        # tick labels are near-constant width, so the fit holds. Fallbacks
        # (one constrained solve, re-frozen by the draw callback like the full
        # rebuild) when the envelope can't be trusted:
        #   * old view was single-pane → no gap to sample;
        #   * the carried-over gap has outgrown the panes it separates. The gap
        #     is sampled once and reused at face value however far the pane
        #     count climbs, so a gap solved at N=2 stays ~62px while the panes
        #     fall to ~34px — every added pane converts plot area into
        #     whitespace. Re-solving resets it (~30px) and self-heals the stack.
        heights_n = list(gridspec_kw.get('height_ratios', [])) or [1.0] * n
        placed = False
        if envelope is not None and resize_scale is not None:
            # The canvas is headed for a different height (one more
            # MIN_STACKED_PANE_HEIGHT_PX band per pane once the stack passes
            # the viewport, and back down again as panes are removed). Margins
            # and the inter-pane gap are pixel-sized decorations — tick labels,
            # the per-pane title — so restate them as fractions of the height
            # they are about to be drawn at, and let the panes absorb the rest.
            # Growing without this leaks the gained band into whitespace;
            # shrinking without it squeezes titles into the pane above and
            # clips the top one against the canvas edge.
            envelope = dict(envelope)
            envelope['gap'] *= resize_scale
            envelope['top'] = 1.0 - (1.0 - envelope['top']) * resize_scale
            envelope['bottom'] *= resize_scale
        if envelope is not None:
            usable = ((envelope['top'] - envelope['bottom'])
                      - envelope['gap'] * (n - 1))
            if (usable > 0.01 * n
                    and envelope['gap'] <= MAX_STACKED_GAP_RATIO * (usable / n)):
                ratio_sum = max(1e-9, sum(heights_n))
                cur = envelope['top']
                for ax, r in zip(new_panes, heights_n):
                    h = max(0.005, usable * (r / ratio_sum))
                    ax.set_position([envelope['x0'], cur - h,
                                     envelope['width'], h])
                    cur -= h + envelope['gap']
                self.fig.set_layout_engine('none')
                self._pending_freeze = False
                placed = True
        if not placed:
            self.fig.set_layout_engine('constrained')
            self._pending_freeze = n > 1
        self.canvas.draw_idle()
        return True


    def _reset_x_axis_scaling(self) -> None:
        """Drop any SI-unit formatter on the X axis (identity tick labels).

        Used when the X axis no longer represents time/frequency — e.g. the
        Lissajous case in plot_function where X becomes a voltage trace.
        """
        self._x_scale = 1.0
        self._x_unit = ''
        for ax in self.panes:
            ax.xaxis.set_major_formatter(ScalarFormatter())

    def _apply_x_axis_scaling(self, scale: float, unit: str,
                              label_prefix: str) -> None:
        """Display-only X-axis scaling via FuncFormatter.

        Line data and xlim stay in raw SI units; tick labels show raw * scale.
        This keeps event.xdata, cursor positions, and stored data coherent and
        eliminates the previous mutate-on-every-refresh xdata bug. The label
        is only attached to the bottom-most pane so stacked panes share one
        unified X axis caption.
        """
        self._x_scale = scale
        self._x_unit = unit
        fmt = FuncFormatter(lambda v, _pos, _s=scale: f"{v * _s:g}")
        for ax in self.panes:
            ax.xaxis.set_major_formatter(fmt)
            ax.set_xlabel('')
        if self.panes:
            self.panes[-1].set_xlabel(f'{label_prefix} ({unit})')

    def set_time_axis_label(self, time_data: Optional["np.ndarray"] = None) -> None:
        if not self.panes or not hasattr(self.obj_dataext, 'x'):
            return
        if time_data is None:
            time_data = np.asarray(self.obj_dataext.x, dtype=float)
        if len(time_data) < 2:
            self._x_scale, self._x_unit = 1.0, 's'
            self.panes[-1].set_xlabel('Time (s)')
            return
        scale, unit = self._get_time_scale_and_unit(time_data)
        self._apply_x_axis_scaling(scale, unit, 'Time')
        self.axes.set_xlim(float(time_data[0]), float(time_data[-1]))

    def _sync_threshold_range(self, gmin: float, gmax: float) -> None:
        """Fit the threshold spin box to the visible signal span.

        ``minimum()`` is reserved as the "Auto" sentinel, one step below the
        lowest real voltage; the usable band is ``[gmin-margin, gmax+margin]``
        with a step of ~1% of the span. Auto / manual state is preserved across
        re-fits, and signals are blocked so re-ranging never re-triggers a
        render.
        """
        sb = self.threshold_spinbox
        span = gmax - gmin
        if not np.isfinite(span) or span < 1e-9:
            gmin, gmax = gmin - 0.5, gmax + 0.5
            span = gmax - gmin
        margin = span * 0.05
        step = round(max(span / 100.0, 1e-3), 3) or 1e-3
        lo = round(gmin - margin, 3)
        hi = round(gmax + margin, 3)
        was_auto = (sb.value() == sb.minimum())
        old_val = sb.value()
        sb.blockSignals(True)
        sb.setSingleStep(step)
        sb.setRange(round(lo - step, 3), hi)
        sb.set_auto_value((gmin + gmax) / 2.0)
        if was_auto:
            sb.setValue(sb.minimum())
        else:
            sb.setValue(min(max(old_val, sb.minimum() + step), hi))
        sb.blockSignals(False)

    def on_threshold_changed(self, value: float) -> None:
        if self.radio_timing.isChecked():
            self._controls_timer.start()

    def on_spacing_changed(self, value: int) -> None:
        self.vertical_spacing = value / 100.0
        self.spacing_label.setText(f"{self.vertical_spacing:.1f}x")
        if self.radio_timing.isChecked():
            self._controls_timer.start()

    def _get_time_scale_and_unit(self, time_data: Optional["np.ndarray"] = None) -> Tuple[float, str]:
        """Single source of truth for time-axis unit selection.

        All callers (set_time_axis_label, _current_time_scale, set_cursor)
        derive their scale factor from here — ensures they can never diverge.
        time_data defaults to obj_dataext.x; pass a trimmed slice when a
        subset of the axis is being displayed (e.g. transient start offset).
        """
        if time_data is None:
            time_data = np.asarray(self.obj_dataext.x, dtype=float)
        time_span = abs(time_data[-1] - time_data[0]) if len(time_data) > 1 else 0.0
        if time_span == 0:                         return 1.0,  's'
        if time_span < TIME_UNIT_THRESHOLD_PS:     return 1e12, 'ps'
        if time_span < TIME_UNIT_THRESHOLD_NS:     return 1e9,  'ns'
        if time_span < TIME_UNIT_THRESHOLD_US:     return 1e6,  'µs'
        if time_span < TIME_UNIT_THRESHOLD_MS:     return 1e3,  'ms'
        return 1.0, 's'

    def _current_time_scale(self) -> float:
        return self._get_time_scale_and_unit()[0]

    def _current_axis_scale(self) -> float:
        if self._current_analysis_type in ('ac_log', 'ac_linear'):
            return self._get_freq_scale_and_unit()[0]
        return self._get_time_scale_and_unit()[0]

    def _update_measure_label(self, delta_original: float, scale: float) -> None:
        if self._current_analysis_type in ('ac_log', 'ac_linear'):
            _, unit = self._get_freq_scale_and_unit()
            self.measure_label.setText(f"ΔF: {delta_original * scale:.6g} {unit}")
        else:
            if delta_original > 0:
                self.measure_label.setText(f"Freq: {1.0 / delta_original:.6g} Hz")

    def _draw_normal_trace_line(self, t: "Trace",
                                x_data: "Optional[np.ndarray]" = None) -> "Line2D":
        """Plot one trace on the shared normal-view axes and store its line.

        Shared by the full rebuild (_plot_analysis_data) and the incremental
        refresh (_incremental_refresh_normal) so the artist type — step vs
        semilogx vs plot — is chosen identically on both paths. Branches on
        self._current_analysis_type, which the full rebuild sets first.
        """
        if x_data is None:
            x_data = np.asarray(self.obj_dataext.x, dtype=float)
        y_data = np.asarray(self.obj_dataext.y[t.index], dtype=float)
        n_pts = min(len(x_data), len(y_data))
        x_plot, y_plot = x_data[:n_pts], y_data[:n_pts]
        analysis_type = self._current_analysis_type
        plot_style = '-' if t.style == 'steps-post' else t.style
        if t.style == 'steps-post' and analysis_type in ['transient', 'dc']:
            kind = 'step'
        elif analysis_type == 'ac_log':
            kind = 'semilogx'
        else:
            kind = 'plot'
        line = self._add_decimated_line(
            self.axes, x_plot, y_plot, kind=kind, color=t.color, label=t.name,
            linewidth=t.thickness, linestyle=plot_style)
        t.line_object = line
        return line

    def _plot_analysis_data(self, analysis_type: str) -> None:
        self._current_analysis_type = analysis_type
        self._build_panes(1)
        traces_plotted = 0
        first_visible = None
        x_data = np.asarray(self.obj_dataext.x, dtype=float)
        for idx, t in self.traces.items():
            if not t.visible:
                continue
            traces_plotted += 1
            if first_visible is None:
                first_visible = idx
            self._draw_normal_trace_line(t, x_data)

        if analysis_type in ['ac_linear', 'ac_log']:
            self.set_freq_axis_label()
        elif analysis_type == 'dc':
            self.axes.set_xlabel('Voltage Sweep (V)')

        if first_visible is not None:
            self.axes.set_ylabel('Voltage (V)' if first_visible < self.volts_length else 'Current (A)')

        if analysis_type == 'transient':
            self.set_time_axis_label()

        # Overlay visible function traces on the shared axes.
        # Stacked mode renders these as separate panes in plot_stacked_diagram,
        # so this block is normal-mode-only (single axes).
        for _f_idx, (_label, _fx, _fy, _color, _thickness, _style) in enumerate(self._func_traces):
            if not (_f_idx < len(self._func_visible) and self._func_visible[_f_idx]):
                continue
            _n = min(len(_fx), len(_fy))
            if _n > 0:
                traces_plotted += 1
                _plot_style = '-' if _style == 'steps-post' else _style
                if _style == 'steps-post':
                    self._add_decimated_line(
                        self.axes, _fx[:_n], _fy[:_n], kind='step',
                        color=_color, label=_label, linewidth=_thickness)
                else:
                    self._add_decimated_line(
                        self.axes, _fx[:_n], _fy[:_n], color=_color,
                        label=_label, linewidth=_thickness, linestyle=_plot_style)

        # After the func overlay: a visible function trace alone is enough to
        # make the axes non-empty, so the placeholder must not appear then.
        if traces_plotted == 0:
            self._empty_placeholder = self.axes.text(
                0.5, 0.5, 'Please select a waveform to plot',
                ha='center', va='center', transform=self.axes.transAxes)


    def on_push_decade(self) -> None:
        self._plot_analysis_data('ac_log')

    def on_push_ac(self) -> None:
        self._plot_analysis_data('ac_linear')

    def on_push_trans(self) -> None:
        self._plot_analysis_data('transient')

    def on_push_dc(self) -> None:
        self._plot_analysis_data('dc')

