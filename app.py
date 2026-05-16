# app.py — Flask server. Entry point. Routing only, no business logic here.

from flask import Flask, render_template, request, jsonify, session
from chat import get_response, clear_history, get_bot_name
from config import DEBUG, PORT, HOST
import uuid

app = Flask(__name__)
app.secret_key = "kuromi-chan-is-chaotic-and-unstoppable-💀"  # Change in production


@app.route("/")
def index():
    """Serve the main chat page."""
    # Assign a unique session ID per browser tab
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    return render_template("index.html", bot_name=get_bot_name())


@app.route("/chat", methods=["POST"])
def chat():
    """Handle chat messages. Expects JSON: { message: string }"""
    data = request.get_json()

    if not data or "message" not in data:
        return jsonify({"error": "No message provided"}), 400

    user_message = data["message"].strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    session_id = session.get("session_id", "default")
    reply = get_response(session_id, user_message)

    return jsonify({"reply": reply})


@app.route("/clear", methods=["POST"])
def clear():
    """Clear conversation history for this session."""
    session_id = session.get("session_id", "default")
    clear_history(session_id)
    return jsonify({"status": "cleared", "message": "History nuked. Fresh chaos begins. 💥"})


if __name__ == "__main__":
    print(f"🌙 {get_bot_name()} is waking up... brace yourself.")
    print(f"🔗 Open in browser: http://localhost:{PORT}")
    print(f"📱 On same WiFi? Open: http://<your-ip>:{PORT}")
    app.run(debug=DEBUG, host=HOST, port=PORT)
