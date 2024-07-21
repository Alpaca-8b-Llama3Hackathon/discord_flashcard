import discord
from discord import app_commands
from discord.ext import commands
import os
from dotenv import load_dotenv
from pathlib import Path
import aiosqlite
import PyPDF2
from dataclasses import dataclass
import asyncio
from llama_index.llms.openai_like import OpenAILike
from llama_index.core.node_parser import SentenceSplitter
from PyPDF2 import PdfReader
import re
from llama_index.core import Document
from typing import List, Tuple
from llama_index.core.extractors import QuestionsAnsweredExtractor
from llama_index.core.node_parser import TokenTextSplitter
from llama_index.core.schema import MetadataMode
from llama_index.core.ingestion import IngestionPipeline

question_template = """\
Here is the context:
{context_str}

Given the contextual information, \
generate {num_questions} questions this context can provide \
specific answers to which are unlikely to be found elsewhere.

Higher-level summaries of surrounding context may be provided \
as well. Try using these summaries to generate better questions \
that this context can answer. \

Please Reply with only the questions and answer. \
    Examples of questions and answer: \
- Question 1 : What is the main idea of the text? \
    Answer 1 : Answer your Question \
- Question 2 : What is the author's purpose in writing the text? \
    Answer 2 : Answer your Question \
"""

def extract_qa_pairs(qa_string):
    pattern = r'\*\*Question (\d+):\*\* (.*?)\s*\*\*Answer \1:\*\* (.*?)(?=\*\*|$)'
    matches = re.findall(pattern, qa_string, re.DOTALL)
    qa_pairs = [{"question": q.strip(), "answer": a.strip()} for _, q, a in matches]
    return qa_pairs

def get_questions(file: str, api_key: str, question_template: str = question_template) -> List[Tuple[str, str]]:
    assert "{context_str}" in question_template, "Prompt template must contain {context_str} placeholder"
    assert "{num_questions}" in question_template, "Prompt template must contain {num_questions} placeholder"

    file = PdfReader(file)
    text = ""
    for page in file.pages:
        text += page.extract_text()

    llm = OpenAILike(
        model="meta-llama/Llama-3-70b-chat-hf",
        api_base="https://api.together.xyz/v1",
        api_key=api_key,
        is_chat_model=True,
        is_function_calling_model=True,
        temperature=0.6,
    )
    splitter = SentenceSplitter(chunk_size=2400, chunk_overlap=500)
    nodes = splitter.get_nodes_from_documents([Document(text=text)])
    text_splitter = TokenTextSplitter(
        separator=" ", chunk_size=768, chunk_overlap=128
    )

    question_generator = QuestionsAnsweredExtractor(
        questions=2, metadata_mode=MetadataMode.EMBED, prompt_template=question_template, llm=llm)
    question_gen_pipeline = IngestionPipeline(transformations=[text_splitter, question_generator])
    questions = question_gen_pipeline.run(nodes=nodes)
    
    results = []
    for question in questions:
        qa = str(question.to_dict()['metadata']['questions_this_excerpt_can_answer'])
        qa_pairs = extract_qa_pairs(qa)
        for i, pair in enumerate(qa_pairs, 1):
            results.append((pair['question'], pair['answer']))

    return results      

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
TOGETHER_API_KEY = os.getenv('TOGETHER_API_KEY')

# Set up intents
intents = discord.Intents.default()
intents.message_content = True

# Create bot instance
bot = commands.Bot(command_prefix='/', intents=intents)

# Database connection
db = None

@dataclass
class Question:
    score: float
    question: str
    answer: str
    index: int

class QAView(discord.ui.View):
    def __init__(self, qa_pairs):
        super().__init__(timeout=None)
        self.qa_pairs = [Question(0, question, answer, i) for i, (question, answer) in enumerate(qa_pairs)]
        self.colors = [discord.Color.random() for _ in range(len(self.qa_pairs))]
        self.current_index = 0

    def update_qa(self, index, score):
        self.qa_pairs[index].score += score
        if self.qa_pairs[index].score >= 8:
            self.qa_pairs.pop(index)
            return
        self.qa_pairs[index].score = max(0, self.qa_pairs[index].score)
        insert_index = min(self.qa_pairs[index].score + score, len(self.qa_pairs) - 1)
        self.qa_pairs.insert(insert_index, self.qa_pairs.pop(index))

    @discord.ui.button(label="", style=discord.ButtonStyle.red, custom_id="rate_1", emoji="💀")
    async def rate_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.rate_question(interaction, -1)

    @discord.ui.button(label="", style=discord.ButtonStyle.gray, custom_id="rate_2", emoji="2️⃣")
    async def rate_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.rate_question(interaction, 2)

    @discord.ui.button(label="", style=discord.ButtonStyle.gray, custom_id="rate_3", emoji="3️⃣")
    async def rate_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.rate_question(interaction, 3)

    @discord.ui.button(label="", style=discord.ButtonStyle.gray, custom_id="rate_4", emoji="4️⃣")
    async def rate_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.rate_question(interaction, 4)

    @discord.ui.button(label="", style=discord.ButtonStyle.green, custom_id="rate_5", emoji="👑")
    async def rate_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.rate_question(interaction, 5)

    async def rate_question(self, interaction: discord.Interaction, score: int):
        self.update_qa(self.current_index, score)
        if len(self.qa_pairs) == 0:
            await self.show_successful_embed(interaction)
        else:
            await self.update_message(interaction)

    @discord.ui.button(label="Show Answer", style=discord.ButtonStyle.secondary, custom_id="show_answer")
    async def show_answer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.qa_pairs) == 0:
            await self.show_successful_embed(interaction)
        else:
            question_no = self.qa_pairs[self.current_index].index + 1
            answer_embed = discord.Embed(title=f"Answer Question: {question_no}", color=discord.Color.green())
            answer_embed.add_field(name="Answer", value=self.qa_pairs[self.current_index].answer, inline=False)
            await interaction.response.edit_message(embeds=[self.get_embed(), answer_embed], view=self)
      
    def get_embed(self):
        if len(self.qa_pairs) == 0:
            return self.get_successful_embed()
        current_pair = self.qa_pairs[self.current_index]
        embed = discord.Embed(title=f"{len(self.qa_pairs)} questions remaining..", color=self.colors[current_pair.index])
        embed.add_field(name=f"Question #: {current_pair.index+1}", value=current_pair.question, inline=False)
        return embed

    def get_successful_embed(self):
        embed = discord.Embed(title="Congratulations! 🎉", color=discord.Color.gold())
        embed.description = "You've completed all the flashcards!"
        embed.add_field(name="Great job!", value="You've mastered all the questions. Keep up the good work!", inline=False)
        return embed

    async def update_message(self, interaction: discord.Interaction):
        if len(self.qa_pairs) == 0:
            await self.show_successful_embed(interaction)
        else:
            await interaction.response.edit_message(embeds=[self.get_embed()], view=self)

    async def show_successful_embed(self, interaction: discord.Interaction):
        successful_embed = self.get_successful_embed()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embeds=[successful_embed], view=self)

async def process_pdf(pdf_file: str):
    try:
        with open(pdf_file, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            return ' '.join(page.extract_text() for page in pdf_reader.pages)
    except Exception as e:
        print(f"Error processing PDF: {str(e)}")
        return None

async def get_pdf_file_content(index, user_id):
    async with db.execute("SELECT pdf_path FROM pdfs WHERE id = ? AND user_id = ?", (index, user_id)) as cursor:
        pdf_path = await cursor.fetchone()
    
    if not pdf_path:
        return ("error", "PDF content not found. Please enter a valid index number.", "")
    
    pdf_content = await process_pdf(pdf_path[0])
    return ("success", pdf_content, pdf_path[0])

@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")
    global db
    db = await aiosqlite.connect("database.db")
    
    # Check if the old tables exist and create new ones if they don't
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pdfs'") as cursor:
        if not await cursor.fetchone():
            await db.execute(
                "CREATE TABLE pdfs (user_id INTEGER, pdf_path TEXT, pdf_title TEXT, id INTEGER PRIMARY KEY)"
            )
        else:
            # Alter the existing table to add user_id column if it doesn't exist
            try:
                await db.execute("ALTER TABLE pdfs ADD COLUMN user_id INTEGER DEFAULT 0")
            except aiosqlite.OperationalError:
                # Column already exists, ignore the error
                pass

    async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='flashcards'") as cursor:
        if not await cursor.fetchone():
            await db.execute(
                "CREATE TABLE flashcards (user_id INTEGER, questions TEXT, answers TEXT, pdf_index INTEGER, id INTEGER PRIMARY KEY)"
            )
        else:
            # Alter the existing table to add user_id column if it doesn't exist
            try:
                await db.execute("ALTER TABLE flashcards ADD COLUMN user_id INTEGER DEFAULT 0")
            except aiosqlite.OperationalError:
                # Column already exists, ignore the error
                pass

    await db.commit()
    print("Database connection successful and tables updated.")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

@bot.tree.command(name="upload_pdf", description="Upload a PDF file")
@app_commands.describe(attachment="The PDF file to upload")
async def upload_pdf(interaction: discord.Interaction, attachment: discord.Attachment):
    if not attachment.filename.lower().endswith('.pdf'):
        await interaction.response.send_message("Please upload a PDF file.", ephemeral=True)
        return

    await interaction.response.defer()

    save_dir = Path(__file__).parent / "temp" / attachment.filename
    save_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        await attachment.save(str(save_dir))

        async with db.execute(
            "SELECT pdf_title FROM pdfs WHERE user_id = ? AND pdf_title = ?",
            (interaction.user.id, attachment.filename),
        ) as cursor:
            if await cursor.fetchone():
                await interaction.followup.send("PDF content already stored.", ephemeral=True)
                return

        await db.execute(
            "INSERT INTO pdfs (user_id, pdf_path, pdf_title) VALUES (?, ?, ?)",
            (interaction.user.id, str(save_dir), attachment.filename),
        )
        await db.commit()

        await interaction.followup.send("PDF content stored successfully.")
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

@bot.tree.command(name="list_pdf", description="List all uploaded PDFs")
async def list_pdf(interaction: discord.Interaction):
    await interaction.response.defer()
    
    if not db:
        await interaction.followup.send("Database connection error.", ephemeral=True)
        return
    
    try:
        async with db.execute("SELECT pdf_title, id FROM pdfs WHERE user_id = ? ORDER BY id", (interaction.user.id,)) as cursor:
            pdf_list = await cursor.fetchall()
        
        if not pdf_list:
            await interaction.followup.send("No PDFs have been uploaded yet.", ephemeral=True)
            return

        embed = discord.Embed(title="Uploaded PDFs", color=discord.Color.blue())
        
        table = "```\n{:<30} : {:<5}\n".format("Filename", "Index")
        table += "-" * (62-6) + "\n"
        
        for pdf_name, index in pdf_list:
            table += "{:<30} : {:<5}\n".format(pdf_name[:30], index)
        
        table += "```"
        
        embed.description = table
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

@bot.tree.command(name="show_pdf_content", description="Displays a snippet of the stored PDF content.")
@app_commands.describe(index="Index of the PDF content to display.")
async def show_pdf_content(interaction: discord.Interaction, index: int):
    await interaction.response.defer()

    try:
        async with db.execute("SELECT pdf_path FROM pdfs WHERE id = ? AND user_id = ?", (index, interaction.user.id)) as cursor:
            pdf_path = await cursor.fetchone()
        
        if not pdf_path:
            await interaction.followup.send("PDF content not found. Please enter a valid index number.", ephemeral=True)
            return

        pdf_content = await process_pdf(pdf_path[0])
        if pdf_content is None:
            await interaction.followup.send("Error processing the PDF.", ephemeral=True)
            return

        snippet = pdf_content[:500] + "..." if len(pdf_content) > 500 else pdf_content
        
        embed = discord.Embed(title=f"PDF Content Snippet (Index {index})", description=f"```{snippet}```", color=discord.Color.blue())
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

@bot.tree.command(name="create_flashcard", description="Create a flashcard.")
@app_commands.describe(pdf_index="Create a flashcard question using the PDF content.")
async def gen_flashcard(interaction: discord.Interaction, pdf_index: int):
    await interaction.response.defer()
    if not db:
        await interaction.followup.send("Database connection error.", ephemeral=True)
        return
    
    pdf_status, pdf_content, pdf_path = await get_pdf_file_content(pdf_index, interaction.user.id)
    if pdf_status == "error":
        await interaction.followup.send(pdf_content, ephemeral=True)
        return
    
    try:
        questions_and_answers = await asyncio.to_thread(get_questions, file=pdf_path, api_key=TOGETHER_API_KEY)

        if not questions_and_answers:
            await interaction.followup.send("No questions were generated from the PDF.")
            return

        async with db.executemany(
            "INSERT INTO flashcards (user_id, questions, answers, pdf_index) VALUES (?, ?, ?, ?)",
            [(interaction.user.id, question, answer, pdf_index) for question, answer in questions_and_answers]
        ):
            await db.commit()
        
        await interaction.followup.send("Flashcards created successfully.")
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {str(e)}")

@bot.tree.command(name="play", description="Play a flashcard game.")
@app_commands.describe(index="Play flashcards using the PDF (index number) or (all) to play all flashcards.")
async def play(interaction: discord.Interaction, index: str):
    await interaction.response.defer()
    user_id = interaction.user.id
    if not db:
        await interaction.followup.send("Database connection error.", ephemeral=True)
        return
    
    try:
        query = "SELECT questions, answers FROM flashcards WHERE user_id = ?"
        params = [user_id]
        
        if index.lower() != "all":
            query += " AND pdf_index = ?"
            params.append(int(index))

        async with db.execute(query, params) as cursor:
            flashcards = await cursor.fetchall()

        if not flashcards:
            await interaction.followup.send("No flashcards found.", ephemeral=True)
            return

        view = QAView(flashcards)
        embed = view.get_embed()
        await interaction.followup.send(embeds=[embed], view=view)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

@bot.tree.command(name="delete", description="Delete a PDF and its associated flashcards")
@app_commands.describe(index="Index of the PDF to delete")
async def delete_pdf(interaction: discord.Interaction, index: int):
    await interaction.response.defer()
    
    if not db:
        await interaction.followup.send("Database connection error.", ephemeral=True)
        return
    
    try:
        # Check if the PDF exists
        async with db.execute("SELECT pdf_path, pdf_title FROM pdfs WHERE id = ? AND user_id = ?", (index, interaction.user.id)) as cursor:
            pdf_info = await cursor.fetchone()
        
        if not pdf_info:
            await interaction.followup.send(f"No PDF found with index {index}.", ephemeral=True)
            return

        pdf_path, pdf_title = pdf_info

        # Delete the PDF file
        try:
            os.remove(pdf_path)
        except OSError as e:
            print(f"Error deleting file: {e}")

        # Delete the PDF entry from the database
        await db.execute("DELETE FROM pdfs WHERE id = ? AND user_id = ?", (index, interaction.user.id))
        
        # Delete associated flashcards
        await db.execute("DELETE FROM flashcards WHERE pdf_index = ? AND user_id = ?", (index, interaction.user.id))
        
        await db.commit()

        embed = discord.Embed(title="PDF Deleted", color=discord.Color.green())
        embed.add_field(name="PDF Name", value=pdf_title, inline=False)
        embed.add_field(name="Index", value=str(index), inline=False)
        embed.add_field(name="Status", value="PDF and associated flashcards have been deleted.", inline=False)
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

@bot.tree.command(name="help", description="Get help about the bot commands.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="Bot Help", description="Here are the available commands:", color=discord.Color.blue())
    embed.add_field(name="/upload_pdf", value="Upload a PDF file to the bot.", inline=False)
    embed.add_field(name="/list_pdf", value="List all uploaded PDFs.", inline=False)
    embed.add_field(name="/show_pdf_content", value="Display a snippet of stored PDF content.", inline=False)
    embed.add_field(name="/create_flashcard", value="Create flashcards from a stored PDF.", inline=False)
    embed.add_field(name="/play", value="Play a flashcard game using stored flashcards.", inline=False)
    embed.add_field(name="/delete", value="Delete a PDF and its associated flashcards.", inline=False)
    embed.add_field(name="/help", value="Show this help message.", inline=False)
    await interaction.response.send_message(embed=embed)

# Run the bot
bot.run(BOT_TOKEN)