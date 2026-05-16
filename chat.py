# chat.py — Gemini API logic only. Nothing else lives here.

import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL, SYSTEM_PROMPT, BOT_NAME

# Configure Gemini once on import
genai.configure(api_key=GEMINI_API_KEY)

# Store conversation history per session (in-memory, resets on restart)
_conversations: dict[str, list] = {}


def _get_model():
    """Returns a configured Gemini model with the bot's system prompt."""
    return genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT
    )


def get_response(session_id: str, user_message: str) -> str:
    """
    Get a response from Gemini for a given session.
    Maintains conversation history per session_id.
    
    Args:
        session_id: Unique ID per browser tab/user
        user_message: What the user typed
    
    Returns:
        Bot's reply as a string
    """
    try:
        # Initialize history for new sessions
        if session_id not in _conversations:
            _conversations[session_id] = []

        model = _get_model()
        chat = model.start_chat(history=_conversations[session_id])

        # Send message and get response
        response = chat.send_message(user_message)
        reply = response.text

        # Update history
        _conversations[session_id] = chat.history

        return reply

    except Exception as e:
        # Graceful error — stays in character
        print(f"[chat.py] Gemini API error: {e}")
        return f"*explodes* My brain short-circuited. yare yare... Try again? (Error: {str(e)[:60]})"


def clear_history(session_id: str) -> None:
    """Clears conversation history for a session (fresh start button)."""
    if session_id in _conversations:
        del _conversations[session_id]


def get_bot_name() -> str:
    return BOT_NAME
