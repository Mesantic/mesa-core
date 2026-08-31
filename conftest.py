"""Pytest conftest — make the local ``mesa_core`` package importable.

SPEC_66: during Slices 1-4 the package is tested in-place using the governance
repo's ``.venv`` interpreter (which has sqlglot + pytest). This shim adds the
repo root to ``sys.path`` so ``import mesa_core`` resolves without a formal
``pip install`` (that happens in Slice 5's standalone packaging).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
