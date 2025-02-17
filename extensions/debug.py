from logging import getLogger
from pathlib import Path
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, TextStyle, ButtonStyle, Embed, SelectOption, Forbidden, HTTPException, Message
from sqlalchemy import text, func
import os
from models import Player
from asyncio import QueueEmpty
import random
from customclient import CustomClient
from utils import uses_db, toggle_command_ban
from sqlalchemy.orm import Session
from coloredformatter import stats
from templates import stats_template
from datetime import datetime, timedelta
from psutil import Process
from MessageManager import MessageManager
logger = getLogger(__name__)

process: Process = None

class Debug(GroupCog):
    def __init__(self, bot: CustomClient):
        global process
        self.bot = bot
 
        self.interaction_check = self._is_mod
        # get the list of extensions from the disk, and create a list of them for the autocomplete
        self.extensions = [f.stem for f in Path("extensions").glob("*.py") if f.stem != "__init__"]

        process = Process() # get the current process
        with open("PID", "w") as f:
            f.write(str(process.pid))
        self._setup_context_menus() # context menus cannot be instance methods, so we need to nest them

    async def _autocomplete_extensions(self, interaction: Interaction, current: str):
        return [ac.Choice(name=extension, value=extension) for extension in self.extensions if current.lower() in extension.lower() and not extension.startswith("template")]

    async def _is_mod(self, interaction: Interaction):
        valid = any(interaction.user.get_role(role_id) for role_id in self.bot.mod_roles)
        if not valid:
            logger.warning(f"{interaction.user.global_name} tried to use debug commands")
        return valid

    def _setup_context_menus(self):
        logger.debug("Setting up context menus for debug commands")
        @self.bot.tree.context_menu(name="~RP Reply~")
        @ac.check(self._is_mod)
        async def rp_reply(interaction: Interaction, message: Message):
            rp_modal = ui.Modal(title="Roleplay Message")
            rp_modal.add_item(ui.TextInput(label="Message", style=TextStyle.paragraph))

            async def on_submit(_interaction: Interaction):
                template = """---- RP POST ----
```ansi
[32m{message}
```"""
                await message.reply(template.format(message=_interaction.data["components"][0]["components"][0]["value"]), mention_author=False)
                await _interaction.response.send_message("Message sent", ephemeral=self.bot.use_ephemeral)

            rp_modal.on_submit = on_submit
            await interaction.response.send_modal(rp_modal)

    @ac.command(name="kill", description="Kill the bot")
    async def kill(self, interaction: Interaction):
        logger.info("Kill command invoked")
        await interaction.response.send_message("Killing bot")
        if os.getenv("LOOP_ACTIVE"):
            with open("terminate.flag", "w"):
                pass # the file just needs to exist, doesn't need to be written to
        await self.bot.close()

    if os.getenv("LOOP_ACTIVE"):
        @ac.command(name="restart", description="Restart the bot")
        async def restart(self, interaction: Interaction):
            logger.info("Restart command invoked") 
            if interaction: # allow the command to be used internally as well as in discord, we can pass None to use it internally and it will not try to send a message
                await interaction.response.send_message("Restarting bot")
            await self.bot.close() # this will trigger the start.sh script to restart, if we used kill it would completely stop the script
        
    @ac.command(name="reload", description="Reload an extension")
    @ac.autocomplete(extension=_autocomplete_extensions)
    async def reload(self, interaction: Interaction, extension: str):
        extension = "extensions." + extension
        logger.info(f"Reload command invoked for {extension}")
        await interaction.response.send_message(f"Reloading {extension}")
        await self.bot.reload_extension(extension)
        await self.bot.tree.sync()

    @ac.command(name="load", description="Load an extension")
    @ac.autocomplete(extension=_autocomplete_extensions)
    async def load(self, interaction: Interaction, extension: str):
        extension = "extensions." + extension
        logger.info(f"Load command invoked for {extension}")
        await interaction.response.send_message(f"Loading {extension} ")
        await self.bot.load_extension(extension)
        if not self.bot.config.get("EXTENSIONS"):
            self.bot.config["EXTENSIONS"] = []
        self.bot.config["EXTENSIONS"].append(extension)
        await self.bot.tree.sync()
    # unload cannot have "debug" as it's argument, as that would cause a deadlock
    @ac.command(name="unload", description="Unload an extension")
    @ac.autocomplete(extension=_autocomplete_extensions)
    async def unload(self, interaction: Interaction, extension: str):
        extension = "extensions." + extension
        if extension == "extensions.debug":
            logger.warning("Attempt to unload debug extension from in Discord")
            await interaction.response.send_message("Cannot unload debug extension from in Discord")
            return
        logger.info(f"Unload command invoked for {extension}")
        await interaction.response.send_message(f"Unloading {extension}")
        await self.bot.unload_extension(extension)
        self.bot.config["EXTENSIONS"].remove(extension)
        await self.bot.tree.sync()

    @ac.command(name="query", description="Run a SQL query")
    @ac.describe(query="SQL query to run")
    @uses_db(CustomClient().sessionmaker)
    async def query(self, interaction: Interaction, query: str, session: Session):
        try:
            logger.info(f"Running query: {query}")
            result = session.execute(text(query))
            session.commit()
            try:
                rows = result.fetchall()
            except Exception:
                rows = None
            await interaction.response.send_message(f"Query result: {rows}" if rows else "No rows returned", ephemeral=self.bot.use_ephemeral)
        except Exception as e:
            logger.error(f"Error running query: {e}")
            await interaction.response.send_message(f"Error: {e}", ephemeral=self.bot.use_ephemeral)

    @uses_db(CustomClient().sessionmaker)
    async def botcompany(self, interaction: Interaction, _: MessageManager, session: Session):
        existing = session.query(Player).filter(Player.discord_id == self.bot.user.id).first()
        if existing:
            await interaction.response.send_message("Bot company already exists", ephemeral=self.bot.use_ephemeral)
            return
        player = Player(discord_id=self.bot.user.id, name="Supply Allocation and Management", rec_points=0)
        session.add(player)
        session.commit()
        await interaction.response.send_message("Bot company created", ephemeral=self.bot.use_ephemeral)

    async def rp(self, interaction: Interaction, _: MessageManager):
        # create a modal with a text input for the message, this can be a two-line code
        rp_modal = ui.Modal(title="Roleplay Message")
        rp_modal.add_item(ui.TextInput(label="Message", style=TextStyle.paragraph))

        async def on_submit(_interaction: Interaction):
            channel = interaction.channel # we are specifically looking at the original command's interaction, not the modal response _interaction
            template = """---- RP POST ----
```ansi
[32m{message}
```"""
            await channel.send(template.format(message=_interaction.data["components"][0]["components"][0]["value"]))
            await _interaction.response.send_message("Message sent", ephemeral=self.bot.use_ephemeral)

        rp_modal.on_submit = on_submit
        await interaction.response.send_modal(rp_modal)

    
    async def dump_queue(self, interaction: Interaction, _: MessageManager):
        await interaction.response.defer()
        while not self.bot.queue.empty():
            try:
                self.bot.queue.get_nowait()
            except QueueEmpty:
                break # handle race condition gracefully
        await interaction.followup.send("Queue emptied", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="clear_deletable", description="Deletes all deletable messages in the channel.")
    async def clear_deletable(self, interaction: Interaction, limit: int = 100):
        """Deletes all deletable messages in the channel."""
        channel = interaction.channel

        # Fetch the last 100 messages (you can adjust this number as needed)
        messages = [message async for message in channel.history(limit=limit)]

        for message in messages:
            # Check if the message is deletable (i.e., sent by the bot)
            if message.author == self.bot.user:
                try:
                    await message.delete()
                    logger.info(f"Deleted message: {message.content}")
                except Forbidden:
                    # The bot does not have permission to delete the message
                    logger.warning(f"Failed to delete message: {message.content} (Forbidden)")
                except HTTPException:
                    # An HTTP error occurred (e.g., message too old)
                    logger.error(f"Failed to delete message: {message.content} (HTTP Exception)")

        await interaction.response.send_message("All deletable messages have been cleared.", ephemeral=True)

    
    async def stats(self, interaction: Interaction, _: MessageManager):
        uptime: timedelta = datetime.now() - self.bot.start_time
        start_time = f"<t:{int(self.bot.start_time.timestamp())}:F>"
        if process:
            resident = process.memory_info().rss / 1024 ** 2 # resident memory in MB
            cpu_time = process.cpu_times().user + process.cpu_times().system # total CPU time in seconds
            average_cpu = cpu_time / uptime.total_seconds() if uptime.total_seconds() > 0 else 0 # average CPU usage
        else:
            resident = "N/A"
            cpu_time = "N/A"
            average_cpu = "N/A"
        await interaction.response.send_message(stats_template.format(**stats, **locals()), ephemeral=self.bot.use_ephemeral)

    @ac.command(name="menu", description="Show the menu")
    async def menu(self, interaction: Interaction):
        # I am moving most of the debug commands to the menu, which will use a MessageManager to keep the command list shorter
        mm = MessageManager(interaction)
        view = ui.View(timeout=None)

        options = [v for k, v in self.__class__.__dict__.items() if not k.startswith("_") and callable(v)]
        if not options:
            await interaction.response.send_message("No commands found", ephemeral=self.bot.use_ephemeral)
            return

        select = ui.Select(placeholder="Select a command", options=[SelectOption(label=option.__name__, value=option.__name__) for option in options])
        async def on_select(interaction: Interaction):
            command = getattr(self, select.values[0])
            await command(interaction, mm)
        select.callback = on_select

        view.add_item(select)
        await mm.send_message(embed=Embed(title="Debug Menu", description="please select a command"), view=view, ephemeral=self.bot.use_ephemeral)

    @ac.command(name="commandban", description="Temporarily disable all commands for non mod users")
    async def commandban(self, interaction: Interaction, check: bool = False):
        # if check is true, compare CustomClient().tree.interaction_check with CustomClient().no_commands
        is_banned = self.bot.tree.interaction_check == self.bot.no_commands
        if check:
            await interaction.response.send_message(f"Command ban is {'enabled' if is_banned else 'disabled'}", ephemeral=self.bot.use_ephemeral)
            return
        await toggle_command_ban(is_banned, interaction.user.mention)
        await interaction.response.send_message(f"Command ban {'disabled' if is_banned else 'enabled'}", ephemeral=self.bot.use_ephemeral)
        

bot: Bot = None
async def setup(_bot: CustomClient):
    global bot
    bot = _bot
    logger.debug("Setting up Debug cog")
    await bot.add_cog(Debug(bot))

async def teardown():
    logger.debug("Tearing down Debug cog")
    bot.remove_cog(Debug.__name__) # remove_cog takes a string, not a class
