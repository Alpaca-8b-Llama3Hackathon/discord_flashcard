import PyPDF2
import io
import asyncio
import requests

from together import Together
from os import remove
from json import load
from io import BytesIO
from aiosqlite import connect
from asyncio import sleep, run
# from freeGPT import AsyncClient
from discord.ui import Button, View
from discord.ext.commands import Bot
from dotenv import load_dotenv
from aiohttp import ClientSession, ClientError
from discord import Intents, Embed, File, Status, Activity, ActivityType, Colour, Attachment
from discord.app_commands import (
    describe,
    checks,
    BotMissingPermissions,
    MissingPermissions,
    CommandOnCooldown,
)

from flashcard_backend.question import get_questions

import discord
import os

path = "pdf path" #Path of file
questions_and_answers = get_questions(path, api_key=os.getenv("TOGETHER_API_KEY"))
text = []
for question, answer in questions_and_answers:
    text.append([question, answer])


def initialize_together_client():
    api_key = os.getenv("TOGETHER_API_KEY")
    if not api_key:
        raise ValueError("TOGETHER_API_KEY environment variable is not set")
    return Together(api_key=api_key)

intents = Intents.default()
intents.message_content = True
bot = Bot(command_prefix="!", intents=intents, help_command=None)
db = None
textCompModels = ["llama3"]
# imageGenModels = ["prodia", "pollinations"]

async def process_pdf(attachment: Attachment):
    pdf_content = await attachment.read()
    pdf_file = io.BytesIO(pdf_content)
    
    text = ""
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        for page in pdf_reader.pages:
            text += page.extract_text()
    except Exception as e:
        print(f"Error processing PDF: {str(e)}")
        return None
    
    return text

async def generate_text(prompt):
    try:
        messages = [{"role": "user", "content": prompt}]
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="meta-llama/Meta-Llama-3-8B-Instruct-Turbo",
            messages=messages,
            temperature=0.7,
        )
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content
        else:
            print("No choices in response")
            return None
    except Exception as e:
        print(f"Error generating text: {str(e)}")
        return None

# Listener for bot initialization
@bot.event
async def on_ready():
    print(f"\033[1;94m INFO \033[0m| {bot.user} has connected to Discord.")
    global client
    client = initialize_together_client()
    global db
    db = await connect("database.db")
    async with db.cursor() as cursor:
        await cursor.execute(
            "CREATE TABLE IF NOT EXISTS database(guilds INTEGER, channels INTEGER, models TEXT)"
        )
    print("\033[1;94m INFO \033[0m| Database connection successful.")
    sync_commands = await bot.tree.sync()
    print(f"\033[1;94m INFO \033[0m| Synced {len(sync_commands)} command(s).")
    while True:
        await bot.change_presence(
            status=Status.online,
            activity=Activity(
                type=ActivityType.watching,
                name=f"{len(bot.guilds)} servers | /help",
            ),
        )
        await sleep(300)

# WA Content
qa_mode = False
num_question = -1
qa_template = "Question! : "

@bot.tree.command(name="genflashcard", description="Send PDF File")
async def gen_flashcard(interaction,qa_size:int):
    global qa_mode
    global num_question
    num_question = qa_size - 1
    qa_mode = True
    num_question -= 1
    await interaction.response.send_message("Start Question\n" + qa_template + text[num_question+1][0])
    # num_question -= 1

@bot.event
async def on_message(message):
    
    global qa_mode
    global num_question
    if(message.author == bot.user):
        return

    if(num_question < 0 and qa_mode):
        qa_mode = False
        num_question = -1
        await message.channel.send("Ending Flashcard")
    if(qa_mode and num_question >= 0):
        # await message.channel.send("True")
        num_question -= 1
        await message.channel.send(qa_template + text[num_question+1][0])
        # print("chk")
        # num_question -= 1
        
    await bot.process_commands(message)

# Event Listener on remove
@bot.event
async def on_guild_remove(guild):
    await db.execute("DELETE FROM database WHERE guilds = ?", (guild.id,))
    await db.commit()

# Logging Error
@bot.tree.error
async def on_app_command_error(interaction, error):
    if isinstance(error, CommandOnCooldown):
        embed = Embed(
            description=f"This command is on cooldown, try again in {error.retry_after:.2f} seconds.",
            colour=Colour.red(),
        )
        await interaction.response.send_message(embed=embed)
    elif isinstance(error, MissingPermissions):
        embed = Embed(
            description=f"**Error:** You are missing the `{error.missing_permissions[0]}` permission to run this command.",
            colour=Colour.red(),
        )
    elif isinstance(error, BotMissingPermissions):
        embed = Embed(
            description=f"**Error:** I am missing the `{error.missing_permissions[0]}` permission to run this command.",
            colour=Colour.red(),
        )
        await interaction.response.send_message(embed=embed)
    else:
        embed = Embed(
            title="An error occurred:",
            description=error,
            color=Colour.red(),
        )
        view = View()
        view.add_item(
            Button(
                label="Report this error",
                url="https://discord.gg/3uUpcRAnDp",
            )
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

#Upload File PDF
@bot.tree.command(name="send", description="Send PDF File")
async def pdf_file(interaction,pdf: discord.Attachment):
    
    await interaction.response.send_message("OK")
    # print(str)
    attachment_url = pdf.url
    print(attachment_url)
    file_request = requests.get(attachment_url)

    # Save File
    if file_request.status_code == 200:
        with open("file.pdf", "wb") as file:
            file.write(file_request.content)
            print("File downloaded successfully!")
    else:
        print("Failed to download the file.")

# Helper function
@bot.tree.command(name="help", description="Get help.")
async def help(interaction):
    embed = Embed(
        title="Help Menu",
        color=0x00FFFF,
    )

    embed.add_field(
        name="Models:",
        value=f"**Text Completion:** `{', '.join(textCompModels)}`",
        inline=False,
    )

    embed.add_field(
        name="Chatbot",
        value="Setup the chatbot: `/setup-chatbot`.\nReset the chatbot: `/reset-chatbot`.",
        inline=False,
    )
    view = View()
    view.add_item(
        Button(
            label="Invite Me",
            url="https://discord.com/oauth2/authorize?client_id=1263923201193414776&permissions=8&integration_type=0&scope=bot",
        )
    )
    view.add_item(
        Button(
            label="Support Server",
            url="https://discord.gg/YOUR_SUPPORT_SERVER_INVITE",
        )
    )
    view.add_item(
        Button(
            label="Source",
            url="https://github.com/Alpaca-8b-Llama3Hackathon/discord_flashcard",
        )
    )
    await interaction.response.send_message(embed=embed, view=view)

# /ask function
@bot.tree.command(name="ask", description="Ask Llama 3 a question.")
@describe(prompt="Your prompt.")
async def ask(interaction, prompt: str):
    try:
        await interaction.response.defer()
        resp = await generate_text(prompt)
        if resp:
            if len(resp) <= 2000:
                await interaction.followup.send(resp)
            else:
                file = File(fp=BytesIO(resp.encode("utf-8")), filename="message.txt")
                await interaction.followup.send(file=file)
        else:
            await interaction.followup.send("Sorry, I couldn't generate a response.")
    except Exception as e:
        await interaction.followup.send(str(e))

# Load LMs/GPT model
@bot.tree.command(name="setup-chatbot", description="Setup the chatbot.")
@checks.has_permissions(manage_channels=True)
@checks.bot_has_permissions(manage_channels=True)
@describe(model=f"Model to use. Choose between {', '.join(textCompModels)}")
async def setup_chatbot(interaction, model: str):
    if model.lower() not in textCompModels:
        await interaction.response.send_message(
            f"**Error:** Model not found! Choose a model between `{', '.join(textCompModels)}`."
        )
        return

    cursor = await db.execute(
        "SELECT channels, models FROM database WHERE guilds = ?",
        (interaction.guild.id,),
    )
    data = await cursor.fetchone()
    if data:
        await interaction.response.send_message(
            "**Error:** The chatbot is already set up. Use the `/reset-chatbot` command to fix this error."
        )
        return

    if model.lower() in textCompModels:
        channel = await interaction.guild.create_text_channel(
            "freegpt-chat", slowmode_delay=15
        )

        await db.execute(
            "INSERT OR REPLACE INTO database (guilds, channels, models) VALUES (?, ?, ?)",
            (
                interaction.guild.id,
                channel.id,
                model,
            ),
        )
        await db.commit()
        await interaction.response.send_message(
            f"**Success:** The chatbot has been set up. The channel is {channel.mention}."
        )
    else:
        await interaction.response.send_message(
            f"**Error:** Model not found! Choose a model between `{', '.join(textCompModels)}`."
        )

# Reset the chatbot model
@bot.tree.command(name="reset-chatbot", description="Reset the chatbot.")
@checks.has_permissions(manage_channels=True)
@checks.bot_has_permissions(manage_channels=True)
async def reset_chatbot(interaction):
    cursor = await db.execute(
        "SELECT channels, models FROM database WHERE guilds = ?",
        (interaction.guild.id,),
    )
    data = await cursor.fetchone()
    if data:
        channel = await bot.fetch_channel(data[0])
        await channel.delete()
        await db.execute(
            "DELETE FROM database WHERE guilds = ?", (interaction.guild.id,)
        )
        await db.commit()
        await interaction.response.send_message(
            "**Success:** The chatbot has been reset."
        )

    else:
        await interaction.response.send_message(
            "**Error:** The chatbot is not set up. Use the `/setup-chatbot` command to fix this error."
        )

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if db:
        cursor = await db.execute(
            "SELECT channels, models FROM database WHERE guilds = ?",
            (message.guild.id,),
        )

        data = await cursor.fetchone()
        if data:
            channel_id, model = data
            if message.channel.id == channel_id:
                await message.channel.edit(slowmode_delay=15)
                async with message.channel.typing():
                    if message.attachments:
                        attachment = message.attachments[0]
                        if attachment.filename.lower().endswith('.pdf'):
                            pdf_text = await process_pdf(attachment)
                            if pdf_text:
                                resp = await AsyncClient.create_completion(
                                    model,
                                    f"PDF content: {pdf_text[:1000]}... (truncated). Prompt: {message.content}"
                                )
                            else:
                                resp = "Sorry, I couldn't process the PDF file."
                        elif attachment.url.endswith(".png"):
                            temp_image = "temp_image.jpg"
                            async with ClientSession() as session:
                                async with session.get(message.attachments[0].url) as image:
                                    image_content = await image.read()
                                    with open(temp_image, "wb") as file:
                                        file.write(image_content)
                                    try:
                                        with open(temp_image, "rb") as file:
                                            data = file.read()
                                    finally:
                                        remove(temp_image)
                                    async with session.post(
                                        "https://api-inference.huggingface.co/models/Salesforce/blip-image-captioning-large",
                                        data=data,
                                        headers={"Authorization": f"Bearer {HF_TOKEN}"},
                                        timeout=20,
                                    ) as resp:
                                        resp_json = await resp.json()
                                        if resp.status != 200:
                                            raise ClientError(
                                                "Unable to fetch the response."
                                            )
                                        resp = await AsyncClient.create_completion(
                                            model,
                                            f"Image detected, description: {resp_json[0]['generated_text']}. Prompt: {message.content}",
                                        )
                    else:
                        resp = await AsyncClient.create_completion(
                            model, message.content
                        )
                        if (
                            "@everyone" in resp
                            or "@here" in resp
                            or "<@" in resp
                            and ">" in resp
                        ):
                            resp = (
                                resp.replace("@everyone", "@|everyone")
                                .replace("@here", "@|here")
                                .replace("<@", "<@|")
                            )
                        if len(resp) <= 2000:
                            await message.reply(resp, mention_author=False)
                        else:
                            await message.reply(
                                file=File(
                                    fp=BytesIO(resp.encode("utf-8")),
                                    filename="message.txt",
                                ),
                                mention_author=False,
                            )


if __name__ == "__main__":
    # Public
    # HF_TOKEN = os.getenv('HF_TOKEN')
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    # BOT_TOKEN = ""
    run(bot.run(BOT_TOKEN))

    # # Private
    # with open("config.json", "r") as file:
    #     data = load(file)
    # HF_TOKEN = data["HF_TOKEN"]
    # run(bot.run(data["BOT_TOKEN"]))
