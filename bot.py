import discord
import os
from dotenv import load_dotenv
from sentiment import analyze_sentiment
from summary import log_mood
from summary import generate_weekly_report
from summary import suggest_better_response



from consent import add_consent, remove_consent, has_consented

# Load API keys
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
TRUSTED_ADMINS = ["938081224864440331"]

# Debug print
print("📦 Loaded Token:", "Yes ✅" if TOKEN else "❌ Missing!")

# Configure bot intents
intents = discord.Intents.default()
intents.message_content = True  # Needed to read messages
intents.members = True          # Needed to fetch users later

# Create Discord client
client = discord.Client(intents=intents)

# When bot starts
@client.event
async def on_ready():
    print(f"✅ {client.user} is now online and connected!")

# Listen for all messages
@client.event
async def on_message(message):
    # 🚫 Ignore bot's own messages to avoid self-replies
    if message.author == client.user:
        return

    user_id = str(message.author.id)

    # ✅ Step 1: Opt-in command
    if message.content.lower() == "!consent":
        add_consent(user_id)
        await message.channel.send(f"{message.author.name}, you've been added to MindPulse tracking ✅")
        return

    # ❌ Step 2: Opt-out command
    if message.content.lower() == "!logout":
        remove_consent(user_id)
        await message.channel.send(f"{message.author.name}, you've been removed from tracking 💤")
        return

    # 📬 Step 3: Weekly report command
    if message.content.lower() == "!weekly":
        from summary import generate_weekly_report
        report = generate_weekly_report(user_id)
        try:
            await message.author.send(report)
            await message.channel.send("📬 Your weekly report has been sent via DM.")
        except:
            await message.channel.send("❌ I couldn't DM you. Check your privacy settings.")
        return
    
    # Step X: Manager requests team summary
    if message.content.lower() == "!team":
        from summary import get_team_summary
        manager_id = str(message.author.id)
        summary = get_team_summary(manager_id)
        await message.channel.send(summary)
        return
    
    # ✅ Step: Assign users to a manager
    if message.content.lower().startswith("!assign"):
        if str(message.author.id) not in TRUSTED_ADMINS:
            await message.channel.send("❌ You don’t have permission to run this command.")
            return

        if not message.mentions or len(message.mentions) < 2:
            await message.channel.send("⚠️ Usage: `!assign @manager @user1 @user2 ...`")
            return

        from roles import assign_user_to_manager

        manager = message.mentions[0]
        users = message.mentions[1:]

        for user in users:
            assign_user_to_manager(str(manager.id), str(user.id))

        user_names = ", ".join([user.name for user in users])
        await message.channel.send(
            f"✅ Assigned {user_names} to manager {manager.name}."
        )
        return
    
    if message.content.lower() == "!myteam":
        from roles import get_users_for_manager
        team = get_users_for_manager(str(message.author.id))
        if not team:
            await message.channel.send("👥 You don't manage anyone yet.")
        else:
            names = []
            for uid in team:
                user = await client.fetch_user(int(uid))
                names.append(user.name)
            await message.channel.send("👥 Your team: " + ", ".join(names))
        return
    
    # 📖 Help command
    if message.content.lower() == "!help":
        help_text = (
            "**📖 MindPulse Bot Commands**\n"
            "`!consent` — Opt in to mood tracking\n"
            "`!logout` — Opt out of tracking\n"
            "`!weekly` — Get your weekly mood report via DM\n"
            "`!team` — (Managers only) View overall mood of your team\n"
            "`!myteam` — (Managers only) List your assigned team members\n"
            "`!assign @manager @user1...` — (Admin only) Assign users to a manager\n"
            "`!help` — Show this help message"
        )
        await message.channel.send(help_text)
        return

    # 🔒 Step 4: Only proceed if user has opted in
    if not has_consented(user_id):
        return

    # 🧠 Step 5: Analyze sentiment of the message
    from sentiment import analyze_sentiment
    from summary import log_mood, suggest_better_response
    sentiment = analyze_sentiment(message.content)
    label = sentiment["label"]
    score = sentiment["score"]

    # 🗂️ Step 6: Log the message to mood_logs.json
    log_mood(user_id, message.content, sentiment)

    # ⚠️ Step 7: Check if message is harmful
    if is_harmful_message(message.content, score):
        await send_calming_dm(message.author, message.content)

    # 💬 Step 8: Send normal mood reflection as DM
    try:
        await message.author.send(
            f"🧠 Your message felt **{label}** "
            f"(score: {score:.2f}). Keep taking care of yourself 💙"
        )
    except Exception as e:
        print(f"❌ Could not DM {message.author.name}: {e}")


# ✅ Harmful message detection
def is_harmful_message(text, score):
    aggressive_keywords = [
        "idiot", "stupid", "shut up", "useless", "trash", "hate you", "wtf", "dumb",
        "kill yourself", "nonsense", "disgusting", "worthless"
    ]
    lowered = text.lower()
    keyword_hit = any(word in lowered for word in aggressive_keywords)
    sentiment_hit = score < -0.6
    return keyword_hit or sentiment_hit

# ✅ Calming response via GPT
async def send_calming_dm(user, original_text):
    try:
        suggestion = suggest_better_response(original_text)
        await user.send(
            f"🧘 Hey {user.name}, I noticed your recent message felt a bit intense:\n\n"
            f"💬 *\"{original_text}\"*\n\n"
            f"{suggestion}\n\n"
            f"Take a deep breath — you’ve got this. 💙"
        )
    except Exception as e:
        print(f"❌ Couldn’t DM calming message to {user.name}: {e}")

client.run(TOKEN)