"""
CustomClient is a specialized subclass of `discord.ext.commands.Bot` to facilitate the S.A.M. bot functionality.

*Features*:
    - Integrates with SQLAlchemy for database operations.
    - Uses an asynchronous task queue for handling various player and unit-related tasks.
    - Periodically keeps the database session alive.
    - Manages bot commands and extensions.
    - Syncs slash commands with Discord's command tree.
    - Employs error handling for database session management.

Modules:
    - `discord.ext.commands`: Provides command-related tools.
    - `discord.app_commands`: Manages Discord's application commands.
    - `sqlalchemy.orm.Session`: Database session handling.
    - `logging`: Logging utilities for debugging and information.
"""

from discord import Interaction, Intents, Status, Activity, ActivityType
from discord.ext.commands import Bot
from discord.ext import tasks
from os import getenv
from sqlalchemy.orm import Session
from models import *
from sqlalchemy import text
from datetime import datetime
from typing import Any
from singleton import Singleton
import asyncio
import templates
import logging

use_ephemeral = getenv("EPHEMERAL", "false").lower() == "true"

logging.basicConfig(level=logging.getLevelName(getenv("LOG_LEVEL", "INFO")))
logger = logging.getLogger(__name__)
logging.getLogger("discord").setLevel(logging.WARNING)

@Singleton
class CustomClient(Bot): # need to inherit from Bot to use Cogs
    """
    CustomClient is a subclass of discord.Bot that adds additional functionality for the S.A.M. bot.

    Attributes:
        - `mod_roles`: (Set[str]) Roles with moderator privileges.
        - `session`: (Session) Database session for executing SQL queries.
        - `use_ephemeral`: (bool) Controls whether to send messages as ephemeral.
        - `config`: (dict) Bot configuration loaded from the database.
    """
    mod_roles = {1308924912936685609, 1302095620231794698}
    session: Session
    use_ephemeral: bool
    config: dict
    def __init__(self, session: Session, **kwargs):
        """
        Initializes the CustomClient instance.

        Args:
            session (Session): The SQLAlchemy session for database operations.
            **kwargs: Additional keyword arguments for the Bot constructor.

        Merges the `DEFAULTS` with provided `kwargs`, loads configurations, and initializes
        the task queue. Additionally, loads or initializes `BOT_CONFIG` and `MEDAL_EMOTES` in the database.
        """
        defintents = Intents.default()
        defintents.members = True
        DEFAULTS = {"command_prefix":"\0", "intents":defintents}
        kwargs = {**DEFAULTS, **kwargs} # merge DEFAULTS and kwargs, kwargs takes precedence
        super().__init__(**kwargs)
        self.owner_ids = {533009808501112881, 126747253342863360}
        self.session = session
        self.queue = asyncio.Queue()
        _Config = self.session.query(Config).filter(Config.key == "BOT_CONFIG").first()
        if not _Config:
            _Config = Config(key="BOT_CONFIG", value={"EXTENSIONS":[]})
            self.session.add(_Config)
            self.session.commit()
        self.config:dict = _Config.value
        _Medal_Emotes = self.session.query(Config).filter(Config.key == "MEDAL_EMOTES").first()
        if not _Medal_Emotes:
            _Medal_Emotes = Config(key="MEDAL_EMOTES", value={})
            self.session.add(_Medal_Emotes)
            self.session.commit()
        self.medal_emotes:dict = _Medal_Emotes.value
        self.use_ephemeral = use_ephemeral

    async def resync_config(self):
        """
        Synchronizes the bot configuration with the database.

        Fetches and updates the in-memory configuration, ensuring the bot is synchronized with the database.

        Raises:
            SQLAlchemyError: If a database operation fails.
        """
        _Config = self.session.query(Config).filter(Config.key == "BOT_CONFIG").first()
        _Config.value = self.config
        self.session.commit()
        logger.debug(f"Resynced config: {self.config}")

    async def queue_consumer(self):
        """
        Consumes tasks from the queue for processing player and unit actions.

        *Task Types*:
            - **0**: Creation tasks.
            - **1**: Update tasks.
            - **2**: Deletion tasks.
            - **4**: Graceful termination of the queue consumer.

        This method runs indefinitely, processing tasks from the queue and managing associated database
        operations, while updating channels as necessary.

        Raises:
            Exception: If task processing encounters an error.
        """
        logger.info("queue consumer started")
        unknown_handler = lambda task: logger.error(f"Unknown task type: {task}")
        handlers = {
            0: self._handle_create_task,
            1: self._handle_update_task,
            2: self._handle_delete_task,
            4: self._handle_terminate_task
        }
        
        while True:
            await asyncio.sleep(5)  # Maintain pacing to avoid hitting downstream timeouts
            logger.debug(f"Queue size: {self.queue.qsize()}")
            task = await self.queue.get()
            logger.debug(f"Processing task: {task}")
            if not isinstance(task, tuple):
                logger.error("Task is not a tuple, skipping")
                continue
            if len(task) == 0:
                logger.error("Empty task received, skipping")
                continue
            # Initialize fail count
            fail_count = task[2] if len(task) > 2 else 0
            if fail_count > 5:
                logger.error(f"Task {task} failed too many times, skipping")
                continue

            try:
                result = await handlers.get(task[0], unknown_handler)(task)
                if result:
                    break
            except Exception as e:
                logger.error(f"Error processing task {task}: {e}")
                # Requeue the task with an incremented fail count
                new_fail_count = fail_count + 1
                if len(task) > 2:
                    task = (*task[:2], new_fail_count)  # Update fail count
                else:
                    task = (*task, new_fail_count)  # Add fail count
                self.queue.put_nowait(task)

    # we are going to start subdividing the queue consumer into multiple functions, for clarity

    async def _handle_create_task(self, task: tuple[int, Any]):
        if self.config.get("dossier_channel_id"):
            if isinstance(task[1], Player):
                player = task[1]
                medals = self.session.query(Medals).filter(Medals.player_id == player.id).all()
                # identify what medals have known emotes
                known_emotes = set(self.medal_emotes.keys())
                known_medals = {medal.name for medal in medals if medal.name in known_emotes}
                unknown_medals = {medal.name for medal in medals if medal.name not in known_emotes}
                known_medals_list = list(known_medals)
                # make rows of 5 medals that have known emotes
                rows = [known_medals_list[i:i+5] for i in range(0, len(known_medals_list), 5)]
                unknown_medals_list = list(unknown_medals)
                unknown_text = "\n".join(unknown_medals_list)
                # convert the rows to a string of emotes, with a space between each emote
                medal_block = "\n".join([" ".join([self.medal_emotes[medal] for medal in row]) for row in rows]) + "\n" + unknown_text
                mention = await self.fetch_user(player.discord_id)
                mention = mention.mention if mention else ""
                # check for an existing dossier message, if it exists, skip creation
                existing_dossier = self.session.query(Dossier).filter(Dossier.player_id == player.id).first()
                if existing_dossier:
                    # check if the message itself actually exists
                    channel = self.get_channel(self.config["dossier_channel_id"])
                    if channel:
                        message = await channel.fetch_message(existing_dossier.message_id)
                        if message:
                            logger.debug(f"Dossier message for player {player.id} already exists, skipping creation")
                            return
                dossier_message = await self.get_channel(self.config["dossier_channel_id"]).send(templates.Dossier.format(mention=mention, player=player, medals=medal_block))
                dossier = Dossier(player_id=player.id, message_id=dossier_message.id)
                self.session.add(dossier)
                self.session.commit()
                logger.debug(f"Created dossier for player {player.id} with message ID {dossier_message.id}")
        if self.config.get("statistics_channel_id"):
            if isinstance(task[1], Player):
                player = task[1]
                unit_message = self.generate_unit_message(player)
                mention = await self.fetch_user(player.discord_id)
                mention = mention.mention if mention else ""
                # check for an existing statistics message, if it exists, skip creation
                existing_statistics = self.session.query(Statistic).filter(Statistic.player_id == player.id).first()
                if existing_statistics:
                    # check if the message itself actually exists
                    channel = self.get_channel(self.config["statistics_channel_id"])
                    if channel:
                        message = await channel.fetch_message(existing_statistics.message_id)
                        if message:
                            logger.debug(f"Statistics message for player {player.id} already exists, skipping creation")
                            return
                statistics_message = await self.get_channel(self.config["statistics_channel_id"]).send(templates.Statistics_Player.format(mention=mention, player=player, units=unit_message))
                statistics = Statistic(player_id=player.id, message_id=statistics_message.id)
                self.session.add(statistics)
                self.session.commit()
                logger.debug(f"Created statistics for player {player.id} with message ID {statistics_message.id}")
            elif isinstance(task[1], Unit):
                player = self.session.query(Player).filter(Player.id == task[1].player_id).first()
                self.queue.put_nowait((1, player))
                logger.debug(f"Queued update task for player {player.id} due to unit {task[1].id}")
            elif isinstance(task[1], Upgrade):
                unit = self.session.query(Unit).filter(Unit.id == task[1].unit_id).first()
                player = self.session.query(Player).filter(Player.id == unit.player_id).first()
                self.queue.put_nowait((1, player))
                logger.debug(f"Queued update task for player {player.id} due to upgrade {task[1].id}")

    async def _handle_update_task(self, task):
        if isinstance(task[1], Player):
            player = task[1]
            dossier = self.session.query(Dossier).filter(Dossier.player_id == player.id).first()
            if dossier:
                channel = self.get_channel(self.config["dossier_channel_id"])
                if channel:
                    message = await channel.fetch_message(dossier.message_id)
                    mention = await self.fetch_user(player.discord_id)
                    mention = mention.mention if mention else ""
                    await message.edit(content=templates.Dossier.format(mention=mention, player=player, medals=""))
                    logger.debug(f"Updated dossier for player {player.id} with message ID {dossier.message_id}")
            else:
                # user doesn't have a dossier message, push a create task on the user, to fudge it back
                self.queue.put_nowait((0, player))
                logger.debug(f"Queued create task for player {player.id} due to missing dossier message")
            statistics = self.session.query(Statistic).filter(Statistic.player_id == player.id).first()
            if statistics:
                channel = self.get_channel(self.config["statistics_channel_id"])
                if channel:
                    message = await channel.fetch_message(statistics.message_id)
                    unit_message = self.generate_unit_message(player)
                    mention = await self.fetch_user(player.discord_id)
                    mention = mention.mention if mention else ""
                    await message.edit(content=templates.Statistics_Player.format(mention=mention, player=player, units=unit_message))
                    logger.debug(f"Updated statistics for player {player.id} with message ID {statistics.message_id}")
                else:
                    # user doesn't have a statistics message, push a create task on the user, to fudge it back
                    self.queue.put_nowait((0, player))
                    logger.debug(f"Queued create task for player {player.id} due to missing statistics message")
        elif isinstance(task[1], Unit):
            unit = task[1]
            player = self.session.query(Player).filter(Player.id == unit.player_id).first()
            self.queue.put_nowait((1, player))
            logger.debug(f"Queued update task for player {player.id} due to unit {unit.id}")
        elif isinstance(task[1], Upgrade):
            upgrade = task[1]
            unit = self.session.query(Unit).filter(Unit.id == upgrade.unit_id).first()
            player = self.session.query(Player).filter(Player.id == unit.player_id).first()
            self.queue.put_nowait((1, player))
            logger.debug(f"Queued update task for player {player.id} due to upgrade {upgrade.id}")

    async def _handle_delete_task(self, task):
        if isinstance(task[1], Dossier):
            dossier = task[1]
            channel = self.get_channel(self.config["dossier_channel_id"])
            if channel:
                message = await channel.fetch_message(dossier.message_id)
                await message.delete()
                logger.debug(f"Deleted dossier message ID {dossier.message_id} for player {dossier.player_id}")
        elif isinstance(task[1], Statistic):
            statistic = task[1]
            channel = self.get_channel(self.config["statistics_channel_id"])
            if channel:
                message = await channel.fetch_message(statistic.message_id)
                await message.delete()
                logger.debug(f"Deleted statistics message ID {statistic.message_id} for player {statistic.player_id}")
        elif isinstance(task[1], Unit):
            unit = task[1]
            player = self.session.query(Player).filter(Player.id == unit.player_id).first()
            self.queue.put_nowait((1, player))
            logger.debug(f"Queued update task for player {player.id} due to unit {unit.id}")
        elif isinstance(task[1], Upgrade):
            upgrade = task[1]
            unit = self.session.query(Unit).filter(Unit.id == upgrade.unit_id).first()
            player = self.session.query(Player).filter(Player.id == unit.player_id).first()
            self.queue.put_nowait((1, player))
            logger.debug(f"Queued update task for player {player.id} due to upgrade {upgrade.id}")

    async def _handle_terminate_task(self, task): 
        logger.debug("Queue consumer terminating")
        return True # this is the only function that returns a value, as that's how we'll know to terminate, is if a value or raise is returned

    stats_map = {
        "INFANTRY": templates.Infantry_Stats,
        "MEDIC": templates.Non_Combat_Stats,
        "ENGINEER": templates.Non_Combat_Stats,
        "ARTILLERY": templates.Artillery_Stats,
        "MAIN_TANK": templates.Armor_Stats,
        "LIGHT_VEHICLE": templates.Armor_Stats,
        "LOGISTIC": templates.Armor_Stats,
        "BOMBER": templates.Air_Stats,
        "FIGHTER": templates.Air_Stats,
        "VTOL": templates.Air_Stats,
        "HVTOL": templates.Air_Stats,
        "HAT": templates.Air_Stats,
        "LIGHT_MECH": templates.Armor_Stats
    }

    def generate_unit_message(self, player: Player):
        """
        Creates a message detailing a player's units, both active and inactive.

        Args:
            player (Player): The player instance for whom the message is generated.

        Returns:
            str: Formatted unit messages for the player, grouped by status.
        """
        logger.debug(f"Generating unit message for player: {player.id}")
        unit_messages = []

        # Query inactive units
        inactive_units = self.session.query(Unit).filter(Unit.player_id == player.id).all()
        logger.debug(f"Found {len(inactive_units)} inactive units for player: {player.id}")
        for unit in inactive_units:
            upgrades = self.session.query(Upgrade).filter(Upgrade.unit_id == unit.id).all()
            upgrade_list = ", ".join([upgrade.name for upgrade in upgrades])
            logger.debug(f"Inactive unit {unit.name} of type {unit.unit_type} has status {unit.status.name}")
            logger.debug(f"Inactive unit {unit.id} has upgrades: {upgrade_list}")
            unit_messages.append(templates.Statistics_Unit.format(unit=unit, upgrades=upgrade_list, callsign=('\"' + unit.callsign + '\"') if unit.callsign else ""))

        # Combine all unit messages into a single string
        combined_message = "\n".join(unit_messages)
        logger.debug(f"Generated unit message for player {player.id}: {combined_message}")
        return combined_message

    @tasks.loop(hours=4)
    async def session_keep_alive(self):
        """
        Maintains the database session by executing a query every 4 hours.

        Ensures the session remains active by running a "SELECT 1" query periodically.

        Raises:
            Exception: If an error occurs during the keep-alive query.
        """
        logger.debug("Session Keep-Alive Task started")
        try:
            self.session.execute(text("SELECT 1"))
            logger.debug("Session Keep-Alive Task successful")
        except Exception as e:
            logger.error(f"Session Keep-Alive Task failed: {e}")

    async def load_extensions(self, extensions: list[str]):
        """
        Loads a list of bot extensions (modules).

        Args:
            extensions (List[str]): List of extension names to load.
        """
        for extension in extensions:
            await self.load_extension(extension)
        logger.debug(f"Loaded extensions: {', '.join(extensions)}")

    async def set_bot_nick(self, nick: str):
        """
        Sets the bot's nickname across all connected guilds.

        Args:
            nick (str): The new nickname for the bot.
        """
        for guild in self.guilds:
            await guild.me.edit(nick=nick)

    async def on_ready(self):
        """
        Event handler for bot readiness.

        Called upon successful login, setting the bot's nickname, starting the queue consumer,
        and logging the bot's information.
        """
        logger.info(f"Logged in as {self.user}")
        await self.set_bot_nick("S.A.M.")
        asyncio.create_task(self.queue_consumer())
        await self.change_presence(status=Status.online, activity=Activity(name="Meta Campaign", type=ActivityType.playing))
        try:
            self.session_keep_alive.start()
        except Exception as e:
            logger.error(f"Error starting session keep-alive: {e}")
        if (getenv("STARTUP_ANIMATION", "false").lower() == "true"):
            try:
                self.startup_animation.start()
            except Exception as e:
                logger.error(f"Error starting startup animation: {e}")

    @tasks.loop(count=1)
    async def startup_animation(self):
        try:
            import sam_startup
        except ImportError:
            return
        channel = await self.fetch_channel(1211454073383952395)
        message =await channel.send(sam_startup.startup_sequence[0])
        for frame in sam_startup.startup_sequence[1:]:
            await message.edit(content=frame)
            await asyncio.sleep(1)
        self.startup_animation.cancel()

    async def close(self):
        """
        Closes the bot and performs necessary cleanup.

        Puts a termination signal in the queue, resyncs configuration, commits database changes,
        and closes the session.
        """
        await self.queue.put((4, None))
        await self.resync_config()
        try:
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error committing session, rolling back: {e}")
        self.session.close()
        await self.change_presence(status=Status.offline, activity=None)
        await super().close()

    async def setup_hook(self):
        """
        Sets up the bot's event listeners and syncs slash commands.

        This method is called when the bot is ready to receive events and commands. It:
            - Defines the `/ping` command
            - Loads core and additional extensions.
            - Synchronizes slash commands with Discord's command tree.
        """
        @self.tree.command(name="ping", description="Ping the bot")
        async def ping(interaction: Interaction):
            """
            Responds with "Pong!" and shows the bot's last restart time.

            *Displays:*
            - A message saying "Pong!" to indicate that the bot is active.
            - The last time the bot was restarted, both in a formatted and relative format.
            
            Example:
                `/ping` returns "Pong! I was last restarted at [formatted date], [relative time]."
            """
            await interaction.response.send_message(f"Pong! I was last restarted at <t:{int(self.start_time.timestamp())}:F>, <t:{int(self.start_time.timestamp())}:R>")

        await self.load_extension("extensions.debug") # the debug extension is loaded first and is always loaded
        #await self.load_extension("extensions.configuration") # for initial setup, we want to disable all user commands, so we only load the configuration extension
        await self.load_extensions(["extensions.admin", "extensions.configuration", "extensions.units", "extensions.shop", "extensions.companies", "extensions.backup", "extensions.search"]) # remaining extensions are currently loaded automatically, but will later support only autoloading extension that were active when it was last stopped
        
        logger.debug("Syncing slash commands")
        await self.tree.sync()
        logger.debug("Slash commands synced")
        
    async def start(self, *args, **kwargs):
        """
        Starts the bot with the provided arguments.

        Records the start time and retrieves the bot token from environment variables.

        Args:
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        self.start_time = datetime.now()
        logger.debug(f"Starting bot at {self.start_time}")
        await super().start(getenv("BOT_TOKEN"), *args, **kwargs)
        logger.debug(f"Bot has terminated at {datetime.now()}")