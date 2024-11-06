from discord.ext import commands
from discord import app_commands, Interaction, Member, Intents, ui, SelectOption, ButtonStyle, TextStyle, TextChannel
from discord.ext.commands import Bot
from discord.ext import tasks
from os import getenv
from sqlalchemy.orm import Session
from models import *
from sqlalchemy import text, select
from datetime import datetime
from typing import List
from singleton import Singleton
import asyncio
import templates
import logging

use_ephemeral = False

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logging.getLogger("discord").setLevel(logging.WARNING)

@Singleton
class CustomClient(Bot): # need to inherit from Bot to use Cogs
    """
    CustomClient is a subclass of discord.Bot that adds additional functionality for the S.A.M. bot.
    """
    mod_roles = {"FLEET OFFICER (Moderator)", "FLEET AMBASSADOR", "FLEET COMMAND"}
    session: Session
    use_ephemeral: bool
    config: dict
    def __init__(self, session: Session, **kwargs):
        """
        Initializes the CustomClient instance.

        Args:
            session (Session): The SQLAlchemy session to be used for database operations.
            **kwargs: Additional keyword arguments to be passed to the Bot constructor.

        The constructor initializes the bot with default and provided settings, sets up the session,
        initializes the task queue, and loads the bot configuration and medal emotes from the database.
        If the configuration or medal emotes are not found in the database, they are created with default values.
        """
        DEFAULTS = {"command_prefix":"\0", "intents":Intents.default()}
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
        Resynchronizes the bot configuration with the database.

        This method fetches the current bot configuration from the database,
        updates the in-memory configuration, and commits any changes back to the database.
        It ensures that the bot's configuration is always in sync with the stored configuration.

        Raises:
            SQLAlchemyError: If there is an issue with the database operation.
        """
        _Config = self.session.query(Config).filter(Config.key == "BOT_CONFIG").first()
        _Config.value = self.config
        self.session.commit()
        logger.debug(f"Resynced config: {self.config}")

    async def queue_consumer(self):
        """
        Consumes tasks from the queue and processes them based on their type.

        This method runs indefinitely, consuming tasks from the queue and processing them
        according to their type. It handles tasks related to players, units, upgrades, and active units,
        updating the database and sending messages to the appropriate channels as needed.

        Task Types:
            0: Creation
            1: Updates
            2: Deletions
            3: Unused
            4: Terminates the queue consumer gracefully.

        Raises:
            Exception: If there is an issue with processing a task.
        """
        logger.info("queue consumer started")
        while True:
            task = await self.queue.get()
            logger.debug(f"Processing task: {task}")
            if task[0] == 0:
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
                        dossier_message = await self.get_channel(self.config["dossier_channel_id"]).send(templates.Dossier.format(player=player, medals=medal_block))
                        dossier = Dossier(player_id=player.id, message_id=dossier_message.id)
                        self.session.add(dossier)
                        self.session.commit()
                        logger.debug(f"Created dossier for player {player.id} with message ID {dossier_message.id}")
                if self.config.get("statistics_channel_id"):
                    if isinstance(task[1], Player):
                        player = task[1]
                        unit_message = self.generate_unit_message(player)
                        statistics_message = await self.get_channel(self.config["statistics_channel_id"]).send(templates.Statistics_Player.format(player=player, units=unit_message))
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
                    elif isinstance(task[1], ActiveUnit):
                        # make the unit flagged ACTIVE, then queue an update task for the player
                        au: ActiveUnit = task[1]
                        unit = self.session.query(Unit).filter(Unit.id == au.unit_id).first()
                        unit.status = UnitStatus.ACTIVE.name
                        self.session.commit()
                        player = self.session.query(Player).filter(Player.id == unit.player_id).first()
                        self.queue.put_nowait((1, player))
                        logger.debug(f"Queued update task for player {player.id} due to active unit {au.id}")
                self.queue.task_done()
            elif task[0] == 1:
                if isinstance(task[1], Player):
                    player = task[1]
                    dossier = self.session.query(Dossier).filter(Dossier.player_id == player.id).first()
                    if dossier:
                        channel = self.get_channel(self.config["dossier_channel_id"])
                        if channel:
                            message = await channel.fetch_message(dossier.message_id)
                            await message.edit(content=templates.Dossier.format(player=player))
                            logger.debug(f"Updated dossier for player {player.id} with message ID {dossier.message_id}")
                    statistics = self.session.query(Statistic).filter(Statistic.player_id == player.id).first()
                    if statistics:
                        channel = self.get_channel(self.config["statistics_channel_id"])
                        if channel:
                            message = await channel.fetch_message(statistics.message_id)
                            unit_message = self.generate_unit_message(player)
                            await message.edit(content=templates.Statistics_Player.format(player=player, units=unit_message))
                            logger.debug(f"Updated statistics for player {player.id} with message ID {statistics.message_id}")
                elif isinstance(task[1], Unit):
                    unit = task[1]
                    player = self.session.query(Player).filter(Player.id == unit.player_id).first()
                    self.queue.put_nowait((1, player))
                    logger.debug(f"Queued update task for player {player.id} due to unit {unit.id}")
                elif isinstance(task[1], ActiveUnit):
                    active_unit = task[1]
                    unit = self.session.query(Unit).filter(Unit.id == active_unit.unit_id).first()
                    player = self.session.query(Player).filter(Player.id == unit.player_id).first()
                    self.queue.put_nowait((1, player))
                    logger.debug(f"Queued update task for player {player.id} due to active unit {active_unit.id}")
                elif isinstance(task[1], Upgrade):
                    upgrade = task[1]
                    unit = self.session.query(Unit).filter(Unit.id == upgrade.unit_id).first()
                    player = self.session.query(Player).filter(Player.id == unit.player_id).first()
                    self.queue.put_nowait((1, player))
                    logger.debug(f"Queued update task for player {player.id} due to upgrade {upgrade.id}")
                self.queue.task_done()
            elif task[0] == 2:
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
                elif isinstance(task[1], ActiveUnit):
                    active_unit = task[1]
                    unit = self.session.query(Unit).filter(Unit.id == active_unit.unit_id).first()
                    unit.status = UnitStatus.INACTIVE if unit.status == UnitStatus.ACTIVE else unit.status
                    self.session.commit()
                    player = self.session.query(Player).filter(Player.id == unit.player_id).first()
                    self.queue.put_nowait((1, player))
                    logger.debug(f"Set unit {unit.id} status to INACTIVE and queued update task for player {player.id}")
                self.queue.task_done()
            elif task[0] == 4:
                logger.info("queue consumer terminating")
                break # graceful termination signal
            elif task[0] == 4:
                break # graceful termination signal

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
    def generate_unit_message(self, player):
        """
        Generates a unit message for a given player.

        Args:
            player (Player): The player for whom to generate the unit message.

        Returns:
            str: A formatted string containing the unit messages for the player.
        """
        logger.debug(f"Generating unit message for player: {player.id}")
        unit_messages = []

        # Query active units
        active_units = self.session.query(ActiveUnit).filter(ActiveUnit.player_id == player.id).all()
        logger.debug(f"Found {len(active_units)} active units for player: {player.id}")
        for unit in active_units:
            upgrades = self.session.query(Upgrade).filter(Upgrade.unit_id == unit.unit_id).all()
            base_unit = self.session.query(Unit).filter(Unit.id == unit.unit_id).first()
            upgrade_list = ", ".join([upgrade.name for upgrade in upgrades])
            logger.debug(f"Active unit {base_unit.name} has upgrades: {upgrade_list}")
            stats = self.stats_map[base_unit.unit_type].format(unit=unit)
            unit_messages.append(templates.Statistics_Unit_Active.format(unit=base_unit, upgrades=upgrade_list, stats=stats))

        # Query inactive units
        inactive_units = self.session.query(Unit).filter(Unit.player_id == player.id).filter(Unit.status != 'ACTIVE').all()
        logger.debug(f"Found {len(inactive_units)} inactive units for player: {player.id}")
        for unit in inactive_units:
            upgrades = self.session.query(Upgrade).filter(Upgrade.unit_id == unit.id).all()
            upgrade_list = ", ".join([upgrade.name for upgrade in upgrades])
            logger.debug(f"Inactive unit {unit.name} of type {unit.unit_type} has status {unit.status.name}")
            logger.debug(f"Inactive unit {unit.id} has upgrades: {upgrade_list}")
            unit_messages.append(templates.Statistics_Unit.format(unit=unit, upgrades=upgrade_list))

        # Combine all unit messages into a single string
        combined_message = "\n".join(unit_messages)
        logger.debug(f"Generated unit message for player {player.id}: {combined_message}")
        return combined_message

    @tasks.loop(hours=4)
    async def session_keep_alive(self):
        """
        Keeps the database session alive by executing a simple query every 4 hours.

        This task ensures that the database session remains active and prevents it from timing out
        due to inactivity. It runs indefinitely, executing a "SELECT 1" query to keep the session alive.

        Raises:
            Exception: If there is an issue with executing the keep-alive query.
        """
        logger.debug("Session Keep-Alive Task started")
        try:
            self.session.execute(text("SELECT 1"))
            logger.debug("Session Keep-Alive Task successful")
        except Exception as e:
            logger.error(f"Session Keep-Alive Task failed: {e}")


    async def load_extensions(self, extensions: List[str]):
        """
        Loads a list of extensions.

        Args:
            extensions (List[str]): A list of extension names to be loaded.
        """
        for extension in extensions:
            await self.load_extension(extension)
        logger.debug(f"Loaded extensions: {', '.join(extensions)}")


    async def set_bot_nick(self, nick: str):
        """
        Sets the bot's nickname in all guilds.

        Args:
            nick (str): The new nickname to be set for the bot.
        """
        for guild in self.guilds:
            await guild.me.edit(nick=nick)

    async def on_ready(self):
        """
        Handles the bot's readiness event.

        This method is called when the bot has successfully logged in. It sets the bot's nickname,
        starts the queue consumer task, and logs the bot's user information.
        """
        logger.info(f"Logged in as {self.user}")
        await self.set_bot_nick("S.A.M.")
        asyncio.create_task(self.queue_consumer())

    async def close(self):
        """
        Closes the bot and performs cleanup tasks.

        This method is called when the bot is shutting down. It puts a termination signal in the queue,
        resynchronizes the bot configuration, commits any outstanding database changes, closes the session,
        and terminates the bot.
        """
        await self.queue.put((4, None))
        await self.resync_config()
        try:
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error committing session, rolling back: {e}")
        self.session.close()
        await super().close()

    async def setup_hook(self):
        """
        Sets up the bot's event listeners and slash commands.

        This method is called when the bot is ready to receive events and commands. It sets up the ping command
        as a slash command and logs the bot's user information.
        """
        @self.tree.command(name="ping", description="Ping the bot")
        async def ping(interaction: Interaction):
            await interaction.response.send_message(f"Pong! I was last restarted at <t:{int(self.start_time.timestamp())}:F>, <t:{int(self.start_time.timestamp())}:R>")

        await self.load_extension("extensions.debug") # the debug extension is loaded first and is always loaded
        await self.load_extensions(["extensions.admin", "extensions.configuration", "extensions.units", "extensions.shop", "extensions.companies", "extensions.backup", "extensions.search"]) # remaining extensions are currently loaded automatically, but will later support only autoloading extension that were active when it was last stopped
        
        logger.debug("Syncing slash commands")
        await self.tree.sync()
        logger.debug("Slash commands synced")
        
    async def start(self, *args, **kwargs):
        """
        Starts the bot with the provided token and arguments.

        Args:
            *args: Additional positional arguments to be passed to the start method.
            **kwargs: Additional keyword arguments to be passed to the start method.
        """
        self.start_time = datetime.now()
        logger.debug(f"Starting bot at {self.start_time}")
        await super().start(getenv("BOT_TOKEN"), *args, **kwargs)
        logger.debug(f"Bot has terminated at {datetime.now()}")