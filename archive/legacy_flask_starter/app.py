"""
archive/legacy_flask_starter/app.py
Archived legacy Flask web starter previously in root.
Replaced by MoonBot's local-first desktop floating HUD and Nocturne Focus architecture.
"""
from flask import Flask, render_template, request, jsonify, session
import uuid

app = Flask(__name__)
app.secret_key = "archived-legacy-key"

@app.route("/")
def index():
    return jsonify({"message": "Archived legacy Flask bot. Use main.py for MoonBot desktop app."})

if __name__ == "__main__":
    print("This is an archived legacy file. Run main.py instead.")
