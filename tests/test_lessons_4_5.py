"""
tests/test_lessons_4_5.py — SPEC_67 Slices 4-5

Test Lesson 4 (semantic compilation) and Lesson 5 (entity isolation + recap).
Lesson 4 verifies dialect-specific differences; Lesson 5 verifies vocabulary recap.
"""
import io
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mesa_core.learn import LessonContext
from mesa_core.learn.lessons import lesson4_compile_portability, lesson5_entity_isolation_recap


def test_lesson4_bigquery_vs_snowflake_differ():
    """Lesson 4: BigQuery and Snowflake produce different Wide Layer SQL."""
    fixture_dir = Path(__file__).parent.parent / "mesa_core" / "learn" / "fixture"
    models_dir = str(fixture_dir / "models")
    
    # Compile for BigQuery
    cmd_bq = [sys.executable, "-m", "mesa_core.cli", "compile", "Customer",
              "--models-dir", models_dir, "--warehouse", "bigquery"]
    result_bq = subprocess.run(cmd_bq, capture_output=True, text=True)
    
    # Compile for Snowflake
    cmd_sf = [sys.executable, "-m", "mesa_core.cli", "compile", "Customer",
              "--models-dir", models_dir, "--warehouse", "snowflake"]
    result_sf = subprocess.run(cmd_sf, capture_output=True, text=True)
    
    # Both should succeed
    assert result_bq.returncode == 0, f"BigQuery failed: {result_bq.stderr}"
    assert result_sf.returncode == 0, f"Snowflake failed: {result_sf.stderr}"
    
    # BigQuery uses simple column names
    assert "  Customer\n" in result_bq.stdout, "BigQuery should use simple column name"
    
    # Snowflake uses as_struct macro
    assert "as_struct" in result_sf.stdout, "Snowflake should use as_struct macro"
    
    # Outputs must differ
    assert result_bq.stdout != result_sf.stdout


def test_lesson4_vocabulary_present():
    """Lesson 4: vocabulary 'semantic compilation', 'portability', 'warehouse as commodity' appear."""
    fixture_dir = Path(__file__).parent.parent / "mesa_core" / "learn" / "fixture"
    ctx = LessonContext(fixture_dir, Path("/tmp/mesa_test_l4"))
    ctx.pause = lambda msg="": None
    
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        lesson4_compile_portability.run(ctx)
    
    output = captured.getvalue()
    
    assert "semantic compilation" in output.lower() or "compile to the warehouse" in output.lower()
    assert "portability" in output.lower() or "write once" in output.lower()
    assert "commodity" in output.lower()


def test_lesson5_reference_carrier_pattern():
    """Lesson 5: demonstrates Reference Carrier (STRUCT link) vs raw cross-entity join."""
    fixture_dir = Path(__file__).parent.parent / "mesa_core" / "learn" / "fixture"
    ctx = LessonContext(fixture_dir, Path("/tmp/mesa_test_l5"))
    ctx.pause = lambda msg="": None
    
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        lesson5_entity_isolation_recap.run(ctx)
    
    output = captured.getvalue()
    
    # Should show the WRONG way (cross-entity reach-across)
    assert "LEFT JOIN customer" in output.lower() or "messy" in output.lower()
    
    # Should show the RIGHT way (Reference Carrier STRUCT)
    assert "Reference Carrier" in output or "STRUCT" in output
    assert "holds an address" in output.lower() or "doesn't make the trip" in output.lower()


def test_lesson5_preach_moment_recap():
    """Lesson 5: includes the vocabulary recap from all 5 lessons (the 'preach moment')."""
    fixture_dir = Path(__file__).parent.parent / "mesa_core" / "learn" / "fixture"
    ctx = LessonContext(fixture_dir, Path("/tmp/mesa_test_l5_recap"))
    ctx.pause = lambda msg="": None
    
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        lesson5_entity_isolation_recap.run(ctx)
    
    output = captured.getvalue()
    
    # The recap must mention all 5 core concepts
    assert "IS vs MEANS" in output or ("IS" in output and "MEANS" in output and "identity" in output.lower())
    assert "fat-finger join" in output.lower() or "collision" in output.lower()
    assert "Reference Carrier" in output or "entity isolation" in output.lower()
    assert "metric encapsulation" in output.lower() or "one file, one owner" in output.lower()
    assert "compile once" in output.lower() or "ship everywhere" in output.lower() or "semantic compilation" in output.lower()


def test_lesson5_vocabulary_present():
    """Lesson 5: vocabulary includes all lesson terms plus the send-off."""
    fixture_dir = Path(__file__).parent.parent / "mesa_core" / "learn" / "fixture"
    ctx = LessonContext(fixture_dir, Path("/tmp/mesa_test_l5_vocab"))
    ctx.pause = lambda msg="": None
    
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        lesson5_entity_isolation_recap.run(ctx)
    
    output = captured.getvalue()
    
    # Specific to Lesson 5
    assert "entity isolation" in output.lower() or "Reference Carrier" in output
    
    # The send-off / preach moment
    assert "preach" in output.lower() or "vocabulary" in output.lower()
    assert "mesa init" in output.lower() or "next steps" in output.lower()
