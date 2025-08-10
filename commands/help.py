# commands/help.py
import os, discord

HELP_TEXT = (
    "**📖 MindPulse Commands**\n"
    "`!consent` — Opt in\n"
    "`!logout` — Opt out\n"
    "`!weekly` — DM me your weekly mood report\n"
    "`!team` — (Managers) Team mood %\n"
    "`!myteam` — (Managers) List your assigned users\n"
    "`!assign @manager @user1 ...` — (Admin) Assign users to a manager\n"
    "`!help` — Show this help"
)

HELP_DM_ONLY = os.getenv("HELP_DM_ONLY", "false").lower() == "true"

async def handle_help(message: discord.Message):
    try:
        if HELP_DM_ONLY:
            await message.author.send(HELP_TEXT)
            try:
                await message.add_reaction("📖")
            except Exception:
                pass
        else:
            await message.channel.send(HELP_TEXT)
    except Exception as e:
        print("Help DM error:", e)
