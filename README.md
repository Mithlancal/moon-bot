# 💀 Kuromi-chan Chatbot

A chaotic, sarcastic anime-persona chatbot with a local web UI. Built with Python, Flask, and Google Gemini API.

---

## ✨ Features

- 🌐 **Runs locally** — open in any browser on Windows, Linux, or Android (same WiFi)
- 💀 **Kuromi-chan persona** — sarcastic, unhinged, anime-coded, somehow helpful
- 🧠 **Conversation memory** — remembers your chat history per session
- 💥 **Nuke history** — clear and start fresh anytime
- 📱 **Mobile-friendly** — works on phone browser via local network
- 🎨 **Chaotic UI** — dark theme, glowing accents, animated mess

---

## 🗂️ Project Structure

```
moonbot/
├── app.py              # Flask server & routes
├── chat.py             # Gemini API logic
├── config.py           # All settings (API key, persona, model)
├── requirements.txt    # Dependencies
├── templates/
│   └── index.html      # Chat UI
└── static/
    ├── style.css        # Chaotic dark theme
    └── script.js        # Frontend chat logic
```

Each file has **one responsibility only**. No spaghetti.

---

## 🚀 Setup & Run

### 1. Clone & install
```bash
git clone https://github.com/yourusername/moonbot.git
cd moonbot
pip install -r requirements.txt
```

### 2. Get your free Gemini API key
→ Go to [aistudio.google.com](https://aistudio.google.com)  
→ Click "Get API Key" → Copy it

### 3. Add your key
Open `config.py` and replace:
```python
GEMINI_API_KEY = "your_gemini_api_key_here"
```

### 4. Run it
```bash
python app.py
```

Open your browser → `http://localhost:5000`

### 📱 Use on Android (same WiFi)
```bash
# Find your IP
ipconfig        # Windows
ip a            # Linux
```
Then open `http://<your-ip>:5000` in your phone browser.

---

## 🛠️ Tech Stack

| Layer    | Tech                        |
|----------|-----------------------------|
| Backend  | Python 3.10+, Flask         |
| AI Model | Google Gemini 2.0 Flash     |
| Frontend | HTML, CSS, Vanilla JS       |
| Styling  | Custom CSS, Google Fonts    |

---

## 🎨 Customizing the Persona

All in `config.py`:
```python
BOT_NAME = "Kuromi-chan"       # Change the name
SYSTEM_PROMPT = "..."          # Change the whole personality
```

---

## 📄 License

MIT — do whatever, just don't blame me if Kuromi-chan roasts you.
