from logging import getLogger
from pathlib import Path
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac
from sqlalchemy import text
import os
logger = getLogger(__name__)

class Debug(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.session = bot.session
        self.interaction_check = self.is_owner
        # get the list of extensions from the disk, and create a list of them for the autocomplete
        self.extensions = [f.stem for f in Path("extensions").glob("*.py") if f.stem != "__init__"]

    async def autocomplete_extensions(self, interaction: Interaction, current: str):
        return [ac.Choice(name=extension, value=extension) for extension in self.extensions if current.lower() in extension.lower()]

    async def is_owner(self, interaction: Interaction):
        valid = interaction.user.id in self.bot.owner_ids
        if not valid:
            logger.warning(f"{interaction.user.global_name} tried to use debug commands")
        return valid

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
    @ac.autocomplete(extension=autocomplete_extensions)
    async def reload(self, interaction: Interaction, extension: str):
        extension = "extensions." + extension
        logger.info(f"Reload command invoked for {extension}")
        await interaction.response.send_message(f"Reloading {extension}")
        await self.bot.reload_extension(extension)
        await self.bot.tree.sync()

    @ac.command(name="load", description="Load an extension")
    @ac.autocomplete(extension=autocomplete_extensions)
    async def load(self, interaction: Interaction, extension: str):
        extension = "extensions." + extension
        logger.info(f"Load command invoked for {extension}")
        await interaction.response.send_message(f"Loading {extension} ")
        await self.bot.load_extension(extension)
        await self.bot.tree.sync()
    # unload cannot have "debug" as it's argument, as that would cause a deadlock
    @ac.command(name="unload", description="Unload an extension")
    @ac.autocomplete(extension=autocomplete_extensions)
    async def unload(self, interaction: Interaction, extension: str):
        extension = "extensions." + extension
        if extension == "extensions.debug":
            logger.warning("Attempt to unload debug extension from in Discord")
            await interaction.response.send_message("Cannot unload debug extension from in Discord")
            return
        logger.info(f"Unload command invoked for {extension}")
        await interaction.response.send_message(f"Unloading {extension}")
        await self.bot.unload_extension(extension)

    @ac.command(name="query", description="Run a SQL query")
    @ac.describe(query="SQL query to run")
    async def query(self, interaction: Interaction, query: str):
        try:
            logger.info(f"Running query: {query}")
            result = self.session.execute(text(query))
            self.session.commit()
            try:
                rows = result.fetchall()
            except Exception:
                rows = None
            await interaction.response.send_message(f"Query result: {rows}" if rows else "No rows returned", ephemeral=self.bot.use_ephemeral)
        except Exception as e:
            logger.error(f"Error running query: {e}")
            await interaction.response.send_message(f"Error: {e}", ephemeral=self.bot.use_ephemeral)

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.debug("Setting up Debug cog")
    await bot.add_cog(Debug(bot))

async def teardown():
    logger.debug("Tearing down Debug cog")
    bot.remove_cog(Debug.__name__) # remove_cog takes a string, not a class
