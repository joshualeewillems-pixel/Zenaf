"""
Heuristic: filesystem basenames that read like course / journal / promo titles,
not structural workspace identity. Used by snapshot scan and buffer filters.

**How much is “your tree” vs “any user”?**
Roughly: **half structural, half vocabulary.** Rules that generalize across roles include
multi‑word length/title shape, spaced hyphens in sentence-like names, mixed SHOUT/lowercase,
punctuation (``;``, em dash), non-code document extensions, and “two words ending in
solutions/project/…” with a **small tech first-token allowlist**. Those help engineers and
designers when their scan roots accidentally include Downloads or personal folders.

The long **starter word list** and many phrase regexes are **defensive tuning** for
coaching/wellness/personal-desktop naming. They will **not** port cleanly to every domain:
graphic designers may use legitimate title-case client folders that look “marketingy”;
engineers may use ``… solutions`` or ``… project`` in real repo paths (we only exempt a
few tech heads). Celebrity/person names and one-off typos do **not** belong here; new
noise is better fixed by **narrowing scan roots** or a future **preset** (e.g. code-only
surfaces) than by endless string lists.

**Operational default:** point workspace scan at the repo (and maybe one docs root), not
whole Desktop—then the mirror stays identity-shaped without chasing every folder title.
"""

from __future__ import annotations

import re

# First token: skip "healing" here so multi-word org names like "Riverbend Healing Clinic" stay
# (use other rules for generic "Frequency healing"-style titles).
_PROMO_OR_COURSE_START_RE = re.compile(
    r"(?i)^(promoting|branding|motivating|outline|pledge|remove|easy\s+launch|holistic|awareness|global|globel|electro|elecgtro|ulan|cttp|aaa|acupuncture|coherence|positive|challenge|walking|hypnotic|awakening|intention|raikov|abdominal|lance|meeditation|moaquito|mosquito|comunity|frequency)\b"
)

# Two-word …solutions / …project / …class etc.; exempt common tech first tokens.
_TECH_FIRST_TOKEN_LOWER: frozenset[str] = frozenset(
    {
        "api",
        "sdk",
        "aws",
        "gcp",
        "sql",
        "cdn",
        "dns",
        "cli",
        "git",
        "npm",
        "csv",
        "json",
        "xml",
        "yaml",
        "node",
        "react",
        "vue",
        "java",
        "rust",
        "go",
        "db",
        "ui",
        "ux",
        "io",
        "s3",
        "gcs",
        "vpc",
        "tcp",
        "udp",
        "http",
        "ssl",
        "tls",
    }
)

_COURSEY_TWO_WORD_TAIL_RE = re.compile(
    r"(?i)\b(solutions|material|music|books|class|project|words|thinking|technique|outreach|massage|healing|secrets?|secretes?)\s*$"
)

# e.g. Raikov-Af Technique — rare in repo paths, common in course folders.
_HYPHEN_THEN_TITLECASE_RE = re.compile(r"(?i)[a-z]-[A-Z][a-z]{0,6}(\s|$)")

_EVENT_OR_SALES_PHRASE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(symposium|summit)s?\b"),
    re.compile(r"(?i)\blanding\s+page\b"),
    re.compile(r"(?i)^(book|law)\s+of\s+\S"),
    re.compile(r"(?i)^writing\s+the\s+\S"),
    re.compile(r"(?i)\bai\s+(book|summit|notes)\b"),
    re.compile(r"(?i)\bbenefits\s*$"),
    re.compile(r"(?i)^a\s+\w{3,}\s+(day|night|life|time|way|year)\s*$"),
    re.compile(r"(?i)(^|\s)20\d{2}\s*$"),
)


def _clean_words(n: str) -> list[str]:
    """Split on whitespace after normalizing ';' (and similar) to spaces; trim punctuation."""
    s = re.sub(r"[;]", " ", n)
    s = re.sub(r"[,/\\]", " ", s)
    raw = [w for w in s.split() if w]
    out: list[str] = []
    for w in raw:
        t = w.strip(" \t.-–—,;:!?\"'()[]_")
        if t:
            out.append(t)
    return out


def _title_case_word(w: str) -> bool:
    al = "".join(c for c in w if c.isalpha())
    if len(al) < 3:
        return False
    return al[0].isupper() and al[1:].islower()


def _mostly_upper_word(w: str) -> bool:
    letters = [c for c in w if c.isalpha()]
    if len(letters) < 4:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.85


def _mostly_lower_word(w: str) -> bool:
    letters = [c for c in w if c.isalpha()]
    if len(letters) < 4:
        return False
    return sum(1 for c in letters if c.islower()) / len(letters) >= 0.85


def mirror_basename_looks_like_prose_title(text: str) -> bool:
    """True when a folder name or file stem looks like prose (Desktop notes, courses)."""
    n = (text or "").strip()
    if len(n) < 10:
        return False
    low = n.casefold()
    if _PROMO_OR_COURSE_START_RE.match(n):
        return True
    for pat in _EVENT_OR_SALES_PHRASE_RES:
        if pat.search(n):
            return True
    words = _clean_words(n)
    if re.search(r"(?i)\s+AI\s*$", n) and len(words) >= 3 and len(n) > 12:
        return True
    # Course-style "Raikov-Af Technique" has a space; pure "Healing-Haven-Clinic" must not match.
    if " " in n and _HYPHEN_THEN_TITLECASE_RE.search(n) and len(n) > 12:
        return True
    if (
        len(words) == 2
        and _COURSEY_TWO_WORD_TAIL_RE.search(n)
        and words[0].lower() not in _TECH_FIRST_TOKEN_LOWER
    ):
        return True
    if low.startswith("copy of ") or low.startswith("copy_of_"):
        return True
    if " — " in n or " – " in n:
        return True
    if "[" in n and "]" in n:
        return True
    if ";" in n:
        return True
    if re.match(r"^\d{1,2}\s+\S", n):
        return True
    if re.match(r"^\d{4}\s+\S", n):
        return True
    if re.match(r"(?i)^a\s+[a-z]{3,}\s+\d", n):
        return True
    if "," in n and len(n) > 22 and " " in n:
        return True
    if " from " in low and len(n) > 16:
        return True
    if re.search(r"\b(my|our|your)\s+[a-z]{3,}", low) and len(n) > 22:
        return True
    if re.search(r"\bwith\s+[A-Z][a-z]", n) and len(n) > 14:
        return True
    if re.search(r"\s[-–—]|[-–—]\s", n) and len(n) > 14:
        return True
    if len(re.findall(r"[-–—]", n)) >= 2 and " " in n and len(n) > 14:
        return True
    if len(words) >= 6:
        return True
    if len(words) >= 5 and len(n) >= 18:
        return True
    if len(words) >= 4 and len(n) >= 16:
        return True
    # Three-word titles: long enough to miss short org-style names (e.g. three-word clinic names ~20 chars).
    if len(words) >= 3 and len(n) >= 22:
        return True
    letters = [c for c in n if c.isalpha()]
    if len(letters) >= 10:
        up = sum(1 for c in letters if c.isupper())
        if up / len(letters) >= 0.8 and len(words) >= 3:
            return True
    if len(words) >= 3:
        titleish = sum(1 for w in words if _title_case_word(w))
        if titleish >= 2 and len(n) >= 24:
            return True
    if len(words) >= 2 and len(n) > 15:
        shouts = [w for w in words if _mostly_upper_word(w)]
        lowers = [w for w in words if _mostly_lower_word(w)]
        if shouts and lowers:
            return True
    if len(words) == 2 and len(n) >= 20:
        if _title_case_word(words[0]) and _title_case_word(words[1]):
            return True
    if "-" in n and " " in n and len(n) > 26:
        return True
    return False
