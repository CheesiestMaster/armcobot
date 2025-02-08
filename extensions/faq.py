from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, SelectOption, TextStyle
from io import BytesIO
import discord
from models import Faq as Faq_model
from templates import faq_response
from utils import uses_db, chunk_list, RollingCounterDict
from customclient import CustomClient
from sqlalchemy.orm import Session
logger = getLogger(__name__)

async def is_answerer(interaction: Interaction):
        """
        Checks if the user is an answerer
        """
        valid = interaction.user.id in {533009808501112881, 805560300258590753, 379951076343939072}
        if not valid:
            await interaction.response.send_message("You are not authorized to use this command", ephemeral=True)
        return valid
counters = RollingCounterDict(24*60*60)
total_views = 0
class Faq(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        
 

    @ac.command(name="how", description="How to use the FAQ")
    async def how(self, interaction: Interaction):
        """
        Displays how to use the FAQ
        """
        await interaction.response.send_message("Use the `/faq list` command to view all the FAQ questions. Use the `/faq view` command to view a specific question.", ephemeral=False) # ephemeral=False to allow other users to help new people find the FAQ

    
    @ac.command(name="view", description="View the FAQ")
    @uses_db(CustomClient().sessionmaker)
    async def view(self, interaction: Interaction, session: Session):
        """
        Displays the FAQ for S.A.M.
        """
        faq_questions = session.query(Faq_model).all()
        if not faq_questions:
            await interaction.response.send_message("No FAQ questions found", ephemeral=True)
            return
        faq_options = [SelectOption(label=question.question, value=str(question.id)) for question in faq_questions]
        faq_chunks = chunk_list(faq_options, 25)
        class FaqDropdown(ui.Select):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
            @uses_db(CustomClient().sessionmaker)
            async def callback(self, interaction: Interaction, session: Session):
                global total_views
                selected_question = session.query(Faq_model).filter(Faq_model.id == int(self.values[0])).first()
                counters[selected_question.question] += 1
                total_views += 1
                await interaction.response.send_message(faq_response.format(selected=selected_question), ephemeral=True)
        faq_dropdowns = [FaqDropdown(placeholder="Select a question", options=chunk) for chunk in faq_chunks]
        view = ui.View()
        for dropdown in faq_dropdowns:
            view.add_item(dropdown)
        await interaction.response.send_message("Select a question", view=view, ephemeral=True)

    @ac.command(name="add", description="Add a question to the FAQ")
    @ac.check(is_answerer)
    @uses_db(CustomClient().sessionmaker)
    async def add(self, interaction: Interaction, session: Session):
        """
        Adds a question to the FAQ
        """
        # send a modal for the question and answer
        # check if 125 questions already exist
        if session.query(Faq_model).count() >= 125:
            await interaction.response.send_message("You cannot add more than 125 questions to the FAQ", ephemeral=True)
            return
        modal = ui.Modal(title="Add a question to the FAQ")
        question = ui.TextInput(label="Question", placeholder="Enter the question here", max_length=100)
        answer = ui.TextInput(label="Answer", placeholder="Enter the answer here", style=TextStyle.paragraph, max_length=500)
        modal.add_item(question)
        modal.add_item(answer)
        @uses_db(CustomClient().sessionmaker)
        async def modal_callback(interaction: Interaction, session: Session):
            session.add(Faq_model(question=question.value, answer=answer.value))
            await interaction.response.send_message("Question added to the FAQ", ephemeral=True)
            logger.debug(f"Added question {question.value} with answer {answer.value}")
        modal.on_submit = modal_callback
        await interaction.response.send_modal(modal)

    @ac.command(name="remove", description="Remove a question from the FAQ")
    @ac.check(is_answerer)
    @uses_db(CustomClient().sessionmaker)
    async def remove(self, interaction: Interaction, session: Session):
        """
        Removes a question from the FAQ
        """
        # send a dropdown with the questions
        faq_questions = session.query(Faq_model).all()
        if not faq_questions:
            await interaction.response.send_message("No FAQ questions found", ephemeral=True)
            return
        faq_options = [SelectOption(label=question.question, value=str(question.id)) for question in faq_questions]
        faq_chunks = chunk_list(faq_options, 25)
        class FaqDropdown(ui.Select):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
            @uses_db(CustomClient().sessionmaker)
            async def callback(self, interaction: Interaction, session: Session):
                selected_question = session.query(Faq_model).filter(Faq_model.id == int(self.values[0])).first()
                logger.debug(f"Removing question {selected_question.question}")
                session.delete(selected_question)
                await interaction.response.send_message("Question removed from the FAQ", ephemeral=True)
        faq_dropdowns = [FaqDropdown(placeholder="Select a question", options=chunk) for chunk in faq_chunks]
        view = ui.View()
        for dropdown in faq_dropdowns:
            view.add_item(dropdown)
        await interaction.response.send_message("Select a question", view=view, ephemeral=True)

    @ac.command(name="edit", description="Edit a question in the FAQ")
    @ac.check(is_answerer)
    @uses_db(CustomClient().sessionmaker)
    async def edit(self, interaction: Interaction, session: Session):
        """
        Edits a question in the FAQ
        """
        # send a dropdown with the questions
        faq_questions = session.query(Faq_model).all()
        if not faq_questions:
            await interaction.response.send_message("No FAQ questions found", ephemeral=True)
            return
        faq_options = [SelectOption(label=question.question, value=str(question.id)) for question in faq_questions]
        faq_chunks = chunk_list(faq_options, 25)
        class FaqDropdown(ui.Select):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)

            @uses_db(CustomClient().sessionmaker)
            async def callback(self, interaction: Interaction, session: Session):
                selected_question = session.query(Faq_model).filter(Faq_model.id == int(self.values[0])).first()
                # send a modal for the question and answer
                modal = ui.Modal(title="Edit a question in the FAQ")
                question = ui.TextInput(label="Question", placeholder="Enter the question here", max_length=255, default=selected_question.question)
                answer = ui.TextInput(label="Answer", placeholder="Enter the answer here", style=TextStyle.paragraph, max_length=500, default=selected_question.answer)
                modal.add_item(question)
                modal.add_item(answer)
                @uses_db(CustomClient().sessionmaker)
                async def modal_callback(interaction: Interaction, session: Session):
                    _selected_question = session.merge(selected_question)
                    _selected_question.question = question.value
                    _selected_question.answer = answer.value
                    await interaction.response.send_message("Question edited in the FAQ", ephemeral=True)
                    logger.debug(f"Edited question {_selected_question.question} with answer {_selected_question.answer}")
                modal.on_submit = modal_callback
                await interaction.response.send_modal(modal)
        faq_dropdowns = [FaqDropdown(placeholder="Select a question", options=chunk) for chunk in faq_chunks]
        view = ui.View()
        for dropdown in faq_dropdowns:
            view.add_item(dropdown)
        await interaction.response.send_message("Select a question", view=view, ephemeral=True)

    @ac.command(name="list", description="List all the FAQ questions")
    @uses_db(CustomClient().sessionmaker)
    async def list(self, interaction: Interaction, session: Session):
        """
        Lists all the FAQ questions
        """
        faq_questions = session.query(Faq_model.question).all()
        faq_questions_str = "\n".join([f"{index + 1}. {question[0]}" for index, question in enumerate(faq_questions)])
        await interaction.response.send_message(faq_questions_str, ephemeral=True)

    @ac.command(name="stats", description="View the FAQ stats")
    async def stats(self, interaction: Interaction):
        """
        Views the FAQ stats
        """
        response = "FAQ stats:\n" + str(counters)
        response = response[:2000]
        await interaction.response.send_message(response, ephemeral=True)

    @ac.command(name="questionfile", description="Get the question file")
    @ac.check(is_answerer)
    @uses_db(CustomClient().sessionmaker)
    async def questionfile(self, interaction: Interaction, session: Session):
        """
        Gets the question file
        """
        questions = session.query(Faq_model).all()
        questions_text = [faq_response.format(selected=question) for question in questions]
        questions_text = "\n\n".join(questions_text)
        file = BytesIO(questions_text.encode())
        dfile = discord.File(file, filename="faq.md")
        await interaction.response.send_message("Here is the question file", ephemeral=True, file=dfile)

bot: Bot | None = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    await bot.add_cog(Faq(bot))

async def teardown():
    bot.remove_cog(Faq.__name__) # remove_cog takes a string, not a class