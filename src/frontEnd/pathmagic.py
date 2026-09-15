import os
import sys

# Application.py can be executed directly from any working directory.  Anchor
# its legacy top-level imports to src/ instead of guessing from os.getcwd().
src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
