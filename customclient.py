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

from discord import Interaction, Intents, Status, Activity, ActivityType, Member
from discord.ext.commands import Bot
from discord.ext import tasks
from os import getenv
from sqlalchemy.orm import Session
from models import *
from sqlalchemy import text, func
from datetime import datetime, timedelta
from typing import Any, Callable
from singleton import Singleton
import asyncio
import templates as tmpl
import logging
from utils import uses_db, RollingCounterDict, callback_listener, toggle_command_ban, is_management_no_notify, on_error_decorator
from prometheus_client import Counter

use_ephemeral = getenv("EPHEMERAL", "false").lower() == "true"

logging.basicConfig(level=logging.getLevelName(getenv("LOG_LEVEL", "INFO")))
logger = logging.getLogger(__name__)
logging.getLogger("discord").setLevel(logging.WARNING)

# Create interaction counter metric
interaction_counter = Counter("interactions_total", "Total number of interactions", labelnames=["guild_name"])
error_counter = Counter("errors_total", "Total number of errors", labelnames=["guild_name", "error"])

@Singleton
class CustomClient(Bot): # need to inherit from Bot to use Cogs
    """
    CustomClient is a subclass of discord.Bot that adds additional functionality for the S.A.M. bot.

    Attributes:
        - `mod_roles`: (Set[str]) Roles with moderator privileges.
        - `session`: (Session) Database session for executing SQL queries.
        - `use_ephemeral`: (bool) Controls whether to send messages as ephemeral.
        - `config`: (dict) Bot configuration loaded from the database.
        - `uses_db`: (Callable) A decorator for database operations.
    """
    mod_roles: set[int] = {int(getenv("MOD_ROLE_1", "1308924912936685609")), int(getenv("MOD_ROLE_2", "1302095620231794698"))}
    gm_role: int = int(getenv("GM_ROLE", "1308925031069388870"))
    session: Session
    use_ephemeral: bool
    config: dict
    sessionmaker: Callable
    start_time: datetime
    def __init__(self, session: Session,/, sessionmaker: Callable, dialect: str, **kwargs):
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
        self.owner_ids = {int(getenv("BOT_OWNER_ID", "533009808501112881")), int(getenv("BOT_OWNER_ID_2", "126747253342863360"))}
        self.sessionmaker = sessionmaker
        self.queue = asyncio.Queue()
        self.dialect = dialect
        _Config = session.query(Config).filter(Config.key == "BOT_CONFIG").first()
        if not _Config:
            _Config = Config(key="BOT_CONFIG", value={"EXTENSIONS":[]})
            session.add(_Config)
            session.commit()
        self.config:dict = _Config.value
        _Medal_Emotes = session.query(Config).filter(Config.key == "MEDAL_EMOTES").first()
        if not _Medal_Emotes:
            _Medal_Emotes = Config(key="MEDAL_EMOTES", value={})
            session.add(_Medal_Emotes)
            session.commit()
        self.medal_emotes:dict = _Medal_Emotes.value
        self.use_ephemeral = use_ephemeral
        self.tree.interaction_check = self.check_banned_interaction # self.no_commands # TODO: switch back to check_banned_interaction, this is a temporary measure

    async def no_commands(self, interaction: Interaction):
        if not await is_management_no_notify(interaction, silent=True):
            await interaction.response.send_message(f"# A COMMAND BAN IS IN EFFECT {interaction.user.mention}, WHY ARE YOU TRYING TO RUN A COMMAND?")
            return False
        return True

    async def check_banned_interaction(self, interaction: Interaction):
        # Increment interaction counter
        guild_name = interaction.guild.name if interaction.guild else "DMs"
        interaction_counter.labels(guild_name=guild_name).inc()
        interaction_counter.labels(guild_name="total").inc()
        
        # check if the user.id is in the BANNED_USERS env variable, if so, reply with a message and return False, else return True
        logger.debug(f"Interaction check for user {interaction.user.global_name} in {interaction.guild.name if interaction.guild else 'DMs'}")
        banned_users = getenv("BANNED_USERS", "").split(",")
        if not banned_users[0]: # if the env was empty, split returns [""], so we need to check for that
            logger.debug(f"Interaction check passed for user {interaction.user.global_name}")
            return True
        banned_users = [int(user) for user in banned_users]
        if interaction.user.id in banned_users:
            await interaction.response.send_message("You are banned from using this bot", ephemeral=self.use_ephemeral)
            logger.warning(f"Interaction check failed for user {interaction.user.global_name}")
            return False
        logger.debug(f"Interaction check passed for user {interaction.user.global_name}")
        return True

    async def resync_config(self, session: Session):
        """
        Synchronizes the bot configuration with the database.

        Fetches and updates the in-memory configuration, ensuring the bot is synchronized with the database.

        Raises:
            SQLAlchemyError: If a database operation fails.
        """
        _Config = session.query(Config).filter(Config.key == "BOT_CONFIG").first()
        _Config.value = self.config
        logger.debug(f"Resynced config: {self.config}")

    async def queue_consumer(self, session: Session):
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
        ratelimit = RollingCounterDict(30)
        nosleep = True
        queue_banned = False
        size_at_ban = None
        
        while True:
            if nosleep:
                await asyncio.sleep(0)
                nosleep = False
            else:
                await asyncio.sleep(7)  # Maintain pacing to avoid hitting downstream timeouts
            queue_size = self.queue.qsize()
            eta = timedelta(seconds=queue_size * 7)
            logger.debug(f"Queue size: {queue_size}, Empty in {eta}")
            await self.change_presence(status=Status.online, activity=Activity(name="Meta Campaign" if queue_size == 0 else f"Updating {queue_size} dossiers, Finished in {eta}", type=ActivityType.playing))
            
            if queue_size >= 1200 and not queue_banned:
                logger.critical(f"Queue size is {queue_size}, this is too high!")
                # fetch the discord user for the bot owner, message them, then call self.close()
                owner = await self.fetch_user(int(getenv("BOT_OWNER_ID", "533009808501112881")))
                if owner:
                    await owner.send("Queue size is too high, Initiating a System Ban")
                await toggle_command_ban(True, self.user.mention)
                queue_banned = True
                size_at_ban = queue_size
            if queue_banned and queue_size < 100:
                logger.debug("Queue size is below 100, disabling command ban")
                await toggle_command_ban(False, self.user.mention)
                queue_banned = False
                size_at_ban = None
            if queue_banned and queue_size >= size_at_ban+200:
                logger.debug("Queue is still growing, Purging")
                owner = await self.fetch_user(int(getenv("BOT_OWNER_ID", "533009808501112881")))
                if owner:
                    await owner.send("Queue is still growing, Purging")
                while not self.queue.empty():
                    self.queue.get_nowait()
                    self.queue.task_done()
            task = await self.queue.get()
            if not isinstance(task, tuple):
                logger.error("Task is not a tuple, skipping")
                nosleep = True
                continue
            # we need to recraft the tuple before we can log it, because the session is detached
            if len(task) == 3:
                task = (task[0], session.merge(task[1]), task[2])
            elif len(task) == 2:
                task = (task[0], session.merge(task[1]), 0)
            elif len(task) == 1:
                if not task[0] == 4:
                    logger.error("Task is a tuple of length 1, but the first element is not 4, skipping")
                    nosleep = True
                    continue
            else:
                logger.error(f"Task is a tuple of length {len(task)}, skipping")
                nosleep = True
                continue
            ratelimit.set(str(task[1]))
            if ratelimit.get(str(task[1])) >=5: # window is 30s, which is 6 tasks, this requires at least 50% different tasks
                logger.warning(f"Ratelimit hit for {task[1]}")
                nosleep = True
                continue # just discard the task
            #logger.debug(f"Processing task: {task}")
            # Initialize fail count
            fail_count = task[2] if len(task) > 2 else 0
            if fail_count > 5:
                logger.error(f"Task {task} failed too many times, skipping")
                nosleep = True
                continue

            try:
                result = await handlers.get(task[0], unknown_handler)(task)
                #session.expunge(task[1]) # expunge the instance to avoid memory leak or stale commits
                if result:
                    break
            except Exception as e:
                logger.error(f"Error processing task: {e}")
                # Requeue the task with an incremented fail count
                new_fail_count = fail_count + 1
                if len(task) > 2:
                    task = (*task[:2], new_fail_count)  # Update fail count
                else:
                    task = (*task, new_fail_count)  # Add fail count
                self.queue.put_nowait(task)
            self.queue.task_done()

    # we are going to start subdividing the queue consumer into multiple functions, for clarity

    async def _handle_create_task(self, task: tuple[int, Player, int], session: Session):
        """Handle creation tasks for players only"""
        if self.dialect == "mysql":
            session.execute(text("SET SESSION innodb_lock_wait_timeout = 10"))
        
        if not isinstance(task[1], Player):
            logger.error(f"Task type 0 (create) received non-Player instance: {type(task[1])}")
            return
        requeued = False
        player = session.query(Player).filter(Player.id == task[1].id).first()
        if not player:
            logger.error(f"Player with id {task[1].id} not found in database")
            return
        
        if self.config.get("dossier_channel_id"):
            medals = session.query(Medals).filter(Medals.player_id == player.id).all()
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
            create_dossier = True
            existing_dossier = session.query(Dossier).filter(Dossier.player_id == player.id).first()
            if existing_dossier:
                # check if the message itself actually exists
                channel = self.get_channel(self.config["dossier_channel_id"])
                if channel:
                    message = await channel.fetch_message(existing_dossier.message_id)
                    if message:
                        logger.debug(f"Dossier message for player {player.id} already exists, skipping creation")
                        self.queue.put_nowait((1, player, 0))
                        create_dossier = False
                        requeued = True
                        
            if not player.id:
                logger.error(f"missing player id, skipping dossier creation")
                create_dossier = False
            
            if create_dossier:
                dossier_message = await self.get_channel(self.config["dossier_channel_id"]).send(
                    tmpl.Dossier.format(mention=mention, player=player, medals=medal_block)
                )
                dossier = Dossier(player_id=player.id, message_id=dossier_message.id)
                session.add(dossier)
                logger.debug(f"Created dossier for player {player.id} with message ID {dossier_message.id}")
            
        if self.config.get("statistics_channel_id"):
            unit_message = await self.generate_unit_message(player)
            _player = session.merge(player)
            discord_id = _player.discord_id
            mention = await self.fetch_user(discord_id)
            mention = mention.mention if mention else ""
            
            # check for an existing statistics message, if it exists, skip creation
            existing_statistics = session.query(Statistic).filter(Statistic.player_id == _player.id).first()
            if existing_statistics:
                # check if the message itself actually exists
                channel = self.get_channel(self.config["statistics_channel_id"])
                if channel:
                    message = await channel.fetch_message(existing_statistics.message_id)
                    if message:
                        logger.debug(f"Statistics message for player {_player.id} already exists, skipping creation")
                        if not requeued:
                            self.queue.put_nowait((1, _player, 0))
                            requeued = True
                        return
                        
            if not _player.id:
                logger.error(f"missing player id, skipping statistics creation")
                return
            
            statistics_message = await self.get_channel(self.config["statistics_channel_id"]).send(
                tmpl.Statistics_Player.format(mention=mention, player=_player, units=unit_message)
            )
            statistics = Statistic(player_id=_player.id, message_id=statistics_message.id)
            session.add(statistics)
            logger.debug(f"Created statistics for player {_player.id} with message ID {statistics_message.id}")

    async def _handle_update_task(self, task: tuple[int, Player, int], session: Session):
        """Handle update tasks for players only"""
        with session.no_autoflush:
            if self.dialect == "mysql":
                session.execute(text("SET SESSION innodb_lock_wait_timeout = 10"))
            requeued = False
            logger.debug(f"handling update task")
        
            if not isinstance(task[1], Player):
                logger.error(f"Task type 1 (update) received non-Player instance: {type(task[1])}")
                return
            
            player = session.query(Player).filter(Player.id == task[1].id).first()
            if not player:
                logger.error(f"Player with id {task[1].id} not found in database")
                return
            
            logger.debug(f"Updating player: {player}")
            
            # Handle dossier update
            logger.debug("fetching dossier")
            dossier = session.query(Dossier).filter(Dossier.player_id == player.id).first()
            if dossier:
                logger.debug("dossier found, fetching channel")
                channel = self.get_channel(self.config["dossier_channel_id"])
                if channel:
                    logger.debug("channel found, fetching message")
                    message = await channel.fetch_message(dossier.message_id)
                    logger.debug("message found, fetching user")
                    mention = await self.fetch_user(player.discord_id)
                    mention = mention.mention if mention else ""
                    logger.debug("user found, editing message")
                    await message.edit(content=tmpl.Dossier.format(mention=mention, player=player, medals=""))
                    logger.debug(f"Updated dossier for player {player.id} with message ID {dossier.message_id}")
            else:
                logger.debug("no dossier found, pushing create task")
                self.queue.put_nowait((0, player, 0))
                requeued = True
                logger.debug(f"Queued create task for player {player.id} due to missing dossier message Location 3")
            
            # Handle statistics update
            statistics = session.query(Statistic).filter(Statistic.player_id == player.id).first()
            if statistics:
                channel = self.get_channel(self.config["statistics_channel_id"])
                if channel:
                    message = await channel.fetch_message(statistics.message_id)
                    discord_id = player.discord_id
                    unit_message = await self.generate_unit_message(player)
                    _player = session.merge(player)
                    _statistics = session.merge(statistics)
                    mention = await self.fetch_user(discord_id)
                    mention = mention.mention if mention else ""
                    await message.edit(content=tmpl.Statistics_Player.format(mention=mention, player=_player, units=unit_message))
                    logger.debug(f"Updated statistics for player {_player.id} with message ID {_statistics.message_id}")
                else:
                    # there should be a message, but the discord side was probably deleted by a mod
                    logger.error(f"No channel found for statistics message of player {player.id}, skipping")
            else:
                # user doesn't have a statistics message, push a create task
                if not requeued:
                    self.queue.put_nowait((0, player, 0))
                    requeued = True
                    logger.debug(f"Queued create task for player {player.id} due to missing statistics message Location 4")
                else:
                    logger.debug(f"Already queued create task for player {player.id} due to missing dossier message, but the statistics message is also missing Location 5")

    async def _handle_delete_task(self, task: tuple[int, Any], session: Session):
        if self.dialect == "mysql":
            session.execute(text("SET SESSION innodb_lock_wait_timeout = 10"))
        logger.debug(f"requerying instance for delete task")
        with session.no_autoflush: # disable flush on delete, to avoid a reinsert
            instance = session.query(task[1].__class__).filter(task[1].__class__.id == task[1].id).first()
        logger.debug(f"instance found for delete task: {instance}") # we can't log the task as it's possibly unbound, but we can log the instance
        requeued = False
        if isinstance(instance, Dossier):
            dossier = instance
            channel = self.get_channel(self.config["dossier_channel_id"])
            if channel:
                message = await channel.fetch_message(dossier.message_id)
                await message.delete()
                logger.debug(f"Deleted dossier message ID {dossier.message_id} for player {dossier.player_id}")
        elif isinstance(instance, Statistic):
            statistic = instance
            channel = self.get_channel(self.config["statistics_channel_id"])
            if channel:
                message = await channel.fetch_message(statistic.message_id)
                await message.delete()
                logger.debug(f"Deleted statistics message ID {statistic.message_id} for player {statistic.player_id}")
        elif isinstance(instance, Unit):
            logger.debug(f"instance is a unit, expunging")
            session.expunge(instance)
            return
            unit = instance
            player = session.query(Player).filter(Player.id == unit.player_id).first()
            if player:
                if not requeued:
                    self.queue.put_nowait((1, player))
                    logger.debug(f"Queued update task for player {player.id} due to unit {unit.id} Location 7")
                    requeued = True
                else:
                    logger.debug(f"Already queued update task for player {player.id} due to unit {unit.id} Location 7")
        elif isinstance(instance, PlayerUpgrade):
            upgrade = instance
            unit = session.query(Unit).filter(Unit.id == upgrade.unit_id).first()
            player = session.query(Player).filter(Player.id == unit.player_id).first()
            if player:
                if not requeued:
                    self.queue.put_nowait((1, player))
                    logger.debug(f"Queued update task for player {player.id} due to upgrade {upgrade.id} Location 8")
                    requeued = True
                else:
                    logger.debug(f"Already queued update task for player {player.id} due to upgrade {upgrade.id} Location 8")
        if instance: # if the instance is not None, we need to expunge it, if the instance is None we can ignore it
            session.expunge(instance)

    async def _handle_terminate_task(self, task): 
        logger.debug("Queue consumer terminating")
        return True # this is the only function that returns a value, as that's how we'll know to terminate, is if a value or raise is returned

    async def generate_unit_message(self, player: Player, session: Session):
        """
        Creates a message detailing a player's units, both active and inactive.

        Args:
            player (Player): The player instance for whom the message is generated.

        Returns:
            str: Formatted unit messages for the player, grouped by status.
        """
        logger.debug(f"Generating unit message for player: {player.id}")
        unit_messages = []

        units = session.query(Unit).filter(Unit.player_id == player.id).all()
        logger.debug(f"Found {len(units)} units for player: {player.id}")
        for unit in units:
            upgrades = session.query(PlayerUpgrade).filter(PlayerUpgrade.unit_id == unit.id).all()
            upgrade_list = ", ".join([upgrade.name for upgrade in upgrades])
            logger.debug(f"Unit {unit.name} of type {unit.unit_type} has status {unit.status.name}")
            logger.debug(f"Unit {unit.id} has upgrades: {upgrade_list}")
            unit_messages.append(tmpl.Statistics_Unit.format(unit=unit, upgrades=upgrade_list, callsign=('\"' + unit.callsign + '\"') if unit.callsign else "", campaign_name=f"In {unit.campaign.name}" if unit.campaign else ""))

        # Combine all unit messages into a single string
        combined_message = "\n".join(unit_messages)
        logger.debug(f"Generated unit message for player {player.id}: {combined_message}")
        return combined_message

    async def load_extensions(self, extensions: list[str]):
        """
        Loads a list of bot extensions (modules).

        Args:
            extensions (List[str]): List of extension names to load.
        """
        results = await asyncio.gather(
            *[self.load_extension(ext) for ext in extensions if not ext in self.extensions.keys()],
            return_exceptions=True
        )
        success = []
        failed = []
        for ext, res in zip(extensions, results):
            if isinstance(res, Exception):
                failed.append(f"{ext}: {res}")
            else:
                success.append(ext)
        if failed:
            logger.error(f"Failed to load extensions: {', '.join(failed)}")
        if success:
            logger.debug(f"Loaded extensions: {', '.join(success)}")

    async def load_extension(self, extension: str):
        await super().load_extension(extension)
        with self.sessionmaker() as session:
            session.merge(Extension(name=extension)) # merge so we don't get integrity errors
            session.commit()

    async def unload_extension(self, extension: str):
        await super().unload_extension(extension)
        with self.sessionmaker() as session:
            session.query(Extension).filter(Extension.name == extension).delete()
            session.commit()

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
        #await self.set_bot_nick("S.A.M.")
        asyncio.create_task(self.queue_consumer())
        await self.change_presence(status=Status.online, activity=Activity(name="Meta Campaign", type=ActivityType.playing))
        if (getenv("STARTUP_ANIMATION", "false").lower() == "true"):
            try:
                self.startup_animation.start()
            except Exception as e:
                logger.error(f"Error starting startup animation: {e}")
        asyncio.create_task(callback_listener(self.shutdown_callback, "127.0.0.1:12345" if getenv("PROD", "false").lower() == "false" else "127.0.0.1:12346"))

    async def shutdown_callback(self):
        try:
            channel = await self.fetch_channel(int(getenv("COMM_NET_CHANNEL_ID", "1211454073383952395")))
        except Exception as e:
            logger.error(f"Error fetching channel: {e}")
            channel = None
        owner = await self.fetch_user(int(getenv("BOT_OWNER_ID", "533009808501112881")))
        if channel:
            await channel.send(f"{owner.mention}\n# S.A.M. was terminated by the system")
        await self.close()

    @tasks.loop(count=1)
    async def startup_animation(self):
        try:
            import sam_startup # type: ignore
        except ImportError:
            return
        channel = await self.fetch_channel(int(getenv("COMM_NET_CHANNEL_ID", "1211454073383952395")))
        if not channel:
            return
        startup_sequence = sam_startup.get_startup_sequence()
        message =await channel.send(startup_sequence[0])
        for frame in startup_sequence[1:]:
            await message.edit(content=frame)
            await asyncio.sleep(1)
        self.startup_animation.cancel()
        self.notify_on_24_hours.start()
        sam_startup.reconnect = True # sets flag so if the bot reconnects, it will use the alternate startup sequence for reconnects

    @tasks.loop(count=1)
    async def notify_on_24_hours(self):
        logger.debug("Starting 24 hour notification loop")
        await asyncio.sleep(24 * 60 * 60)
        channel = await self.fetch_channel(int(getenv("COMM_NET_CHANNEL_ID", "1211454073383952395")))
        if not channel:
            return
        owner = await self.fetch_user(int(getenv("BOT_OWNER_ID", "533009808501112881")))
        await channel.send(f"{owner.mention}\n# I have successfully survived 24 Hours!")
        logger.debug("24 hour notification loop finished")
        self.notify_on_24_hours.cancel()
    
    async def close(self, session: Session):
        """
        Closes the bot and performs necessary cleanup.

        Puts a termination signal in the queue, resyncs configuration, commits database changes,
        and closes the session.
        """
        import prometheus
        prometheus.poll_metrics_fast.stop()
        prometheus.poll_metrics_slow.stop()
        await self.queue.put((4, None))
        await self.resync_config(session=session)
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
        last_ping: datetime | None = None
        last_pinger: Member | None = None
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
            nonlocal last_pinger, last_ping
            if interaction.user.id == last_pinger:
                await interaction.response.send_message("You've already pinged me recently, wait a bit before pinging again", ephemeral=True)
                return
            if last_ping and (datetime.now() - last_ping).total_seconds() < 10:
                await interaction.response.send_message("I've been pinged recently, wait a bit before pinging again", ephemeral=True)
                return
            last_pinger = interaction.user.id if not interaction.user.id == int(getenv("BOT_OWNER_ID", "533009808501112881")) else last_pinger # don't lockout the owner from pings
            last_ping = datetime.now()
            await interaction.response.send_message(f"Pong! I was last restarted at <t:{int(self.start_time.timestamp())}:F>, <t:{int(self.start_time.timestamp())}:R>")

        @self.tree.command(name="patchnotes", description="Show the patch notes")
        async def patchnotes(interaction: Interaction):
            with open("patchnotes.md", "r") as file:
                content = file.read()
                if len(content) > 2000:
                    content = content[:1997] + "..."
            await interaction.response.send_message(content, ephemeral=True)

        last_stats_fetch = None
        last_stats_message = None
        @self.tree.command(name="stats", description="Show the stats")
        async def stats(interaction: Interaction):
            nonlocal last_stats_fetch, last_stats_message
            if last_stats_fetch and (datetime.now() - last_stats_fetch).total_seconds() < 10:
                await interaction.response.send_message(last_stats_message, ephemeral=True)
                return
            last_stats_fetch = datetime.now()
            with self.sessionmaker() as session:
                stats_dict = {
                    "players": session.query(Player).count(),
                    "rec_points": session.query(func.sum(Player.rec_points)).scalar() or 0,
                    "bonus_pay": session.query(func.sum(Player.bonus_pay)).scalar() or 0,
                    "units": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").count(),
                    "purchased": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").filter(Unit.status != "PROPOSED").count(),
                    "active": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").filter(Unit.status == "ACTIVE").count(),
                    "dead": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").filter(Unit.status.in_(["KIA", "MIA"])).count(),
                    "upgrades": session.query(PlayerUpgrade).filter(PlayerUpgrade.original_price > 0).count()
                }
            logger.debug(f"Stats: {stats_dict}")
            stats = tmpl.general_stats.format(**stats_dict)
            last_stats_message = stats
            await interaction.response.send_message(stats, ephemeral=True)

        with self.sessionmaker() as session:
            if len(session.query(Extension.name).all()) > 0:
                await self.load_extensions([ext[0] for ext in session.query(Extension.name).all()])
            else:
                await self.load_extension("extensions.debug") # the debug extension is always loaded
                await self.load_extensions(["extensions.configuration", "extensions.admin", "extensions.faq", "extensions.companies", "extensions.units", "extensions.shop", "extensions.campaigns", "extensions.stockpile"])

        logger.debug("Syncing slash commands")
        await self.tree.sync()
        logger.debug("Slash commands synced")
        import prometheus

        # wrap all the consumer methods in uses_db now, since we can access the sessionmaker after init
        decorator = uses_db(sessionmaker=self.sessionmaker)
        self.queue_consumer = decorator(self.queue_consumer)
        self._handle_create_task = decorator(self._handle_create_task)
        self._handle_update_task = decorator(self._handle_update_task)
        self._handle_delete_task = decorator(self._handle_delete_task)
        self.generate_unit_message = decorator(self.generate_unit_message)
        self.close = decorator(self.close)
        self.tree.on_error = on_error_decorator(error_counter)(self.tree.on_error)
        
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