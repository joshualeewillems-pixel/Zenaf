"""mirror_prose_title: Desktop / course-style basenames vs project identity."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.workspace_identity.mirror_prose_title import mirror_basename_looks_like_prose_title


def test_course_and_journal_style_titles() -> None:
    assert mirror_basename_looks_like_prose_title("The way of mthe law")
    assert mirror_basename_looks_like_prose_title("Flushing our bad bacteria")
    assert mirror_basename_looks_like_prose_title("FOr website and promotion")
    assert mirror_basename_looks_like_prose_title("Be Light Breath training")
    assert mirror_basename_looks_like_prose_title("Meditaton from tbe heart")
    assert mirror_basename_looks_like_prose_title("Ton y Robins Mastermind")
    assert mirror_basename_looks_like_prose_title("AI book writing skills")
    assert mirror_basename_looks_like_prose_title("Writings about my life")
    assert mirror_basename_looks_like_prose_title("2024 Exam Study Guide")
    assert mirror_basename_looks_like_prose_title("Spark to raging flame")
    assert mirror_basename_looks_like_prose_title("Group of 8 intention")
    assert mirror_basename_looks_like_prose_title("HAPPY FOR NO REASON")
    assert mirror_basename_looks_like_prose_title("Conversation-McTaggart, Braden, Lipton")
    assert mirror_basename_looks_like_prose_title("Emotional SOverenty-vagus nerve")
    assert mirror_basename_looks_like_prose_title("A Oct 4 class")
    assert mirror_basename_looks_like_prose_title("Awareness faci;litator school")
    assert mirror_basename_looks_like_prose_title("Elecgtro Acupuncture medicine")
    assert mirror_basename_looks_like_prose_title("REMOVE NEGATIVITY sleeping")
    assert mirror_basename_looks_like_prose_title("GLobel information network")
    assert mirror_basename_looks_like_prose_title("AI SUmmit- Alicia-2026")
    assert mirror_basename_looks_like_prose_title("Holistic Wellness FSM")
    assert mirror_basename_looks_like_prose_title("Motivating the Masses")
    assert mirror_basename_looks_like_prose_title("Rey- Creating success")
    assert mirror_basename_looks_like_prose_title("Easy Launch Acxademy")
    assert mirror_basename_looks_like_prose_title("Promoting the clinic")
    assert mirror_basename_looks_like_prose_title("Pledge of alligence")
    assert mirror_basename_looks_like_prose_title("Branding with Rey")
    assert mirror_basename_looks_like_prose_title("Outline opf videos")
    assert mirror_basename_looks_like_prose_title("CHi Gong benefits")
    assert mirror_basename_looks_like_prose_title("Ulan SYmposium 23")
    assert mirror_basename_looks_like_prose_title("AAA Landing page")
    assert mirror_basename_looks_like_prose_title("Book of Miracles")
    assert mirror_basename_looks_like_prose_title("Writing the book")
    assert mirror_basename_looks_like_prose_title("AI book notes")
    assert mirror_basename_looks_like_prose_title("CTTP days hours")
    assert mirror_basename_looks_like_prose_title("A powerful day")
    assert mirror_basename_looks_like_prose_title("AI summit 2024")
    assert mirror_basename_looks_like_prose_title("Brian Tracy AI")
    assert mirror_basename_looks_like_prose_title("Law of love")
    assert mirror_basename_looks_like_prose_title("Healing Summits-trauma")
    assert mirror_basename_looks_like_prose_title("Acupuncture Marketing")
    assert mirror_basename_looks_like_prose_title("Coherence advantage")
    assert mirror_basename_looks_like_prose_title("Raikov-Af Technique")
    assert mirror_basename_looks_like_prose_title("Challenge secretes")
    assert mirror_basename_looks_like_prose_title("Moaquito solutions")
    assert mirror_basename_looks_like_prose_title("Positive thibnking")
    assert mirror_basename_looks_like_prose_title("Abdominal massage")
    assert mirror_basename_looks_like_prose_title("comunity outreach")
    assert mirror_basename_looks_like_prose_title("Frequency healing")
    assert mirror_basename_looks_like_prose_title("Meeditation music")
    assert mirror_basename_looks_like_prose_title("Positive thinking")
    assert mirror_basename_looks_like_prose_title("Awakening books")
    assert mirror_basename_looks_like_prose_title("Intention Class")
    assert mirror_basename_looks_like_prose_title("Walking project")
    assert mirror_basename_looks_like_prose_title("Hypnotic words")
    assert mirror_basename_looks_like_prose_title("Lance material")


def test_typical_project_segments_stay() -> None:
    assert not mirror_basename_looks_like_prose_title("local_ai")
    assert not mirror_basename_looks_like_prose_title("HealingHavenModule")
    assert not mirror_basename_looks_like_prose_title("user_files")
    assert not mirror_basename_looks_like_prose_title("api")
    assert not mirror_basename_looks_like_prose_title("frontend")
    assert not mirror_basename_looks_like_prose_title("Healing Haven Clinic")
    assert not mirror_basename_looks_like_prose_title("Chicago North Office")
    assert not mirror_basename_looks_like_prose_title("React project")
