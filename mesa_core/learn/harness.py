# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
mesa_core/learn/harness.py — SPEC_67 Slice 2

The resumable lesson driver for `mesa learn`. Tracks progress in a dotfile,
supports --reset and jumping to specific lessons.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import click


class Lesson(Protocol):
    """Protocol for a lesson module."""
    
    @property
    def number(self) -> int:
        """Lesson number (1-5)."""
        ...
    
    @property
    def title(self) -> str:
        """Lesson title (for display)."""
        ...
    
    def run(self, ctx: LessonContext) -> None:
        """Execute the lesson interactively."""
        ...


class LessonContext:
    """Context passed to each lesson during execution."""
    
    def __init__(self, fixture_dir: Path, working_dir: Path):
        self.fixture_dir = fixture_dir
        self.working_dir = working_dir
        self.db_path = working_dir / "tutorial.duckdb"
    
    def echo(self, message: str, **kwargs) -> None:
        """Print a message (wraps click.echo for consistency)."""
        click.echo(message, **kwargs)
    
    def style(self, text: str, **kwargs) -> str:
        """Style text (wraps click.style)."""
        return click.style(text, **kwargs)
    
    def pause(self, message: str = "Press Enter to continue...") -> None:
        """Pause and wait for user input."""
        click.prompt(message, default="", show_default=False)


class ProgressTracker:
    """Tracks which lesson the user has reached."""
    
    def __init__(self, progress_file: Path):
        self.progress_file = progress_file
    
    def load(self) -> int:
        """Load the highest lesson reached (0 if never started)."""
        if not self.progress_file.exists():
            return 0
        try:
            data = json.loads(self.progress_file.read_text())
            return data.get("highest_lesson", 0)
        except (json.JSONDecodeError, KeyError):
            return 0
    
    def save(self, lesson_number: int) -> None:
        """Save progress (highest lesson reached)."""
        data = {"highest_lesson": lesson_number}
        self.progress_file.write_text(json.dumps(data, indent=2))
    
    def reset(self) -> None:
        """Clear progress."""
        if self.progress_file.exists():
            self.progress_file.unlink()


def run_learn(
    lessons: list[Lesson],
    fixture_dir: Path,
    working_dir: Path | None = None,
    reset: bool = False,
    jump_to: int | None = None,
) -> None:
    """
    Run the `mesa learn` tutorial.
    
    Args:
        lessons: Ordered list of lesson modules (1-5)
        fixture_dir: Path to the tutorial fixture project
        working_dir: Where to create the working copy and track progress
        reset: If True, clear progress and restart from lesson 1
        jump_to: If set, jump directly to this lesson number
    """
    if working_dir is None:
        working_dir = Path.cwd() / ".mesa_learn"
    
    working_dir.mkdir(exist_ok=True)
    progress = ProgressTracker(working_dir / ".mesa_learn_progress")
    
    if reset:
        progress.reset()
        click.echo(click.style("Progress reset. Starting from lesson 1...", fg="yellow"))
    
    # Determine where to start
    if jump_to is not None:
        start_lesson = jump_to
        if start_lesson < 1 or start_lesson > len(lessons):
            click.echo(click.style(
                f"Invalid lesson number: {start_lesson}. Choose 1-{len(lessons)}.",
                fg="red"), err=True)
            return
    else:
        highest_reached = progress.load()
        if highest_reached >= len(lessons):
            click.echo(click.style(
                f"You've completed all {len(lessons)} lessons! Use --reset to start over.",
                fg="green"))
            return
        start_lesson = highest_reached + 1
    
    # Welcome banner
    if start_lesson == 1:
        _print_welcome()
    
    # Run lessons starting from start_lesson
    ctx = LessonContext(fixture_dir, working_dir)
    
    for lesson in lessons:
        if lesson.number < start_lesson:
            continue  # skip already-completed lessons
        
        click.echo("\n" + "=" * 70)
        click.echo(click.style(
            f"  LESSON {lesson.number}: {lesson.title}",
            fg="cyan", bold=True))
        click.echo("=" * 70 + "\n")
        
        # Run the lesson
        try:
            lesson.run(ctx)
        except KeyboardInterrupt:
            click.echo(click.style("\n\nInterrupted. Progress saved.", fg="yellow"))
            return
        except Exception as e:
            click.echo(click.style(f"\n\nLesson failed: {e}", fg="red"), err=True)
            raise
        
        # Save progress
        progress.save(lesson.number)
        
        # Pause before next lesson (unless it's the last one)
        if lesson.number < len(lessons):
            ctx.echo("")
            ctx.pause(click.style(
                f"✓ Lesson {lesson.number} complete. Press Enter for Lesson {lesson.number + 1}...",
                fg="green"))
    
    # All done
    click.echo("\n" + "=" * 70)
    click.echo(click.style("  🎉 Congratulations! You've completed all 5 lessons.", fg="green", bold=True))
    click.echo("=" * 70)
    _print_sendoff()


def _print_welcome() -> None:
    """Print the welcome banner for lesson 1."""
    click.echo(click.style("""
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║                        WELCOME TO MESA LEARN                         ║
║                                                                      ║
║  This tutorial shows you MESA's vocabulary by letting you watch     ║
║  things break — then watch MESA catch them. Every lesson starts     ║
║  with the mess, on your machine, in your terminal. No lecture       ║
║  first. The dopamine is in the catch.                               ║
║                                                                      ║
║  Time: ~20 minutes | 5 lessons | 100% local (no account needed)    ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
""", fg="cyan", bold=True))


def _print_sendoff() -> None:
    """Print the sendoff message after lesson 5."""
    click.echo("""
You now have the vocabulary to explain MESA to a coworker. Here's what you learned:

  1. IS vs MEANS — identity vs conclusion. Never confuse them.
  2. The fat-finger join — same ID, different customer, silently doubled revenue.
  3. Entity isolation — declare relationships once, Reference Carriers hold addresses.
  4. Metric encapsulation — one file, one owner. Point at a line, name the owner.
  5. Compile once, ship everywhere — semantic compilation turns a MESA metric into
     Snowflake SQL, BigQuery SQL, Cube, MetricFlow... from the same source file.

That's the whole pitch. Go tell someone.

Next steps:
  • `mesa init my-project` — scaffold your own four-tier project
  • `mesa new entity Customer --from-ddl schema.sql` — onboard an existing table
  • Read the docs: https://github.com/Mesantic/mesa-core
""")
