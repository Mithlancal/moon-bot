"""
core/reader_assistant.py — Ask & Learn assistant and memory vault link.
Coordinates copied text, questions, quizzes and translations, then stores the
results in the local JSON vault.
"""

import logging
from typing import Any, Dict, Optional

from core import gemini_service, json_db, web_context

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

    def process_query(
        self,
        text: str,
        mode: str = "natural",
        context: str = "",
        target_language: str = ""
    ) -> Dict[str, Any]:
        """
        Process a natural-language request or captured highlight.

        Modes: 'natural', 'explain', 'quiz', 'links', 'translate', 'memo',
        'formula', 'search'. Natural mode interprets the user's intent first.
        """
        text = (text or "").strip()
        if not isinstance(context, str):
            context = web_context.context_for_prompt(context)
        if not text:
            return {
                "title": "Empty Query",
                "explanation": "Please provide or copy some text from your study material.",
                "takeaways": [],
                "formula": "",
                "reference_links": [],
                "source": "local"
            }

        if mode == "natural":
            # Local routing is instant. A second Gemini call just to classify a
            # simple question made the HUD look stuck before the answer began.
            routing = gemini_service.interpret_query(text, context=context, use_model=False)
            intent = routing.get("intent", "explain")
            text = routing.get("query") or text
            target_language = routing.get("target_language") or target_language
            if intent == "search":
                intent = "links"
            elif intent == "formula":
                text = f"Derive and explain the variables in: {text}"
                intent = "explain"
            mode = intent

        if mode == "translate":
            data = gemini_service.translate_text(
                text, target_language or "English", context=context
            )
            data["intent"] = "translate"
            data["reference_links"] = gemini_service.generate_reference_links(
                text, context=context, intent="translate"
            )
            self._last_result = {
                "type": "translation", "raw_text": text, "data": data,
                "context": context
            }
            json_db.append_daily_event(
                event_type="translation",
                title=f"Translated: {data.get('title', 'Study excerpt')}",
                details=f"Target: {data.get('language', 'English')}. Context: {context[:80]}"
            )
            json_db.add_history_entry(
                text, mode="translate", source=data.get("source", "local"),
                result=data.get("translation", "")
            )
            return data

        if mode == "memo":
            memo = gemini_service.generate_memo(text, context=context)
            data = dict(memo)
            data["reference_links"] = gemini_service.generate_reference_links(
                memo.get("title", text[:40]), context=context, intent="memo"
            )
            data["source"] = memo.get("source", "local")
            self._last_result = {
                "type": "memo", "raw_text": text, "data": data, "context": context
            }
            json_db.append_daily_event(
                event_type="memo",
                title=f"Memo: {memo.get('title', 'Study excerpt')}",
                details=f"Context: {context[:80]}"
            )
            json_db.add_history_entry(
                text, mode="memo", source=data.get("source", "local"),
                result=memo.get("summary", "")
            )
            return data

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
            local_hits = json_db.search_memory(text)
            links = gemini_service.generate_reference_links(text, context=context, intent="links")
            explanation = f"Here are places to look up '{text}'." + (
                f" I also found {len(local_hits)} matching note(s) in your vault." if local_hits else ""
            )
            result = {
                "title": f"Search: {text[:52]}",
                "explanation": explanation,
                "takeaways": [
                    "Open a link below to read more about it.",
                    f"Current view: {context[:80]}" if context else "General context."
                ],
                "formula": "",
                "reference_links": links,
                "local_matches": local_hits,
                "source": "local"
            }
            self._last_result = {"type": "explain", "raw_text": text, "data": result, "context": context}
            json_db.append_daily_event(
                event_type="reference_links",
                title=f"Reference lookup: {text[:40]}",
                details=f"{len(links)} search links generated."
            )
            json_db.add_history_entry(text, mode="links", source="local", result=result["title"])
            return result

        # Default: explain / formula
        explanation_data = gemini_service.explain_concept(text, context=context)
        self._last_result = {
            "type": "explain",
            "raw_text": text,
            "data": explanation_data,
            "context": context
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
        """Save the most recent explanation, quiz, memo or translation to the vault."""
        if not self._last_result:
            return None

        context = self._last_result.get("context", "")
        topic = course_or_topic if course_or_topic and course_or_topic != "General" else (context or "General")

        if self._last_result.get("type") == "memo":
            d = self._last_result.get("data", {})
            return json_db.add_memo_note(
                title=d.get("title", "Study Memo"),
                topic=d.get("topic", topic),
                cues=d.get("cues", ""),
                notes=d.get("notes", d.get("explanation", "")),
                summary=d.get("summary", ""),
                source_text=self._last_result.get("raw_text", ""),
                context=context,
                tags=["Study Memo", "Cornell"]
            )

        if self._last_result.get("type") == "translation":
            d = self._last_result.get("data", {})
            return json_db.add_quick_note(
                title=d.get("title", "Translation"),
                content=d.get("translation", "") or d.get("explanation", ""),
                tags=["Translation", d.get("language", "English")]
            )

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
