from discord.ext import commands
from discord import app_commands, Client, Interaction, Member, Intents, ui, SelectOption, ButtonStyle, TextStyle, TextChannel
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
class CustomClient(Client):
    mod_roles = {"FLEET OFFICER (Moderator)", "FLEET AMBASSADOR", "FLEET COMMAND"}
    def __init__(self, session: Session, **kwargs):
        if not kwargs.get("intents"):
            kwargs["intents"] = Intents.default()
            #kwargs["intents"].members = True
        super().__init__(**kwargs)
        self.tree = app_commands.CommandTree(self)
        self.owner_ids = {533009808501112881}
        self.session = session
        self.queue = asyncio.Queue()
        _Config = self.session.query(Config).filter(Config.key == "BOT_CONFIG").first()
        if not _Config:
            _Config = Config(key="BOT_CONFIG", value={})
            self.session.add(_Config)
            self.session.commit()
        self.config:dict = _Config.value

    async def queue_consumer(self):
        logger.info("queue consumer started")
        while True:
            task = await self.queue.get()
            logger.debug(f"Processing task: {task}")
            if task[0] == 0:
                if self.config.get("dossier_channel_id"):
                    if isinstance(task[1], Player):
                        player = task[1]
                        dossier_message = await self.get_channel(self.config["dossier_channel_id"]).send(templates.Dossier.format(player=player))
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
        UnitType.INFANTRY: templates.Infantry_Stats,
        UnitType.MEDIC: templates.Non_Combat_Stats,
        UnitType.ENGINEER: templates.Non_Combat_Stats,
        UnitType.ARTILLERY: templates.Artillery_Stats,
        UnitType.MAIN_TANK: templates.Armor_Stats,
        UnitType.LIGHT_VEHICLE: templates.Armor_Stats,
        UnitType.LOGISTIC: templates.Armor_Stats,
        UnitType.BOMBER: templates.Air_Stats,
        UnitType.FIGHTER: templates.Air_Stats,
        UnitType.VTOL: templates.Air_Stats,
        UnitType.HVTOL: templates.Air_Stats,
        UnitType.HAT: templates.Air_Stats,
        UnitType.LIGHT_MECH: templates.Armor_Stats
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
            logger.debug(f"Inactive unit {unit.name} of type {unit.unit_type.name} has status {unit.status.name}")
            logger.debug(f"Inactive unit {unit.id} has upgrades: {upgrade_list}")
            unit_messages.append(templates.Statistics_Unit.format(unit=unit, upgrades=upgrade_list))

        # Combine all unit messages into a single string
        combined_message = "\n".join(unit_messages)
        logger.debug(f"Generated unit message for player {player.id}: {combined_message}")
        return combined_message

    async def set_bot_nick(self, nick: str):
        for guild in self.guilds:
            await guild.me.edit(nick=nick)

    async def on_ready(self):
        logger.info(f"Logged in as {self.user}")
        await self.set_bot_nick("Meta Campaign Bot")
        asyncio.create_task(self.queue_consumer())

    async def close(self):
        await self.queue.put((4, None))
        await super().close()

    async def setup_hook(self):
        async def is_owner(interaction: Interaction):
            logger.info(f"Checking if {interaction.user.id} is in {self.owner_ids}")
            valid = interaction.user.id in self.owner_ids
            if not valid:
                logger.warning(f"{interaction.user.id} is not in {self.owner_ids}")
                await interaction.response.send_message("You don't have permission to use this command", ephemeral=use_ephemeral)
                return False
            return True

        @self.tree.command(name="ping", description="Ping the bot")
        async def ping(interaction: Interaction):
            await interaction.response.send_message(f"Pong! I was last restarted at {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}, {datetime.now() - self.start_time} ago")

        @self.tree.command(name="kill", description="Force kill the bot")
        @app_commands.check(is_owner)
        async def kill(interaction: Interaction):
            await interaction.response.send_message("Bot is shutting down") # ephemeral=False because this is an owner only command and breaks the bot
            logger.info("Bot is shutting down via owner command")
            await self.close()

        @self.tree.command(name="query", description="Query the database")
        @app_commands.describe(query="The SQL query to run")
        @app_commands.check(is_owner)
        async def query(interaction: Interaction, query: str):
            try:
                logger.info(f"Running query: {query}")
                result = self.session.execute(text(query))
                self.session.commit()
                try:
                    rows = result.fetchall()
                except Exception:
                    rows = None
                await interaction.response.send_message(f"Query result: {rows}" if rows else "No rows returned", ephemeral=use_ephemeral)
            except Exception as e:
                await interaction.response.send_message(f"Error: {e}", ephemeral=use_ephemeral)

        @self.tree.command(name="setnick", description="Set the bot's nickname")
        async def setnick(interaction: Interaction, nick: str):
            if is_owner(interaction):
                logger.info(f"Setting bot nickname to {nick} globally")
                await self.set_bot_nick(nick)
                await interaction.response.send_message(f"Bot nickname globally set to {nick}", ephemeral=use_ephemeral)
            elif interaction.user.guild_permissions.manage_nicknames:
                logger.info(f"Setting bot nickname to {nick} in {interaction.guild.name}")
                await interaction.guild.me.edit(nick=nick)
                await interaction.response.send_message(f"Bot nickname in {interaction.guild.name} set to {nick}", ephemeral=use_ephemeral)
            else:
                logger.info(f"User {interaction.user.display_name} does not have permission to set the bot's nickname in {interaction.guild.name}")
                await interaction.response.send_message("You don't have permission to set the bot's nickname", ephemeral=use_ephemeral)

        @self.tree.command(name="setdossier", description="Set the dossier channel to the current channel")
        #@app_commands.checks.has_any_role(self.mod_roles)
        async def setdossier(interaction: Interaction):
            self.config["dossier_channel_id"] = interaction.channel.id
            _Config = self.session.query(Config).filter(Config.key == "BOT_CONFIG").first()
            _Config.value = self.config
            self.session.commit()
            logger.info(f"Dossier channel set to {interaction.channel.name}")
            old_dossiers = self.session.query(Dossier).all()
            for dossier in old_dossiers:
                self.session.delete(dossier)
            self.session.commit()
            for player in self.session.query(Player).all():
                self.queue.put_nowait((0, player))
            await interaction.response.send_message(f"Dossier channel set to {interaction.channel.mention}", ephemeral=use_ephemeral)

        @self.tree.command(name="setstatistics", description="Set the statistics channel to the current channel")
        #@app_commands.checks.has_any_role(self.mod_roles)
        async def setstatistics(interaction: Interaction):
            self.config["statistics_channel_id"] = interaction.channel.id
            _Config = self.session.query(Config).filter(Config.key == "BOT_CONFIG").first()
            _Config.value = self.config
            self.session.commit()
            logger.info(f"Statistics channel set to {interaction.channel.name}")
            old_statistics = self.session.query(Statistic).all()
            for statistic in old_statistics:
                self.session.delete(statistic)
            self.session.commit()
            for player in self.session.query(Player).all():
                self.queue.put_nowait((0, player))
            await interaction.response.send_message(f"Statistics channel set to {interaction.channel.mention}", ephemeral=use_ephemeral)

        # join command
        @self.tree.command(name="createcompany", description="Create a new Meta Campaign company")
        async def createcompany(interaction: Interaction):
            # check if the user already has a company
            player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
            if player:
                logger.debug(f"User {interaction.user.display_name} already has a Meta Campaign company")
                await interaction.response.send_message("You already have a Meta Campaign company", ephemeral=use_ephemeral)
                return
            
            # create a new Player in the database
            player = Player(discord_id=interaction.user.id, name=interaction.user.name, rec_points=2)
            self.session.add(player)
            self.session.commit()
            logger.debug(f"User {interaction.user.display_name} created a new Meta Campaign company")
            await interaction.response.send_message("You have joined Meta Campaign", ephemeral=use_ephemeral)
        
        @self.tree.command(name="editcompany", description="Edit your Meta Campaign company")
        async def editcompany(interaction: Interaction):
            # we need a long text input for this, so modal is needed
            class EditCompanyModal(ui.Modal):
                def __init__(self, player):
                    super().__init__(title="Edit your Meta Campaign company")
                    self.player = player
                    self.session = CustomClient().session
                    self.add_item(ui.TextInput(label="Name", placeholder="Enter the company name", required=True, max_length=255, default=player.name))
                    self.add_item(ui.TextInput(label="Lore", placeholder="Enter the company lore", max_length=1000, style=TextStyle.paragraph, default=player.lore or ""))


                async def on_submit(self, interaction: Interaction):
                    self.player.name = self.children[0].value
                    self.player.lore = self.children[1].value
                    self.session.commit()
                    await interaction.response.send_message("Company updated", ephemeral=use_ephemeral)

            player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
            if not player:
                logger.debug(f"User {interaction.user.display_name} does not have a Meta Campaign company and is trying to edit it")
                await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=use_ephemeral)
                return

            modal = EditCompanyModal(player)
            await interaction.response.send_modal(modal)

        # define a slash command which gives a user a rec point, can only be used by one of 3 roles, and takes a user mention as a parameter
        @self.tree.command(name="recpoint", description="Give or remove a number of requisition points from a player")
        @app_commands.describe(player="The player to give or remove points from")
        @app_commands.describe(points="The number of points to give or remove")
        @app_commands.describe(reason="The reason for giving or removing the points")
        #@app_commands.checks.has_any_role(self.mod_roles)
        async def recpoint(interaction: Interaction, player: Member, points: int, reason: str):
            # find the player by discord id
            player = self.session.query(Player).filter(Player.discord_id == player.id).first()
            if not player:
                await interaction.response.send_message("User doesn't have a Meta Campaign company", ephemeral=use_ephemeral)
                return
            
            # update the player's rec points
            player.rec_points += points
            self.session.commit()
            logger.debug(f"User {player.name} now has {player.rec_points} requisition points")
            await interaction.response.send_message(f"{player.name} now has {player.rec_points} requisition points", ephemeral=use_ephemeral)

        @self.tree.command(name="bonuspay", description="Give or remove a number of bonus pay from a player")
        @app_commands.describe(player="The player to give or remove bonus pay from")
        @app_commands.describe(points="The number of bonus pay to give or remove")
        @app_commands.describe(reason="The reason for giving or removing the bonus pay")
        async def bonuspay(interaction: Interaction, player: Member, points: int, reason: str):
            # find the player by discord id
            player = self.session.query(Player).filter(Player.discord_id == player.id).first()
            if not player:
                await interaction.response.send_message("User doesn't have a Meta Campaign company", ephemeral=use_ephemeral)
                return
            
            # update the player's bonus pay
            player.bonus_pay += points
            self.session.commit()
            logger.debug(f"User {player.name} now has {player.bonus_pay} bonus pay")
            await interaction.response.send_message(f"{player.name} now has {player.bonus_pay} bonus pay", ephemeral=use_ephemeral)

        @self.tree.command(name="createunit", description="Create a new unit for a player")
        async def createunit(interaction: Interaction, unit_name: str):
            # we need to make a modal for this, as we need a dropdown for the unit type
            class UnitSelect(ui.Select):
                def __init__(self):
                    options = [SelectOption(label=unit_type.name, value=unit_type.name) for unit_type in UnitType]
                    super().__init__(placeholder="Select the type of unit to create", options=options)

                async def callback(self, interaction: Interaction):
                    await interaction.response.defer(ephemeral=True)

            class CreateUnitView(ui.View):
                def __init__(self):
                    super().__init__()
                    self.session = CustomClient().session
                    self.add_item(UnitSelect())

                @ui.button(label="Create Unit", style=ButtonStyle.primary)
                async def create_unit_callback(self, interaction: Interaction, button: ui.Button):
                    # get the player id from the database
                    player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
                    if not player:
                        await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=use_ephemeral)
                        return
                    
                    # create the unit in the database
                    unit_type = self.children[1].values[0]
                    logger.debug(f"Unit type selected: {unit_type}")
                    unit = Unit(player_id=player.id, name=unit_name, unit_type=unit_type)
                    self.session.add(unit)
                    self.session.commit()
                    logger.debug(f"Unit {unit.name} created for player {player.name}")
                    await interaction.response.send_message(f"Unit {unit.name} created", ephemeral=use_ephemeral)

            view = CreateUnitView()
            await interaction.response.send_message("Please select the unit type and enter the unit name", view=view, ephemeral=use_ephemeral)

        logger.debug("Syncing slash commands")
        await self.tree.sync()
        logger.debug("Slash commands synced")
        
    async def start(self, *args, **kwargs):
        self.start_time = datetime.now()
        logger.debug(f"Starting bot at {self.start_time}")
        await super().start(getenv("BOT_TOKEN"), *args, **kwargs)
        logger.debug(f"Bot has terminated at {datetime.now()}")