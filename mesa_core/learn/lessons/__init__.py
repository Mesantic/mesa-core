# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
mesa_core/learn/lessons/__init__.py — lesson module registry

Each lesson is imported and registered here in order (1-5).
"""
from . import lesson1_fat_finger_join
from . import lesson2_silent_schema_change
from . import lesson3_one_metric_one_owner
from . import lesson4_compile_portability
from . import lesson5_entity_isolation_recap

ALL_LESSONS = [
    lesson1_fat_finger_join,
    lesson2_silent_schema_change,
    lesson3_one_metric_one_owner,
    lesson4_compile_portability,
    lesson5_entity_isolation_recap,
]

__all__ = ["ALL_LESSONS"]
