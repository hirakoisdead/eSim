# ==============================================================================
#  modelCache.py -- a cross-project "remember the file I picked for this model"
#  hint for the KiCad-to-ngspice converter.
#
#  A small per-user store mapping a model / subcircuit name to the file or
#  directory last chosen for it, used ONLY to pre-fill an otherwise-blank group
#  default in the converter (like browser autofill). It is a hint, never
#  authority:
#
#    * stored under ~/.esim (never inside a project), so sharing/zipping a
#      project never carries it -- a recipient cold-starts with their own cache;
#    * lookup() returns a remembered path only if it still EXISTS on this
#      machine, so a path remembered on another machine, or since deleted, is
#      silently dropped and the field stays blank rather than wrong;
#    * the converter applies it only to a blank field the user can see and edit,
#      and a project's own Previous_Values always takes precedence.
#
#  Keyed by model name alone (lowercased), so it spans projects on purpose:
#  that cross-project reuse is the whole point, and the exists-check is what
#  keeps it safe. Last write wins.
# ==============================================================================
import json
import os
import tempfile


def _cache_path():
    base = os.path.join(os.path.expanduser('~'), '.esim')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'model_cache.json')


def load():
    """Return the cache as a {model_name: path} dict; {} if missing/corrupt."""
    try:
        with open(_cache_path(), 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (IOError, OSError, ValueError):
        pass
    return {}


def _save(data):
    """Atomically write the cache (temp file + os.replace)."""
    path = _cache_path()
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.json.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def lookup(model_name):
    """Return the remembered path for `model_name` IF it still exists on this
    machine, else None. The exists-check is the safety net: a stale or foreign
    path is treated as "not remembered" so the converter leaves the field blank
    instead of suggesting something wrong."""
    if not model_name:
        return None
    path = load().get(str(model_name).lower())
    if path and os.path.exists(path):
        return path
    return None


def remember(model_name, path):
    """Remember `path` for `model_name`. No-op for empty inputs."""
    if model_name and path:
        remember_many({model_name: path})


def remember_many(mapping):
    """Merge {model_name: path} into the cache and save once. Empty paths are
    ignored; existing entries are overwritten (last write wins)."""
    additions = {str(k).lower(): str(v)
                 for k, v in (mapping or {}).items() if k and v}
    if not additions:
        return
    data = load()
    if all(data.get(k) == v for k, v in additions.items()):
        return                      # nothing actually changed
    data.update(additions)
    _save(data)
