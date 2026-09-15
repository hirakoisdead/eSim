"""Process-tree termination, shared by every subprocess runner in maker.

``Popen.kill()`` ends the DIRECT child only. That is not what a build needs:
``mingw32-make`` spawns gcc/ld (and ``iverilog`` spawns ivlpp/ivl), so killing
the parent on a timeout or a Cancel click leaves those grandchildren running,
holding open handles on the ``.o``/``.exe`` files in the model directory. On
Windows the user's retry then dies with "Permission denied" removing or
rewriting an object file -- which reads as a brand-new, unrelated bug rather
than fallout from the step that was cancelled a minute earlier.

psutil is a hard dependency of eSim on both platforms (``requirements-windows``
and the apt list in ``install-eSim.sh``), but the import is guarded anyway: a
partially provisioned environment must degrade to the old single-process kill,
never crash the very code path whose job is to stop a runaway build.
"""
try:
    import psutil
except Exception:            # pragma: no cover - psutil is a hard dependency
    psutil = None


def kill_process_tree(proc):
    """Kill ``proc`` and every descendant it spawned.

    Returns True when the descendants were enumerated with psutil, False when
    it fell back to killing just ``proc`` (no psutil, or the process was
    already gone). Never raises: callers use this from watchdog timers and
    GUI slots where an exception would be swallowed or would kill the thread.
    """
    if proc is None:
        return False

    walked = False
    pid = getattr(proc, "pid", None)
    if psutil is not None and pid:
        try:
            # Snapshot the children BEFORE killing the parent: once make is
            # gone its children are re-parented and can no longer be found
            # through it.
            children = psutil.Process(pid).children(recursive=True)
            walked = True
            for child in children:
                try:
                    child.kill()
                except Exception:
                    pass
        except Exception:
            # NoSuchProcess/AccessDenied/ZombieProcess -- fall through to the
            # plain kill below, which is what the code did before.
            pass

    try:
        proc.kill()
    except Exception:
        pass
    return walked
