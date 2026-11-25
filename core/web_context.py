"""
core/web_context.py — Privacy-safe context parsing for the foreground window.

MoonBot does not read browser URLs, browser DOMs, or incognito/private content.
It only interprets the public window title that the OS exposes, plus text the
user explicitly copies. This module turns those signals into a clean context
object that can be shown in the UI and attached to Gemini prompts so answers are
about the PDF/site the student is actually reading.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import unquote_plus, urlparse

BROWSER_PROCESSES = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
    "opera.exe", "vivaldi.exe", "webkit2webprocess.exe"
}

PDF_PROCESSES = {
    "acrobat.exe", "acrord32.exe", "sumatrapdf.exe", "foxitreader.exe",
    "msedge.exe", "chrome.exe", "firefox.exe"
}

KNOWN_SITES = {
    "youtube": "YouTube",
    "wikipedia": "Wikipedia",
    "github": "GitHub",
    "stackoverflow": "Stack Overflow",
    "stackexchange": "Stack Exchange",
    "geeksforgeeks": "GeeksforGeeks",
    "leetcode": "LeetCode",
    "arxiv": "arXiv",
    "scholar.google": "Google Scholar",
    "google scholar": "Google Scholar",
    "canvas": "Canvas LMS",
    "blackboard": "Blackboard",
    "moodle": "Moodle",
    "coursera": "Coursera",
    "edx": "edX",
    "nptel": "NPTEL",
    "notion": "Notion",
    "obsidian": "Obsidian",
    "medium": "Medium",
    "springer": "Springer",
    "sciencedirect": "ScienceDirect",
    "ieee": "IEEE Xplore",
    "researchgate": "ResearchGate",
    "docs.python": "Python Docs",
    "mdn": "MDN Web Docs",
    "chatgpt": "ChatGPT",
    "gemini": "Gemini",
}

_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_DOMAIN_RE = re.compile(
    r"\b((?:[a-z0-9-]+\.)+(?:com|org|net|edu|gov|io|dev|ai|co|in|uk|de|fr|info|me|tv))\b",
    re.IGNORECASE,
)
_FILE_RE = re.compile(r"\b[\w().@ -]+\.(pdf|pptx?|docx?|md|txt|ipynb|tex)\b", re.IGNORECASE)
_BROWSER_SUFFIX_RE = re.compile(
    r"\s+[-—]\s+(?:Google Chrome|Microsoft Edge|Mozilla Firefox|Brave|Opera|Vivaldi|"
    r"Adobe Acrobat(?: Pro| Reader)?|Acrobat|Foxit Reader|SumatraPDF)$",
    re.IGNORECASE,
)
_PROFILE_SUFFIX_RE = re.compile(r"\s+[-—]\s+(?:Personal|Work|School|Default)$", re.IGNORECASE)

PROCESS_LABELS = {
    "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "brave": "Brave",
    "opera": "Opera", "acrobat": "Acrobat", "acrord32": "Acrobat",
    "sumatrapdf": "SumatraPDF", "foxitreader": "Foxit Reader",
    "code": "VS Code", "cursor": "Cursor", "pycharm": "PyCharm",
    "winword": "Word", "powerpnt": "PowerPoint", "notion": "Notion",
    "obsidian": "Obsidian", "python": "Python", "explorer": "File Explorer",
}


def _clean_title(title: str) -> str:
    """Remove browser/app suffixes and keep the page, tab or document title."""
    text = (title or "").strip()
    stripped_app_suffix = False
    for _ in range(4):
        match = _BROWSER_SUFFIX_RE.search(text)
        if match:
            text = text[:match.start()].strip()
            stripped_app_suffix = True
            continue
        if stripped_app_suffix:
            match = _PROFILE_SUFFIX_RE.search(text)
            if match:
                text = text[:match.start()].strip()
                continue
        break
    if stripped_app_suffix:
        text = re.sub(r"\s+and more$", "", text, flags=re.IGNORECASE).strip()
    return text or "Untitled Window"


def _clean_process(app_name: str) -> str:
    """Turn 'msedge.exe' into a readable app name for the UI."""
    text = (app_name or "").strip()
    base = re.sub(r"\.exe$", "", text, flags=re.IGNORECASE)
    if not base:
        return ""
    return PROCESS_LABELS.get(base.lower(), base.replace("_", " ").title())


def _site_from_text(text: str) -> str:
    lowered = (text or "").lower()
    for needle, label in KNOWN_SITES.items():
        if needle in lowered:
            return label
    match = _DOMAIN_RE.search(text or "")
    if match:
        domain = match.group(1).lower()
        return domain.split(".")[-2].capitalize() if len(domain.split(".")) > 1 else domain
    return ""


def _url_from_title(title: str) -> str:
    match = _URL_RE.search(title or "")
    if not match:
        return ""
    url = match.group(0).rstrip(".,;")
    return unquote_plus(url) if "%" in url else url


def parse_context(app_name: str, window_title: str, clipboard_text: str = "") -> Dict[str, str]:
    """
    Build a structured context snapshot from OS-visible signals.
    Returns: kind, site, document, title, url, process, category_hint, description.
    """
    process_raw = (app_name or "").strip()
    process = _clean_process(process_raw)
    process_lower = process_raw.lower()
    title = _clean_title(window_title)
    combined = f"{process_lower} {title.lower()} {clipboard_text[:200].lower()}"

    url = _url_from_title(window_title) or _url_from_title(clipboard_text[:500])
    site = _site_from_text(combined) or _site_from_text(url)

    file_match = _FILE_RE.search(title) or _FILE_RE.search(clipboard_text[:300])
    document = file_match.group(0).strip() if file_match else ""

    is_browser = process_lower in BROWSER_PROCESSES or _site_from_text(title) != ""

    if document:
        extension = document.rsplit(".", 1)[-1].lower()
        kind = "pdf" if extension == "pdf" else "slides" if extension in ("ppt", "pptx") else "document"
    elif site:
        kind = "web"
    elif any(word in process_lower for word in ("code.exe", "cursor", "pycharm", "idea", "vim")):
        kind = "code"
    elif is_browser:
        kind = "web"
    else:
        kind = "app"

    if kind == "pdf":
        description = f"PDF: {document}"
        if site:
            description = f"{site} · {description}"
    elif kind == "slides":
        description = f"Slides: {document}"
    elif site:
        description = f"{site}: {title[:70]}"
    else:
        description = title[:70]

    return {
        "kind": kind,
        "site": site,
        "document": document,
        "title": title,
        "url": url,
        "process": process,
        "process_raw": process_raw,
        "description": description,
    }


def context_for_prompt(context: Any) -> str:
    """Render a context dict (or string) as a compact prompt prefix."""
    if not context:
        return "General study material"
    if isinstance(context, str):
        return context[:500]
    parts = []
    for key in ("description", "process", "site", "document", "title", "url"):
        value = str(context.get(key, "")).strip()
        if value and value not in parts:
            parts.append(value)
    return " | ".join(parts)[:800] or "General study material"


def site_summary(context: Any) -> str:
    """Short UI badge text for the active context."""
    if not context:
        return "Detecting the active page or PDF..."
    if isinstance(context, str):
        return f"🌐 {context[:60]}"
    icon = {"pdf": "📄", "slides": "📊", "web": "🌐", "code": "💻", "document": "📝", "app": "🪟"}.get(
        str(context.get("kind", "")), "🌐"
    )
    description = str(context.get("description") or context.get("title") or "Unknown context")[:70]
    process = str(context.get("process") or context.get("process_raw") or "").strip()
    return f"{icon} {description}" + (f" · {process[:20]}" if process else "")


def url_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
