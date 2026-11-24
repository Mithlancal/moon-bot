"""
core/gemini_service.py — Google Gemini AI Integration for MoonBot
Provides concept explanation, active recall pop quizzes, formula derivations,
and academic reference links using the official google-genai SDK.
Includes robust offline fallback when offline or without an API key.
"""

import json
import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger("MoonBot.GeminiService")

# Try initializing google-genai client
_client = None
HAS_GEMINI_CLIENT = False

try:
    from google import genai
    from google.genai import types
    HAS_GENAI_PKG = True
except ImportError:
    HAS_GENAI_PKG = False


def _get_client():
    global _client, HAS_GEMINI_CLIENT
    if _client is not None:
        return _client

    api_key = config.GEMINI_API_KEY
    if not api_key or api_key == "your_gemini_api_key_here":
        return None

    if HAS_GENAI_PKG:
        try:
            _client = genai.Client(api_key=api_key)
            HAS_GEMINI_CLIENT = True
            return _client
        except Exception as e:
            logger.warning(f"Failed to initialize google.genai Client: {e}")
            return None
    return None


SYSTEM_STUDY_PROMPT = """
You are MoonBot, an elite, high-efficiency academic study companion for a university computer science and engineering student.
Your goals:
1. Explain concepts concisely with zero fluff.
2. Provide an intuitive mental model, high-yield exam takeaways, and formal definitions or equations when relevant.
3. Keep responses structured, clean, and easily skimmable during fast reading sessions.
"""


def _parse_json_response(raw_text: str) -> Dict[str, Any]:
    """Extract a JSON object from a model reply, tolerating markdown fences and chatter."""
    text = (raw_text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Model response did not contain a JSON object.")
    parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON was not an object.")
    return parsed


def _normalise_quiz(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate quiz fields so malformed model output can never break the UI."""
    options = data.get("options", [])
    if not isinstance(options, list):
        options = []
    options = [str(o).strip() for o in options[:4]]
    option_count = len(options)
    while len(options) < 4:
        options.append("—")

    try:
        correct_index = int(data.get("correct_index", 0))
    except (TypeError, ValueError):
        correct_index = 0
    # Clamp against real options only, never against the placeholder padding.
    correct_index = max(0, min(correct_index, max(0, option_count - 1)))

    return {
        "question": str(data.get("question") or "Conceptual recall question").strip(),
        "options": options,
        "correct_index": correct_index,
        "explanation": str(data.get("explanation") or "").strip(),
        "source": data.get("source", "gemini")
    }


def explain_concept(text: str, context: str = "") -> Dict[str, Any]:
    """
    Explain a highlighted concept, definition, or paragraph from a PDF/slide/tab.
    Returns: {
        "title": str,
        "explanation": str,
        "takeaways": list[str],
        "formula": str,
        "reference_links": list[dict],
        "source": "gemini" | "offline_fallback"
    }
    """
    client = _get_client()

    if client:
        try:
            prompt = f"""
Analyze and synthesize the following academic text excerpt:
Context: {context or 'General Study Material'}
Text:
\"\"\"{text.strip()}\"\"\"

Provide your answer in strict valid JSON matching this schema:
{{
  "title": "Concise concept name (3-6 words)",
  "explanation": "Clear 2-3 paragraph intuition and academic breakdown",
  "takeaways": ["High-yield bullet 1", "High-yield bullet 2", "High-yield bullet 3"],
  "formula": "Key equation if applicable, or empty string",
  "recommended_keywords": ["keyword1", "keyword2"]
}}
Return ONLY JSON without markdown fences.
"""
            model_name = config.GEMINI_MODEL or "gemini-2.5-flash"
            response = client.models.generate_content(
                model=model_name,
                contents=f"{SYSTEM_STUDY_PROMPT}\n\n{prompt}"
            )
            parsed = _parse_json_response(response.text or "")

            # Generate reference links based on keywords and title
            kw = parsed.get("recommended_keywords", [])
            query_term = kw[0] if kw else parsed.get("title", text[:30])
            links = generate_reference_links(query_term)

            return {
                "title": parsed.get("title", "Concept Explanation"),
                "explanation": parsed.get("explanation", ""),
                "takeaways": parsed.get("takeaways", []),
                "formula": parsed.get("formula", ""),
                "reference_links": links,
                "source": "gemini"
            }
        except Exception as e:
            logger.warning(f"Gemini API request failed, falling back to local synthesis: {e}")

    # Offline / Local fallback mode
    return _offline_explain_concept(text)


def generate_pop_quiz(text: str) -> Dict[str, Any]:
    """
    Generate an active recall multiple-choice question from study material.
    Returns: {
        "question": str,
        "options": [A, B, C, D],
        "correct_index": int (0-3),
        "explanation": str,
        "source": "gemini" | "offline_fallback"
    }
    """
    client = _get_client()

    if client:
        try:
            prompt = f"""
Generate 1 active-recall multiple choice quiz question from the following study text:
\"\"\"{text.strip()}\"\"\"

Provide your answer in strict JSON:
{{
  "question": "Clear, testing conceptual question",
  "options": [
    "Option A",
    "Option B",
    "Option C",
    "Option D"
  ],
  "correct_index": 0,
  "explanation": "Why this option is correct and why common misconceptions fail"
}}
Return ONLY JSON without markdown code fences.
"""
            model_name = config.GEMINI_MODEL or "gemini-2.5-flash"
            response = client.models.generate_content(
                model=model_name,
                contents=f"{SYSTEM_STUDY_PROMPT}\n\n{prompt}"
            )
            data = _parse_json_response(response.text or "")
            data["source"] = "gemini"
            return _normalise_quiz(data)
        except Exception as e:
            logger.warning(f"Gemini quiz generation failed: {e}")

    return _offline_pop_quiz(text)


def generate_reference_links(query: str) -> List[Dict[str, str]]:
    """Generate verified academic search links for rapid lookup."""
    q_enc = urllib.parse.quote_plus(query.strip())
    return [
        {
            "title": f"Wikipedia: {query}",
            "url": f"https://en.wikipedia.org/wiki/Special:Search?search={q_enc}"
        },
        {
            "title": f"Google Scholar: {query}",
            "url": f"https://scholar.google.com/scholar?q={q_enc}"
        },
        {
            "title": f"GeeksforGeeks / Tech: {query}",
            "url": f"https://www.google.com/search?q=site%3Ageeksforgeeks.org+{q_enc}"
        },
        {
            "title": f"arXiv Research: {query}",
            "url": f"https://arxiv.org/search/?query={q_enc}&searchtype=all"
        }
    ]


def _offline_explain_concept(text: str) -> Dict[str, Any]:
    """Smart offline fallback when API key is missing or offline."""
    clean_text = text.strip()
    words = clean_text.split()
    title = " ".join(words[:5]).capitalize() if words else "Study Excerpt"
    links = generate_reference_links(title)

    explanation = (
        f"Offline Academic Digest: {clean_text}\n\n"
        "(Note: GEMINI_API_KEY is not configured or network is offline. "
        "Add your free Gemini API key to .env to unlock real-time neural explanations, "
        "deep derivations, and automatic formula LaTeX rendering.)"
    )

    takeaways = [
        "Core idea extracted directly from reading buffer.",
        "Add GEMINI_API_KEY to .env for multi-source knowledge synthesis.",
        "Verified reference links generated below for instant browser reading."
    ]

    return {
        "title": title,
        "explanation": explanation,
        "takeaways": takeaways,
        "formula": "",
        "reference_links": links,
        "source": "offline_fallback"
    }


def _offline_pop_quiz(text: str) -> Dict[str, Any]:
    """Offline multiple choice quiz generator."""
    words = text.split()
    sample_topic = " ".join(words[:4]) if words else "the studied topic"

    return {
        "question": f"Based on your study of '{sample_topic}', which statement best summarizes the core principle?",
        "options": [
            f"The primary mechanism depends on fundamental system constraints.",
            f"It operates completely independently without state or memory.",
            f"The execution time degrades asymptotically to infinity.",
            f"No theoretical limit applies to this configuration."
        ],
        "correct_index": 0,
        "explanation": "In engineering and computer systems, core principles are primarily bounded by system constraints and invariants.",
        "source": "offline_fallback"
    }
