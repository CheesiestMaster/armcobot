import asyncio
from discord.ext.tasks import Loop
from logging import getLogger
import logging
from pathlib import Path
from discord.ext.commands import GroupCog, Bot, Cog
from discord import Interaction, app_commands as ac, ui, TextStyle, Embed, SelectOption, Forbidden, HTTPException, Message, NotFound, TextChannel, File
from sqlalchemy import text, func
import os
from models import Player, Statistic, Dossier, Campaign, CampaignInvite, Unit, UnitStatus
from asyncio import QueueEmpty
import random
from customclient import CustomClient
from coloredformatter import stats
from utils import error_reporting, uses_db, toggle_command_ban, is_server
from sqlalchemy.orm import Session
from sqlalchemy import exists
import templates as tmpl
from datetime import datetime, timedelta
from psutil import Process
from MessageManager import MessageManager
from discord.ext.tasks import loop
from io import BytesIO
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
        #self._bump_briefing.start()

    async def _autocomplete_extensions(self, interaction: Interaction, current: str):
        return [ac.Choice(name=extension, value=extension) for extension in self.extensions if current.lower() in extension.lower() and not extension.startswith("template")]

    async def _is_mod(self, interaction: Interaction):
        try:
            logger.debug(f"Checking if {interaction.user.global_name} is a mod")
            casting_guild=self.bot.get_guild(int(os.getenv("MAIN_GUILD_ID", 222052888531173386)))
            logger.debug(f"Casting guild: {casting_guild} from environ {os.getenv('MAIN_GUILD_ID')}")
            
            if casting_guild is None:
                logger.error(f"Failed to get guild for mod check - guild cache may be unavailable")
                return False
                
            cast_user = casting_guild.get_member(interaction.user.id)
            logger.debug(f"Casting user: {cast_user}")
            valid = any(cast_user.get_role(role_id) for role_id in self.bot.mod_roles)
            logger.debug(f"Valid: {valid}")
            if not valid:
                logger.warning(f"{interaction.user.global_name} tried to use debug commands")
            return valid
        except AttributeError as e:
            if "'NoneType' object has no attribute 'get_member'" in str(e):
                logger.debug(f"Suppressing race condition error during reload: {e}")
                return False
            raise

    def _setup_context_menus(self):
        logger.debug("Setting up context menus for debug commands")
        @self.bot.tree.context_menu(name="~RP Reply~")
        @ac.check(self._is_mod)
        async def rp_reply(interaction: Interaction, message: Message):
            rp_modal = ui.Modal(title="Roleplay Message")
            rp_modal.add_item(ui.TextInput(label="Message", style=TextStyle.paragraph))

            async def on_submit(_interaction: Interaction):
                await message.reply(tmpl.rp_template.format(message=_interaction.data["components"][0]["components"][0]["value"]), mention_author=False)
                await _interaction.response.send_message(tmpl.message_sent, ephemeral=self.bot.use_ephemeral)

            rp_modal.on_submit = on_submit
            await interaction.response.send_modal(rp_modal)

    @ac.command(name="stop", description="Stop the bot")
    async def stop(self, interaction: Interaction):
        logger.info("Stop command invoked")
        await interaction.response.send_message(tmpl.stopping_bot)
        if os.getenv("LOOP_ACTIVE"):
            open("terminate.flag", "w").close()
        await self.bot.close()

    if os.getenv("LOOP_ACTIVE"):
        @ac.command(name="restart", description="Restart the bot")
        async def restart(self, interaction: Interaction):
            logger.info("Restart command invoked") 
            if interaction: # allow the command to be used internally as well as in discord, we can pass None to use it internally and it will not try to send a message
                await interaction.response.send_message(tmpl.restarting_bot)
            await self.bot.close() # this will trigger the start.sh script to restart, if we used kill it would completely stop the script

        @ac.command(name="update_and_restart", description="Update the bot and restart it")
        async def update_and_restart(self, interaction: Interaction):
            # just like restart, except we touch the update.flag file
            logger.info("Update and restart command invoked")
            if interaction:
                await interaction.response.send_message(tmpl.updating_bot)
            open("update.flag", "w").close()
            await self.bot.close()

        
    @ac.command(name="reload_strings", description="Reload the templates module")
    async def reload_strings(self, interaction: Interaction):
        """Reload the templates module to refresh string templates."""
        global tmpl
        logger.info("Reload strings command invoked")
        try:
            import importlib
            import sys
            
            # Check if user_templates exists and is loaded
            if 'user_templates' in sys.modules:
                try:
                    importlib.reload(sys.modules['user_templates'])
                except (ImportError, ModuleNotFoundError):
                    # Handle case where user_templates was deleted or can't be reloaded
                    pass
            
            # Always reload templates.py
            import templates
            importlib.reload(templates)
            
            # Reload all modules that import templates
            modules_to_reload = [
                'customclient',
                'extensions.shop',
                'extensions.faq', 
                'extensions.companies',
                'extensions.updater',
                'extensions.campaigns'
            ]
            
            for module_name in modules_to_reload:
                if module_name in sys.modules:
                    try:
                        importlib.reload(sys.modules[module_name])
                        logger.info(f"Reloaded {module_name}")
                    except Exception as e:
                        logger.warning(f"Failed to reload {module_name}: {e}")
            
            # Update the global tmpl reference
            import templates as tmpl
            await interaction.response.send_message(tmpl.debug_reload_success, ephemeral=self.bot.use_ephemeral)
        except Exception as e:
            logger.error(f"Error reloading templates: {e}")
            await interaction.response.send_message(tmpl.debug_reload_error.format(e=e), ephemeral=self.bot.use_ephemeral)

    @ac.command(name="reload", description="Reload an extension")
    @ac.autocomplete(extension=_autocomplete_extensions)
    async def reload(self, interaction: Interaction, extension: str):
        extension = "extensions." + extension
        logger.info(f"Reload command invoked for {extension}")
        await interaction.response.send_message(tmpl.debug_reloading.format(extension=extension), ephemeral=self.bot.use_ephemeral)
        await self.bot.reload_extension(extension)
        await self.bot.tree.sync()

    @ac.command(name="load", description="Load an extension")
    @ac.autocomplete(extension=_autocomplete_extensions)
    async def load(self, interaction: Interaction, extension: str):
        extension = "extensions." + extension
        logger.info(f"Load command invoked for {extension}")
        await interaction.response.send_message(tmpl.debug_loading.format(extension=extension))
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
            await interaction.response.send_message(tmpl.cannot_unload_debug)
            return
        logger.info(f"Unload command invoked for {extension}")
        await interaction.response.send_message(tmpl.debug_unloading.format(extension=extension))
        await self.bot.unload_extension(extension)
        self.bot.config["EXTENSIONS"].remove(extension)
        await self.bot.tree.sync()

    @ac.command(name="query", description="Run a SQL query")
    @ac.describe(query="SQL query to run (leave empty for modal)")
    @uses_db(CustomClient().sessionmaker)
    async def query(self, interaction: Interaction, query: str = "", session: Session = None) -> None:
        if not query:
            # Send modal for multi-line SQL input
            query_modal = ui.Modal(title="SQL Query")
            query_modal.add_item(ui.TextInput(label="SQL Query", style=TextStyle.paragraph, placeholder="Enter your SQL query here..."))

            async def on_submit(_interaction: Interaction):
                sql_query = _interaction.data["components"][0]["components"][0]["value"]
                try:
                    # Split query on semicolons and run sequentially
                    queries = [q.strip() for q in sql_query.split(';') if q.strip()]
                    logger.info(f"Running {len(queries)} queries sequentially")
                    
                    all_results = []
                    for i, query in enumerate(queries):
                        logger.info(f"Running query {i+1}/{len(queries)}: {query}")
                        try:
                            result = session.execute(text(query))
                            
                            try:
                                rows = result.fetchall()
                                all_results.append((i+1, query, rows))
                            except Exception as fetch_error:
                                # If fetchall fails, still add the result but don't fail the transaction
                                # This handles cases like INSERT/UPDATE/DELETE that don't return rows
                                all_results.append((i+1, query, None))
                                logger.debug(f"Query {i+1} returned no rows (likely INSERT/UPDATE/DELETE): {fetch_error}")
                        except Exception as query_error:
                            # If the query execution itself fails, propagate the exception immediately
                            logger.error(f"Query {i+1} failed: {query_error}")
                            raise query_error
                    
                    # Single commit for all queries to maintain transactional atomicity
                    session.commit()
                    logger.info("All queries committed successfully")
                    
                    # Build response message
                    response_text = ""
                    for query_num, query, rows in all_results:
                        if rows:
                            response_text += f"**Query {query_num}:**\n```{query}```\n**Result:**\n```{rows}```\n\n"
                        else:
                            response_text += f"**Query {query_num}:**\n```{query}```\n**Result:** No rows returned\n\n"
                    
                    # Chunk the response if it's too large
                    await self._send_chunked_response(_interaction, response_text)
                        
                except Exception as e:
                    logger.error(f"Error running query: {e}")
                    # Rollback on error to maintain transactional atomicity
                    session.rollback()
                    logger.info("Transaction rolled back due to error")
                    error_message = tmpl.debug_query_error.format(e=e)
                    if _interaction.response.is_done():
                        await _interaction.followup.send(error_message, ephemeral=self.bot.use_ephemeral)
                    else:
                        await _interaction.response.send_message(error_message, ephemeral=self.bot.use_ephemeral)

            query_modal.on_submit = on_submit
            await interaction.response.send_modal(query_modal)
            return

        # Handle direct query input
        try:
            logger.info(f"Running query: {query}")
            result = session.execute(text(query))
            session.commit()
            try:
                rows = result.fetchall()
            except Exception:
                rows = None
            
            response_text = tmpl.debug_query_result.format(rows=rows) if rows else tmpl.debug_query_no_rows
            await self._send_chunked_response(interaction, response_text)
        except Exception as e:
            logger.error(f"Error running query: {e}")
            await interaction.response.send_message(tmpl.debug_query_error.format(e=e), ephemeral=self.bot.use_ephemeral)

    async def _send_chunked_response(self, interaction: Interaction, text: str, chunk_size: int = 2000):
        """
        Send a response in chunks if it exceeds the Discord message limit.
        
        Args:
            interaction: The Discord interaction
            text: The text to send
            chunk_size: Maximum characters per chunk (default 2000)
        """
        if len(text) <= chunk_size:
            # Single message is fine
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=self.bot.use_ephemeral)
            else:
                await interaction.response.send_message(text, ephemeral=self.bot.use_ephemeral)
            return
        
        # Need to chunk the response
        chunks = []
        current_chunk = ""
        
        # Split by lines to avoid breaking in the middle of a line
        lines = text.split('\n')
        
        for line in lines:
            # If adding this line would exceed chunk size, start a new chunk
            if len(current_chunk) + len(line) + 1 > chunk_size:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk += ('\n' + line) if current_chunk else line
        
        # Add the last chunk if it has content
        if current_chunk:
            chunks.append(current_chunk)
        
        # Send the first chunk as the main response
        if interaction.response.is_done():
            await interaction.followup.send(chunks[0], ephemeral=self.bot.use_ephemeral)
        else:
            await interaction.response.send_message(chunks[0], ephemeral=self.bot.use_ephemeral)
        
        # Send remaining chunks as followups
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=self.bot.use_ephemeral)

    @uses_db(CustomClient().sessionmaker)
    async def botcompany(self, interaction: Interaction, _: MessageManager, session: Session):
        existing = session.query(Player).filter(Player.discord_id == self.bot.user.id).first()
        if existing:
            await interaction.response.send_message(tmpl.bot_company_exists, ephemeral=self.bot.use_ephemeral)
            return
        player = Player(discord_id=self.bot.user.id, name="Supply Allocation and Management", rec_points=0)
        session.add(player)
        session.commit()
        await interaction.response.send_message(tmpl.bot_company_created, ephemeral=self.bot.use_ephemeral)

    async def rp(self, interaction: Interaction, _: MessageManager):
        # create a modal with a text input for the message, this can be a two-line code
        rp_modal = ui.Modal(title="Roleplay Message")
        rp_modal.add_item(ui.TextInput(label="Message", style=TextStyle.paragraph))

        async def on_submit(_interaction: Interaction):
            channel = interaction.channel # we are specifically looking at the original command's interaction, not the modal response _interaction
            await channel.send(tmpl.rp_template.format(message=_interaction.data["components"][0]["components"][0]["value"]))
            await _interaction.response.send_message(tmpl.message_sent, ephemeral=self.bot.use_ephemeral)

        rp_modal.on_submit = on_submit
        await interaction.response.send_modal(rp_modal)

    
    async def dump_queue(self, interaction: Interaction, _: MessageManager):
        await interaction.response.defer()
        while not self.bot.queue.empty():
            try:
                self.bot.queue.get_nowait()
            except QueueEmpty:
                break # handle race condition gracefully
        await interaction.followup.send(tmpl.queue_emptied, ephemeral=self.bot.use_ephemeral)

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

        await interaction.response.send_message(tmpl.all_deletable_cleared, ephemeral=True)

    
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
        await interaction.response.send_message(tmpl.stats_template.format(**stats, **locals()), ephemeral=self.bot.use_ephemeral)

    @ac.command(name="menu", description="Show the menu")
    async def menu(self, interaction: Interaction):
        # I am moving most of the debug commands to the menu, which will use a MessageManager to keep the command list shorter
        mm = MessageManager(interaction)
        view = ui.View(timeout=None)

        options = [v for k, v in self.__class__.__dict__.items() if not k.startswith("_") and callable(v)]
        if not options:
            await interaction.response.send_message(tmpl.debug_no_commands, ephemeral=self.bot.use_ephemeral)
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
            await interaction.response.send_message(tmpl.debug_command_ban_status.format(status='enabled' if is_banned else 'disabled'), ephemeral=self.bot.use_ephemeral)
            return
        await toggle_command_ban(is_banned, interaction.user.mention)
        await interaction.response.send_message(tmpl.debug_command_ban_toggle.format(action='disabled' if is_banned else 'enabled'), ephemeral=self.bot.use_ephemeral)
        
    @ac.command(name="fkcheck", description="Validate External Foreign Keys")
    async def fkcheck(self, interaction: Interaction):
        if not await is_server(interaction):
            await interaction.response.send_message(tmpl.dm_not_allowed, ephemeral=True)
            return
        await interaction.response.send_message(tmpl.checking_fk)
        # get the 3 tables that have external foreign keys (Player, Statistics, Dossiers)
        players = self.bot.sessionmaker.query(Player).all()
        invalid_players = {}
        for player in players:
            # check if the player.discord_id returns a valid result from fetch_member
            try:
                member = await interaction.guild.fetch_member(player.discord_id)
            except NotFound:
                invalid_players[player.name] = player.discord_id
        if invalid_players:
            await interaction.followup.send(f"Invalid players: {invalid_players}")
        else:
            await interaction.followup.send("No invalid players found")
        invalid_statistics = {}
        statistics = self.bot.sessionmaker.query(Statistic).all()
        stats_channel: TextChannel = self.bot.get_channel(self.bot.config["statistics_channel_id"])
        if stats_channel:
            for statistic in statistics:
                try:
                    message = await stats_channel.fetch_message(statistic.message_id)
                except NotFound:
                    invalid_statistics[statistic.player.name] = statistic.message_id
        if invalid_statistics:
            await interaction.followup.send(f"Invalid statistics: {invalid_statistics}")
        else:
            await interaction.followup.send("No invalid statistics found")
        invalid_dossiers = {}
        dossiers = self.bot.sessionmaker.query(Dossier).all()
        dossier_channel: TextChannel = self.bot.get_channel(self.bot.config["dossier_channel_id"])
        if dossier_channel:
            for dossier in dossiers:
                try:
                    message = await dossier_channel.fetch_message(dossier.message_id)
                except NotFound:
                    invalid_dossiers[dossier.player.name] = dossier.message_id
        if invalid_dossiers:
            await interaction.followup.send(f"Invalid dossiers: {invalid_dossiers}")
        else:
            await interaction.followup.send("No invalid dossiers found")
        await interaction.followup.send(tmpl.fk_check_complete)

    @ac.command(name="guilds", description="Show all guilds the bot is in")
    async def guilds(self, interaction: Interaction):
        message = "Guilds:\n"
        for guild in self.bot.guilds:
            message += f"{guild.name}\n"
        await interaction.response.send_message(message, ephemeral=self.bot.use_ephemeral)

    @ac.command(name="test", description="Does whatever Cheese made it do today")
    @uses_db(CustomClient().sessionmaker)
    async def test(self, interaction: Interaction, session: Session):
        await interaction.response.defer(ephemeral=True)
        main_guild = self.bot.get_guild(int(os.getenv("MAIN_GUILD_ID", "222052888531173386")))
        if main_guild:
            # get all the users and roles in the environment, and send f"{key}: {value.mention}" for each
            message = "Users:\n"
            owner1 = main_guild.get_member(int(os.getenv("BOT_OWNER_ID")))
            owner2 = main_guild.get_member(int(os.getenv("BOT_OWNER_ID_2")))
            answerer1 = main_guild.get_member(int(os.getenv("FAQ_ANSWERER_1")))
            answerer2 = main_guild.get_member(int(os.getenv("FAQ_ANSWERER_2")))
            mod1 = main_guild.get_role(int(os.getenv("MOD_ROLE_1")))
            mod2 = main_guild.get_role(int(os.getenv("MOD_ROLE_2")))
            gm = main_guild.get_role(int(os.getenv("GM_ROLE")))
            commnet = main_guild.get_channel(int(os.getenv("COMM_NET_CHANNEL_ID")))
            message += f"Owner 1: {owner1.mention if owner1 else 'Unknown'}\n"
            message += f"Owner 2: {owner2.mention if owner2 else 'Unknown'}\n"
            message += f"Answerer 1: {answerer1.mention if answerer1 else 'Unknown'}\n"
            message += f"Answerer 2: {answerer2.mention if answerer2 else 'Unknown'}\n"
            message += f"Mod 1: {mod1.mention if mod1 else 'Unknown'}\n"
            message += f"Mod 2: {mod2.mention if mod2 else 'Unknown'}\n"
            message += f"GM: {gm.mention if gm else 'Unknown'}\n"
            message += f"CommNet: {commnet.mention if commnet else 'Unknown'}\n"
            await interaction.followup.send(message)
        else:
            await interaction.followup.send("Main guild not found")

    @ac.command(name="logmark", description="make a marker in the logs")
    async def logmark(self, interaction: Interaction):
        logger.info(f"[LOGMARK] {interaction.user.global_name} used logmark")
        await interaction.response.send_message(tmpl.marker_made, ephemeral=True)

    @ac.command(name="set_level", description="Set the log level")
    async def set_level(self, interaction: Interaction, _logger: str, level: int):
        if _logger == "root":
            # the logger in scope is not the root logger, so we need to get the root logger
            logger = logging.getLogger()
        else:
            logger = logging.getLogger(_logger)
        logger.setLevel(level)
        logger.info(f"Log level set to {level}")
        await interaction.response.send_message(tmpl.debug_log_level.format(level=level), ephemeral=True)

    @ac.command(name="tail", description="Get the last ~2000 characters of the log file")
    async def tail(self, interaction: Interaction):
        with open(os.getenv("LOG_FILE"), "r") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 2500))
            lines = f.readlines()
        good_lines = []
        if lines[0].startswith("20") and lines[0][2:4].isdigit():
            good_lines = lines
        elif "Error" in lines[0] or "Exception" in lines[0]:
            good_lines = lines
        else:
            good_lines = lines[1:]
        output_lines = []
        current_length = 0
        for line in reversed(good_lines):
            new_length = current_length + len(line)
            if new_length > 2000:
                break
            output_lines.append(line)
            current_length = new_length
        output_lines.reverse()
        await interaction.response.send_message(("\n".join(output_lines))[:2000], ephemeral=True)

    @ac.command(name="logfile", description="Get the current log file as a Discord file")
    @error_reporting(True)
    async def logfile(self, interaction: Interaction):
        """Get the current log file opened by __main__.file_handler as a Discord file."""
        try:
            # Get the log file path from environment
            log_file_path = os.getenv("LOG_FILE")
            if not log_file_path or not os.path.exists(log_file_path):
                await interaction.response.send_message("Log file not found or not configured", ephemeral=True)
                return
            
            # Read the log file
            with open(log_file_path, "r", encoding="utf-8") as f:
                log_content = f.read()
            
            # Create a BytesIO object with the log content
            log_bytes = BytesIO(log_content.encode("utf-8"))
            
            # Create a Discord file
            discord_file = File(log_bytes, filename=f"armco_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
            
            await interaction.response.send_message(
                f"Current log file ({len(log_content)} characters):",
                file=discord_file,
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            await interaction.response.send_message(f"Error reading log file: {e}", ephemeral=True)

    has_run = True # False
    @loop(hours=3)
    async def _bump_briefing(self):
        if not self.has_run:
            self.has_run = True
            return # skip the first run, so we don't send a message when the module is reloaded
        channel = self.bot.get_channel(1382037040438181950)
        if channel:
            async for message in channel.history(limit=5):
                if message.author == self.bot.user:
                    return
            target = "https://discord.com/channels/222052888531173386/1382037040438181950/1392894268263239730"
            message = f"## Atlas Briefing T7 - {target}"
            await channel.send(message)

    async def cog_unload(self):
        self._bump_briefing.cancel()

bot: Bot = None
async def setup(_bot: CustomClient):
    global bot
    bot = _bot
    logger.debug("Setting up Debug cog")
    await bot.add_cog(Debug(bot))

async def teardown():
    logger.debug("Tearing down Debug cog")
    bot.remove_cog(Debug.__name__) # remove_cog takes a string, not a class
