"""
bot.py
-------
Discord client entrypoint for MindPulse.

What this file does:
- Initializes the Discord client (privileged intents) and slash commands.
- Registers ephemeral slash commands:
  /help, /consent, /logout, /weekly, /team, /myteam, /assign, /mention
- Captures recent conversation context and logs context‑aware sentiment for consented users.
- Triggers real-time harmful-behavior detection (DM coaching with cooldown).
- Delegates all AI work to core/ai.py (centralized), not here.

Notes:
- For fast dev, set GUILD_ID in .env to sync commands instantly to one server.
- Make sure the bot invite includes scope "applications.commands".
"""


import os
from dotenv import load_dotenv
load_dotenv()

import discord
from discord import app_commands

import asyncio

# --- MindPulse modules ---
from commands.consent import add_consent, remove_consent, has_consented
from commands.assign import assign_user_to_manager, get_users_for_manager
from commands.summary import handle_weekly_command  # DMs the weekly report
from commands.monitor import detect_and_handle_harmful  # burst + context + cooldown
from commands.mentions import run_mentions_command
from core.context import ctx_store
from core.sentiment import analyze_sentiment  # thin wrapper over core.ai.ai.sentiment()
from core.analyzer import log_mood, get_team_summary
from core.utils import ensure_dirs

# -------------------------
# Bootstrap & Intents
# -------------------------

TOKEN = os.getenv("DISCORD_TOKEN")

# Optional: limit slash-command sync to a single guild for instant availability
GUILD_ID = os.getenv("GUILD_ID")  # e.g. "123456789012345678"
GUILD = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None

# Privileged intents required for this bot’s features
intents = discord.Intents.default()
intents.message_content = True   # read messages for sentiment + monitoring
intents.members = True           # resolve users for /myteam, /assign

class MindPulseClient(discord.Client):
    """Discord client with an app commands tree attached."""
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

client = MindPulseClient(intents=intents)

# -------------------------
# Helpers
# -------------------------

def _build_context_lines(message: discord.Message, limit: int = 15) -> list[str]:
    """
    Build a compact, recent conversation window for context-aware sentiment.
    - Pulls last N messages from this channel via core.context.ctx_store.
    - Marks lines as "You" vs "Other" relative to current author.
    - Truncates lines to keep tokens under control.
    - Adds replied-to message text (if any) at the end.
    """
    window = ctx_store.window(message.guild.id if message.guild else None,
                              message.channel.id,
                              limit=limit)
    context: list[str] = []
    for m in window:
        speaker = "You" if m.author_id == message.author.id else "Other"
        line = (m.content or "").strip().replace("\n", " ")
        if len(line) > 200:
            line = line[:200] + "…"
        context.append(f"{speaker}: {line}")

    # Include replied-to message content, if present
    if message.reference and message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
        replied = message.reference.resolved
        who = "Other" if replied.author.id != message.author.id else "You"
        txt = (replied.content or "").strip().replace("\n", " ")
        if len(txt) > 200:
            txt = txt[:200] + "…"
        context.append(f"{who} (replied): {txt}")

    return context

# -------------------------
# Lifecycle
# -------------------------

@client.event
async def on_ready():
    """Ensure folders exist and sync slash commands."""
    ensure_dirs()
    try:
        if GUILD:
            # Fast: guild-only sync during development
            client.tree.copy_global_to(guild=GUILD)
            synced = await client.tree.sync(guild=GUILD)
            print(f"🛠️ Slash commands synced to guild {GUILD.id}: {len(synced)}")
        else:
            # Global sync can take up to ~1 hour
            synced = await client.tree.sync()
            print(f"🛠️ Global slash commands synced: {len(synced)} (may take ~1 hour to appear)")
    except Exception as e:
        print("❌ Slash command sync error:", e)

    print(f"✅ {client.user} is online and ready!")

# -------------------------
# Slash Commands (ephemeral)
# -------------------------

@client.tree.command(name="help", description="Show available MindPulse commands")
async def help_cmd(interaction: discord.Interaction):
    help_text = (
        "**📖 MindPulse Commands**\n"
        "/consent — Opt in to mood tracking\n"
        "/logout — Opt out of tracking\n"
        "/weekly — DM your weekly mood report (with chart)\n"
        "/team — (Managers) Your team’s overall mood % (last 7 days)\n"
        "/myteam — (Managers) List your assigned users\n"
        "/assign — (Admin) Assign ONE user to a manager\n"
        "/mention — List your mentions for today or a specific date "
    )
    await interaction.response.send_message(help_text, ephemeral=True)

@client.tree.command(name="consent", description="Opt in to MindPulse tracking")
async def consent_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    add_consent(user_id)
    await interaction.followup.send("You're now opted in to MindPulse ✅", ephemeral=True)

@client.tree.command(name="logout", description="Opt out of MindPulse tracking")
async def logout_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    remove_consent(user_id)
    await interaction.followup.send("You've been unsubscribed from MindPulse 💤", ephemeral=True)

@client.tree.command(name="weekly", description="Send me my weekly mood report (via DM)")
async def weekly_cmd(interaction: discord.Interaction):
    """
    Ephemeral ack, then DM the weekly report (text is chunked; first DM may include a pie chart).
    """
    user_id = str(interaction.user.id)
    if not has_consented(user_id):
        await interaction.response.send_message("Please /consent first to enable reports.", ephemeral=True)
        return

    # Acknowledge immediately so the interaction doesn't time out
    await interaction.response.send_message("📬 Check your DMs for your weekly report.", ephemeral=True)

    # Minimal message-like shim so we can reuse handle_weekly_command(message, user_id)
    class _Shim:
        author = interaction.user
        channel = interaction.channel
        guild = interaction.guild
        async def add_reaction(self, _):
            pass

    try:
        await handle_weekly_command(_Shim(), user_id)
    except Exception as e:
        print("Weekly DM error:", e)

@client.tree.command(name="team", description="(Managers) See your team’s overall mood %")
async def team_cmd(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    summary = get_team_summary(user_id)
    await interaction.response.send_message(summary, ephemeral=True)

@client.tree.command(name="myteam", description="(Managers) List your assigned users")
async def myteam_cmd(interaction: discord.Interaction):
    """
    Defer first (avoids 'Unknown interaction' if lookups take >3s), then follow up ephemerally.
    """
    user_id = str(interaction.user.id)
    await interaction.response.defer(ephemeral=True)

    try:
        team_ids = get_users_for_manager(user_id)
        if not team_ids:
            await interaction.followup.send("👥 You have no assigned team members.", ephemeral=True)
            return

        names: list[str] = []
        for uid in team_ids:
            member = interaction.guild.get_member(int(uid)) if interaction.guild else None
            if member:
                names.append(member.display_name or member.name)
            else:
                try:
                    u = await interaction.client.fetch_user(int(uid))
                    names.append(getattr(u, "global_name", None) or u.name)
                except Exception:
                    names.append(f"(Unknown {uid})")

        await interaction.followup.send("👥 Your team: " + ", ".join(names), ephemeral=True)

    except Exception as e:
        await interaction.followup.send("❌ Failed to load your team. Try again.", ephemeral=True)
        print("myteam error:", e)

@client.tree.command(name="assign", description="(Admin) Assign ONE user to a manager")
@app_commands.describe(manager="Manager to assign to", user="User to add under this manager")
async def assign_cmd(interaction: discord.Interaction, manager: discord.Member, user: discord.Member):
    # (Optional) Enforce admin role/ID checks here
    assign_user_to_manager(str(manager.id), str(user.id))
    await interaction.response.send_message(
        f"✅ Assigned **{user.display_name}** to manager **{manager.display_name}**.",
        ephemeral=True
    )

@client.tree.command(name="mentions", description="List your mentions for today or a specific date")
@app_commands.describe(date="Use 'today', 'yesterday', or YYYY-MM-DD")
async def mentions_cmd(interaction: discord.Interaction, date: str | None = None):
    # Instant ack so we never hit 10062
    await interaction.response.send_message("🔎 Gathering your mentions…", ephemeral=True)

    # Run the heavy work without blocking the event loop
    async def _work():
        from commands.mentions import run_mentions_command
        await run_mentions_command(interaction, date_text=date)

    # Don’t await here; do it in the background so the ack is immediate
    asyncio.create_task(_work())


# -------------------------
# Passive Monitoring & Logging
# -------------------------

@client.event
async def on_message(message: discord.Message):
    """
    Passive pipeline for each message by consented users:
    1) Add message to context store (per guild/channel).
    2) Build compact context lines (You/Other).
    3) Analyze sentiment (context-aware via core.ai).
    4) Persist to weekly logs (core.analyzer.log_mood).
    5) Trigger harmful-behavior detection (commands.monitor).
    """
    if message.author == client.user:
        return

    user_id = str(message.author.id)
    if not has_consented(user_id):
        return

    # 1) Add this message to the rolling context
    ctx_store.add(
        message.guild.id if message.guild else None,
        message.channel.id,
        message.author.id,
        message.content or ""
    )

    # 2) Build context window for the AI
    context_lines = _build_context_lines(message, limit=15)

    # 3) Context-aware sentiment (centralized via core.ai), off the event loop
    import asyncio
    sentiment_result = await asyncio.to_thread(
        analyze_sentiment,
        message.content or "",
        context_lines=context_lines,
    )

    # 4) Store for weekly reporting & team summaries
    log_mood(user_id, message.content or "", sentiment_result)

    # 5) Harmful-behavior detection (multilingual, burst-aware, DM with cooldown)
    await detect_and_handle_harmful(message)

# -------------------------
# Run
# -------------------------

if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_TOKEN missing in .env")
        raise SystemExit(1)

    client.run(TOKEN)
