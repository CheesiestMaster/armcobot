from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction
import asyncio
from datetime import datetime
logger = getLogger(__name__)

class Updater(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.loop = bot.loop
        self.loop.create_task(self.update_loop())

    async def update_loop(self):
        logger.info("Updater loop started")
        # wait until 8pm
        now = datetime.now()
        wait_time = (now.replace(hour=20, minute=0, second=0, microsecond=0) - now).total_seconds()
        if wait_time > 0:
            logger.info(f"Waiting {wait_time} seconds until 8pm")
            await asyncio.sleep(wait_time)
        while True:
            logger.info("Checking for updates")
            proc = await asyncio.create_subprocess_exec("git", "log", "HEAD..origin/main", "--oneline", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await proc.communicate()
            if stdout:
                logger.info(f"Updates found: {stdout.decode()}")
            else:
                logger.info("No updates found")
                continue
            # check what files are changed, and if all are in the extensions folder, fetch them and apply them if they are running
            
            # wait until 8pm tomorrow
            now = datetime.now()
            wait_time = (now.replace(day=now.day + 1, hour=20, minute=0, second=0, microsecond=0) - now).total_seconds()
            if wait_time > 0:
                logger.info(f"Waiting {wait_time} seconds until 8pm tomorrow")
                await asyncio.sleep(wait_time)
        


bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Updater")
    await bot.add_cog(Updater(bot))

async def teardown():
    logger.info("Tearing down Updater")
    bot.remove_cog(Updater.__name__) # remove_cog takes a string, not a class