# ==============================================================================
#  test_model_cache.py -- unit tests for the cross-project model_cache hint.
#
#  HOME is redirected to a temp dir so the real ~/.esim is never touched.
# ==============================================================================
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))       # .../src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# Redirect HOME before importing the module under test.
_TMP_HOME = tempfile.mkdtemp(prefix="esim_home_")
os.environ["HOME"] = _TMP_HOME

from projManagement import modelCache               # noqa: E402


def _cache_file():
    # Resolve at call time: the repo-wide isolated_user_home fixture points
    # HOME at a fresh tmp dir per test, so the module-level _TMP_HOME is only
    # correct under the standalone runner below.
    return os.path.join(os.path.expanduser("~"), ".esim", "model_cache.json")


def _reset():
    p = _cache_file()
    if os.path.exists(p):
        os.remove(p)


def _real_file():
    return tempfile.NamedTemporaryFile(suffix=".lib", delete=False).name


# -- basics --------------------------------------------------------------------

def test_missing_cache_is_empty():
    _reset()
    assert modelCache.load() == {}
    assert modelCache.lookup("eSim_NPN") is None


def test_remember_then_lookup_existing():
    _reset()
    f = _real_file()
    try:
        modelCache.remember("eSim_NPN", f)
        assert modelCache.lookup("eSim_NPN") == f
    finally:
        os.remove(f)


def test_lookup_is_case_insensitive():
    _reset()
    f = _real_file()
    try:
        modelCache.remember("eSim_NPN", f)
        assert modelCache.lookup("esim_npn") == f
        assert modelCache.lookup("ESIM_NPN") == f
    finally:
        os.remove(f)


def test_lookup_drops_missing_path():
    # The safety net: a remembered path that no longer exists is not suggested.
    _reset()
    f = _real_file()
    modelCache.remember("eSim_NPN", f)
    os.remove(f)
    assert modelCache.lookup("eSim_NPN") is None


def test_last_write_wins():
    _reset()
    f1, f2 = _real_file(), _real_file()
    try:
        modelCache.remember("m", f1)
        modelCache.remember("m", f2)
        assert modelCache.lookup("m") == f2
    finally:
        os.remove(f1)
        os.remove(f2)


def test_remember_many_and_empty_ignored():
    _reset()
    f = _real_file()
    try:
        modelCache.remember_many({"a": f, "b": "", "": f})
        assert modelCache.lookup("a") == f
        assert modelCache.lookup("b") is None
        assert "" not in modelCache.load()
    finally:
        os.remove(f)


def test_corrupt_cache_tolerated():
    _reset()
    p = os.path.join(_TMP_HOME, ".esim", "model_cache.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write("{ this is not json")
    assert modelCache.load() == {}            # no raise
    f = _real_file()
    try:
        modelCache.remember("x", f)           # still writable over corruption
        assert modelCache.lookup("x") == f
    finally:
        os.remove(f)


def test_no_op_write_when_unchanged():
    _reset()
    f = _real_file()
    try:
        modelCache.remember("a", f)
        p = _cache_file()
        mtime = os.path.getmtime(p)
        modelCache.remember("a", f)            # identical -> should not rewrite
        assert os.path.getmtime(p) == mtime
    finally:
        os.remove(f)


# -- standalone runner ---------------------------------------------------------
def _main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS  " + fn.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL  " + fn.__name__ + "  " + str(e))
        except Exception as e:                       # noqa: BLE001
            failed += 1
            import traceback
            print("ERROR " + fn.__name__ + "  " + repr(e))
            traceback.print_exc()
    print("\n==== %d / %d PASS ====" % (len(fns) - failed, len(fns)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
