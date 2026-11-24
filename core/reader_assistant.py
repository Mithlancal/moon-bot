"""
core/reader_assistant.py — No-Tab-Switch Reader Assistant & Memory Vault Link
Coordinates clipboard grabs, user queries, Gemini synthesis, pop quizzes,
and automatic storage in local JSON memory vault.
"""

import logging
from typing import Any, Dict, Optional

from core import gemini_service, json_db

logger = logging.getLogger("MoonBot.ReaderAssistant")

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    pyperclip = None
    HAS_PYPERCLIP = False


class ReaderAssistant:
    """
    Orchestrates reading assistance directly over slides, PDFs, and browser tabs.
    Allows capturing text without tab switching, querying Gemini, generating pop quizzes,
    and persisting memory cards into local JSON storage.
    """

    def __init__(self):
        self._last_result: Optional[Dict[str, Any]] = None

    def grab_clipboard_text(self) -> str:
        """
        Grab whatever text the user highlighted and copied (Ctrl+C).
        Enables seamless zero-click extraction from any PDF reader, browser tab, or slide deck.
        """
        if not HAS_PYPERCLIP:
            logger.warning("pyperclip is unavailable; use the paste field instead.")
            return ""
        try:
            text = pyperclip.paste()
            return text.strip() if text else ""
        except Exception as e:
            logger.warning(f"Failed to grab clipboard: {e}")
            return ""

    def process_query(self, text: str, mode: str = "explain", context: str = "") -> Dict[str, Any]:
        """
        Process user query or captured text.
        Modes: 'explain', 'quiz', 'links'
        """
        text = text.strip()
        if not text:
            return {
                "title": "Empty Query",
                "explanation": "Please provide or copy some text from your study material.",
                "takeaways": [],
                "formula": "",
                "reference_links": [],
                "source": "local"
            }

        if mode == "quiz":
            quiz_data = gemini_service.generate_pop_quiz(text)
            self._last_result = {
                "type": "quiz",
                "raw_text": text,
                "quiz": quiz_data
            }
            json_db.append_daily_event(
                event_type="pop_quiz",
                title=f"Pop Quiz: {quiz_data.get('question', '')[:40]}...",
                details=f"Generated from excerpt: {text[:60]}..."
            )
            json_db.add_history_entry(
                text, mode="quiz", source=quiz_data.get("source", "local"),
                result=quiz_data.get("question", "")
            )
            return quiz_data

        if mode == "links":
            result = {
                "title": f"Reference Search: {text[:40]}",
                "explanation": f"Ready-made academic search links for '{text}'.",
                "takeaways": ["Open a link below to look this up without leaving MoonBot."],
                "formula": "",
                "reference_links": gemini_service.generate_reference_links(text),
                "source": "local"
            }
            self._last_result = {"type": "explain", "raw_text": text, "data": result}
            json_db.append_daily_event(
                event_type="reference_links",
                title=f"Reference lookup: {text[:40]}",
                details=f"{len(result['reference_links'])} search links generated."
            )
            json_db.add_history_entry(text, mode="links", source="local", result=result["title"])
            return result

        # Default: explain
        explanation_data = gemini_service.explain_concept(text, context=context)
        self._last_result = {
            "type": "explain",
            "raw_text": text,
            "data": explanation_data
        }

        json_db.append_daily_event(
            event_type="concept_lookup",
            title=f"Lookup: {explanation_data.get('title', 'Study Excerpt')}",
            details=f"Topic: {context or 'General'}. Source: {explanation_data.get('source')}"
        )
        json_db.add_history_entry(
            text, mode="explain", source=explanation_data.get("source", "local"),
            result=explanation_data.get("explanation", "")
        )
        return explanation_data

    def save_last_result_to_memory(self, course_or_topic: str = "General") -> Optional[Dict[str, Any]]:
        """Save the most recent explanation or quiz to data/memory.json."""
        if not self._last_result:
            return None

        if self._last_result.get("type") == "explain":
            d = self._last_result.get("data", {})
            return json_db.add_saved_concept(
                title=d.get("title", "Concept"),
                explanation=d.get("explanation", ""),
                query=self._last_result.get("raw_text", ""),
                course_or_topic=course_or_topic,
                formula=d.get("formula", ""),
                reference_links=d.get("reference_links", [])
            )
        elif self._last_result.get("type") == "quiz":
            q = self._last_result.get("quiz", {})
            return json_db.add_saved_concept(
                title=f"Quiz: {q.get('question', '')[:30]}",
                explanation=q.get("explanation", ""),
                query=self._last_result.get("raw_text", ""),
                course_or_topic=course_or_topic,
                quiz=q
            )
        return None
