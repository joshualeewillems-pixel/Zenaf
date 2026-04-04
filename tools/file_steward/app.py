# =========================================================
# AI FILE STEWARD - appx.py
# =========================================================
# PURPOSE
# -------
# This app is a local-first Streamlit file organizer with:
#
# 1. Top-level domain sorting
# 2. Guided sub-sorting inside any chosen folder
# 3. Pattern detection for better child-folder suggestions
# 4. Editable folder architecture planning
# 5. Editable item assignments
# 6. Validation before move
# 7. Undo support via batch logs
# 8. Local navigation helpers for Windows
#
# DESIGN PRINCIPLES
# -----------------
# - Preview first
# - No blind moves
# - User can edit the plan
# - Validation before execution
# - Undo after execution
# - Keep clinic-sensitive handling cautious
#
# IMPORTANT
# ---------
# This build does NOT read file contents.
# It uses:
# - filenames
# - extensions
# - folder context
# - repeated token patterns
# - repeated year patterns
#
# =========================================================

import json
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


# =========================================================
# SECTION 1 - STREAMLIT PAGE SETUP
# =========================================================

st.set_page_config(page_title="AI File Steward", layout="wide")

st.title("AI File Steward")
st.caption(
    "Preview-first local file organizer with domain sorting, guided subsorting, "
    "validation, editable folder plans, and undo. Suggestions favor filename and "
    "folder context over file type alone."
)

st.warning(
    "Local-only workflow recommended. Clinic-related material should be manually reviewed. "
    "This app is path/name/extension based unless explicitly expanded later."
)


# =========================================================
# SECTION 2 - GLOBAL PATHS / CONSTANTS
# =========================================================

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Recent roots persisted across runs (scan + explore)
RECENT_ROOTS_FILE = LOG_DIR / "recent_roots.json"
MAX_RECENT_ROOTS = 10


def get_smart_default_paths():
    """
    Build suggested folder roots from Windows environment.
    Use these for quick-access buttons and default inputs.
    """
    paths = {}
    try:
        user = os.environ.get("USERPROFILE", "C:\\Users")
        one_drive = os.environ.get("OneDrive", os.path.join(user, "OneDrive"))
        paths["Desktop"] = os.path.join(user, "Desktop")
        paths["OneDrive"] = one_drive
        paths["OneDrive Desktop"] = os.path.join(one_drive, "Desktop")
        paths["Downloads"] = os.path.join(user, "Downloads")
        paths["Documents"] = os.path.join(user, "Documents")
        # Common archive-style folder if present
        archive = os.path.join(one_drive, "Desktop", "07_ARCHIVE")
        if os.path.isdir(archive):
            paths["07_ARCHIVE"] = archive
    except Exception:
        pass
    return {k: v for k, v in paths.items() if v and os.path.isdir(v)}


def load_recent_roots():
    """Load list of recent scan/explore roots from disk."""
    if not RECENT_ROOTS_FILE.exists():
        return []
    try:
        with open(RECENT_ROOTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("roots", [])[:MAX_RECENT_ROOTS]
    except Exception:
        return []


def save_recent_root(path: str):
    """Append a path to recent roots (dedupe, newest first) and persist."""
    path = str(Path(path).resolve()) if path else ""
    if not path or not Path(path).exists():
        return
    current = load_recent_roots()
    current = [path] + [p for p in current if p != path]
    current = current[:MAX_RECENT_ROOTS]
    try:
        with open(RECENT_ROOTS_FILE, "w", encoding="utf-8") as f:
            json.dump({"roots": current}, f, indent=0)
    except Exception:
        pass


def find_folders_to_subsort(parent_root: str, min_items: int = 5):
    """
    List immediate subfolders of parent_root that are good candidates for
    subsorting: many items and/or mixed file types (high extension diversity).
    Returns DataFrame: path, name, item_count, extension_count, mix_score, suggested.
    """
    parent = Path(parent_root)
    if not parent.exists() or not parent.is_dir():
        return pd.DataFrame()

    rows = []
    for child in parent.iterdir():
        if not child.is_dir():
            continue
        skip, _ = should_skip_path(child)
        if skip:
            continue
        try:
            items = []
            for p in child.iterdir():
                if should_skip_path(p)[0]:
                    continue
                items.append(p)
            item_count = len(items)
            exts = set()
            for p in items:
                if p.is_file():
                    exts.add(p.suffix.lower())
            ext_count = len(exts)
            # Simple "messiness" score: more items + more types = better subsort candidate
            mix_score = min(1.0, (item_count / 50) * 0.5 + (ext_count / 10) * 0.5) if (item_count or ext_count) else 0
            suggested = item_count >= min_items and (item_count >= 10 or ext_count >= 3)
            rows.append({
                "path": str(child),
                "name": child.name,
                "item_count": item_count,
                "extension_count": ext_count,
                "mix_score": round(mix_score, 2),
                "suggested": suggested,
            })
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values(["suggested", "item_count", "extension_count"], ascending=[False, False, False])
    return df.reset_index(drop=True)


ALLOWED_DOMAINS = [
    "CLINIC",
    "MOVEMENT",
    "PERSONAL_DEVELOPMENT",
    "MEDIA",
    "PROJECTS",
    "RESEARCH",
    "UNSORTED",
    "SKIP",
]

EXCLUDED_PREFIXES = ("~$",)
EXCLUDED_EXTENSIONS = {
    ".ini",
    ".tmp",
    ".lnk",
}
EXCLUDED_FOLDER_NAMES = {
    "__pycache__",
    ".git",
}

# These are words we generally do not want to over-use as clustering tokens.
STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "your", "you",
    "our", "are", "was", "were", "have", "has", "had", "but", "not", "all",
    "new", "old", "final", "draft", "copy", "version", "file", "folder",
    "doc", "docs", "document", "documents", "sheet", "sheets", "pdf"
}


# =========================================================
# SECTION 3 - DOMAIN CLASSIFICATION RULES
# =========================================================
# These rules drive the top-level broad sort.
# They are intentionally readable and easy to edit.

RULES = [
    {
        "name": "clinic_patient_admin",
        "domain": "CLINIC",
        "keywords_any": [
            "patient", "patients", "acupuncture", "clinic", "treatment",
            "electro acupuncture", "notes to treat", "nutrition", "cryo",
            "cell core"
        ],
        "keywords_boost": [
            "intake", "soap", "chart", "case", "insurance",
            "consent", "billing", "progress note", "superbill"
        ],
        "extensions": [".pdf", ".doc", ".docx", ".txt", ".rtf", ".xlsx", ".csv", ""],
        "max_confidence": 0.85,
        "sensitivity": "high",
    },
    {
        "name": "movement_group_material",
        "domain": "MOVEMENT",
        "keywords_any": [
            "heart", "movement", "group of 8", "power of 8",
            "many 8", "anna and i", "mind movie", "sojul"
        ],
        "keywords_boost": ["agenda", "practice", "session", "circle"],
        "extensions": [".pdf", ".doc", ".docx", ".ppt", ".pptx", ".mp3", ".mp4", ""],
        "max_confidence": 0.80,
        "sensitivity": "normal",
    },
    {
        "name": "personal_dev_material",
        "domain": "PERSONAL_DEVELOPMENT",
        "keywords_any": [
            "routine", "performance", "body language", "influence",
            "success", "lisa nichols", "hemisync", "powerful day",
            "morning routine", "daily routine", "toast masters"
        ],
        "keywords_boost": ["habit", "self", "motivation", "speaking"],
        "extensions": [".pdf", ".doc", ".docx", ".mp3", ".mp4", ""],
        "max_confidence": 0.80,
        "sensitivity": "normal",
    },
    {
        "name": "media_assets",
        "domain": "MEDIA",
        "keywords_any": [
            "video", "videos", "image", "images", "audio",
            "slides", "media", "photos"
        ],
        "keywords_boost": ["edited", "final", "draft", "raw"],
        "extensions": [".jpg", ".jpeg", ".png", ".gif", ".mp3", ".wav", ".mp4", ".mov", ".ppt", ".pptx", ""],
        "max_confidence": 0.90,
        "sensitivity": "normal",
    },
    {
        "name": "project_working_docs",
        "domain": "PROJECTS",
        "keywords_any": [
            "project", "projects", "to do", "programs in action",
            "products", "forms", "docs", "sheets", "folders"
        ],
        "keywords_boost": ["roadmap", "plan", "tracker", "workflow", "spec"],
        "extensions": [".pdf", ".doc", ".docx", ".xlsx", ".csv", ".md", ""],
        "max_confidence": 0.80,
        "sensitivity": "normal",
    },
    {
        "name": "research_reference",
        "domain": "RESEARCH",
        "keywords_any": [
            "to buy", "bought", "to look at", "read",
            "article", "research", "book", "books", "look at"
        ],
        "keywords_boost": ["journal", "paper", "study", "reference"],
        "extensions": [".pdf", ".epub", ".mobi", ".doc", ".docx", ".txt", ""],
        "max_confidence": 0.75,
        "sensitivity": "normal",
    },
]


# =========================================================
# SECTION 4 - PHI / SENSITIVE RISK HINTS
# =========================================================
# This is not a perfect detector.
# It is only a filename-based caution layer.

PHI_HINTS = [
    "patient", "patients", "dob", "ssn", "mrn", "diagnosis", "treatment",
    "insurance", "claim", "intake", "soap", "chart", "consent",
    "progress note", "case note", "superbill", "billing"
]

SENSITIVE_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".rtf", ".xlsx", ".csv"}


# =========================================================
# SECTION 5 - DEFAULT SUBFOLDER SCHEMAS
# =========================================================
# These are schema suggestions based on context domain.
# They are NOT the only categories the app can propose.
# Dynamic / pattern-generated categories get merged in later.

SUBFOLDER_SCHEMAS = {
    "CLINIC": [
        "Intake_Forms",
        "Billing_Insurance",
        "Treatment_Notes",
        "Patient_Education",
        "Admin",
        "Unsorted_Clinic",
    ],
    "MEDIA": [
        "Images",
        "Audio",
        "Video",
        "Slides",
        "Exports",
        "Source_Files",
        "Web_Assets",
        "Embeds",
        "Unsorted_Media",
    ],
    "PROJECTS": [
        "Active",
        "Planning",
        "Assets",
        "Deliverables",
        "Reference",
        "Archive",
        "Web_Assets",
        "Templates",
        "Drafts",
        "Final",
        "Unsorted_Projects",
    ],
    "RESEARCH": [
        "Articles",
        "Books",
        "Notes",
        "To_Read",
        "Referenced",
        "Unsorted_Research",
    ],
    "MOVEMENT": [
        "Session_Materials",
        "Practices",
        "Planning",
        "Media",
        "Reference",
        "Web_Assets",
        "Unsorted_Movement",
    ],
    "PERSONAL_DEVELOPMENT": [
        "Routines",
        "Training",
        "Audio",
        "Video",
        "Notes",
        "Reference",
        "Web_Assets",
        "Unsorted_Personal_Development",
    ],
    "UNKNOWN": [
        "Documents",
        "Images",
        "Audio",
        "Video",
        "Web_Assets",
        "HTML",
        "CSS",
        "JavaScript",
        "Embeds",
        "Reference",
        "Archive",
        "Unsorted",
    ],
}


# =========================================================
# SECTION 6 - DOMAIN-SPECIFIC CHILD SORT RULES
# =========================================================
# These are used inside Explore & Subsort to suggest child folders.

SUBFOLDER_RULES = {
    "CLINIC": [
        {
            "child": "Intake_Forms",
            "keywords": ["intake", "consent", "new patient", "registration", "demographic"],
            "extensions": [".pdf", ".doc", ".docx", ".txt", ".rtf"],
        },
        {
            "child": "Billing_Insurance",
            "keywords": ["billing", "insurance", "claim", "invoice", "superbill", "payment"],
            "extensions": [".pdf", ".doc", ".docx", ".xlsx", ".csv"],
        },
        {
            "child": "Treatment_Notes",
            "keywords": ["soap", "progress note", "treatment", "chart", "case note", "notes"],
            "extensions": [".pdf", ".doc", ".docx", ".txt", ".rtf"],
        },
        {
            "child": "Patient_Education",
            "keywords": ["education", "exercise", "aftercare", "instructions", "handout"],
            "extensions": [".pdf", ".doc", ".docx", ".ppt", ".pptx"],
        },
        {
            "child": "Admin",
            "keywords": ["admin", "policy", "staff", "template", "schedule"],
            "extensions": [".pdf", ".doc", ".docx", ".xlsx", ".csv"],
        },
    ],
    "MEDIA": [
        {
            "child": "Images",
            "keywords": ["image", "photo", "picture", "screenshot", "logo", "favicon"],
            "extensions": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"],
        },
        {
            "child": "Audio",
            "keywords": ["audio", "podcast", "recording", "voice"],
            "extensions": [".mp3", ".wav", ".m4a"],
        },
        {
            "child": "Video",
            "keywords": ["video", "clip", "footage"],
            "extensions": [".mp4", ".mov", ".avi", ".mkv"],
        },
        {
            "child": "Slides",
            "keywords": ["slides", "presentation", "deck"],
            "extensions": [".ppt", ".pptx", ".pdf"],
        },
        {
            "child": "Web_Assets",
            "keywords": ["index", "site", "web", "assets"],
            "extensions": [".html", ".css", ".js"],
        },
        {
            "child": "Embeds",
            "keywords": ["iframe", "embed"],
            "extensions": [".html", ".js"],
        },
    ],
    "PROJECTS": [
        {
            "child": "Planning",
            "keywords": ["plan", "roadmap", "timeline", "tracker", "proposal", "spec"],
            "extensions": [".pdf", ".doc", ".docx", ".xlsx", ".csv", ".md"],
        },
        {
            "child": "Assets",
            "keywords": ["asset", "logo", "brand", "image", "media"],
            "extensions": [".jpg", ".jpeg", ".png", ".gif", ".svg", ".mp4", ".mov"],
        },
        {
            "child": "Deliverables",
            "keywords": ["final", "deliverable", "submission", "sent"],
            "extensions": [".pdf", ".doc", ".docx", ".ppt", ".pptx", ".zip"],
        },
        {
            "child": "Reference",
            "keywords": ["reference", "inspiration", "research", "example"],
            "extensions": [".pdf", ".doc", ".docx", ".txt", ".url"],
        },
        {
            "child": "Archive",
            "keywords": ["old", "archive", "done", "completed"],
            "extensions": [""],
        },
        {
            "child": "Active",
            "keywords": ["draft", "working", "current", "todo", "to do"],
            "extensions": [""],
        },
        {
            "child": "Web_Assets",
            "keywords": ["index", "site", "web", "assets", "html", "css", "js"],
            "extensions": [".html", ".css", ".js"],
        },
        {
            "child": "Templates",
            "keywords": ["template", "boilerplate"],
            "extensions": [".doc", ".docx", ".xlsx", ".csv", ".md", ".html"],
        },
    ],
    "RESEARCH": [
        {
            "child": "Articles",
            "keywords": ["article", "paper", "study", "journal"],
            "extensions": [".pdf", ".doc", ".docx", ".txt"],
        },
        {
            "child": "Books",
            "keywords": ["book", "ebook"],
            "extensions": [".pdf", ".epub", ".mobi"],
        },
        {
            "child": "Notes",
            "keywords": ["notes", "summary", "highlights"],
            "extensions": [".txt", ".doc", ".docx", ".md"],
        },
        {
            "child": "To_Read",
            "keywords": ["to read", "read later", "queue", "look at"],
            "extensions": [".pdf", ".doc", ".docx", ".txt", ".url"],
        },
        {
            "child": "Referenced",
            "keywords": ["reference", "cited", "quoted"],
            "extensions": [".pdf", ".doc", ".docx", ".txt"],
        },
    ],
    "MOVEMENT": [
        {
            "child": "Session_Materials",
            "keywords": ["session", "agenda", "circle", "group", "power of 8"],
            "extensions": [".pdf", ".doc", ".docx", ".ppt", ".pptx"],
        },
        {
            "child": "Practices",
            "keywords": ["practice", "exercise", "breath", "movement"],
            "extensions": [".pdf", ".doc", ".docx", ".mp3", ".mp4"],
        },
        {
            "child": "Planning",
            "keywords": ["plan", "schedule", "outline"],
            "extensions": [".pdf", ".doc", ".docx", ".xlsx"],
        },
        {
            "child": "Media",
            "keywords": ["image", "video", "audio", "photo"],
            "extensions": [".jpg", ".jpeg", ".png", ".mp3", ".wav", ".mp4", ".mov"],
        },
        {
            "child": "Reference",
            "keywords": ["reference", "research", "inspiration"],
            "extensions": [".pdf", ".doc", ".docx", ".txt"],
        },
        {
            "child": "Web_Assets",
            "keywords": ["index", "site", "web", "assets", "iframe", "embed"],
            "extensions": [".html", ".css", ".js"],
        },
    ],
    "PERSONAL_DEVELOPMENT": [
        {
            "child": "Routines",
            "keywords": ["routine", "daily", "morning", "habit"],
            "extensions": [".pdf", ".doc", ".docx", ".txt"],
        },
        {
            "child": "Training",
            "keywords": ["training", "toastmasters", "performance", "influence", "body language"],
            "extensions": [".pdf", ".doc", ".docx", ".ppt", ".pptx", ".mp3", ".mp4"],
        },
        {
            "child": "Audio",
            "keywords": ["audio", "hemisync", "recording"],
            "extensions": [".mp3", ".wav", ".m4a"],
        },
        {
            "child": "Video",
            "keywords": ["video"],
            "extensions": [".mp4", ".mov", ".mkv"],
        },
        {
            "child": "Notes",
            "keywords": ["notes", "journal", "summary"],
            "extensions": [".txt", ".doc", ".docx", ".md"],
        },
        {
            "child": "Reference",
            "keywords": ["book", "article", "reference", "read"],
            "extensions": [".pdf", ".doc", ".docx", ".txt", ".epub", ".mobi"],
        },
    ],
}


# =========================================================
# SECTION 7 - LOW-LEVEL UTILITY FUNCTIONS
# =========================================================

def should_skip_path(path: Path):
    """Return (skip_boolean, reason_string)."""
    if path.name.startswith(EXCLUDED_PREFIXES):
        return True, "temporary/lock file"
    if path.suffix.lower() in EXCLUDED_EXTENSIONS:
        return True, f"excluded extension {path.suffix.lower()}"
    if any(part in EXCLUDED_FOLDER_NAMES for part in path.parts):
        return True, "excluded folder"
    return False, ""


def detect_phi_risk(path: Path):
    """Very simple path-name based PHI risk hint."""
    name = path.name.lower()
    hits = [term for term in PHI_HINTS if term in name]
    risk = "HIGH" if hits and path.suffix.lower() in SENSITIVE_EXTENSIONS.union({""}) else "LOW"
    return risk, ", ".join(hits) if hits else ""


# Content reading: only for non-PHI, non-CLINIC. Used to improve suggestions.
CONTENT_SAMPLE_MAX_CHARS = 3000
READABLE_TEXT_EXTENSIONS = {".txt", ".md", ".csv"}
# Optional PDF extraction if pypdf or PyPDF2 available
_PDF_READER = None
try:
    import pypdf
    _PDF_READER = pypdf
except ImportError:
    try:
        import PyPDF2 as _PDF_READER
    except ImportError:
        pass


def read_safe_content_sample(
    path: Path,
    *,
    skip_domain: str | None = None,
    phi_risk: str = "LOW",
    max_chars: int = CONTENT_SAMPLE_MAX_CHARS,
) -> str:
    """
    Read a short sample of file content for hinting. Returns "" if:
    - Path is not a file, or
    - skip_domain is "CLINIC", or
    - phi_risk is "HIGH", or
    - Extension not supported (.txt, .md, .csv, or .pdf if library available).
    """
    if path.is_dir() or skip_domain == "CLINIC" or phi_risk == "HIGH":
        return ""
    ext = path.suffix.lower()
    if ext not in READABLE_TEXT_EXTENSIONS and (ext != ".pdf" or _PDF_READER is None):
        return ""
    try:
        if ext in (".txt", ".md", ".csv"):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(max_chars)
        if ext == ".pdf" and _PDF_READER is not None:
            try:
                reader = _PDF_READER.PdfReader(path)
                text = ""
                for i, page in enumerate(reader.pages):
                    if i >= 3:
                        break
                    text += page.extract_text() or ""
                    if len(text) >= max_chars:
                        break
                return text[:max_chars]
            except Exception:
                return ""
    except Exception:
        return ""
    return ""


def tokenize_name(name: str):
    """
    Convert filename stem into tokens for clustering.
    Example:
      'invoice_2025_final.pdf' -> ['invoice', '2025', 'final']
    """
    base = Path(name).stem.lower()
    tokens = re.findall(r"[a-zA-Z0-9]+", base)
    cleaned = [t for t in tokens if len(t) >= 3 and t not in STOP_WORDS]
    return cleaned


def tokenize_text(text: str):
    """Tokenize any string (e.g. file content sample) for keyword/topic matching."""
    if not text:
        return []
    low = text.lower()
    tokens = re.findall(r"[a-zA-Z0-9]+", low)
    return [t for t in tokens if len(t) >= 3 and t not in STOP_WORDS]


def safe_count_dir(item: Path):
    """Count files and total size inside a folder, skipping excluded files."""
    file_count = 0
    total_size = 0

    for sub in item.rglob("*"):
        try:
            if sub.is_file():
                skip, _ = should_skip_path(sub)
                if skip:
                    continue
                file_count += 1
                total_size += sub.stat().st_size
        except Exception:
            pass

    return file_count, total_size


def list_batches():
    """Return batch log files newest first."""
    return sorted(LOG_DIR.glob("move_batch_*.json"), reverse=True)


def infer_context_domain(folder_path: Path):
    """
    Determine the likely context domain of a folder.
    This lets subsorting inherit some structure from the parent,
    but later logic should still respect strong local evidence.
    """
    parts = [p.upper() for p in folder_path.parts]
    folder_name = folder_path.name.upper()

    for domain in ALLOWED_DOMAINS:
        if domain in parts or folder_name == domain:
            return domain

    classification = classify_item(folder_path)
    if classification["domain"] in ALLOWED_DOMAINS:
        return classification["domain"]

    return "UNKNOWN"


# =========================================================
# SECTION 8 - WINDOWS NAVIGATION HELPERS
# =========================================================
# NOTE:
# Streamlit tables are not great at row-level buttons.
# So we provide helper functions and then use a selected-item
# inspector UI lower in the Explore tab.

def open_path_windows(path: str):
    """Open a file or folder in Windows default handler."""
    try:
        os.startfile(path)  # type: ignore[attr-defined]
        return True, ""
    except Exception as e:
        return False, str(e)


def reveal_in_explorer(path: str):
    """Reveal file or folder in Explorer."""
    try:
        subprocess.run(["explorer", "/select,", str(Path(path))], check=False)
        return True, ""
    except Exception as e:
        return False, str(e)


def open_folder_picker(title: str = "Select folder") -> str | None:
    """
    Open the system folder picker (Windows Explorer). Returns the selected path or None.
    Uses tkinter when available; no-op on headless or when tkinter fails.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title=title)
        root.destroy()
        return path if path else None
    except Exception:
        return None


# =========================================================
# SECTION 9 - TOP-LEVEL DOMAIN CLASSIFICATION
# =========================================================

def classify_item(
    path: Path,
    content_sample: str | None = None,
    folder_context: str | None = None,
):
    """
    Broad domain classification.
    This is used for the top-level domain sort.
    - content_sample: from read_safe_content_sample; keyword matching uses name + content.
    - folder_context: e.g. names of immediate children (from dir listing); use for folders
      so we classify by what's inside, not just the folder name.
    """
    name = path.name.lower().strip()
    text = name
    if content_sample:
        text = (name + " " + content_sample[:CONTENT_SAMPLE_MAX_CHARS]).lower()
    if folder_context:
        text = (text + " " + folder_context[:CONTENT_SAMPLE_MAX_CHARS]).lower()
    ext = path.suffix.lower()

    best_match = None
    best_score = -1

    for rule in RULES:
        score = 0
        reasons = []

        # Extension fit
        ext_match = (ext in rule["extensions"]) or ("" in rule["extensions"])
        if ext_match:
            score += 1
            reasons.append(f"extension matched {ext or '[folder]'}")

        # Main keyword hits (name + optional content)
        any_hits = [k for k in rule["keywords_any"] if k in text]
        if any_hits:
            score += len(any_hits) * 2
            reasons.append(f"keywords matched: {', '.join(any_hits)}")

        # Boost keyword hits
        boost_hits = [k for k in rule["keywords_boost"] if k in text]
        if boost_hits:
            score += len(boost_hits)
            reasons.append(f"boost terms: {', '.join(boost_hits)}")

        if any_hits and score > best_score:
            confidence = min(0.35 + (score * 0.1), rule["max_confidence"])
            best_score = score
            best_match = {
                "domain": rule["domain"],
                "confidence": round(confidence, 2),
                "rule_name": rule["name"],
                "reason": "; ".join(reasons),
                "sensitivity": rule["sensitivity"],
            }

    if best_match:
        return best_match

    # ---- fallback heuristics (name only for fallbacks) ----
    if name.startswith("a "):
        return {
            "domain": "PERSONAL_DEVELOPMENT",
            "confidence": 0.45,
            "rule_name": "fallback_a_prefix",
            "reason": "fallback: starts with 'A '",
            "sensitivity": "normal",
        }
    if "book" in text:
        return {
            "domain": "RESEARCH",
            "confidence": 0.55,
            "rule_name": "fallback_book",
            "reason": "fallback: contains 'book' (name or content)",
            "sensitivity": "normal",
        }
    if "program" in text:
        return {
            "domain": "PROJECTS",
            "confidence": 0.55,
            "rule_name": "fallback_program",
            "reason": "fallback: contains 'program' (name or content)",
            "sensitivity": "normal",
        }
    if "video" in text or "image" in text:
        return {
            "domain": "MEDIA",
            "confidence": 0.60,
            "rule_name": "fallback_media",
            "reason": "fallback: contains media term",
            "sensitivity": "normal",
        }

    return {
        "domain": "UNSORTED",
        "confidence": 0.10,
        "rule_name": "no_rule",
        "reason": "no matching rule",
        "sensitivity": "normal",
    }


# =========================================================
# SECTION 10 - TOP-LEVEL SCAN
# =========================================================

def scan_top_level(root: str, use_content_hints: bool = False):
    """
    Scan only immediate children of the root folder.
    This is intentionally conservative and safer than deep recursion.
    When use_content_hints is True, reads a short sample of non-PHI, non-CLINIC
    file content to improve domain classification.
    """
    rows = []
    p = Path(root)

    if not p.exists():
        return pd.DataFrame()

    for item in p.iterdir():
        try:
            skip, skip_reason = should_skip_path(item)
            if skip:
                rows.append({
                    "approve": False,
                    "name": item.name,
                    "path": str(item),
                    "type": "skipped",
                    "files": 0,
                    "size_mb": 0.0,
                    "suggested_domain": "SKIP",
                    "target_domain": "SKIP",
                    "confidence": 0.0,
                    "rule_name": "excluded_path",
                    "reason": skip_reason,
                    "phi_risk": "LOW",
                    "phi_hits": "",
                    "review_note": "",
                    "proposed_dest": "",
                    "validation": "Skipped",
                    "blocked_reason": skip_reason,
                    "status": "Skipped",
                })
                continue

            phi_risk, phi_hits = detect_phi_risk(item)
            folder_context = ""
            if item.is_dir():
                try:
                    child_names = [
                        c.name for c in item.iterdir()
                        if not should_skip_path(c)[0]
                    ]
                    folder_context = " ".join(child_names)[:CONTENT_SAMPLE_MAX_CHARS]
                except Exception:
                    pass

            classification = classify_item(
                item,
                content_sample=None,
                folder_context=folder_context if folder_context else None,
            )
            if use_content_hints and item.is_file() and phi_risk != "HIGH" and classification["domain"] != "CLINIC":
                content_sample = read_safe_content_sample(
                    item, skip_domain="CLINIC", phi_risk=phi_risk,
                )
                if content_sample:
                    classification = classify_item(item, content_sample=content_sample)

            if item.is_dir():
                file_count, total_size = safe_count_dir(item)
                item_type = "folder"
                size_mb = round(total_size / (1024 * 1024), 2)
                files = file_count
            else:
                item_type = "file"
                size_mb = round(item.stat().st_size / (1024 * 1024), 2)
                files = 1

            rows.append({
                "approve": False,
                "name": item.name,
                "path": str(item),
                "type": item_type,
                "files": files,
                "size_mb": size_mb,
                "suggested_domain": classification["domain"],
                "target_domain": classification["domain"],
                "confidence": classification["confidence"],
                "rule_name": classification["rule_name"],
                "reason": classification["reason"],
                "phi_risk": phi_risk,
                "phi_hits": phi_hits,
                "review_note": "",
                "proposed_dest": "",
                "validation": "Not reviewed",
                "blocked_reason": "",
                "status": "Proposed",
            })

        except Exception as e:
            rows.append({
                "approve": False,
                "name": item.name,
                "path": str(item),
                "type": "error",
                "files": 0,
                "size_mb": 0,
                "suggested_domain": "UNSORTED",
                "target_domain": "UNSORTED",
                "confidence": 0.0,
                "rule_name": "scan_error",
                "reason": f"scan error: {e}",
                "phi_risk": "LOW",
                "phi_hits": "",
                "review_note": "",
                "proposed_dest": "",
                "validation": "Blocked",
                "blocked_reason": str(e),
                "status": "Error",
            })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(
        ["phi_risk", "confidence", "size_mb"],
        ascending=[False, False, False]
    ).reset_index(drop=True)


# =========================================================
# SECTION 11 - TOP-LEVEL VALIDATION / EXECUTION / UNDO
# =========================================================

def validate_moves(df: pd.DataFrame, scan_root: str, domain_root: str):
    """
    Validate proposed top-level domain moves before execution.
    """
    validated_rows = []
    scan_root_path = Path(scan_root).resolve()
    domain_root_path = Path(domain_root).resolve()

    for _, row in df.iterrows():
        row = row.copy()
        src = Path(row["path"])

        if row["target_domain"] in ["SKIP", "UNSORTED"]:
            row["proposed_dest"] = ""
            row["validation"] = "No move"
            row["blocked_reason"] = "target domain is SKIP/UNSORTED"
            row["status"] = "Pending Review"
            validated_rows.append(row)
            continue

        if not src.exists():
            row["proposed_dest"] = ""
            row["validation"] = "Blocked"
            row["blocked_reason"] = "source no longer exists"
            row["status"] = "Blocked"
            validated_rows.append(row)
            continue

        try:
            src_resolved = src.resolve()
        except Exception:
            src_resolved = src

        if scan_root_path not in src_resolved.parents and src_resolved != scan_root_path:
            row["proposed_dest"] = ""
            row["validation"] = "Blocked"
            row["blocked_reason"] = "source is outside allowed scan root"
            row["status"] = "Blocked"
            validated_rows.append(row)
            continue

        dest_dir = domain_root_path / row["target_domain"]
        proposed_dest = dest_dir / src.name
        row["proposed_dest"] = str(proposed_dest)

        if proposed_dest.exists():
            row["validation"] = "Blocked"
            row["blocked_reason"] = "destination already exists"
            row["status"] = "Blocked"
            validated_rows.append(row)
            continue

        if src.parent.resolve() == dest_dir.resolve():
            row["validation"] = "Blocked"
            row["blocked_reason"] = "already in target folder"
            row["status"] = "Blocked"
            validated_rows.append(row)
            continue

        if row["phi_risk"] == "HIGH" and row["target_domain"] == "CLINIC" and not row["approve"]:
            row["validation"] = "Sensitive Review Required"
            row["blocked_reason"] = "possible PHI: manual approval required"
            row["status"] = "Sensitive Review Required"
            validated_rows.append(row)
            continue

        row["validation"] = "Valid"
        row["blocked_reason"] = ""
        row["status"] = "Ready" if row["approve"] else "Proposed"
        validated_rows.append(row)

    return pd.DataFrame(validated_rows)


def execute_moves(df: pd.DataFrame, scan_root: str, domain_root: str):
    """
    Execute approved valid top-level domain moves only.
    """
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"move_batch_{batch_id}.json"

    validated_df = validate_moves(df, scan_root, domain_root)
    approved_valid = validated_df[
        (validated_df["approve"] == True) &
        (validated_df["validation"] == "Valid")
    ].copy()

    moves = []
    blocked = []

    for _, row in approved_valid.iterrows():
        src = Path(row["path"])
        dest = Path(row["proposed_dest"])

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))

            moves.append({
                "batch_id": batch_id,
                "timestamp": datetime.now().isoformat(),
                "action": "move",
                "move_type": "domain_sort",
                "approved": True,
                "src": str(src),
                "dest": str(dest),
                "name": row["name"],
                "type": row["type"],
                "target_domain": row["target_domain"],
                "rule_name": row["rule_name"],
                "confidence": float(row["confidence"]),
                "phi_risk": row["phi_risk"],
                "phi_hits": row["phi_hits"],
                "review_note": row["review_note"],
                "status": "executed",
            })
        except Exception as e:
            blocked.append({
                "name": row["name"],
                "reason": str(e),
            })

    payload = {
        "batch_id": batch_id,
        "created_at": datetime.now().isoformat(),
        "move_type": "domain_sort",
        "move_count": len(moves),
        "blocked_count": len(blocked),
        "moves": moves,
        "blocked": blocked,
    }

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return log_path, len(moves), blocked, validated_df


def undo_batch(log_file: Path):
    """
    Undo a chosen batch.
    Reverses move order to better preserve nested logic.
    """
    with open(log_file, "r", encoding="utf-8") as f:
        payload = json.load(f)

    moves = payload.get("moves", [])
    restored = 0
    blocked = []

    for move in reversed(moves):
        src = Path(move["dest"])
        dest = Path(move["src"])

        try:
            if not src.exists():
                blocked.append({"item": move.get("name", src.name), "reason": "moved item not found"})
                continue

            if dest.exists():
                blocked.append({"item": move.get("name", src.name), "reason": "original path already occupied"})
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            restored += 1
        except Exception as e:
            blocked.append({"item": move.get("name", src.name), "reason": str(e)})

    return restored, blocked


# =========================================================
# SECTION 12 - STALE FILE REPORT
# =========================================================

def stale_files(root: str, days: int = 90):
    """
    Find old files for review/reporting.
    """
    cutoff = datetime.now() - timedelta(days=days)
    rows = []

    for f in Path(root).rglob("*"):
        if f.is_file():
            try:
                skip, _ = should_skip_path(f)
                if skip:
                    continue

                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    rows.append({
                        "name": f.name,
                        "path": str(f),
                        "last_modified": mtime.strftime("%Y-%m-%d"),
                        "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                    })
            except Exception:
                pass

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("last_modified").reset_index(drop=True)


# =========================================================
# SECTION 13 - PATTERN DETECTION AND THEME DISCOVERY
# =========================================================
# Theme discovery: infer themes from item names (tokens and phrases) in this folder,
# so suggested folders reflect what's actually present rather than a fixed taxonomy.

# Optional fallback taxonomy for keyword hints when scoring items against a theme name.
THEME_TAXONOMY = [
    {"name": "Healing_Stress_Management", "keywords": ["emdr", "breathwork", "stress", "healing", "trauma", "relaxation", "meditation", "therapy", "yoga", "mindfulness"]},
    {"name": "Courses_Workshops", "keywords": ["course", "courses", "workshop", "workshops", "training", "seminar", "class", "program"]},
    {"name": "To_Buy_Reference", "keywords": ["to buy", "buy", "wishlist", "reference", "referenced"]},
    {"name": "Wellness_Body", "keywords": ["wellness", "health", "nutrition", "diet", "fitness", "supplement"]},
    {"name": "Books_Reading", "keywords": ["book", "books", "reading", "read", "ebook", "author"]},
    {"name": "Articles_Research", "keywords": ["article", "articles", "paper", "study", "research", "science"]},
]


def _token_to_folder_name(token: str) -> str:
    """Turn a token into a folder name (Title_Case)."""
    if not token:
        return ""
    return token[0].upper() + token[1:].lower()


def _bigram_to_folder_name(w1: str, w2: str) -> str:
    """Turn a bigram into a folder name (Word_One_Word_Two)."""
    return f"{_token_to_folder_name(w1)}_{_token_to_folder_name(w2)}"


def discover_themes(items: list) -> list[tuple[str, float]]:
    """
    Infer themes from the folder's item names (tokens and bigrams).
    Returns list of (theme_name, score) sorted by score descending.
    Themes are derived from repeated tokens and two-word phrases across filenames.
    """
    if not items:
        return []
    n = len(items)
    min_items = 2 if n >= 5 else 1  # require at least 2 items for a theme unless folder is tiny

    # Count in how many items each token appears
    token_item_count = defaultdict(set)
    bigram_item_count = defaultdict(set)

    for item in items:
        tokens = tokenize_name(item.name)
        for t in tokens:
            token_item_count[t].add(id(item))
        for i in range(len(tokens) - 1):
            bigram = (tokens[i], tokens[i + 1])
            bigram_item_count[bigram].add(id(item))

    results_map = {}  # theme_name -> best score

    for token, item_ids in token_item_count.items():
        if len(item_ids) < min_items:
            continue
        name = _token_to_folder_name(token)
        if not name or len(name) < 3:
            continue
        score = (len(item_ids) / n) * 0.7 + min(0.3, len(item_ids) * 0.04)
        score = round(min(1.0, score), 2)
        if name not in results_map or results_map[name] < score:
            results_map[name] = score

    for (w1, w2), item_ids in bigram_item_count.items():
        if len(item_ids) < min_items:
            continue
        name = _bigram_to_folder_name(w1, w2)
        if not name or len(name) < 5:
            continue
        score = (len(item_ids) / n) * 0.65 + min(0.35, len(item_ids) * 0.05)
        score = round(min(1.0, score), 2)
        if name not in results_map or results_map[name] < score:
            results_map[name] = score

    return sorted(results_map.items(), key=lambda x: -x[1])


def _score_item_for_theme(text: str, theme_name: str) -> float:
    """Score how well an item (name + optional content) fits a theme. 0 = no match."""
    text_lower = text.lower()
    theme = next((t for t in THEME_TAXONOMY if t["name"] == theme_name), None)
    if theme:
        keywords = theme["keywords"]
    else:
        # Data-driven theme: derive keywords from theme name (e.g. Stress_Management -> stress, management)
        keywords = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", theme_name) if len(w) >= 2]
    if not keywords:
        return 0.0
    hits = [k for k in keywords if k in text_lower]
    if not hits:
        return 0.0
    return min(1.0, 0.3 + len(hits) * 0.15)


def detect_local_patterns(items):
    """
    Build local pattern stats for a folder's immediate children.
    """
    token_counter = Counter()
    ext_counter = Counter()
    year_counter = Counter()

    for item in items:
        for token in tokenize_name(item.name):
            token_counter[token] += 1

        if item.is_file():
            ext_counter[item.suffix.lower()] += 1

        year_matches = re.findall(r"(20\d{2}|19\d{2})", item.name)
        for y in year_matches:
            year_counter[y] += 1

    repeated_tokens = [tok for tok, count in token_counter.items() if count >= 2]
    repeated_years = [yr for yr, count in year_counter.items() if count >= 2]

    return {
        "token_counter": token_counter,
        "ext_counter": ext_counter,
        "year_counter": year_counter,
        "repeated_tokens": repeated_tokens[:20],
        "repeated_years": repeated_years[:20],
    }


def suggest_schema_children(context_domain: str):
    """
    Pull domain-based child folder suggestions.
    """
    return SUBFOLDER_SCHEMAS.get(context_domain, SUBFOLDER_SCHEMAS["UNKNOWN"])


def build_dynamic_children(patterns):
    """
    Generate child folder suggestions from local evidence.
    Context-first: we add folders from name/token meaning first; extension-based
    tech folders (HTML, CSS, JS, Images) only when filenames also suggest that context.
    """
    dynamic_children = []
    ext_counter = patterns.get("ext_counter", {})
    repeated_tokens = patterns.get("repeated_tokens", [])

    # ---- 1. Context from names: years and token-driven (semantic) ----
    for year in patterns.get("repeated_years", []):
        dynamic_children.append(year)

    token_map = {
        "favicon": "Images",
        "logo": "Images",
        "image": "Images",
        "photo": "Images",
        "screenshot": "Screenshots",
        "video": "Video",
        "audio": "Audio",
        "iframe": "Embeds",
        "embed": "Embeds",
        "html": "HTML",
        "css": "CSS",
        "javascript": "JavaScript",
        "script": "JavaScript",
        "style": "CSS",
        "form": "Forms",
        "template": "Templates",
        "draft": "Drafts",
        "final": "Final",
        "notes": "Notes",
        "research": "Research",
        "invoice": "Invoices",
        "receipt": "Receipts",
        "claim": "Claims",
        "insurance": "Insurance",
        "article": "Articles",
        "articles": "Articles",
        "book": "Books",
        "books": "Books",
        "agenda": "Session_Materials",
        "session": "Session_Materials",
        "practice": "Practices",
        "routine": "Routines",
        "reference": "Referenced",
        "referenced": "Referenced",
        "intake": "Intake_Forms",
        "consent": "Intake_Forms",
        "billing": "Billing_Insurance",
        "treatment": "Treatment_Notes",
        "soap": "Treatment_Notes",
        "chart": "Treatment_Notes",
        "minutes": "Notes",
        "read": "To_Read",
    }

    for token in repeated_tokens:
        if token in token_map:
            dynamic_children.append(token_map[token])

    # ---- 2. Document clusters (semantic: Documents, Reference) ----
    doc_ext_count = sum(ext_counter.get(ext, 0) for ext in [".pdf", ".doc", ".docx", ".txt", ".md"])
    if doc_ext_count >= 2:
        dynamic_children.extend(["Documents", "Reference"])

    # ---- 3. Tech / asset folders only when names suggest it (not extension alone) ----
    web_tokens = {"favicon", "iframe", "index", "logo", "assets", "embed", "script", "style", "html", "css", "javascript"}
    has_web_tokens = any(tok in web_tokens for tok in repeated_tokens)
    web_ext_count = sum(ext_counter.get(ext, 0) for ext in [".html", ".css", ".js"])
    if web_ext_count >= 2 and has_web_tokens:
        dynamic_children.extend(["HTML", "CSS", "JavaScript", "Images", "Web_Assets"])
    elif has_web_tokens:
        dynamic_children.extend(["Images", "Embeds", "Web_Assets"])

    image_tokens = {"image", "photo", "logo", "screenshot", "favicon"}
    if sum(ext_counter.get(ext, 0) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]) >= 2:
        if any(tok in image_tokens for tok in repeated_tokens) or has_web_tokens:
            dynamic_children.append("Images")
    if sum(ext_counter.get(ext, 0) for ext in [".mp4", ".mov", ".avi", ".mkv"]) >= 2:
        if "video" in repeated_tokens or has_web_tokens:
            dynamic_children.append("Video")
    if sum(ext_counter.get(ext, 0) for ext in [".mp3", ".wav", ".m4a"]) >= 2:
        if "audio" in repeated_tokens:
            dynamic_children.append("Audio")

    return sorted(set(dynamic_children))


# Guardrails for analyze_folder_structure: avoid crashes and huge output on large folders
MAX_ANALYZE_ITEMS = 200
MAX_REPEATED_TOKENS = 20
MAX_REPEATED_YEARS = 20
MAX_EXTENSION_BREAKDOWN = 20
MAX_SUGGESTED_CHILD_FOLDERS = 30


def analyze_folder_structure(folder_path):
    """
    Reusable non-UI analysis of a folder. No file moves, no UI.
    Uses existing File Steward logic: pattern detection, domain inference, suggested children.
    Limited to immediate children only; caps item count and list sizes for large folders.
    Returns a dict suitable for callers (e.g. Atria) or for further processing.
    """
    p = Path(folder_path).expanduser().resolve()
    if not p.exists():
        return {"error": f"Folder does not exist: {folder_path}"}
    if not p.is_dir():
        return {"error": f"Not a folder: {folder_path}"}

    try:
        # Immediate children only; single pass: count all but keep at most MAX_ANALYZE_ITEMS for analysis
        children = []
        total_items_seen = 0
        for item in p.iterdir():
            skip, _ = should_skip_path(item)
            if skip:
                continue
            total_items_seen += 1
            if len(children) < MAX_ANALYZE_ITEMS:
                children.append(item)

        truncated = total_items_seen > MAX_ANALYZE_ITEMS
        items_analyzed = len(children)

        file_count = sum(1 for c in children if c.is_file())
        folder_count = len(children) - file_count

        patterns = detect_local_patterns(children)
        repeated_tokens = list(patterns.get("repeated_tokens", []))[:MAX_REPEATED_TOKENS]
        repeated_years = list(patterns.get("repeated_years", []))[:MAX_REPEATED_YEARS]
        ext_counter = patterns.get("ext_counter", Counter())
        extension_breakdown = dict(ext_counter.most_common(MAX_EXTENSION_BREAKDOWN))

        inferred_context_domain = infer_context_domain(p)
        schema_children = suggest_schema_children(inferred_context_domain)
        dynamic_children = build_dynamic_children(patterns)
        suggested_child_folders = sorted(set(schema_children + dynamic_children))[:MAX_SUGGESTED_CHILD_FOLDERS]

        out = {
            "folder_path": str(p),
            "item_count": items_analyzed,
            "file_count": file_count,
            "folder_count": folder_count,
            "repeated_tokens": repeated_tokens,
            "repeated_years": repeated_years,
            "extension_breakdown": extension_breakdown,
            "inferred_context_domain": inferred_context_domain,
            "suggested_child_folders": suggested_child_folders,
        }
        if truncated:
            out["truncated"] = True
            out["total_items_seen"] = total_items_seen
            out["items_analyzed"] = items_analyzed
        return out
    except Exception as e:
        return {"error": f"Error analyzing folder: {e}"}


def simulate_folder_plan(
    folder_path,
    use_llm_second_pass: bool = False,
    ollama_url: str | None = None,
    model: str | None = None,
    allowed_folders: list[str] | None = None,
):
    """
    Non-destructive preview of how File Steward would organize a folder.
    Pass 1: deterministic classification (unchanged).
    Optional pass 2: for low-confidence / Unsorted / fallback items, uses the shared model provider (same as Atria).
    Capped at MAX_ANALYZE_ITEMS for large folders.
    If allowed_folders is provided (user-approved list), only those folders are used; any suggestion
    not in the list is mapped to "Unsorted".
    Returns dict: folder_path, inferred_context_domain, suggested_child_folders,
    proposed_assignments, blocked_items, notes.
    ollama_url/model are ignored; provider is from local_ai/providers.
    """
    p = Path(folder_path).expanduser().resolve()
    if not p.exists():
        return {"error": f"Folder does not exist: {folder_path}"}
    if not p.is_dir():
        return {"error": f"Not a folder: {folder_path}"}

    try:
        items = []
        blocked_items = []
        total_seen = 0
        for item in p.iterdir():
            skip, reason = should_skip_path(item)
            if skip:
                blocked_items.append({"item_name": item.name, "reason": reason or "skipped"})
                continue
            total_seen += 1
            if len(items) < MAX_ANALYZE_ITEMS:
                items.append(item)

        truncated = total_seen > MAX_ANALYZE_ITEMS
        notes = []
        if truncated:
            notes.append(f"Truncated at {MAX_ANALYZE_ITEMS} items (total seen: {total_seen}).")

        root = p
        context_domain = infer_context_domain(root)
        patterns = detect_local_patterns(items)
        schema_children = suggest_schema_children(context_domain)
        dynamic_children_base = build_dynamic_children(patterns)
        discovered_themes = discover_themes(items)
        theme_names = [t[0] for t in discovered_themes if t[1] >= 0.15]
        dynamic_children = dynamic_children_base + theme_names

        if allowed_folders:
            suggested_child_folders = list(allowed_folders)
            if "Unsorted" not in suggested_child_folders:
                suggested_child_folders.append("Unsorted")
            notes.append("Simulation used user-approved folder list.")
        else:
            combined = set(schema_children + dynamic_children)
            all_children = sorted(combined, key=lambda c: (c in _FOLDER_SOURCE_EXTENSION_TYPE, c))
            suggested_child_folders = all_children[:MAX_SUGGESTED_CHILD_FOLDERS]

        allowed_set = set(suggested_child_folders)
        proposed_assignments = []
        for item in items:
            try:
                suggested_child = None
                confidence = 0.0
                reason = ""
                engine = ""
                # When using user-approved list, exact name match: e.g. existing folder "logs" -> approved folder "logs"
                if allowed_folders and item.name in allowed_set:
                    suggested_child = item.name
                    confidence = 1.0
                    reason = "Exact match to approved folder"
                    engine = "allowed_folders"
                if suggested_child is None:
                    suggested_child, confidence, reason, engine = suggest_child_folder_for_item(
                        item=item,
                        context_domain=context_domain,
                        dynamic_children=dynamic_children,
                        content_sample=None,
                        theme_folders=theme_names if theme_names else None,
                    )
                    if allowed_folders and suggested_child not in allowed_set:
                        suggested_child = "Unsorted"
                proposed_assignments.append({
                    "item_name": item.name,
                    "item_type": "folder" if item.is_dir() else "file",
                    "suggested_child": suggested_child,
                    "confidence": round(confidence, 2),
                    "reason": reason,
                    "engine": engine,
                })
            except Exception as e:
                blocked_items.append({"item_name": item.name, "reason": str(e)})

        if use_llm_second_pass:
            proposed_assignments = refine_low_confidence_with_llm(
                proposed_assignments,
                inferred_context_domain=context_domain,
                suggested_child_folders=suggested_child_folders,
                repeated_tokens=patterns.get("repeated_tokens"),
                folder_context=None,
            )
            notes.append("LLM second pass was applied to low-confidence/Unsorted/fallback items.")

        return {
            "folder_path": str(p),
            "inferred_context_domain": context_domain,
            "suggested_child_folders": suggested_child_folders,
            "proposed_assignments": proposed_assignments,
            "blocked_items": blocked_items,
            "notes": notes,
        }
    except Exception as e:
        return {"error": f"Error simulating folder plan: {e}"}


# --- Internal two-level reasoning: latent buckets for flat suggestions ---
# Fixed bucket order used to build the flat list (grouped mentally, not exposed in UI).
BUCKET_ORDER = ["Work", "Writing", "Media", "Temporary", "Other"]

# Token (from repeated_tokens) -> bucket for inferring which buckets are active.
TOKEN_TO_BUCKET = {
    "clinic": "Work", "billing": "Work", "invoice": "Work", "invoices": "Work", "intake": "Work",
    "treatment": "Work", "session": "Work", "practice": "Work", "practices": "Work", "admin": "Work",
    "insurance": "Work", "soap": "Work", "chart": "Work", "receipt": "Work", "receipts": "Work",
    "claim": "Work", "claims": "Work", "routine": "Work", "routines": "Work", "training": "Work",
    "article": "Writing", "articles": "Writing", "book": "Writing", "books": "Writing",
    "research": "Writing", "notes": "Writing", "reference": "Writing", "referenced": "Writing",
    "read": "Writing", "minutes": "Writing",
    "image": "Media", "photo": "Media", "video": "Media", "audio": "Media", "screenshot": "Media",
    "screenshots": "Media", "favicon": "Media", "logo": "Media", "embed": "Media", "embeds": "Media",
    "iframe": "Media", "html": "Media", "css": "Media", "javascript": "Media", "script": "Media",
    "style": "Media", "assets": "Media",
    "draft": "Temporary", "drafts": "Temporary", "template": "Temporary", "templates": "Temporary",
    "final": "Temporary", "archive": "Temporary", "planning": "Temporary", "active": "Temporary",
    "form": "Temporary", "forms": "Temporary",
}

# File extension (lower, with dot) -> bucket for inferring from ext_counter.
EXT_TO_BUCKET = {
    ".jpg": "Media", ".jpeg": "Media", ".png": "Media", ".gif": "Media", ".webp": "Media",
    ".svg": "Media", ".mp4": "Media", ".mov": "Media", ".avi": "Media", ".mkv": "Media",
    ".mp3": "Media", ".wav": "Media", ".m4a": "Media",
    ".pdf": "Writing", ".doc": "Writing", ".docx": "Writing", ".txt": "Writing", ".md": "Writing",
    ".html": "Media", ".css": "Media", ".js": "Media",
}

# Context domain -> primary bucket when domain is known.
DOMAIN_TO_BUCKET = {
    "CLINIC": "Work", "MOVEMENT": "Work", "PERSONAL_DEVELOPMENT": "Work",
    "RESEARCH": "Writing", "MEDIA": "Media", "PROJECTS": "Temporary",
}

# Child folder name -> bucket for assign_children_to_buckets (schema + dynamic + theme names).
CHILD_NAME_TO_BUCKET = {
    "Intake_Forms": "Work", "Billing_Insurance": "Work", "Treatment_Notes": "Work",
    "Patient_Education": "Work", "Admin": "Work", "Unsorted_Clinic": "Work",
    "Session_Materials": "Work", "Practices": "Work", "Routines": "Work", "Training": "Work",
    "Invoices": "Work", "Receipts": "Work", "Claims": "Work", "Insurance": "Work",
    "Articles": "Writing", "Books": "Writing", "Notes": "Writing", "To_Read": "Writing",
    "Referenced": "Writing", "Unsorted_Research": "Writing", "Documents": "Writing",
    "Reference": "Writing", "Research": "Writing",
    "Images": "Media", "Audio": "Media", "Video": "Media", "Slides": "Media",
    "Exports": "Media", "Source_Files": "Media", "Web_Assets": "Media", "Embeds": "Media",
    "Unsorted_Media": "Media", "Screenshots": "Media", "HTML": "Media", "CSS": "Media",
    "JavaScript": "Media", "Media": "Media",
    "Active": "Temporary", "Planning": "Temporary", "Archive": "Temporary",
    "Templates": "Temporary", "Drafts": "Temporary", "Final": "Temporary",
    "Unsorted_Projects": "Temporary", "Forms": "Temporary", "Assets": "Temporary",
    "Deliverables": "Temporary",
}


def infer_latent_buckets(context_domain, patterns, theme_names, existing_children):
    """
    Infer an ordered list of latent bucket labels from context_domain, patterns,
    theme_names, and existing_children. Used internally to improve flat suggestions.
    Returns a subset of BUCKET_ORDER (so the flat list is grouped by these buckets).
    """
    buckets_seen = set()
    repeated_tokens = patterns.get("repeated_tokens") or []
    ext_counter = patterns.get("ext_counter") or {}

    if context_domain in DOMAIN_TO_BUCKET:
        buckets_seen.add(DOMAIN_TO_BUCKET[context_domain])

    for token in repeated_tokens:
        b = TOKEN_TO_BUCKET.get(token.lower())
        if b:
            buckets_seen.add(b)

    for ext, _ in ext_counter.items():
        ext_lower = ext.lower() if isinstance(ext, str) else ext
        b = EXT_TO_BUCKET.get(ext_lower)
        if b:
            buckets_seen.add(b)

    # Existing subfolders: hint Temporary if we see To Do / Projects / Drafts / Archive
    temp_hints = {"to do", "to_do", "projects", "drafts", "archive", "planning", "active"}
    for name in existing_children:
        if name and (name.lower().replace(" ", "_") in temp_hints or any(h in name.lower() for h in ("draft", "archive", "todo"))):
            buckets_seen.add("Temporary")
            break

    # Strong themes can reinforce buckets (theme name might match a child name)
    for theme in theme_names:
        if theme in CHILD_NAME_TO_BUCKET:
            buckets_seen.add(CHILD_NAME_TO_BUCKET[theme])

    if not buckets_seen:
        return list(BUCKET_ORDER)

    # Return ordered subset: only buckets we have evidence for, then Other last if any
    ordered = [b for b in BUCKET_ORDER if b in buckets_seen]
    if "Other" not in ordered:
        ordered.append("Other")
    return ordered


def assign_children_to_buckets(schema_children, dynamic_children, theme_names, bucket_labels):
    """
    Assign each candidate child (from schema, dynamic, themes) to at most one bucket.
    Returns (per_bucket, unassigned) where per_bucket is list of (bucket_label, [child_name, ...])
    in bucket_labels order, and unassigned is list of children not assigned to any bucket.
    Each child appears at most once (first matching bucket wins).
    """
    all_candidates = list(dict.fromkeys(schema_children + dynamic_children + theme_names))
    assigned = set()
    per_bucket = {b: [] for b in bucket_labels}

    for child in all_candidates:
        bucket = CHILD_NAME_TO_BUCKET.get(child)
        if bucket is None:
            bucket = "Other"
        if bucket not in per_bucket:
            per_bucket[bucket] = []
        if child not in assigned:
            per_bucket[bucket].append(child)
            assigned.add(child)

    unassigned = [c for c in all_candidates if c not in assigned]
    result = [(b, per_bucket[b]) for b in bucket_labels if per_bucket.get(b)]
    return result, unassigned


def recommend_child_folders(folder_path):
    """
    Return File Steward's recommended child folders for a path (schema + dynamic + themes).
    Same logic as the app's folder plan; no file moves.
    Capped at MAX_ANALYZE_ITEMS for large folders.
    """
    p = Path(folder_path).expanduser().resolve()
    if not p.exists():
        return {"error": f"Folder does not exist: {folder_path}"}
    if not p.is_dir():
        return {"error": f"Not a folder: {folder_path}"}

    try:
        items = []
        total_seen = 0
        for item in p.iterdir():
            skip, _ = should_skip_path(item)
            if skip:
                continue
            total_seen += 1
            if len(items) < MAX_ANALYZE_ITEMS:
                items.append(item)

        notes = []
        if total_seen > MAX_ANALYZE_ITEMS:
            notes.append(f"Truncated at {MAX_ANALYZE_ITEMS} items (total seen: {total_seen}).")

        root = p
        context_domain = infer_context_domain(root)
        patterns = detect_local_patterns(items)
        schema_children = suggest_schema_children(context_domain)
        dynamic_children_base = build_dynamic_children(patterns)
        discovered_themes = discover_themes(items)
        theme_names = [t[0] for t in discovered_themes if t[1] >= 0.15]
        dynamic_children = dynamic_children_base + theme_names

        combined = set(schema_children + dynamic_children)
        all_children = sorted(combined, key=lambda c: (c in _FOLDER_SOURCE_EXTENSION_TYPE, c))
        existing_children = {x.name for x in root.iterdir() if x.is_dir()}
        discovered_theme_set = set(theme_names)

        folder_plan_df = build_folder_plan(all_children, existing_children, discovered_theme_names=discovered_theme_set)

        # Internal two-level reasoning: latent buckets -> flat list (same API, better order/selection).
        buckets = infer_latent_buckets(context_domain, patterns, theme_names, existing_children)
        per_bucket, unassigned = assign_children_to_buckets(
            schema_children, dynamic_children, theme_names, buckets
        )
        flat_from_buckets = []
        seen = set()
        for _bucket, children in per_bucket:
            for c in children:
                if c not in seen:
                    flat_from_buckets.append(c)
                    seen.add(c)
        for c in unassigned:
            if c not in seen:
                flat_from_buckets.append(c)
                seen.add(c)
        if len(flat_from_buckets) >= 3:
            suggested_child_folders = flat_from_buckets[:MAX_SUGGESTED_CHILD_FOLDERS]
            hierarchy_proposal = {"buckets": [{"name": b, "children": cs} for b, cs in per_bucket]}
        else:
            suggested_child_folders = all_children[:MAX_SUGGESTED_CHILD_FOLDERS]
            hierarchy_proposal = None

        folder_plan = []
        if not folder_plan_df.empty:
            for _, row in folder_plan_df.iterrows():
                folder_plan.append({
                    "suggested_child": row["suggested_child"],
                    "source": row["source"],
                    "confidence": round(float(row["confidence"]), 2),
                    "exists": bool(row["exists"]),
                })

        out = {
            "folder_path": str(p),
            "inferred_context_domain": context_domain,
            "suggested_child_folders": suggested_child_folders,
            "folder_plan": folder_plan,
            "notes": notes,
        }
        if hierarchy_proposal is not None:
            out["hierarchy_proposal"] = hierarchy_proposal
        return out
    except Exception as e:
        return {"error": f"Error recommending child folders: {e}"}


# Confidence bands for assess_plan_strength
_STRENGTH_HIGH = 0.6
_STRENGTH_LOW = 0.4
_MAX_LOW_CONFIDENCE_IN_RESULT = 30
_MAX_WEAK_SUGGESTIONS = 20


def assess_plan_strength(folder_path):
    """
    Assess strength/confidence of the simulated plan for a folder.
    Uses File Steward's simulate_folder_plan and aggregates confidence.
    Returns strength summary, low-confidence assignments, weak suggestions; no file moves.
    """
    sim = simulate_folder_plan(folder_path)
    if isinstance(sim, dict) and "error" in sim:
        return sim

    try:
        assignments = sim.get("proposed_assignments", [])
        total = len(assignments)

        high_count = sum(1 for a in assignments if a.get("confidence", 0) >= _STRENGTH_HIGH)
        medium_count = sum(1 for a in assignments if _STRENGTH_LOW <= a.get("confidence", 0) < _STRENGTH_HIGH)
        low_count = sum(1 for a in assignments if a.get("confidence", 0) < _STRENGTH_LOW)

        low_confidence_assignments = sorted(
            [a for a in assignments if a.get("confidence", 0) < _STRENGTH_LOW],
            key=lambda a: a.get("confidence", 0),
        )[: _MAX_LOW_CONFIDENCE_IN_RESULT]

        # Per suggested_child: item count and average confidence
        by_child = defaultdict(list)
        for a in assignments:
            by_child[a.get("suggested_child", "Unsorted")].append(a.get("confidence", 0))

        weak_suggestions = []
        for child, confs in sorted(by_child.items()):
            avg = sum(confs) / len(confs) if confs else 0
            if len(confs) == 0 or avg < _STRENGTH_LOW:
                weak_suggestions.append({
                    "suggested_child": child,
                    "item_count": len(confs),
                    "avg_confidence": round(avg, 2),
                })
        weak_suggestions = weak_suggestions[:_MAX_WEAK_SUGGESTIONS]

        return {
            "folder_path": sim.get("folder_path", ""),
            "inferred_context_domain": sim.get("inferred_context_domain", ""),
            "strength_summary": {
                "total_assignments": total,
                "high_confidence_count": high_count,
                "medium_confidence_count": medium_count,
                "low_confidence_count": low_count,
            },
            "low_confidence_assignments": low_confidence_assignments,
            "weak_suggestions": weak_suggestions,
            "notes": sim.get("notes", []),
        }
    except Exception as e:
        return {"error": f"Error assessing plan strength: {e}"}


# =========================================================
# SECTION 13b - OPTIONAL LLM SECOND PASS (low-confidence / Unsorted only)
# =========================================================
# Non-destructive. Only items with confidence <= 0.35, suggested_child starting
# with "Unsorted", or engine "fallback" get a second pass; rest stay as-is.

SECOND_PASS_CONFIDENCE_THRESHOLD = 0.35


def _needs_second_pass(assignment: dict) -> bool:
    """True if this assignment should get an optional LLM second pass."""
    conf = assignment.get("confidence", 1.0)
    child = assignment.get("suggested_child", "")
    engine = assignment.get("engine", "")
    return (
        conf <= SECOND_PASS_CONFIDENCE_THRESHOLD
        or (child and child.startswith("Unsorted"))
        or engine == "fallback"
    )


def _get_llm_adapter():
    """Principal-based adapter (same stack as Atria). Ensures Atria root is on path when run from tools/file_steward."""
    import sys
    atria_root = Path(__file__).resolve().parent.parent.parent
    atria_root_str = str(atria_root)
    if atria_root_str not in sys.path:
        sys.path.insert(0, atria_root_str)
    from local_ai.llm.execution_principal import anonymous_account_principal
    from local_ai.llm.resolver import get_llm_adapter_for_principal

    return get_llm_adapter_for_principal(anonymous_account_principal())


def _llm_suggest_child(
    item_name: str,
    item_type: str,
    inferred_context_domain: str,
    allowed_folders: list,
    repeated_tokens: list | None = None,
    folder_context: str | None = None,
) -> dict:
    """
    Ask the shared model provider (same as Atria) for a suggested child folder for one item.
    Returns {suggested_child, confidence, reason, engine: "llm_pass2"} or {error: "..."}.
    Non-destructive; no file moves.
    """
    folders_str = ", ".join(allowed_folders[:40])
    tokens_str = ", ".join((repeated_tokens or [])[:15])
    context_str = (folder_context or "")[:200]

    prompt = f"""You are a file organization assistant. Given an item and allowed folder names, pick the best folder and give a short reason.

Item name: {item_name}
Item type: {item_type}
Context domain: {inferred_context_domain}
Repeated tokens in folder: {tokens_str or "none"}
Folder context: {context_str or "none"}

Allowed child folders (pick one): {folders_str}

Respond with exactly three lines:
LINE1: the folder name (exactly as listed)
LINE2: confidence 0.0 to 1.0 (number only)
LINE3: short reason (one line)
"""

    try:
        from local_ai.llm.adapter import LLMRequest

        adapter = _get_llm_adapter()
        text = (adapter.generate_text(LLMRequest(task="file_steward_pass2", prompt=prompt, timeout=60)) or "").strip()
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()][:3]
        suggested_child = (lines[0] or "").strip() if lines else ""
        confidence_str = (lines[1] or "0.25").strip() if len(lines) > 1 else "0.25"
        reason = (lines[2] or "LLM second pass").strip() if len(lines) > 2 else "LLM second pass"

        try:
            confidence = max(0.0, min(1.0, float(confidence_str)))
        except (ValueError, TypeError):
            confidence = 0.25

        if not suggested_child or suggested_child not in allowed_folders:
            suggested_child = next((f for f in allowed_folders if f.startswith("Unsorted")), allowed_folders[0] if allowed_folders else "Unsorted")

        return {
            "suggested_child": suggested_child,
            "confidence": round(confidence, 2),
            "reason": reason[:200],
            "engine": "llm_pass2",
        }
    except Exception as e:
        return {"error": str(e)}


def refine_low_confidence_with_llm(
    proposed_assignments: list,
    inferred_context_domain: str,
    suggested_child_folders: list,
    repeated_tokens: list | None = None,
    folder_context: str | None = None,
) -> list:
    """
    Run optional LLM second pass on assignments that need it.
    Uses the shared model provider (same as Atria).
    Returns a new list (non-destructive); low-confidence/Unsorted/fallback items
    are replaced with LLM result when successful; others are copied as-is.
    """
    allowed = list(suggested_child_folders) or ["Unsorted"]
    out = []
    for a in proposed_assignments:
        if not _needs_second_pass(a):
            out.append(dict(a))
            continue
        result = _llm_suggest_child(
            item_name=a.get("item_name", ""),
            item_type=a.get("item_type", "file"),
            inferred_context_domain=inferred_context_domain,
            allowed_folders=allowed,
            repeated_tokens=repeated_tokens,
            folder_context=folder_context,
        )
        if "error" in result:
            out.append(dict(a))
            continue
        out.append({
            "item_name": a.get("item_name", ""),
            "item_type": a.get("item_type", "file"),
            "suggested_child": result["suggested_child"],
            "confidence": result["confidence"],
            "reason": result["reason"],
            "engine": result["engine"],
        })
    return out


# =========================================================
# SECTION 14 - SUGGEST CHILD FOLDER FOR EACH ITEM
# =========================================================
# Context-first: filename and domain context outweigh extension when
# they give a clear semantic signal. Extension is used when context
# is weak or to validate that a suggested folder is compatible.
# (This app does not read file contents; context = name + folder + patterns.)

CONTEXT_MIN = 0.58  # Min confidence for context to override extension-only

# Extensions that are "compatible" with semantic/document folders (so context can win)
DOC_MEDIA_EXTS = {
    ".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".xlsx", ".csv",
    ".ppt", ".pptx", ".epub", ".mobi", ".mp3", ".wav", ".m4a",
    ".mp4", ".mov", ".avi", ".mkv", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ""
}


def _extension_compatible_with_child(ext: str, child_name: str) -> bool:
    """
    True if this file extension is a reasonable fit for the suggested child folder.
    Lets context (name-based) win over extension when e.g. "session agenda.pdf" -> Session_Materials.
    """
    ext = ext.lower()
    child = child_name.lower()
    # Tech/asset folders: only that type is compatible
    if child in ("html",):
        return ext == ".html"
    if child in ("css",):
        return ext == ".css"
    if child in ("javascript",):
        return ext == ".js"
    if child in ("images", "screenshots"):
        return ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg")
    if child in ("audio",):
        return ext in (".mp3", ".wav", ".m4a")
    if child in ("video",):
        return ext in (".mp4", ".mov", ".avi", ".mkv")
    if child in ("embeds",):
        return ext in (".html", ".js", "")
    # Semantic/document folders: any doc or media is compatible
    return ext in DOC_MEDIA_EXTS


def suggest_child_folder_for_item(
    item: Path,
    context_domain: str,
    dynamic_children: list,
    content_sample: str | None = None,
    theme_folders: list | None = None,
):
    """
    Suggest a child folder for one item.
    Context-first: theme (from folder-wide discovery), then name keywords, domain rules,
    and token patterns. Extension is used when context is weak.
    Returns:
        (child_name, confidence, reason, engine)
    """
    name = item.name.lower()
    text = name + (" " + (content_sample or "").lower()[:CONTENT_SAMPLE_MAX_CHARS])
    ext = item.suffix.lower()

    # -----------------------------------------------------
    # 1. DIRECTORY NAME ROUTING (high priority for folders)
    # -----------------------------------------------------

    if item.is_dir():
        # Do not treat default "New folder" as Archive (e.g. Windows default name)
        if name.strip().lower() in ("new folder",) or name.strip().lower().startswith("new folder ("):
            pass  # fall through to other logic
        elif any(k in name for k in ["archive", "old", "completed", "done"]):
            return "Archive", 0.75, "folder name suggests archive/completed state", "rules"
        if any(k in name for k in ["draft", "working", "current", "todo", "to do"]):
            return "Active", 0.72, "folder name suggests active work", "rules"
        if any(k in name for k in ["assets", "site", "web"]):
            return "Web_Assets", 0.72, "folder name suggests website/app asset grouping", "rules"

    # -----------------------------------------------------
    # 2. THEME MATCH (from folder-wide discovery: larger themes first)
    # -----------------------------------------------------
    if theme_folders:
        best_theme = None
        best_theme_score = 0.0
        for theme_name in theme_folders:
            if theme_name not in dynamic_children:
                continue
            score = _score_item_for_theme(text, theme_name)
            if score > best_theme_score and score >= 0.35:
                best_theme_score = score
                best_theme = theme_name
        if best_theme:
            confidence = min(0.88, 0.65 + best_theme_score * 0.2)
            return best_theme, round(confidence, 2), f"theme: {best_theme}", "theme"

    # -----------------------------------------------------
    # 3. CONTEXT FROM FILENAME: domain rules + tokens + phrases
    # -----------------------------------------------------

    domain_rules = SUBFOLDER_RULES.get(context_domain, [])
    best_rule = None
    best_rule_score = -1

    for rule in domain_rules:
        score = 0
        reasons = []

        keyword_hits = [k for k in rule["keywords"] if k in text]
        if keyword_hits:
            score += len(keyword_hits) * 2
            reasons.append(f"keyword hits: {', '.join(keyword_hits)}")

        if ext in rule["extensions"] or "" in rule["extensions"]:
            score += 1
            reasons.append(f"extension fit: {ext or '[folder]'}")

        if score > best_rule_score and keyword_hits:
            confidence = min(0.35 + score * 0.1, 0.92)
            best_rule_score = score
            best_rule = (
                rule["child"],
                round(confidence, 2),
                "; ".join(reasons) + (" (incl. content)" if content_sample else ""),
                "rules",
            )

    # Phrase-in-name hints (context beyond single tokens)
    phrase_to_child = [
        (["to read", "read later", "to look at", "look at", "queue"], "To_Read", 0.72),
        (["session agenda", "agenda", "circle agenda", "group agenda"], "Session_Materials", 0.70),
        (["session notes", "meeting notes", "minutes"], "Notes", 0.70),
        (["intake form", "new patient", "registration", "consent"], "Intake_Forms", 0.72),
        (["progress note", "soap", "treatment note", "case note"], "Treatment_Notes", 0.72),
        (["invoice", "superbill", "billing", "insurance claim"], "Billing_Insurance", 0.70),
        (["article", "journal", "paper", "study"], "Articles", 0.68),
        (["book", "ebook"], "Books", 0.68),
        (["reference", "referenced", "cited"], "Referenced", 0.66),
        (["practice", "exercise", "breath"], "Practices", 0.66),
        (["routine", "morning routine", "daily routine"], "Routines", 0.66),
        (["template", "boilerplate"], "Templates", 0.64),
    ]
    best_phrase = None
    for phrases, child_name, conf in phrase_to_child:
        if child_name not in dynamic_children:
            continue
        if any(p in text for p in phrases):
            if best_phrase is None or conf > best_phrase[1]:
                src = "name+content" if content_sample else "filename"
                best_phrase = (child_name, conf, f"{src} phrase suggests {child_name}", "phrase")

    # Token-based pattern (expanded map for context; use content when available)
    tokens = tokenize_text(text) if content_sample else tokenize_name(item.name)
    token_to_child = {
        "favicon": "Images",
        "logo": "Images",
        "image": "Images",
        "photo": "Images",
        "screenshot": "Screenshots",
        "video": "Video",
        "audio": "Audio",
        "iframe": "Embeds",
        "embed": "Embeds",
        "template": "Templates",
        "draft": "Drafts",
        "final": "Final",
        "notes": "Notes",
        "invoice": "Invoices",
        "receipt": "Receipts",
        "claim": "Claims",
        "insurance": "Insurance",
        "research": "Research",
        "article": "Articles",
        "articles": "Articles",
        "book": "Books",
        "books": "Books",
        "agenda": "Session_Materials",
        "session": "Session_Materials",
        "practice": "Practices",
        "routine": "Routines",
        "reference": "Referenced",
        "referenced": "Referenced",
        "intake": "Intake_Forms",
        "consent": "Intake_Forms",
        "billing": "Billing_Insurance",
        "treatment": "Treatment_Notes",
        "soap": "Treatment_Notes",
        "chart": "Treatment_Notes",
        "minutes": "Notes",
        "read": "To_Read",
    }
    best_token = None
    for token in tokens:
        if token in token_to_child and token_to_child[token] in dynamic_children:
            # Slightly higher confidence when token is in repeated patterns (handled via dynamic_children)
            best_token = (token_to_child[token], 0.66, f"filename token suggests: {token}", "pattern")
            break

    # Year pattern
    year_matches = re.findall(r"(20\d{2}|19\d{2})", item.name)
    best_year = None
    if year_matches and year_matches[0] in dynamic_children:
        best_year = (year_matches[0], 0.68, f"repeated year in filename: {year_matches[0]}", "pattern")

    # Pick best context candidate (rules > phrase > token > year by priority; then by confidence)
    context_candidates = []
    if best_rule:
        context_candidates.append(best_rule)
    if best_phrase:
        context_candidates.append(best_phrase)
    if best_token:
        context_candidates.append(best_token)
    if best_year:
        context_candidates.append(best_year)

    context_winner = None
    if context_candidates:
        context_winner = max(context_candidates, key=lambda c: c[1])
        if context_winner[1] >= CONTEXT_MIN and _extension_compatible_with_child(ext, context_winner[0]):
            return context_winner[0], context_winner[1], context_winner[2], context_winner[3]

    # -----------------------------------------------------
    # 3. EXTENSION-ONLY ROUTING (when context weak or incompatible)
    # -----------------------------------------------------
    # For .html/.css/.js, only treat as tech asset when the *filename* suggests
    # a technical file (index, style, script, app), not e.g. "agenda.html" or "notes.css".
    stem = Path(item.name).stem.lower()
    tech_like_stems = {"index", "default", "style", "script", "main", "app", "bundle", "vendor", "base", "config"}
    tech_like_name = stem in tech_like_stems or any(t in stem for t in ("index", "style", "script", "main", "app"))

    if ext == ".html" and tech_like_name and "HTML" in dynamic_children:
        return "HTML", 0.78, "filename suggests HTML asset", "extension"
    if ext == ".css" and tech_like_name and "CSS" in dynamic_children:
        return "CSS", 0.78, "filename suggests stylesheet asset", "extension"
    if ext == ".js" and tech_like_name and "JavaScript" in dynamic_children:
        return "JavaScript", 0.78, "filename suggests script asset", "extension"
    # .html/.css/.js with semantic names (e.g. agenda.html, notes.css) fall through to document/semantic fallback

    if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]:
        if "favicon" in name or "logo" in name:
            return "Images", 0.84, "image asset from filename and extension", "extension"
        return "Images", 0.76, "extension indicates image (no stronger context in name)", "extension"
    if ext in [".mp3", ".wav", ".m4a"]:
        return "Audio", 0.76, "extension indicates audio (no stronger context in name)", "extension"
    if ext in [".mp4", ".mov", ".avi", ".mkv"]:
        return "Video", 0.76, "extension indicates video (no stronger context in name)", "extension"

    if "iframe" in name or "embed" in name:
        return "Embeds", 0.80, "filename suggests embedded/web asset", "rules"

    # -----------------------------------------------------
    # 4. DOCUMENT FALLBACKS BY EXTENSION
    # -----------------------------------------------------
    # Includes .html/.css/.js when filename was not tech-like (e.g. agenda.html -> Documents).

    if ext in [".pdf", ".doc", ".docx", ".txt", ".md", ".html", ".css", ".js"]:
        if context_domain == "RESEARCH":
            return "Articles", 0.52, f"document/content for {ext}", "extension"
        return "Documents", 0.50, f"document/content for {ext}", "extension"

    # -----------------------------------------------------
    # 5. DOMAIN UNSORTED FALLBACK
    # -----------------------------------------------------

    fallback_map = {
        "CLINIC": "Unsorted_Clinic",
        "MEDIA": "Unsorted_Media",
        "PROJECTS": "Unsorted_Projects",
        "RESEARCH": "Unsorted_Research",
        "MOVEMENT": "Unsorted_Movement",
        "PERSONAL_DEVELOPMENT": "Unsorted_Personal_Development",
    }
    fallback_child = fallback_map.get(context_domain, "Unsorted")
    return fallback_child, 0.25, "no strong name/context match; routed to unsorted", "fallback"


# =========================================================
# SECTION 15 - ARCHITECTURE PLAN GENERATION
# =========================================================
# This creates TWO editable planning tables:
# 1. folder plan
# 2. item assignment plan

# Folders inferred mainly from file type; others are context/semantic or theme.
_FOLDER_SOURCE_EXTENSION_TYPE = {"HTML", "CSS", "JavaScript", "Images", "Web_Assets", "Embeds", "Screenshots", "Video", "Audio"}


def build_folder_plan(all_children: list, existing_children: set, discovered_theme_names: set | None = None):
    """
    Build folder-plan DataFrame.
    This is what the user can edit to rename / merge / keep / skip categories.
    Source: "theme" (from folder-wide discovered themes), "schema/pattern" (extension-type), "user", else "context".
    """
    theme_set = discovered_theme_names or set()
    rows = []

    for child in all_children:
        if child in theme_set:
            source = "theme"
        elif child in _FOLDER_SOURCE_EXTENSION_TYPE:
            source = "schema/pattern"
        else:
            source = "context"
        rows.append({
            "approve": True,
            "suggested_child": child,
            "final_child": child,
            "source": source,
            "confidence": 0.80 if child in existing_children else 0.65,
            "exists": child in existing_children,
            "create": child not in existing_children,
            "note": "",
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["exists", "suggested_child"], ascending=[False, True]).reset_index(drop=True)
    return df


def build_assignment_plan(folder_path: str, use_content_hints: bool = False):
    """
    Analyze a specific folder for child sorting.
    When use_content_hints is True, reads a short sample of non-PHI file content
    (and skips content when context_domain is CLINIC) to improve child-folder suggestions.
    Returns:
      item_df, folder_plan_df, patterns, context_domain, discovered_themes (list of (name, score))
    """
    root = Path(folder_path)

    if not root.exists() or not root.is_dir():
        return pd.DataFrame(), pd.DataFrame(), {}, "UNKNOWN", []

    context_domain = infer_context_domain(root)

    items = []
    for item in root.iterdir():
        skip, _ = should_skip_path(item)
        if not skip:
            items.append(item)

    patterns = detect_local_patterns(items)
    schema_children = suggest_schema_children(context_domain)
    dynamic_children_base = build_dynamic_children(patterns)

    # Theme discovery: infer larger themes from all names, add as child folder options
    discovered_themes = discover_themes(items)
    theme_names = [t[0] for t in discovered_themes if t[1] >= 0.15]
    dynamic_children = dynamic_children_base + theme_names

    # Semantic/context folders first; extension-type folders (HTML, CSS, etc.) last
    combined = set(schema_children + dynamic_children)
    all_children = sorted(combined, key=lambda c: (c in _FOLDER_SOURCE_EXTENSION_TYPE, c))
    existing_children = {p.name for p in root.iterdir() if p.is_dir()}
    discovered_theme_set = set(theme_names)

    folder_plan_df = build_folder_plan(all_children, existing_children, discovered_theme_names=discovered_theme_set)

    rows = []
    for item in items:
        try:
            phi_risk, phi_hits = detect_phi_risk(item)
            content_sample = ""
            if use_content_hints and item.is_file() and phi_risk != "HIGH" and context_domain != "CLINIC":
                content_sample = read_safe_content_sample(
                    item, skip_domain="CLINIC", phi_risk=phi_risk,
                )

            suggested_child, confidence, reason, engine = suggest_child_folder_for_item(
                item=item,
                context_domain=context_domain,
                dynamic_children=dynamic_children,
                content_sample=content_sample if content_sample else None,
                theme_folders=theme_names if theme_names else None,
            )

            target_path = root / suggested_child / item.name

            rows.append({
                "approve": False,
                "item_name": item.name,
                "item_path": str(item),
                "item_type": "folder" if item.is_dir() else "file",
                "parent_folder": str(root),
                "context_domain": context_domain,
                "suggested_child": suggested_child,
                "final_child": suggested_child,
                "confidence": confidence,
                "reason": reason,
                "engine": engine,
                "phi_risk": phi_risk,
                "phi_hits": phi_hits,
                "review_note": "",
                "target_path": str(target_path),
                "validation": "Not reviewed",
                "blocked_reason": "",
                "status": "Proposed",
            })

        except Exception as e:
            rows.append({
                "approve": False,
                "item_name": item.name,
                "item_path": str(item),
                "item_type": "error",
                "parent_folder": str(root),
                "context_domain": context_domain,
                "suggested_child": "Unsorted",
                "final_child": "Unsorted",
                "confidence": 0.0,
                "reason": f"explore error: {e}",
                "engine": "error",
                "phi_risk": "LOW",
                "phi_hits": "",
                "review_note": "",
                "target_path": "",
                "validation": "Blocked",
                "blocked_reason": str(e),
                "status": "Error",
            })

    item_df = pd.DataFrame(rows)
    if not item_df.empty:
        item_df = item_df.sort_values(
            ["phi_risk", "confidence", "item_name"],
            ascending=[False, False, True]
        ).reset_index(drop=True)

    return item_df, folder_plan_df, patterns, context_domain, discovered_themes


# =========================================================
# SECTION 16 - APPLY USER-EDITED FOLDER PLAN TO ASSIGNMENTS
# =========================================================
# This is how user folder-name edits propagate into item assignments.

def apply_folder_plan_to_assignments(item_df: pd.DataFrame, folder_plan_df: pd.DataFrame, explore_root: str):
    """
    Map suggested/final folder plan names into the item assignment plan.
    If the user renames a folder in the folder plan,
    all items assigned to that child get updated.
    """
    if item_df.empty:
        return item_df

    if folder_plan_df.empty:
        return item_df

    folder_map = {}

    for _, row in folder_plan_df.iterrows():
        suggested = str(row["suggested_child"]).strip()
        final_name = str(row["final_child"]).strip()

        if suggested:
            folder_map[suggested] = final_name if final_name else suggested

    updated = item_df.copy()

    updated["final_child"] = updated["suggested_child"].map(folder_map).fillna(updated["final_child"])

    root = Path(explore_root)
    updated["target_path"] = updated.apply(
        lambda r: str(root / str(r["final_child"]).strip() / r["item_name"])
        if str(r["final_child"]).strip()
        else "",
        axis=1
    )

    return updated


# =========================================================
# SECTION 17 - VALIDATE CHILD MOVES
# =========================================================

def validate_child_moves(item_df: pd.DataFrame, folder_plan_df: pd.DataFrame, explore_root: str):
    """
    Validate the edited child-folder move plan.
    """
    validated_rows = []
    root_path = Path(explore_root).resolve()

    approved_child_names = {
        str(row["final_child"]).strip()
        for _, row in folder_plan_df.iterrows()
        if bool(row["approve"]) and str(row["final_child"]).strip()
    }

    for _, row in item_df.iterrows():
        row = row.copy()
        src = Path(row["item_path"])
        target_child = str(row["final_child"]).strip()

        if not src.exists():
            row["validation"] = "Blocked"
            row["blocked_reason"] = "source no longer exists"
            row["status"] = "Blocked"
            validated_rows.append(row)
            continue

        try:
            src_resolved = src.resolve()
        except Exception:
            src_resolved = src

        if root_path not in src_resolved.parents and src_resolved != root_path:
            row["validation"] = "Blocked"
            row["blocked_reason"] = "source is outside selected explore root"
            row["status"] = "Blocked"
            validated_rows.append(row)
            continue

        if not target_child:
            row["validation"] = "Blocked"
            row["blocked_reason"] = "final child folder is blank"
            row["status"] = "Blocked"
            validated_rows.append(row)
            continue

        if target_child not in approved_child_names:
            row["validation"] = "Blocked"
            row["blocked_reason"] = "target child folder is not approved in folder plan"
            row["status"] = "Blocked"
            validated_rows.append(row)
            continue

        if any(sep in target_child for sep in ["\\", "/"]):
            row["validation"] = "Blocked"
            row["blocked_reason"] = "target child must be a single folder name"
            row["status"] = "Blocked"
            validated_rows.append(row)
            continue

        dest_dir = root_path / target_child
        proposed_dest = dest_dir / src.name
        row["target_path"] = str(proposed_dest)

        if src.parent.resolve() == dest_dir.resolve():
            row["validation"] = "Blocked"
            row["blocked_reason"] = "already in target child folder"
            row["status"] = "Blocked"
            validated_rows.append(row)
            continue

        if proposed_dest.exists():
            row["validation"] = "Blocked"
            row["blocked_reason"] = "destination already exists"
            row["status"] = "Blocked"
            validated_rows.append(row)
            continue

        if row["context_domain"] == "CLINIC" and row["phi_risk"] == "HIGH" and not row["approve"]:
            row["validation"] = "Sensitive Review Required"
            row["blocked_reason"] = "possible PHI: manual approval required"
            row["status"] = "Sensitive Review Required"
            validated_rows.append(row)
            continue

        row["validation"] = "Valid"
        row["blocked_reason"] = ""
        row["status"] = "Ready" if row["approve"] else "Proposed"
        validated_rows.append(row)

    return pd.DataFrame(validated_rows)


# =========================================================
# SECTION 18 - EXECUTE CHILD MOVES
# =========================================================

def execute_child_moves(item_df: pd.DataFrame, folder_plan_df: pd.DataFrame, explore_root: str):
    """
    Execute only approved valid child-folder moves.
    """
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"move_batch_{batch_id}.json"

    validated_df = validate_child_moves(item_df, folder_plan_df, explore_root)
    approved_valid = validated_df[
        (validated_df["approve"] == True) &
        (validated_df["validation"] == "Valid")
    ].copy()

    moves = []
    blocked = []

    for _, row in approved_valid.iterrows():
        src = Path(row["item_path"])
        dest = Path(row["target_path"])

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))

            moves.append({
                "batch_id": batch_id,
                "timestamp": datetime.now().isoformat(),
                "action": "move",
                "move_type": "child_sort",
                "approved": True,
                "src": str(src),
                "dest": str(dest),
                "name": row["item_name"],
                "type": row["item_type"],
                "context_domain": row["context_domain"],
                "target_child": row["final_child"],
                "engine": row["engine"],
                "confidence": float(row["confidence"]),
                "phi_risk": row["phi_risk"],
                "phi_hits": row["phi_hits"],
                "review_note": row["review_note"],
                "status": "executed",
            })
        except Exception as e:
            blocked.append({
                "name": row["item_name"],
                "reason": str(e),
            })

    payload = {
        "batch_id": batch_id,
        "created_at": datetime.now().isoformat(),
        "move_type": "child_sort",
        "move_count": len(moves),
        "blocked_count": len(blocked),
        "moves": moves,
        "blocked": blocked,
    }

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return log_path, len(moves), blocked, validated_df


# =========================================================
# SECTION 19 - SIMULATED FINAL TREE
# =========================================================
# This gives the user a readable preview of the final edited structure.

def build_simulated_tree(item_df: pd.DataFrame, folder_plan_df: pd.DataFrame):
    """
    Build a dict:
      {folder_name: [item1, item2, ...]}
    from approved folder plan + current item assignments.
    """
    tree = defaultdict(list)

    approved_folders = {
        str(row["final_child"]).strip()
        for _, row in folder_plan_df.iterrows()
        if bool(row["approve"]) and str(row["final_child"]).strip()
    }

    for _, row in item_df.iterrows():
        folder_name = str(row["final_child"]).strip()
        if folder_name in approved_folders:
            tree[folder_name].append({
                "item_name": row["item_name"],
                "item_type": row["item_type"],
                "approve": row["approve"],
                "confidence": row["confidence"],
                "validation": row["validation"],
            })

    # Sort tree entries alphabetically by folder, then by item name
    sorted_tree = {}
    for folder_name in sorted(tree.keys()):
        sorted_tree[folder_name] = sorted(tree[folder_name], key=lambda x: x["item_name"].lower())

    return sorted_tree


# =========================================================
# SECTION 20 - STREAMLIT UI: SIDEBAR + TABS
# =========================================================

# Initialize path session state once (uses smart defaults)
_smart_paths = get_smart_default_paths()
_default_scan = _smart_paths.get("07_ARCHIVE") or _smart_paths.get("OneDrive Desktop") or _smart_paths.get("Desktop") or ""
if "scan_root" not in st.session_state:
    st.session_state["scan_root"] = _default_scan
if "domain_root" not in st.session_state:
    st.session_state["domain_root"] = _default_scan
if "explore_root" not in st.session_state:
    _exp = (_smart_paths.get("07_ARCHIVE") and os.path.join(_smart_paths["07_ARCHIVE"], "PROJECTS")) or _default_scan
    st.session_state["explore_root"] = _exp
if "stale_root" not in st.session_state:
    st.session_state["stale_root"] = _smart_paths.get("OneDrive") or _default_scan
if "organize_root" not in st.session_state:
    st.session_state["organize_root"] = _default_scan
if "find_subsort_root" not in st.session_state:
    st.session_state["find_subsort_root"] = _default_scan

# Sidebar: quick folder access and recent roots
with st.sidebar:
    if "use_content_hints" not in st.session_state:
        st.session_state["use_content_hints"] = False
    use_content_hints = st.checkbox(
        "Use file content hints (non-PHI, skips Clinic)",
        value=st.session_state["use_content_hints"],
        key="use_content_hints_cb",
        help="Read a short sample of .txt, .md, .csv (and .pdf if pypdf/PyPDF2 installed) to improve suggestions. Never used for PHI or Clinic.",
    )
    st.session_state["use_content_hints"] = use_content_hints

    st.subheader("Quick paths")
    for label, path in _smart_paths.items():
        if not path or not os.path.isdir(path):
            continue
        st.caption(label)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Scan", key=f"sb_scan_{label}", help=f"Set as folder to scan: {path}"):
                st.session_state["scan_root"] = path
                st.session_state["domain_root"] = path
                st.session_state["organize_root_requested"] = path
                st.rerun()
        with c2:
            if st.button("Organize", key=f"sb_organize_{label}", help=f"Set as folder to organize: {path}"):
                st.session_state["organize_root_requested"] = path
                for key in ("sub_item_df", "sub_folder_plan_df", "sub_patterns", "sub_context_domain", "sub_themes"):
                    st.session_state.pop(key, None)
                st.rerun()
    st.divider()
    recent = load_recent_roots()
    if recent:
        st.subheader("Recent roots")
        for p in recent[:5]:
            disp = p if len(p) <= 40 else "..." + p[-37:]
            if st.button(disp, key=f"recent_{hash(p) % 10**6}", help=p):
                st.session_state["scan_root"] = p
                st.session_state["domain_root"] = p
                st.session_state["organize_root_requested"] = p
                st.rerun()

tab0, tab1, tab2, tab3, tab4 = st.tabs([
    "Organize", "Scan", "Stale Files", "Undo", "Find to Subsort",
])

# Apply requested organize path before any widget uses key="organize_root"
if "organize_root_requested" in st.session_state:
    st.session_state["organize_root"] = st.session_state.pop("organize_root_requested")


# =========================================================
# SECTION 20.5 - TAB 0: ORGANIZE (nested sort, one level at a time)
# =========================================================

with tab0:
    st.subheader("Organize: sort one level at a time")
    st.caption("Pick a folder, sort its contents into subfolders, then sort any subfolder the same way to build a tree.")

    or_col1, or_col2 = st.columns([4, 1])
    with or_col1:
        organize_root = st.text_input(
            "Folder to organize",
            key="organize_root",
            placeholder="C:\\Users\\...\\Desktop",
            label_visibility="collapsed",
        )
    with or_col2:
        if st.button("Browse…", key="browse_organize", help="Select folder in Explorer"):
            path = open_folder_picker("Select folder to organize")
            if path:
                st.session_state["organize_root_requested"] = path
                st.session_state["scan_root"] = path
                st.session_state["domain_root"] = path
                for key in ("sub_item_df", "sub_folder_plan_df", "sub_patterns", "sub_context_domain", "sub_themes"):
                    st.session_state.pop(key, None)
                st.rerun()

    if not organize_root:
        st.info("Enter a path above or click **Browse…** to pick a folder.")
    else:
        save_recent_root(organize_root)
        org_path = Path(organize_root)

        # Breadcrumb: current folder + optional Parent
        if org_path.exists():
            try:
                parent = org_path.resolve().parent
                if str(parent) != str(org_path.resolve()):
                    if st.button("↑ Parent folder", key="org_parent_btn"):
                        st.session_state["organize_root_requested"] = str(parent)
                        for key in ("sub_item_df", "sub_folder_plan_df", "sub_patterns", "sub_context_domain", "sub_themes"):
                            st.session_state.pop(key, None)
                        st.rerun()
            except Exception:
                pass
        st.caption(f"**Current folder:** `{organize_root}`")

        # ---- Single flow: Analyze → Folder plan + Item assignments → Execute ----
        # Optional LLM second pass: refine_low_confidence_with_llm(assignments, ...) or simulate_folder_plan(..., use_llm_second_pass=True)
        st.markdown("### Sort this folder (one level)")
        os1, os2, os3 = st.columns(3)
        with os1:
            if st.button("Analyze folder", key="org_analyze_btn"):
                item_df, folder_plan_df, patterns, context_domain, themes = build_assignment_plan(
                    organize_root, use_content_hints=st.session_state.get("use_content_hints", False),
                )
                st.session_state["sub_item_df"] = item_df
                st.session_state["sub_folder_plan_df"] = folder_plan_df
                st.session_state["sub_patterns"] = patterns
                st.session_state["sub_context_domain"] = context_domain
                st.session_state["sub_themes"] = themes
                st.rerun()
        with os2:
            if st.button("Validate plan", key="org_validate_sub_btn"):
                if "sub_item_df" in st.session_state and "sub_folder_plan_df" in st.session_state:
                    up = apply_folder_plan_to_assignments(st.session_state["sub_item_df"], st.session_state["sub_folder_plan_df"], organize_root)
                    st.session_state["sub_item_df"] = validate_child_moves(up, st.session_state["sub_folder_plan_df"], organize_root)
                st.rerun()
        with os3:
            if st.button("Clear", key="org_clear_sub_btn"):
                st.session_state.pop("sub_item_df", None)
                st.session_state.pop("sub_folder_plan_df", None)
                st.session_state.pop("sub_patterns", None)
                st.session_state.pop("sub_context_domain", None)
                st.session_state.pop("sub_themes", None)
                st.rerun()

        if "sub_item_df" in st.session_state and "sub_folder_plan_df" in st.session_state:
            o_item_df = st.session_state["sub_item_df"].copy()
            o_folder_plan_df = st.session_state["sub_folder_plan_df"].copy()
            st.info(f"Context: {st.session_state.get('sub_context_domain', 'UNKNOWN')}")

            themes = st.session_state.get("sub_themes", [])
            if themes:
                with st.expander("Discovered themes", expanded=True):
                    for theme_name, score in themes:
                        st.write(f"**{theme_name}** — {score}")

            st.markdown("**Folder plan**")
            visible_cols = ["approve", "suggested_child", "final_child", "exists", "create", "note"]
            o_edited_fp = st.data_editor(o_folder_plan_df[visible_cols], use_container_width=True, num_rows="fixed", hide_index=True, key="org_fp_editor")
            for col in visible_cols:
                o_folder_plan_df[col] = o_edited_fp[col].values
            o_folder_plan_df["exists"] = o_folder_plan_df["final_child"].astype(str).isin({p.name for p in org_path.iterdir() if p.is_dir()}) if org_path.exists() else False
            o_folder_plan_df["create"] = ~o_folder_plan_df["exists"]
            st.session_state["sub_folder_plan_df"] = o_folder_plan_df

            # Allow user to add a folder to the proposed buildout
            add_col1, add_col2 = st.columns([2, 1])
            with add_col1:
                new_folder_name = st.text_input("Add folder to plan", key="org_new_folder", placeholder="e.g. My_Projects or To Review")
            with add_col2:
                st.write("")  # align button with input
                if st.button("Add folder", key="org_add_folder"):
                    raw = (new_folder_name or "").strip()
                    if raw:
                        # Normalize to safe folder name: spaces -> _, remove path chars
                        safe = re.sub(r"[\s]+", "_", raw)
                        safe = re.sub(r'[<>:"/\\|?*]', "", safe).strip("._ ")
                        if safe:
                            existing = set(o_folder_plan_df["final_child"].astype(str).str.strip())
                            if safe not in existing:
                                new_row = {
                                    "approve": True,
                                    "suggested_child": safe,
                                    "final_child": safe,
                                    "source": "user",
                                    "confidence": 0.90,
                                    "exists": (org_path / safe).is_dir() if org_path.exists() else False,
                                    "create": not ((org_path / safe).is_dir() if org_path.exists() else False),
                                    "note": "",
                                }
                                o_folder_plan_df = pd.concat([o_folder_plan_df, pd.DataFrame([new_row])], ignore_index=True)
                                st.session_state["sub_folder_plan_df"] = o_folder_plan_df
                                st.rerun()
                            else:
                                st.warning(f"Folder «{safe}» is already in the plan.")
                        else:
                            st.warning("Enter a valid folder name.")
                    else:
                        st.warning("Enter a folder name.")

            o_folder_plan_df = st.session_state["sub_folder_plan_df"]
            o_item_df = apply_folder_plan_to_assignments(o_item_df, o_folder_plan_df, organize_root)
            target_opts = sorted({str(v).strip() for v in o_folder_plan_df["final_child"].dropna().astype(str) if str(v).strip()})
            st.markdown("**Item assignments**")
            o_edited_items = st.data_editor(o_item_df[["approve", "item_name", "item_type", "final_child", "confidence", "reason", "phi_risk", "validation", "blocked_reason"]], use_container_width=True, num_rows="fixed", hide_index=True, column_config={"approve": st.column_config.CheckboxColumn("Approve"), "final_child": st.column_config.SelectboxColumn("Final Child", options=target_opts), "confidence": st.column_config.NumberColumn("Confidence", format="%.2f")}, key="org_items_editor")
            o_item_df.loc[o_item_df.index, "approve"] = o_edited_items["approve"].values
            o_item_df.loc[o_item_df.index, "final_child"] = o_edited_items["final_child"].values
            o_item_df["target_path"] = o_item_df.apply(lambda r: str(org_path / str(r["final_child"]).strip() / r["item_name"]) if str(r["final_child"]).strip() else "", axis=1)
            st.session_state["sub_item_df"] = validate_child_moves(o_item_df, o_folder_plan_df, organize_root)
            o_item_df = st.session_state["sub_item_df"]
            if st.checkbox("I have reviewed; execute approved moves", key="org_confirm_sub"):
                if st.button("Execute", key="org_exec_sub"):
                    _, moved, blocked, _ = execute_child_moves(o_item_df, o_folder_plan_df, organize_root)
                    st.success(f"Moved {moved} items.") if moved else st.warning("No moves executed.")
                    if blocked:
                        st.warning(f"Blocked: {len(blocked)}")
                    st.rerun()

        # ---- Subfolders: sort one level deeper ----
        if org_path.exists() and org_path.is_dir():
            subdirs = [p for p in org_path.iterdir() if p.is_dir() and not should_skip_path(p)[0]]
            if subdirs:
                st.markdown("### Subfolders — sort one level deeper")
                st.caption("Choose a subfolder to run the same sort inside it (one level at a time).")
                for sub in sorted(subdirs, key=lambda p: p.name.lower()):
                    with st.container():
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.text(sub.name)
                        with c2:
                            if st.button("Sort this subfolder", key=f"org_drill_{hash(sub) % 10**8}"):
                                st.session_state["organize_root_requested"] = str(sub)
                                for key in ("sub_item_df", "sub_folder_plan_df", "sub_patterns", "sub_context_domain", "sub_themes"):
                                    st.session_state.pop(key, None)
                                st.rerun()


# =========================================================
# SECTION 21 - TAB 1: TOP-LEVEL SCAN
# =========================================================

with tab1:
    st.subheader("Scan and Review")

    sr_col1, sr_col2 = st.columns([4, 1])
    with sr_col1:
        root = st.text_input("Folder to scan", key="scan_root", placeholder="C:\\Users\\...\\Desktop")
    with sr_col2:
        if st.button("Browse…", key="browse_scan", help="Select folder in Explorer"):
            path = open_folder_picker("Select folder to scan")
            if path:
                st.session_state["scan_root"] = path
                st.session_state["domain_root"] = path
                st.rerun()
    domain_root = st.text_input("Destination root", key="domain_root", placeholder="Same or parent folder for domain subfolders")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Scan Folder"):
            st.session_state["scan_df"] = scan_top_level(
                root, use_content_hints=st.session_state.get("use_content_hints", False),
            )
            if root:
                save_recent_root(root)

    with col2:
        if st.button("Validate Proposed Moves"):
            if "scan_df" in st.session_state and not st.session_state["scan_df"].empty:
                st.session_state["scan_df"] = validate_moves(st.session_state["scan_df"], root, domain_root)

    with col3:
        if st.button("Clear Scan"):
            st.session_state.pop("scan_df", None)

    if "scan_df" in st.session_state:
        df = st.session_state["scan_df"].copy()
        st.write(f"Items found: {len(df)}")

        if not df.empty:
            # Bulk approve by confidence (non-PHI only for safety)
            with st.expander("Bulk approve", expanded=False):
                bc1, bc2, bc3 = st.columns(3)
                with bc1:
                    if st.button("Approve all with confidence ≥ 0.80", key="bulk_scan_80"):
                        idx = (df["confidence"] >= 0.80) & (df["phi_risk"] != "HIGH") & (df["target_domain"].isin(ALLOWED_DOMAINS))
                        df.loc[idx, "approve"] = True
                        df = validate_moves(df, root, domain_root)
                        st.session_state["scan_df"] = df
                        st.rerun()
                with bc2:
                    if st.button("Approve all with confidence ≥ 0.70", key="bulk_scan_70"):
                        idx = (df["confidence"] >= 0.70) & (df["phi_risk"] != "HIGH") & (df["target_domain"].isin(ALLOWED_DOMAINS))
                        df.loc[idx, "approve"] = True
                        df = validate_moves(df, root, domain_root)
                        st.session_state["scan_df"] = df
                        st.rerun()
                with bc3:
                    if st.button("Clear all approvals", key="bulk_scan_clear"):
                        df["approve"] = False
                        df = validate_moves(df, root, domain_root)
                        st.session_state["scan_df"] = df
                        st.rerun()

            show_only_blocked = st.checkbox("Show only blocked", key="scan_blocked")
            show_only_approved = st.checkbox("Show only approved", key="scan_approved")
            low_conf_only = st.checkbox("Show confidence < 0.70", key="scan_low_conf")
            show_phi_only = st.checkbox("Show PHI-risk only", key="scan_phi")

            display_df = df.copy()

            if show_only_blocked:
                display_df = display_df[display_df["validation"] == "Blocked"]
            if show_only_approved:
                display_df = display_df[display_df["approve"] == True]
            if low_conf_only:
                display_df = display_df[display_df["confidence"] < 0.70]
            if show_phi_only:
                display_df = display_df[display_df["phi_risk"] == "HIGH"]

            edited = st.data_editor(
                display_df[[
                    "approve", "name", "type", "files", "size_mb",
                    "suggested_domain", "target_domain", "confidence",
                    "rule_name", "reason", "phi_risk", "phi_hits",
                    "review_note", "validation", "blocked_reason"
                ]],
                use_container_width=True,
                num_rows="fixed",
                hide_index=True,
                column_config={
                    "approve": st.column_config.CheckboxColumn("Approve"),
                    "target_domain": st.column_config.SelectboxColumn("Target Domain", options=ALLOWED_DOMAINS),
                    "confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
                    "reason": st.column_config.TextColumn("Reason", width="large"),
                    "phi_hits": st.column_config.TextColumn("PHI Hits", width="medium"),
                    "review_note": st.column_config.TextColumn("Review Note", width="medium"),
                    "blocked_reason": st.column_config.TextColumn("Blocked Reason", width="large"),
                },
                key="review_editor",
            )

            merged_df = df.copy()
            merged_df.loc[display_df.index, "approve"] = edited["approve"].values
            merged_df.loc[display_df.index, "target_domain"] = edited["target_domain"].values
            merged_df.loc[display_df.index, "review_note"] = edited["review_note"].values

            merged_df = validate_moves(merged_df, root, domain_root)
            st.session_state["scan_df"] = merged_df

            approved_count = int(merged_df["approve"].sum())
            valid_count = int(((merged_df["approve"] == True) & (merged_df["validation"] == "Valid")).sum())
            blocked_count = int((merged_df["validation"] == "Blocked").sum())
            phi_count = int((merged_df["phi_risk"] == "HIGH").sum())

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Approved", approved_count)
            c2.metric("Approved + Valid", valid_count)
            c3.metric("Blocked", blocked_count)
            c4.metric("PHI Risk", phi_count)

            preview_df = merged_df[(merged_df["approve"] == True)][[
                "name", "type", "target_domain", "phi_risk",
                "proposed_dest", "validation", "blocked_reason"
            ]]

            with st.expander("Approved move preview", expanded=True):
                if preview_df.empty:
                    st.info("No approved items yet.")
                else:
                    st.dataframe(preview_df, use_container_width=True, hide_index=True)

            confirm_execute = st.checkbox(
                "I have reviewed the approved items and want to execute only approved valid moves locally",
                key="scan_confirm"
            )

            if st.button("Execute Approved Valid Moves", disabled=not confirm_execute):
                log_path, moved_count, blocked, validated_df = execute_moves(merged_df, root, domain_root)
                st.session_state["scan_df"] = validated_df

                if moved_count > 0:
                    st.success(f"Moved {moved_count} items. Log saved to {log_path}")
                else:
                    st.warning("No approved valid moves were executed.")

                if blocked:
                    st.warning(f"{len(blocked)} move attempts were blocked.")
                    st.dataframe(pd.DataFrame(blocked), use_container_width=True, hide_index=True)


# =========================================================
# SECTION 22 - TAB 2: STALE FILES
# =========================================================

with tab2:
    st.subheader("Stale File Report")

    st_col1, st_col2 = st.columns([4, 1])
    with st_col1:
        stale_root = st.text_input("Folder for stale report", key="stale_root", placeholder="C:\\Users\\...\\OneDrive")
    with st_col2:
        if st.button("Browse…", key="browse_stale", help="Select folder in Explorer"):
            path = open_folder_picker("Select folder for stale report")
            if path:
                st.session_state["stale_root"] = path
                st.rerun()
    stale_days = st.slider("Days since last modified", 30, 365, 90)

    if st.button("Generate Stale File Report"):
        st.session_state["stale_df"] = stale_files(stale_root, stale_days)

    if "stale_df" in st.session_state:
        if not st.session_state["stale_df"].empty:
            st.dataframe(st.session_state["stale_df"], use_container_width=True, hide_index=True)

            if st.button("Save Stale Report CSV"):
                report_name = LOG_DIR / f"stale_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                st.session_state["stale_df"].to_csv(report_name, index=False)
                st.success(f"CSV report saved to {report_name}")
        else:
            st.info("No stale files found.")


# =========================================================
# SECTION 23 - TAB 3: UNDO
# =========================================================

with tab3:
    st.subheader("Undo")

    batches = list_batches()

    if not batches:
        st.info("No move batches found.")
    else:
        batch_names = [b.name for b in batches]
        selected_name = st.selectbox("Choose batch to undo", batch_names)
        selected_batch = next(b for b in batches if b.name == selected_name)

        with open(selected_batch, "r", encoding="utf-8") as f:
            payload = json.load(f)

        move_rows = payload.get("moves", [])
        move_type = payload.get("move_type", "unknown")

        st.write(f"Move type: {move_type}")
        st.write(f"Moves in batch: {len(move_rows)}")

        if move_rows:
            st.dataframe(pd.DataFrame(move_rows), use_container_width=True, hide_index=True)

        if st.button("Undo Selected Batch"):
            restored, blocked = undo_batch(selected_batch)

            if restored:
                st.success(f"Restored {restored} items from {selected_batch.name}")

            if blocked:
                st.warning(f"{len(blocked)} items could not be restored.")
                st.dataframe(pd.DataFrame(blocked), use_container_width=True, hide_index=True)


# =========================================================
# SECTION 24 - TAB 4: FIND FOLDERS TO SUBSORT (helper: sets Organize path)
# =========================================================
# Discovers subfolders that are good candidates to organize (many items / mixed types).
# Sets the chosen folder as the Organize path so you can sort it in the Organize tab.

with tab4:
    st.subheader("Find folders to organize")
    st.caption(
        "Pick a parent folder. Subfolders with many items or mixed file types "
        "are suggested. Choose one to set as the folder to sort in **Organize**."
    )

    fi_col1, fi_col2 = st.columns([4, 1])
    with fi_col1:
        find_parent = st.text_input(
            "Parent folder to scan",
            key="find_subsort_root",
            placeholder="C:\\Users\\...\\Desktop",
        )
    with fi_col2:
        if st.button("Browse…", key="browse_find", help="Select folder in Explorer"):
            path = open_folder_picker("Select parent folder")
            if path:
                st.session_state["find_subsort_root"] = path
                st.rerun()
    min_items = st.slider("Min items to suggest", 3, 30, 5, key="find_min_items")

    if st.button("Find subfolders to subsort"):
        st.session_state["subsort_candidates_df"] = find_folders_to_subsort(find_parent, min_items=min_items)

    if "subsort_candidates_df" in st.session_state:
        cand_df = st.session_state["subsort_candidates_df"]
        if cand_df.empty:
            st.info("No subfolders found, or none meet the threshold.")
        else:
            st.dataframe(
                cand_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "path": st.column_config.TextColumn("Path", width="large"),
                    "suggested": st.column_config.CheckboxColumn("Suggested", disabled=True),
                },
            )
            choices = [f"{row['name']} ({row['item_count']} items, {row['extension_count']} types)" for _, row in cand_df.iterrows()]
            path_by_idx = cand_df["path"].tolist()
            chosen = st.selectbox("Use folder in Organize", range(len(choices)), format_func=lambda i: choices[i], key="subsort_choice")
            if st.button("Set as Organize folder", key="set_organize_from_find"):
                st.session_state["organize_root_requested"] = path_by_idx[chosen]
                for key in ("sub_item_df", "sub_folder_plan_df", "sub_patterns", "sub_context_domain", "sub_themes"):
                    st.session_state.pop(key, None)
                st.success(f"Folder set. Switch to **Organize** tab to sort it.")
                st.rerun()