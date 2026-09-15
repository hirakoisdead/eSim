"""Canonical filesystem locations used throughout eSim.

All install resources are anchored to this file, never the process working
directory.  Per-user state lives under ``~/.esim`` on every platform.
"""

import os


def repo_root():
    """Return the eSim checkout/install root."""
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def src_root():
    return os.path.join(repo_root(), "src")


def image_path(*parts):
    return os.path.join(repo_root(), "images", *parts)


def library_path(*parts):
    return os.path.join(repo_root(), "library", *parts)


def user_home():
    """Return the current user's home, expanded at call time for testability."""
    return os.path.expanduser("~")


def esim_config_dir():
    return os.path.join(user_home(), ".esim")


def esim_config_path(*parts):
    return os.path.join(esim_config_dir(), *parts)


def nghdl_config_path():
    return os.path.join(user_home(), ".nghdl", "config.ini")


def atomic_write_text(path, text, encoding="utf-8"):
    """Atomically replace ``path`` with ``text`` and return ``path``.

    Uses a fixed sibling temp name with ONE create attempt, never
    tempfile.mkstemp: in a directory this process cannot write (admin-owned,
    revoked ACL) mkstemp on Windows spins through all 10000 candidate names
    because ``os.access(dir, W_OK)`` misreports ACL-denied directories as
    writable -- on the GUI thread that is a minutes-long freeze. A plain
    open() raises PermissionError immediately so callers can degrade. These
    are per-user config files, so a stale temp from an earlier attempt by
    the same app is safe to overwrite.
    """
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return path


def write_json_atomic(path, data, indent=2):
    """Atomically write ``data`` as JSON to ``path`` (tmp file + os.replace).

    Bare ``open(w) + json.dump`` leaves a truncated/corrupt file if the process
    dies mid-write; every config writer should go through this instead.
    """
    import json
    return atomic_write_text(path, json.dumps(data, indent=indent))


def read_workspace(default_path=None, default_check="0"):
    """Return ``(check, path)`` from workspace.txt with safe defaults."""
    fallback = default_path or os.path.join(user_home(), "eSim-Workspace")
    try:
        with open(esim_config_path("workspace.txt"), encoding="utf-8") as fh:
            check, path = fh.readline().strip().split(" ", 1)
        if not path:
            raise ValueError("workspace path is empty")
        # The check token feeds a two-state QCheckBox via Qt.CheckState(int(..))
        # in Workspace -- only "0" (Unchecked) and "2" (Checked) are ever
        # written. A hand-edited/corrupt token ("5", "x") otherwise reaches
        # that constructor and aborts startup with a raw ValueError before any
    # window appears. Clamp anything unexpected to the default here,
        # the single source every consumer reads.
        if check not in ("0", "2"):
            check = str(default_check)
        return check, path
    except (OSError, ValueError):
        return str(default_check), fallback


def write_workspace(check, path):
    """Persist workspace selection without exposing a truncated file."""
    return atomic_write_text(
        esim_config_path("workspace.txt"), f"{int(check)} {path}")


def workspace_is_usable(home):
    """True when ``home`` exists (or can be created) and THIS process can
    create files in it.

    A real create-and-delete probe, not ``os.access``: on Windows access()
    ignores ACLs, so a directory owned by another account (or left behind by
    an elevated test run) reads as writable and then every actual write
    fails. A stale workspace pointer must send the user back to the picker,
    not freeze startup.
    """
    if not home:
        return False
    try:
        os.makedirs(home, exist_ok=True)
        probe = os.path.join(home, ".esim-write-probe")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False
