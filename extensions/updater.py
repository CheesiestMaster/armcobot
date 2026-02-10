import asyncio
import datetime
import os
from logging import getLogger

from discord import Interaction, app_commands as ac
from discord.ext.commands import GroupCog
from discord.ext import tasks
import templates as tmpl

from customclient import CustomClient
from utils import EnvironHelpers

logger = getLogger(__name__)

class Updater(GroupCog, description="Daily git update check; notifies owner when updates available."):
    """
    Cog that runs a daily check for git updates and notifies the bot owner
    when updates are available. No slash commands; only a background loop.
    """

    def __init__(self, bot: CustomClient):
        """Store bot reference and start the daily update check loop."""

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

async def setup(_bot: CustomClient):
    logger.info("Setting up Updater")
    await _bot.add_cog(Updater(_bot))


async def teardown(_bot: CustomClient):
    logger.info("Tearing down Updater")
    _bot.remove_cog(Updater.__name__)  # remove_cog takes a string, not a class