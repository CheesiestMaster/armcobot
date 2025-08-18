from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, SelectOption, TextStyle
from io import BytesIO
import discord
from models import Faq as Faq_model
import templates as tmpl
from utils import uses_db, chunk_list, RollingCounterDict
from customclient import CustomClient
from sqlalchemy.orm import Session
from os import getenv
logger = getLogger(__name__)

async def is_answerer(interaction: Interaction):
        """
        Checks if the user is an answerer
        """
        # Check if user is one of the authorized users
        authorized_users = {
            int(getenv("BOT_OWNER_ID")), 
            int(getenv("BOT_OWNER_ID_2")), 
            int(getenv("FAQ_ANSWERER_1")), 
            int(getenv("FAQ_ANSWERER_2"))
        }
        
        # Check if user has any of the mod roles
        mod_roles = {int(getenv("MOD_ROLE_1")), int(getenv("MOD_ROLE_2"))}
        
        # Check if user ID is in authorized users
        if interaction.user.id in authorized_users:
            return True
            
        if interaction.guild:
            user_roles = {role.id for role in interaction.user.roles}
            if user_roles & mod_roles:  # Check intersection
                return True
        
        # User is not authorized
        await interaction.response.send_message(tmpl.not_authorized, ephemeral=True)
        return False

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
        await interaction.response.send_message(tmpl.faq_how_to_use, ephemeral=False) # ephemeral=False to allow other users to help new people find the FAQ

    
    @ac.command(name="view", description="View the FAQ")
    @uses_db(CustomClient().sessionmaker)
    async def view(self, interaction: Interaction, session: Session):
        """
        Displays the FAQ for S.A.M.
        """
        faq_questions = session.query(Faq_model).all()
        if not faq_questions:
            await interaction.response.send_message(tmpl.faq_no_questions, ephemeral=True)
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
                await interaction.response.send_message(tmpl.faq_response.format(selected=selected_question), ephemeral=True)
        faq_dropdowns = [FaqDropdown(placeholder="Select a question", options=chunk) for chunk in faq_chunks]
        view = ui.View()
        for dropdown in faq_dropdowns:
            view.add_item(dropdown)
        await interaction.response.send_message(tmpl.faq_select_question, view=view, ephemeral=True)

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
            await interaction.response.send_message(tmpl.faq_max_questions, ephemeral=True)
            return
        modal = ui.Modal(title="Add a question to the FAQ")
        question = ui.TextInput(label="Question", placeholder="Enter the question here", max_length=100)
        answer = ui.TextInput(label="Answer", placeholder="Enter the answer here", style=TextStyle.paragraph, max_length=1718)
        modal.add_item(question)
        modal.add_item(answer)
        @uses_db(CustomClient().sessionmaker)
        async def modal_callback(interaction: Interaction, session: Session):
            session.add(Faq_model(question=question.value, answer=answer.value))
            await interaction.response.send_message(tmpl.faq_question_added, ephemeral=True)
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
            await interaction.response.send_message(tmpl.faq_no_questions, ephemeral=True)
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
                await interaction.response.send_message(tmpl.faq_question_removed, ephemeral=True)
        faq_dropdowns = [FaqDropdown(placeholder="Select a question", options=chunk) for chunk in faq_chunks]
        view = ui.View()
        for dropdown in faq_dropdowns:
            view.add_item(dropdown)
        await interaction.response.send_message(tmpl.faq_select_question, view=view, ephemeral=True)

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
            await interaction.response.send_message(tmpl.faq_no_questions, ephemeral=True)
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
                question = ui.TextInput(label="Question", placeholder="Enter the question here", max_length=100, default=selected_question.question)
                answer = ui.TextInput(label="Answer", placeholder="Enter the answer here", style=TextStyle.paragraph, max_length=1718, default=selected_question.answer)
                modal.add_item(question)
                modal.add_item(answer)
                @uses_db(CustomClient().sessionmaker)
                async def modal_callback(interaction: Interaction, session: Session):
                    _selected_question = session.merge(selected_question)
                    _selected_question.question = question.value
                    _selected_question.answer = answer.value
                    await interaction.response.send_message(tmpl.faq_question_edited, ephemeral=True)
                    logger.debug(f"Edited question {_selected_question.question} with answer {_selected_question.answer}")
                modal.on_submit = modal_callback
                await interaction.response.send_modal(modal)
        faq_dropdowns = [FaqDropdown(placeholder="Select a question", options=chunk) for chunk in faq_chunks]
        view = ui.View()
        for dropdown in faq_dropdowns:
            view.add_item(dropdown)
        await interaction.response.send_message(tmpl.faq_select_question, view=view, ephemeral=True)

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
        questions_text = [tmpl.faq_response.format(selected=question) for question in questions]
        questions_text = "\n\n".join(questions_text)
        file = BytesIO(questions_text.encode())
        dfile = discord.File(file, filename="faq.md")
        await interaction.response.send_message(tmpl.faq_file_here, ephemeral=True, file=dfile)

bot: Bot | None = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    await bot.add_cog(Faq(bot))

async def teardown():
    bot.remove_cog(Faq.__name__) # remove_cog takes a string, not a class