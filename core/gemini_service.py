"""
core/gemini_service.py — Google Gemini AI Integration for MoonBot
Provides concept explanation, active recall pop quizzes, formula derivations,
and academic reference links using the official google-genai SDK.
Includes robust offline fallback when offline or without an API key.
"""

import json
import logging
import re
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger("MoonBot.GeminiService")

# Try initializing google-genai client
_client = None
HAS_GEMINI_CLIENT = False
_model_lock = threading.RLock()
_active_model: Optional[str] = None
_working_model: Optional[str] = None
_failed_models: set[str] = set()
_discovered_models: Optional[List[str]] = None

# Text flash models are tried in this order when the configured model is
# unavailable. Dynamic discovery can add newer models as Google releases them.
# Lite models are first because free-tier daily quota is shared across accounts.
_PREFERRED_TEXT_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-2.0-flash",
)
# A missing/unsupported model is specific to that model, so trying the next
# candidate is cheap and useful. Quota, timeout and network failures are not:
# retrying them just keeps the user staring at “processing”.
_MODEL_NOT_FOUND_TOKENS = (
    "not_found", "not found", "unsupported", "invalid model", "unknown model",
    "does not exist", "no model", "404", "model is not supported",
)
_STOP_RETRY_TOKENS = (
    "resource_exhausted", "quota", "rate limit", "429", "unavailable", "503",
    "504", "overloaded", "deadline", "timeout", "timed out", "connection",
    "network", "socket", "temporarily unavailable",
)

try:
    from google import genai
    from google.genai import types
    HAS_GENAI_PKG = True
except ImportError:
    HAS_GENAI_PKG = False


def _redact(text: str) -> str:
    """Never echo the API key, even if an SDK error happens to include it."""
    result = str(text or "")
    key = getattr(config, "GEMINI_API_KEY", "")
    if key:
        result = result.replace(key, "<redacted-api-key>")
    return result


def _describe_error(exc: BaseException) -> str:
    """Return useful exception details without revealing the API key."""
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None) or ""
    detail = _redact(exc)
    return f"{type(exc).__name__}{f' [{status}]' if status else ''}: {detail[:700]}"


def _normalise_model_name(name: str) -> str:
    """Accept both 'models/gemini-x' and 'gemini-x'."""
    return re.sub(r"^models/", "", (name or "").strip())


def _is_missing_model(exc: BaseException) -> bool:
    """True only when this exact model name is unusable."""
    text = _describe_error(exc).lower()
    return any(token in text for token in _MODEL_NOT_FOUND_TOKENS)


def _should_stop_retrying(exc: BaseException) -> bool:
    """True for quota, deadline and network errors that will not improve by retrying."""
    text = _describe_error(exc).lower()
    return any(token in text for token in _STOP_RETRY_TOKENS)


def _discover_text_models(client: Any) -> List[str]:
    """Find currently available text flash models from the Gemini account."""
    global _discovered_models
    with _model_lock:
        if _discovered_models is not None:
            return list(_discovered_models)

    found: List[str] = []
    try:
        for model in client.models.list():
            name = _normalise_model_name(getattr(model, "name", ""))
            if not name.startswith("gemini-") or "flash" not in name:
                continue
            if not (name.endswith("-flash") or name.endswith("-flash-lite")):
                continue
            if any(skip in name for skip in ("image", "preview", "tts", "audio", "video")):
                continue
            found.append(name)
    except Exception as exc:
        # Model listing is optional; the configured/static list still works.
        logger.debug(f"Gemini model discovery unavailable: {_describe_error(exc)}")

    def rank(name: str) -> tuple[int, str]:
        try:
            return (_PREFERRED_TEXT_MODELS.index(name), name)
        except ValueError:
            return (len(_PREFERRED_TEXT_MODELS), name)

    found = sorted(set(found), key=rank)
    with _model_lock:
        _discovered_models = found
    return list(found)


def _candidate_models(client: Any) -> List[str]:
    """Configured model first, then a known-good working model, then fallbacks."""
    with _model_lock:
        active = _active_model
        working = _working_model
        failed = set(_failed_models)

    candidates: List[str] = []

    def add(name: str) -> None:
        clean = _normalise_model_name(name)
        if clean and clean not in candidates and clean not in failed:
            candidates.append(clean)

    add(config.GEMINI_MODEL)
    add(working)
    add(active)
    # Never block the first question on a models/list network call. Discovery is
    # optional; use it only if another part of the app already populated it.
    with _model_lock:
        discovered = list(_discovered_models or ())
    for name in discovered:
        add(name)
    for name in _PREFERRED_TEXT_MODELS:
        add(name)
    for name in getattr(config, "GEMINI_FALLBACK_MODELS", ()):
        add(name)
    return candidates


def _mark_model_failed(model: str) -> None:
    global _active_model
    with _model_lock:
        _failed_models.add(model)
        if _active_model == model:
            _active_model = None


def _mark_model_ok(model: str) -> None:
    global _active_model, _working_model
    with _model_lock:
        _active_model = model
        _working_model = model


def _get_client():
    global _client, HAS_GEMINI_CLIENT
    if _client is not None:
        return _client

    api_key = config.GEMINI_API_KEY
    if not api_key or api_key == "your_gemini_api_key_here":
        return None

    if HAS_GENAI_PKG:
        try:
            http_options = types.HttpOptions(timeout=config.GEMINI_TIMEOUT_MS)
            _client = genai.Client(api_key=api_key, http_options=http_options)
            HAS_GEMINI_CLIENT = True
            return _client
        except Exception as exc:
            logger.warning(f"Failed to initialize google.genai Client: {_describe_error(exc)}")
            return None
    return None


SYSTEM_STUDY_PROMPT = """
You are MoonBot, a focused study assistant for a computer science student.
Explain clearly and briefly. Use simple language, useful examples, and equations
when they help. Keep the response easy to scan while studying.
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


def _generate_text(prompt: str, purpose: str) -> str:
    """Call Gemini with a small, bounded model fallback chain."""
    client = _get_client()
    if not client:
        raise RuntimeError("Gemini client unavailable (API key or google-genai package is missing)")

    last_error: Optional[BaseException] = None
    max_attempts = max(1, getattr(config, "GEMINI_MAX_MODEL_ATTEMPTS", 3))
    budget_ms = getattr(config, "GEMINI_TOTAL_TIMEOUT_MS", 13000)
    deadline = time.monotonic() + max(10000, budget_ms) / 1000.0

    for model in _candidate_models(client)[:max_attempts]:
        if time.monotonic() >= deadline:
            last_error = RuntimeError("Live answer took too long; using the local answer")
            break
        try:
            response = client.models.generate_content(
                model=model,
                contents=f"{SYSTEM_STUDY_PROMPT}\n\n{prompt}"
            )
            text = (response.text or "").strip()
            if not text:
                raise ValueError("Gemini returned an empty response")
            _mark_model_ok(model)
            return text
        except Exception as exc:
            last_error = exc
            logger.warning(f"Gemini {purpose} failed with model {model}: {_describe_error(exc)}")
            if _is_missing_model(exc):
                # Only a genuinely unusable model is retired; quota/timeout errors
                # may clear later, so do not poison the configured model for the
                # rest of the session.
                _mark_model_failed(model)
            if _should_stop_retrying(exc):
                logger.debug(f"Stopping {purpose} fallback after quota/timeout/network error")
                break
            if not _is_missing_model(exc):
                break

    if last_error is not None:
        raise last_error
    raise RuntimeError("No Gemini text model is available right now")


def _generate_json(prompt: str, purpose: str = "JSON request") -> Dict[str, Any]:
    """Call Gemini and parse a strict JSON response."""
    return _parse_json_response(_generate_text(prompt, purpose))


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


def explain_concept(
    text: str,
    context: str = "",
    intent: str = "explain",
    target_language: str = ""
) -> Dict[str, Any]:
    """
    Explain a highlighted concept, definition, or paragraph from a PDF/slide/tab.

    `intent` lets the natural-language router request a translation or memo
    without changing the return shape used by the UI.
    """
    if intent == "translate" and target_language:
        translation = translate_text(text, target_language, context=context)
        return {
            "title": translation.get("title", "Translation"),
            "explanation": translation.get("explanation", ""),
            "takeaways": translation.get("takeaways", []),
            "formula": "",
            "reference_links": generate_reference_links(text, context=context, intent="translate"),
            "source": translation.get("source", "offline_fallback"),
            "intent": "translate",
            "translation": translation.get("translation", ""),
            "language": translation.get("language", target_language),
        }

    if intent == "memo":
        memo = generate_memo(text, context=context)
        return {
            "title": memo.get("title", "Study Memo"),
            "explanation": memo.get("notes", ""),
            "takeaways": [memo.get("summary", "")] if memo.get("summary") else [],
            "formula": "",
            "reference_links": generate_reference_links(text, context=context, intent="memo"),
            "source": memo.get("source", "offline_fallback"),
            "intent": "memo",
            "memo": memo,
        }

    if _get_client():
        try:
            parsed = _generate_json(f"""
Explain the following study excerpt.
Current view: {context or 'General study material'}
Text:
\"\"\"{text.strip()}\"\"\"

Answer in the language of the user's request. Provide strict valid JSON:
{{
  "title": "Short concept name (3-6 words)",
  "explanation": "Clear explanation with a simple example where useful",
  "takeaways": ["Key point 1", "Key point 2", "Key point 3"],
  "formula": "Key equation if applicable, or empty string",
  "recommended_keywords": ["keyword1", "keyword2"],
  "language": "Language used for the answer"
}}
Return ONLY JSON without markdown fences.
""", purpose="explanation")
            kw = parsed.get("recommended_keywords", [])
            query_term = kw[0] if kw else parsed.get("title", text[:30])
            return {
                "title": parsed.get("title", "Concept Explanation"),
                "explanation": parsed.get("explanation", ""),
                "takeaways": parsed.get("takeaways", []),
                "formula": parsed.get("formula", ""),
                "reference_links": generate_reference_links(
                    query_term, context=context, intent="explain"
                ),
                "source": "gemini",
                "intent": "explain",
                "language": parsed.get("language", ""),
            }
        except Exception as exc:
            logger.warning(f"Gemini explanation failed: {_describe_error(exc)}")
            result = _offline_explain_concept(text, reason=_describe_error(exc))
            result["intent"] = "explain"
            return result

    result = _offline_explain_concept(text)
    result["intent"] = "explain"
    return result


def _interpret_locally(text: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    """Route obvious study requests without a network round trip."""
    lowered = text.lower()
    cleaned = text.strip()
    if any(word in lowered for word in ("translate", "translation", "meaning in", "in hindi", "in tamil", "in english")):
        language = "English"
        for candidate in ("hindi", "tamil", "telugu", "english", "spanish", "french", "german"):
            if f"in {candidate}" in lowered or candidate in lowered:
                language = candidate.capitalize()
                break
        fallback.update({"intent": "translate", "target_language": language})
    elif any(word in lowered for word in ("memo", "cornell", "notes", "summary note")):
        fallback["intent"] = "memo"
    elif any(word in lowered for word in ("quiz", "test me", "question")):
        fallback["intent"] = "quiz"
    elif any(word in lowered for word in ("formula", "derive", "equation", "solve")):
        fallback["intent"] = "formula"
    elif any(word in lowered for word in ("search", "find", "look up", "reference", "source")):
        fallback["intent"] = "search"
    for lead in (
        "please ", "can you ", "could you ", "what is ", "what's ", "explain ",
        "tell me about ", "tell me ", "translate ", "summarize ", "make a memo of ",
    ):
        if cleaned.lower().startswith(lead) and len(cleaned) > len(lead):
            cleaned = cleaned[len(lead):].strip()
            break
    fallback["query"] = cleaned.rstrip("?")
    return fallback


def interpret_query(text: str, context: str = "", use_model: bool = True) -> Dict[str, Any]:
    """
    Understand a natural-language study request and route it to the right tool.
    `use_model=False` keeps simple questions local and immediate.
    """
    fallback = {
        "intent": "explain",
        "query": (text or "").strip(),
        "target_language": "",
        "keywords": [],
        "note": "",
        "source": "local",
    }

    if not text or not text.strip():
        return fallback
    if not use_model:
        return _interpret_locally(text, fallback)

    if _get_client():
        try:
            data = _generate_json(f"""
Interpret this student's natural-language study request.
Active context: {context or 'General study material'}
Request:
\"\"\"{text.strip()}\"\"\"

Choose exactly one intent: explain, quiz, formula, translate, memo, search, links.
Extract the concrete topic/excerpt to work on. If the user asks for translation,
set target_language to the requested language (e.g. "Hindi", "English", "Tamil").
Return strict JSON:
{{
  "intent": "explain|quiz|formula|translate|memo|search|links",
  "query": "the text to analyse",
  "target_language": "language name or empty string",
  "keywords": ["keyword1", "keyword2"],
  "note": "short acknowledgement or clarification"
}}
Return ONLY JSON.
""", purpose="request routing")
            intent = str(data.get("intent", "explain")).strip().lower()
            if intent not in {"explain", "quiz", "formula", "translate", "memo", "search", "links"}:
                intent = "explain"
            fallback.update({
                "intent": intent,
                "query": str(data.get("query") or text).strip(),
                "target_language": str(data.get("target_language") or "").strip(),
                "keywords": [str(k).strip() for k in data.get("keywords", []) if str(k).strip()][:8],
                "note": str(data.get("note") or "").strip(),
                "source": "gemini",
            })
            return fallback
        except Exception as exc:
            logger.warning(f"Natural-language routing failed, using local parser: {_describe_error(exc)}")

    return _interpret_locally(text, fallback)


def translate_text(
    text: str,
    target_language: str,
    source_language: str = "auto",
    context: str = ""
) -> Dict[str, Any]:
    """Translate and explain highlighted study text in the requested language."""
    if _get_client():
        try:
            data = _generate_json(f"""
Translate the following study excerpt into {target_language}.
Source language: {source_language}
Active context: {context or 'General study material'}
Excerpt:
\"\"\"{text.strip()}\"\"\"

Return strict JSON:
{{
  "title": "Short topic name in the target language",
  "translation": "Natural, faithful translation in {target_language}",
  "meaning": "Simple explanation of what it means, in {target_language}",
  "key_terms": [{{"original": "term", "translated": "term", "meaning": "short meaning"}}],
  "language": "{target_language}"
}}
Return ONLY JSON.
""", purpose="translation")
            terms = data.get("key_terms", [])
            if not isinstance(terms, list):
                terms = []
            meaningful = []
            for term in terms:
                if isinstance(term, dict):
                    meaningful.append(
                        f"{term.get('original', '')} → {term.get('translated', '')}: {term.get('meaning', '')}"
                    )
            explanation = f"{data.get('translation', '')}\n\nMeaning: {data.get('meaning', '')}"
            if meaningful:
                explanation += "\n\nKey terms:\n" + "\n".join(f"• {t}" for t in meaningful[:8])
            return {
                "title": data.get("title", f"Translation — {target_language}"),
                "translation": data.get("translation", ""),
                "explanation": explanation,
                "takeaways": meaningful[:5],
                "language": data.get("language", target_language),
                "source": "gemini",
            }
        except Exception as exc:
            logger.warning(f"Gemini translation failed: {_describe_error(exc)}")
            detail = _describe_error(exc)
            return {
                "title": f"Translation — {target_language}",
                "translation": "",
                "explanation": (
                    f"Couldn't translate this right now ({detail}). "
                    "Original text:\n\n" + text.strip()
                ),
                "takeaways": [],
                "language": target_language,
                "source": "offline_fallback",
            }

    return {
        "title": f"Translation — {target_language}",
        "translation": "",
        "explanation": (
            f"Couldn't translate into {target_language} right now. "
            "Add a GEMINI_API_KEY to .env or check your connection. Original text:\n\n" + text.strip()
        ),
        "takeaways": [],
        "language": target_language,
        "source": "offline_fallback",
    }


def generate_memo(text: str, context: str = "") -> Dict[str, Any]:
    """Create a structured Cornell-style memo from highlighted study text."""
    if _get_client():
        try:
            data = _generate_json(f"""
Turn this study excerpt into a high-quality Cornell memo.
Active context: {context or 'General study material'}
Excerpt:
\"\"\"{text.strip()}\"\"\"

Return strict JSON:
{{
  "title": "Descriptive memo title",
  "topic": "Course/topic label",
  "cues": "Short trigger words/questions for active recall, comma separated",
  "notes": "Concise explanation, mental model and key details",
  "summary": "2-3 sentence exam-ready summary"
}}
Return ONLY JSON.
""", purpose="memo")
            data["source"] = "gemini"
            return data
        except Exception as exc:
            logger.warning(f"Gemini memo generation failed: {_describe_error(exc)}")

    words = text.strip().split()
    title = " ".join(words[:6]).capitalize() if words else "Study Memo"
    return {
        "title": title,
        "topic": context or "General Study",
        "cues": ", ".join(words[:8]),
        "notes": text.strip(),
        "summary": "Local memo from your text. Add GEMINI_API_KEY to .env for a structured summary.",
        "source": "offline_fallback",
    }


def generate_pop_quiz(text: str) -> Dict[str, Any]:
    """
    Generate one multiple-choice question from study material.
    Returns: {
        "question": str,
        "options": [A, B, C, D],
        "correct_index": int (0-3),
        "explanation": str,
        "source": "gemini" | "offline_fallback"
    }
    """
    if _get_client():
        try:
            data = _generate_json(f"""
Write one clear practice question about this study text:
\"\"\"{text.strip()}\"\"\"

Return strict JSON:
{{
  "question": "A question that tests understanding of the main idea",
  "options": ["First option", "Second option", "Third option", "Fourth option"],
  "correct_index": 0,
  "explanation": "Why the correct option is right and why the others are not"
}}
Return ONLY JSON without markdown fences.
""", purpose="quiz")
            question = str(data.get("question") or "").strip()
            raw_options = data.get("options")
            real_options = [
                str(option).strip() for option in raw_options
                if str(option).strip()
            ] if isinstance(raw_options, list) else []
            if not question or len(real_options) < 2:
                raise ValueError("Gemini quiz response was missing a question or two real options")
            data["source"] = "gemini"
            return _normalise_quiz(data)
        except Exception as exc:
            logger.warning(f"Gemini quiz generation failed: {_describe_error(exc)}")
            return _offline_pop_quiz(text, reason=_describe_error(exc))

    return _offline_pop_quiz(text)


def generate_reference_links(
    query: str,
    context: str = "",
    intent: str = ""
) -> List[Dict[str, str]]:
    """Generate natural-language-aware academic search links for rapid lookup."""
    clean = re.sub(r"\s+", " ", (query or "").strip())[:180]
    if not clean:
        return []
    q_enc = urllib.parse.quote_plus(clean)
    ctx_enc = urllib.parse.quote_plus(context[:120]) if context else ""
    links = [
        {
            "title": f"Search: {clean[:52]}",
            "url": f"https://www.google.com/search?q={q_enc}"
        },
        {
            "title": f"Wikipedia: {clean[:52]}",
            "url": f"https://en.wikipedia.org/wiki/Special:Search?search={q_enc}"
        },
    ]

    links.extend([
        {
            "title": f"Scholar: {clean[:52]}",
            "url": f"https://scholar.google.com/scholar?q={q_enc}"
        },
        {
            "title": f"arXiv: {clean[:52]}",
            "url": f"https://arxiv.org/search/?query={q_enc}&searchtype=all"
        }
    ])

    if intent == "translate":
        links.append({
            "title": f"Wiktionary: {clean[:52]}",
            "url": f"https://en.wiktionary.org/w/index.php?search={q_enc}"
        })

    if ctx_enc and len(links) < 4:
        links.append({
            "title": "Find in active context",
            "url": f"https://www.google.com/search?q={q_enc}+{ctx_enc}"
        })
    return links[:5]


def _short_reason(reason: str = "") -> str:
    """Keep error details useful but readable inside the answer box."""
    detail = (reason or "").strip()
    return detail[:180] + ("..." if len(detail) > 180 else "")


def _offline_explain_concept(text: str, reason: str = "") -> Dict[str, Any]:
    """Clear local answer when Gemini cannot be reached or has no quota left."""
    clean_text = text.strip()
    words = clean_text.split()
    title = " ".join(words[:5]).capitalize() if words else "Study Excerpt"
    links = generate_reference_links(title)

    opening = re.split(r"(?<=[.!?])\s+", clean_text, maxsplit=1)[0][:260] or clean_text[:260]
    detail = _short_reason(reason)
    if detail:
        status = f"Live explanation unavailable right now ({detail})."
    elif config.GEMINI_API_KEY:
        status = "Live explanation unavailable right now. Your text and links are still here; try again shortly."
    else:
        status = "Add GEMINI_API_KEY to .env to enable live explanations."

    explanation = f"From your text:\n\n{opening}\n\n{status}"
    takeaways = [
        "Use the reference links below to look up the topic.",
        "Copy a shorter passage and ask again for a focused explanation.",
        "Your original text is kept here so you can keep reading without switching tabs.",
    ]

    return {
        "title": title,
        "explanation": explanation,
        "takeaways": takeaways,
        "formula": "",
        "reference_links": links,
        "source": "offline_fallback"
    }


def _offline_pop_quiz(text: str, reason: str = "") -> Dict[str, Any]:
    """Working local practice question when Gemini cannot generate one."""
    words = text.split()
    sample_topic = " ".join(words[:6]) if words else "this topic"
    detail = _short_reason(reason)
    note = (
        f"Local practice question. Live quiz unavailable ({detail})." if detail
        else "Local practice question. Add GEMINI_API_KEY to .env for topic-specific quizzes."
    )

    return {
        "question": f"Which sentence best captures the main idea of '{sample_topic}'?",
        "options": [
            "The passage explains one main idea using supporting details or examples.",
            "The passage is only a list of unrelated words.",
            "The passage describes events that happen without any connection.",
            "The passage gives no information about the topic.",
        ],
        "correct_index": 0,
        "explanation": (
            "The correct option is the only one that describes a normal explanatory passage. "
            + note
        ),
        "note": note,
        "source": "offline_fallback"
    }


def offline_answer(
    text: str,
    mode: str = "explain",
    target_language: str = "",
    context: str = "",
    reason: str = ""
) -> Dict[str, Any]:
    """Instant local result used by the UI watchdog when a live call runs long."""
    clean = (text or "").strip()
    mode = (mode or "explain").strip().lower()
    if mode == "natural":
        routing = _interpret_locally(clean, {
            "intent": "explain", "query": clean, "target_language": "",
            "keywords": [], "note": "", "source": "local"
        })
        mode = routing.get("intent", "explain")
        clean = str(routing.get("query") or clean)
        target_language = str(routing.get("target_language") or target_language)

    if mode == "quiz":
        return _offline_pop_quiz(clean, reason=reason)
    if mode in {"links", "search"}:
        return {
            "title": f"Search: {clean[:52]}" if clean else "Search",
            "explanation": (
                "Here are places to look this up. The live lookup is taking longer "
                "than expected, so these links are ready now."
            ),
            "takeaways": [],
            "formula": "",
            "reference_links": generate_reference_links(clean, context=context, intent="links"),
            "source": "offline_fallback",
            "intent": "links",
        }
    if mode == "memo":
        words = clean.split()
        return {
            "title": " ".join(words[:6]).capitalize() if words else "Study Memo",
            "topic": context or "General Study",
            "cues": ", ".join(words[:8]),
            "notes": clean,
            "summary": "Local memo from your text. A fuller summary will appear if the live request finishes.",
            "explanation": clean,
            "takeaways": [],
            "formula": "",
            "reference_links": generate_reference_links(clean, context=context, intent="memo"),
            "source": "offline_fallback",
            "intent": "memo",
        }
    if mode == "translate":
        language = target_language or "English"
        return {
            "title": f"Translation — {language}",
            "translation": "",
            "explanation": (
                f"Couldn't translate into {language} right now. Original text:\n\n{clean}"
            ),
            "takeaways": [],
            "formula": "",
            "reference_links": generate_reference_links(clean, context=context, intent="translate"),
            "source": "offline_fallback",
            "intent": "translate",
            "language": language,
        }

    result = _offline_explain_concept(clean, reason=reason)
    result["intent"] = "explain"
    return result
