from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac
import asyncio
import os
from datetime import datetime, timedelta
import templates as tmpl
logger = getLogger(__name__)

class Updater(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.loop = bot.loop
        self.loop.create_task(self.daily_update_check())
        logger.debug("Updater cog initialized")

    async def run_command(self, command: list[str]):
        try:
            proc = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            return stdout.decode(), stderr.decode()
        except Exception as e:
            logger.error(f"Error running command {' '.join(command)}: {e}")
            return "", str(e)

    async def is_behind(self):
        logger.debug("Checking if the repository is behind")
        stdout, _ = await self.run_command(["git", "fetch", "--dry-run"])
        is_behind = bool(stdout.strip())
        logger.debug(f"Repository is {'behind' if is_behind else 'up to date'}")
        return is_behind
    
    async def get_diff_files(self):
        logger.debug("Getting list of changed files")
        stdout, _ = await self.run_command(["git", "diff", "--name-only", "HEAD", "origin/main"])
        diff_files = stdout.splitlines()
        logger.debug(f"Changed files: {diff_files}")
        return diff_files
    
    async def daily_update_check(self):
        """Runs the update check daily at 8 PM."""
        while True:
            now = datetime.now()
            target_time = now.replace(hour=20, minute=0, second=0, microsecond=0)
            logger.debug(f"Next update check at {target_time}")
            if now >= target_time:
                logger.debug("It's time to check for updates")
                target_time += timedelta(days=1)
                logger.debug(f"Next update check at {target_time}")
            sleep_duration = (target_time - now).total_seconds()
            logger.debug(f"Sleeping for {sleep_duration} seconds until the next update check")
            await asyncio.sleep(sleep_duration)

            await self.check_and_apply_updates()

    async def check_and_apply_updates(self):
        try:
            if not await self.is_behind():
                logger.info("Up to date")
                return
            diff_files = await self.get_diff_files()
            if all(file.startswith("extensions/") and not file.endswith("updater.py") for file in diff_files):
                logger.info("Applying updates")
                await self.apply_updates(None)
            else:
                logger.info("Not applying updates, some files are not in the extensions directory or updater.py")
                await self.bot.get_user(self.bot.owner_ids[0]).send(
                    "There are updates available for the bot, but they cannot be applied automatically because some non-reloadable files have changed. Please pull the changes and apply them manually."
                )
        except Exception as e:
            logger.error(f"Error during update check: {e}")
            await self.bot.get_user(self.bot.owner_ids[0]).send(f"Error during update check: {e}")

    @ac.command(name="apply-updates", description="Apply updates to the bot")
    @ac.check(lambda i: i.user.id in bot.owner_ids)
    async def apply_updates(self, interaction: Interaction):
        if interaction:
            await interaction.response.send_message(tmpl.applying_updates)
        
        stdout, stderr = await self.run_command(["git", "pull", "origin", "main"])
        
        if "CONFLICT" in stderr:
            logger.error("Merge conflict detected during update")
            if interaction:
                await interaction.followup.send("Merge conflict detected. Please resolve manually.", ephemeral=True)
            return
        
        if "fatal" in stderr:
            logger.error(f"Fatal error during git pull: {stderr}")
            if interaction:
                await interaction.followup.send(f"Fatal error during update: {stderr}", ephemeral=True)
            return
        
        if stderr:
            logger.error(f"Error pulling updates: {stderr}")
            if interaction:
                await interaction.followup.send(f"Error pulling updates: {stderr}", ephemeral=True)
            return
        
        if interaction:
            await interaction.followup.send("Updates applied successfully" + ("\nRestarting bot" if os.getenv("LOOP_ACTIVE") else "\nTerminating bot, please restart it manually"), ephemeral=True)
        
        await self.bot.close()

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Updater")
    await bot.add_cog(Updater(bot))

async def teardown():
    logger.info("Tearing down Updater")
    bot.remove_cog(Updater.__name__) # remove_cog takes a string, not a class