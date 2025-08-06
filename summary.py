import json
import os
from datetime import datetime, timedelta
from collections import Counter
from dotenv import load_dotenv
import openai

# Load API key
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

MOOD_LOG_FILE = "mood_logs.json"

# ------------------ Persistence ------------------

def load_logs():
    if not os.path.exists(MOOD_LOG_FILE):
        return []
    with open(MOOD_LOG_FILE, "r") as f:
        return json.load(f)

def save_logs(logs):
    with open(MOOD_LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)

# ------------------ Logging ------------------

def log_mood(user_id, text, sentiment_result):
    logs = load_logs()
    logs.append({
        "user_id": user_id,
        "timestamp": datetime.utcnow().isoformat(),
        "content": text,
        "sentiment": sentiment_result["label"],
        "score": sentiment_result["score"]
    })
    save_logs(logs)

# ------------------ Summaries ------------------

def get_today_summary():
    logs = load_logs()
    today = datetime.utcnow().date()
    counts = Counter()

    for entry in logs:
        timestamp = datetime.fromisoformat(entry["timestamp"])
        if timestamp.date() == today:
            counts[entry["sentiment"]] += 1

    total = sum(counts.values())
    if total == 0:
        return "No mood data recorded today yet."

    lines = [f"{label.capitalize()}: {count} ({(count/total)*100:.0f}%)"
             for label, count in counts.items()]
    return "**Team Mood Summary** (Today):\n" + "\n".join(lines)

def get_weekly_logs(user_id):
    logs = load_logs()
    one_week_ago = datetime.utcnow() - timedelta(days=7)
    return [
        entry for entry in logs
        if entry["user_id"] == user_id and datetime.fromisoformat(entry["timestamp"]) >= one_week_ago
    ]

# ------------------ Weekly Report ------------------

def generate_weekly_report(user_id):
    logs = get_weekly_logs(user_id)
    if not logs:
        return "No messages logged for you in the past 7 days."

    mood_counts = Counter(log["sentiment"] for log in logs)
    total = sum(mood_counts.values())

    mood_summary = "\n".join([
        f"- {label.capitalize()}: {count} ({(count/total)*100:.0f}%)"
        for label, count in mood_counts.items()
    ])

    # Extract key moments for feedback
    flagged = []
    for log in logs:
        if log["sentiment"] == "negative" or log["score"] < -0.4:
            flagged.append(log)

    suggestions = []
    for entry in flagged:
        suggestion = suggest_better_response(entry["content"])
        time = datetime.fromisoformat(entry["timestamp"]).strftime("%A %H:%M")
        suggestions.append(
            f"🕒 **{time}**\n"
            f"💬 *\"{entry['content']}\"*\n"
            f"💡 {suggestion}"
        )

    return (
        f"🧘 **Your Weekly Mood Report**\n\n"
        f"**Mood Distribution:**\n{mood_summary}\n\n"
        f"**Situations to Reflect On:**\n"
        + ("\n\n".join(suggestions) if suggestions else "✅ No major concerns this week — great job staying balanced!")
    )

# ------------------ GPT-Powered Suggestion ------------------

def suggest_better_response(text):
    prompt = (
        f"A user wrote this message in a workplace chat:\n\n"
        f"\"{text}\"\n\n"
        f"It sounds emotionally intense or negative. Give constructive, calm advice on how to express themselves better next time, "
        f"and suggest a more professional way to handle the situation. Keep the tone warm and supportive. Reply in 2–3 sentences."
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful and friendly mental wellness assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=150
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        print("❌ OpenAI API error:", e)
        return "Try to stay calm and express your frustration constructively. It helps to explain the issue and suggest a solution."
