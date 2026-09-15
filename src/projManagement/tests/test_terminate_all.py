"""terminate_all bounds exit to a shared wait budget.

Calling terminate_handle in a loop serialised its per-child terminate->wait(2s)
->kill->wait(1s) escalation, so N open external windows froze the GUI thread for
up to N*3s. terminate_all asks all children to stop first, waits within ONE
total_deadline shared across the batch, then kills stragglers.

These use fake Popen-like handles (poll/terminate/wait/kill) -- no real
processes -- to pin the graceful path, the kill path, and the wall-time bound.
"""
import time

from projManagement.Worker import terminate_all


class _WellBehaved:
    """Exits promptly on terminate()."""

    def __init__(self):
        self._alive = True
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self._alive = False


class _Stubborn:
    """Ignores terminate(); wait() blocks for its timeout then times out."""

    def __init__(self):
        self._alive = True
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True          # but stays alive

    def wait(self, timeout=None):
        if timeout:
            time.sleep(timeout)
        raise TimeoutError

    def kill(self):
        self.killed = True
        self._alive = False


def test_well_behaved_child_is_not_killed():
    proc = _WellBehaved()
    terminate_all([proc], total_deadline=1.0)
    assert proc.terminated is True
    assert proc.killed is False


def test_stubborn_child_is_killed():
    proc = _Stubborn()
    terminate_all([proc], total_deadline=0.1)
    assert proc.terminated is True
    assert proc.killed is True


def test_wait_budget_is_shared_across_children_not_per_child():
    procs = [_Stubborn() for _ in range(4)]
    start = time.monotonic()
    terminate_all(procs, total_deadline=0.2)
    elapsed = time.monotonic() - start
    # Shared budget: total wait ~= 0.2s once, NOT 4 * 0.2s. Generous ceiling to
    # stay robust on a busy CI box while still failing the per-child regression.
    assert elapsed < 0.6, elapsed
    assert all(p.killed for p in procs)


def test_none_and_empty_are_safe():
    terminate_all([])
    terminate_all([None, None])
