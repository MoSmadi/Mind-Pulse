import json
import os
from datetime import datetime, timedelta
from collections import Counter
import openai
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

MOOD_LOG_FILE = "mood_logs.json"

# -------------------- Storage --------------------

def load_logs():
    if not os.path.exists(MOOD_LOG_FILE):
        return []
    with open(MOOD_LOG_FILE, "r") as f:
        return json.load(f)

def save_logs(logs):
    with open(MOOD_LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)

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

# -------------------- Weekly Summary --------------------

def get_weekly_logs(user_id):
    logs = load_logs()
    one_week_ago = datetime.utcnow() - timedelta(days=7)
    return [
        entry for entry in logs
        if entry["user_id"] == user_id and datetime.fromisoformat(entry["timestamp"]) >= one_week_ago
    ]

def generate_weekly_report(user_id):
    logs = get_weekly_logs(user_id)
    if not logs:
        return "No messages logged for you in the past 7 days."

    # Mood distribution
    mood_counts = Counter(entry["sentiment"] for entry in logs)
    total = sum(mood_counts.values())
    mood_summary = "\n".join([
        f"- {label.capitalize()}: {count} ({(count/total)*100:.0f}%)"
        for label, count in mood_counts.items()
    ])

    # Filter only pain points
    pain_points = [entry for entry in logs if entry["sentiment"] == "negative" or entry["score"] < -0.4]

    reflections = []
    for entry in pain_points:
        suggestion = suggest_better_response(entry["content"])
        time = datetime.fromisoformat(entry["timestamp"]).strftime("%A %H:%M")
        reflections.append(
            f"🕒 **{time}**\n💬 *\"{entry['content']}\"*\n💡 {suggestion}"
        )

    return (
        f"🧘 **Your Weekly Mood Report**\n\n"
        f"**Mood Summary:**\n{mood_summary}\n\n"
        f"**Situations to Reflect On:**\n" +
        ("\n\n".join(reflections) if reflections else "✅ No major concerns this week — great job!")
    )

# -------------------- GPT Suggestion --------------------

def suggest_better_response(text):
    prompt = (
        f"A user said this in a work chat:\n"
        f"\"{text}\"\n\n"
        f"It feels emotionally intense. Suggest how they could reframe it in a calmer, more professional way. "
        f"Keep it short (1-2 sentences), supportive, and clear."
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a supportive emotional wellness assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=150
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        print("❌ GPT Error:", e)
        return "Try to pause and rephrase how you express frustration to avoid escalation."

def get_team_summary(manager_id):
    from roles import get_users_for_manager
    users = get_users_for_manager(manager_id)
    logs = load_logs()

    # Filter logs to only the manager's users (last 7 days)
    cutoff = datetime.utcnow() - timedelta(days=7)
    relevant_logs = [
        entry for entry in logs
        if entry["user_id"] in users and datetime.fromisoformat(entry["timestamp"]) >= cutoff
    ]

    if not relevant_logs:
        return "📉 No mood data from your team this week."

    mood_counts = Counter(entry["sentiment"] for entry in relevant_logs)
    total = sum(mood_counts.values())

    # Get most dominant mood
    most_common = mood_counts.most_common(1)[0]
    label, count = most_common
    percent = int((count / total) * 100)

    return f"📊 Your team's overall feel is: **{percent}% {label.capitalize()}**"
