# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
mesa_core/learn — SPEC_67 `mesa learn` tutorial

The guided, resumable tutorial that teaches MESA's vocabulary by letting users
watch things break, then watch MESA catch them.
"""
from .harness import run_learn, LessonContext, Lesson

__all__ = ["run_learn", "LessonContext", "Lesson"]
