from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord.ext import tasks
from discord import Interaction, app_commands as ac
import asyncio
import os
import datetime
import templates as tmpl
from utils import EnvironHelpers
logger = getLogger(__name__)

class Updater(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.daily_update_check.start()
    
    @tasks.loop(time=datetime.time(hour=8))
    async def daily_update_check(self):
        process = await asyncio.create_subprocess_exec("git", "fetch", "--dry-run", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"Error fetching updates: {stderr.decode() if stderr else 'Unknown error'}")
            return
        if stdout.strip() != b"":
            owner = await self.bot.fetch_user(EnvironHelpers.required_int("BOT_OWNER_ID"))
            await owner.send("An Update is available")

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Updater")
    await bot.add_cog(Updater(bot))

async def teardown():
    logger.info("Tearing down Updater")
    bot.remove_cog(Updater.__name__) # remove_cog takes a string, not a class