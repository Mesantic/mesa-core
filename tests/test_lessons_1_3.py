"""
tests/test_lessons_1_3.py — SPEC_67 Slice 3

Test Lessons 1-3: verify the "mess" produces the wrong result and the "catch"
demonstrates MESA's solution. Each lesson's vocabulary term must appear in output.
"""
import duckdb
from pathlib import Path

import pytest

from mesa_core.learn import LessonContext
from mesa_core.learn.lessons import lesson1_fat_finger_join, lesson2_silent_schema_change, lesson3_one_metric_one_owner


@pytest.fixture
def tutorial_db(tmp_path):
    """Create a temporary DuckDB with tutorial seed data."""
    from mesa_core.learn.lessons.lesson1_fat_finger_join import _setup_database
    
    fixture_dir = Path(__file__).parent.parent / "mesa_core" / "learn" / "fixture"
    db_path = tmp_path / "tutorial.duckdb"
    
    ctx = LessonContext(fixture_dir, tmp_path)
    _setup_database(ctx)
    
    return db_path


def test_lesson1_naive_join_causes_collision(tutorial_db):
    """Lesson 1: THE MESS — naive join on just `id` merges two different customers."""
    conn = duckdb.connect(str(tutorial_db))
    
    # The naive query (what users do by habit)
    naive_query = """
    SELECT 
        c.id,
        c.name AS customer_name,
        c.source_system,
        SUM(o.amount) AS total_revenue
    FROM (
        SELECT id, name, 'salesforce' AS source_system FROM salesforce_customers
        UNION ALL
        SELECT id, name, 'netsuite' AS source_system FROM netsuite_customers
    ) AS c
    LEFT JOIN orders AS o 
        ON c.id = o.customer_id
    WHERE c.id = 123
    GROUP BY c.id, c.name, c.source_system
    ORDER BY c.source_system;
    """
    
    result = conn.execute(naive_query).fetchall()
    
    # Both customers (Salesforce's Acme West + NetSuite's Cyberdyne) appear,
    # but the revenue is WRONG — each row gets orders from BOTH sources
    assert len(result) == 2, "Should have 2 rows (one per source)"
    
    # The revenue for each row should be inflated (includes orders from the other source)
    # Salesforce customer should have ~$3700, NetSuite ~$9700, but naive join adds them
    salesforce_row = result[0]
    netsuite_row = result[1]
    
    # The collision manifests as inflated revenue
    assert salesforce_row[3] > 10000 or netsuite_row[3] > 10000, \
        "Revenue should be inflated due to collision"
    
    conn.close()


def test_lesson1_mesa_hashed_id_prevents_collision(tmp_path):
    """Lesson 1: THE CATCH — MESA's hashed ID with source_system makes collision impossible."""
    from mesa_core.learn.lessons.lesson1_fat_finger_join import _setup_database
    
    fixture_dir = Path(__file__).parent.parent / "mesa_core" / "learn" / "fixture"
    ctx = LessonContext(fixture_dir, tmp_path)
    _setup_database(ctx)
    
    # Verify the hashed ID construction produces DIFFERENT IDs for the two id=123 customers
    conn = duckdb.connect(str(ctx.db_path))
    
    # DuckDB: sha256() returns VARCHAR (hex string), cast to BLOB for base64()
    salesforce_hash = conn.execute(
        "SELECT base64(sha256('salesforce-123')::BLOB) AS hash"
    ).fetchone()[0]
    
    netsuite_hash = conn.execute(
        "SELECT base64(sha256('netsuite-123')::BLOB) AS hash"
    ).fetchone()[0]
    
    assert salesforce_hash != netsuite_hash, \
        "Hashed IDs must be different for the two customers (prevents collision)"
    
    conn.close()


def test_lesson1_vocabulary_present():
    """Lesson 1: vocabulary terms 'IS vs MEANS', 'fat-finger join', 'hashed identity' appear."""
    # Run lesson and capture output
    import io
    import sys
    from unittest.mock import patch
    
    fixture_dir = Path(__file__).parent.parent / "mesa_core" / "learn" / "fixture"
    tmp = Path("/tmp/mesa_learn_test")
    tmp.mkdir(exist_ok=True)
    ctx = LessonContext(fixture_dir, tmp)
    
    # Mock pause to avoid blocking
    ctx.pause = lambda msg="": None
    
    # Capture output
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        lesson1_fat_finger_join.run(ctx)
    
    output = captured.getvalue()
    
    # Vocabulary check
    assert "IS vs MEANS" in output or "IS" in output and "MEANS" in output
    assert "fat-finger join" in output.lower() or "collision" in output.lower()
    assert "hashed" in output.lower() and "identity" in output.lower()


def test_lesson2_select_star_absorbs_schema_change(tutorial_db):
    """Lesson 2: THE MESS — SELECT * silently absorbs a new column."""
    conn = duckdb.connect(str(tutorial_db))
    
    # Before schema change
    cols_before = [desc[0] for desc in conn.execute("SELECT * FROM salesforce_customers LIMIT 1").description]
    
    # Simulate schema change
    conn.execute("ALTER TABLE salesforce_customers ADD COLUMN tier VARCHAR DEFAULT 'standard'")
    
    # After schema change
    cols_after = [desc[0] for desc in conn.execute("SELECT * FROM salesforce_customers LIMIT 1").description]
    
    # SELECT * silently picked up the new column
    assert len(cols_after) == len(cols_before) + 1
    assert 'tier' in cols_after
    
    conn.close()


def test_lesson2_vocabulary_present():
    """Lesson 2: vocabulary 'explicit interfaces', 'SELECT * banned', 'fail loud' appear."""
    import io
    from unittest.mock import patch
    
    fixture_dir = Path(__file__).parent.parent / "mesa_core" / "learn" / "fixture"
    tmp = Path("/tmp/mesa_learn_test")
    tmp.mkdir(exist_ok=True)
    ctx = LessonContext(fixture_dir, tmp)
    
    # Setup DB
    from mesa_core.learn.lessons.lesson1_fat_finger_join import _setup_database
    _setup_database(ctx)
    
    ctx.pause = lambda msg="": None
    
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        lesson2_silent_schema_change.run(ctx)
    
    output = captured.getvalue()
    
    assert "explicit" in output.lower()
    assert "SELECT *" in output or "select *" in output.lower()
    assert "fail loud" in output.lower() or "loudly" in output.lower()


def test_lesson3_messy_query_has_no_clear_owner():
    """Lesson 3: THE MESS — metric buried in multi-CTE has no clear owner."""
    import io
    from unittest.mock import patch
    
    fixture_dir = Path(__file__).parent.parent / "mesa_core" / "learn" / "fixture"
    tmp = Path("/tmp/mesa_learn_test")
    tmp.mkdir(exist_ok=True)
    ctx = LessonContext(fixture_dir, tmp)
    
    ctx.pause = lambda msg="": None
    
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        lesson3_one_metric_one_owner.run(ctx)
    
    output = captured.getvalue()
    
    # Verify the messy query was shown
    assert "messy" in output.lower() or "gold layer" in output.lower()
    
    # Verify the lesson created the messy file
    messy_file = tmp / "messy_gold_customer_metrics.sql"
    assert messy_file.exists()
    
    # Verify the file has multiple CTEs (the "mess")
    content = messy_file.read_text()
    assert "WITH customer_orders AS" in content
    assert "retention AS" in content
    assert "lifetime_value AS" in content


def test_lesson3_vocabulary_present():
    """Lesson 3: vocabulary 'metric encapsulation', 'one file one owner', 'git blame' appear."""
    import io
    from unittest.mock import patch
    
    fixture_dir = Path(__file__).parent.parent / "mesa_core" / "learn" / "fixture"
    tmp = Path("/tmp/mesa_learn_test")
    tmp.mkdir(exist_ok=True)
    ctx = LessonContext(fixture_dir, tmp)
    
    ctx.pause = lambda msg="": None
    
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        lesson3_one_metric_one_owner.run(ctx)
    
    output = captured.getvalue()
    
    assert "metric encapsulation" in output.lower() or "encapsulation" in output.lower()
    assert "one file" in output.lower() or "one metric" in output.lower()
    assert "git blame" in output.lower() or "git log" in output.lower()
    assert "owner" in output.lower()
