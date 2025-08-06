# bot.py
import discord
import os
from dotenv import load_dotenv
from sentiment import analyze_sentiment
from summary import log_mood, get_today_summary
from consent import add_consent, has_consented, remove_consent
from discord.ext import tasks
from consent import load_consents
from summary import generate_weekly_report
from datetime import datetime
import asyncio



load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True  # This is required to read messages

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'{client.user} is online and connected to Discord!')
    send_weekly_reports.start()


# @tasks.loop(hours=24)
@tasks.loop(seconds=10)  # for test purposes only
async def send_weekly_reports():
    # Only run on Sunday
    # if datetime.utcnow().weekday() != 6:  # Sunday = 6
    if False:  # disable day check just for test
        return

    print("📤 Sending weekly reports...")
    for user_id in load_consents():
        try:
            user = await client.fetch_user(int(user_id))
            report = generate_weekly_report(user_id)
            await user.send(report)
            print(f"✅ Sent weekly report to {user.name}")
        except Exception as e:
            print(f"❌ Failed to send weekly report to {user_id}: {e}")


@client.event
async def on_message(message):
    # if message.author == client.user:
    #     return
    
    # if message.content.lower() == "ping":
    #     await message.channel.send("pong!")
    
    # if message.content.lower() == "smadi":
    #     await message.channel.send("is the best")
    
    # if message.content.lower() == "hazem":
    #     await message.channel.send("hahahahahahahhahaha")

    # if message.author.display_name == "Hazem":
    #         await message.channel.send("حازم اسكت تضلكش تحكي -- صمادي سيدك وتاج راسك")
    from sentiment import analyze_sentiment


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    user_id = str(message.author.id)

    # Step 1: Allow user to opt-in
    if message.content.lower() == "!consent":
        add_consent(user_id)
        await message.channel.send(f"{message.author.name}, you've successfully opted in ✅")
        return

    # Step 2: Check if user has consented
    if not has_consented(user_id):
        return  # Ignore their message

    # Step 3: Allow team leads to request summary
    if message.content.lower() == "!summary":
        summary = get_today_summary()
        await message.channel.send(summary)
        return
    
        # Weekly mood report
    if message.content.lower() == "!weekly":
        from summary import generate_weekly_report
        report = generate_weekly_report(user_id)
        try:
            await message.author.send(report)
            await message.channel.send("✅ Weekly report sent to your DM.")
        except:
            await message.channel.send("❌ I couldn’t DM you. Check your privacy settings.")
        return

    
    if message.content.lower() == "!logout":
        remove_consent(user_id)
        await message.channel.send(f"{message.author.name}, you have been unsubscribed from Mind Pulse Bot 💤")
        return


    # Step 4: Skip command messages
    if message.content.startswith("!"):
        return

    # Step 5: Analyze mood
    sentiment = analyze_sentiment(message.content)
    label = sentiment["label"]

    log_mood(user_id, message.content, sentiment)

    try:
        await message.author.send(
            f"Hey {message.author.name}, your message felt **{label}** today "
            f"(score: {sentiment['score']:.2f}). Keep taking care of yourself 💙"
        )
    except:
        print(f"❌ Could not DM {message.author.name}")



        
client.run(TOKEN)
