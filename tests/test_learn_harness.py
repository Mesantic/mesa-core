"""
tests/test_learn_harness.py — SPEC_67 Slice 2

Test the lesson harness: progress tracking, resumability, --reset, jump-to.
"""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from mesa_core.learn import harness, LessonContext


class MockLesson:
    """Mock lesson for testing the harness."""
    
    def __init__(self, number: int, title: str):
        self._number = number
        self._title = title
        self.run_count = 0
    
    @property
    def number(self) -> int:
        return self._number
    
    @property
    def title(self) -> str:
        return self._title
    
    def run(self, ctx: LessonContext) -> None:
        self.run_count += 1
        ctx.echo(f"Lesson {self.number} ran")


def test_progress_tracker_saves_and_loads(tmp_path):
    """Progress is persisted across invocations."""
    progress_file = tmp_path / ".mesa_learn_progress"
    tracker = harness.ProgressTracker(progress_file)
    
    # Initially no progress
    assert tracker.load() == 0
    
    # Save progress
    tracker.save(3)
    assert tracker.load() == 3
    
    # Reset clears progress
    tracker.reset()
    assert tracker.load() == 0


def test_run_learn_starts_from_lesson_1_on_first_run(tmp_path):
    """First run starts at lesson 1."""
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    working_dir = tmp_path / "working"
    
    lessons = [MockLesson(1, "First"), MockLesson(2, "Second"), MockLesson(3, "Third")]
    
    # Mock the interactive pause to auto-continue
    original_pause = LessonContext.pause
    LessonContext.pause = lambda self, msg="": None
    
    try:
        harness.run_learn(lessons, fixture_dir, working_dir)
        
        # All lessons should have run
        assert all(L.run_count == 1 for L in lessons)
        
        # Progress saved
        tracker = harness.ProgressTracker(working_dir / ".mesa_learn_progress")
        assert tracker.load() == 3
    finally:
        LessonContext.pause = original_pause


def test_run_learn_resumes_from_saved_progress(tmp_path):
    """Subsequent runs resume from saved progress."""
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    
    # Pre-save progress at lesson 2
    tracker = harness.ProgressTracker(working_dir / ".mesa_learn_progress")
    tracker.save(2)
    
    lessons = [MockLesson(1, "First"), MockLesson(2, "Second"), MockLesson(3, "Third")]
    
    original_pause = LessonContext.pause
    LessonContext.pause = lambda self, msg="": None
    
    try:
        harness.run_learn(lessons, fixture_dir, working_dir)
        
        # Lessons 1-2 skipped, only lesson 3 ran
        assert lessons[0].run_count == 0
        assert lessons[1].run_count == 0
        assert lessons[2].run_count == 1
        
        # Progress updated to 3
        assert tracker.load() == 3
    finally:
        LessonContext.pause = original_pause


def test_run_learn_reset_clears_progress(tmp_path):
    """--reset clears saved progress and restarts from lesson 1."""
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    
    # Pre-save progress at lesson 3
    tracker = harness.ProgressTracker(working_dir / ".mesa_learn_progress")
    tracker.save(3)
    
    lessons = [MockLesson(1, "First"), MockLesson(2, "Second")]
    
    original_pause = LessonContext.pause
    LessonContext.pause = lambda self, msg="": None
    
    try:
        harness.run_learn(lessons, fixture_dir, working_dir, reset=True)
        
        # Both lessons ran
        assert lessons[0].run_count == 1
        assert lessons[1].run_count == 1
        
        # Progress now at 2
        assert tracker.load() == 2
    finally:
        LessonContext.pause = original_pause


def test_run_learn_jump_to_specific_lesson(tmp_path):
    """Can jump directly to a specific lesson number."""
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    working_dir = tmp_path / "working"
    
    lessons = [MockLesson(1, "First"), MockLesson(2, "Second"), MockLesson(3, "Third")]
    
    original_pause = LessonContext.pause
    LessonContext.pause = lambda self, msg="": None
    
    try:
        harness.run_learn(lessons, fixture_dir, working_dir, jump_to=2)
        
        # Only lessons 2-3 ran
        assert lessons[0].run_count == 0
        assert lessons[1].run_count == 1
        assert lessons[2].run_count == 1
    finally:
        LessonContext.pause = original_pause
