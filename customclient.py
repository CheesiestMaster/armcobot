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

use_ephemeral = True


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
        print("queue consumer started")
        while True:
            task = await self.queue.get()
            if task[0] == 0:
                # TODO: send a message to the dossier and statistics channels, and create a new dossier and statistic in the database to reference them
                if self.config.get("dossier_channel_id"):
                    if isinstance(task[1], Player):
                        dossier_message = await self.get_channel(self.config["dossier_channel_id"]).send(templates.Dossier.format(player=task[1]))
                        dossier = Dossier(player_id=task[1].id, message_id=dossier_message.id)
                        self.session.add(dossier)
                        self.session.commit()
                if self.config.get("statistics_channel_id"):
                    if isinstance(task[1], Player):
                        statistics_message = await self.get_channel(self.config["statistics_channel_id"]).send(f"Statistics message:Insert for {task[1].name}")
                        statistics = Statistic(player_id=task[1].id, message_id=statistics_message.id)
                        self.session.add(statistics)
                        self.session.commit()
                    elif isinstance(task[1], Unit):
                        # queue a new task with the edit type and the unit's Player
                        player = self.session.query(Player).filter(Player.id == task[1].player_id).first()
                        self.queue.put_nowait((1, player))
                    elif isinstance(task[1], Upgrade):
                        # queue a new task with the edit type and the upgrade's unit's Player
                        unit = self.session.query(Unit).filter(Unit.id == task[1].unit_id).first()
                        player = self.session.query(Player).filter(Player.id == unit.player_id).first()
                        self.queue.put_nowait((1, player))
                self.queue.task_done()
            elif task[0] == 1:
                # TODO: depending on the model, update the dossier message, statistic message, or both
                if isinstance(task[1], Player):
                    # check if the player has a dossier message
                    dossier = self.session.query(Dossier).filter(Dossier.player_id == task[1].id).first()
                    if dossier:
                        channel = self.get_channel(self.config["dossier_channel_id"])
                        if channel:
                            message = await channel.fetch_message(dossier.message_id)
                            await message.edit(content=templates.Dossier.format(player=task[1]))
                    statistics = self.session.query(Statistic).filter(Statistic.player_id == task[1].id).first()
                    if statistics:
                        channel = self.get_channel(self.config["statistics_channel_id"])
                        if channel:
                            message = await channel.fetch_message(statistics.message_id)
                            await message.edit(content=f"Statistics message:Update for {task[1].name}")
                elif isinstance(task[1], Unit):
                    player = self.session.query(Player).filter(Player.id == task[1].player_id).first()
                    self.queue.put_nowait((1, player))
                elif isinstance(task[1], Upgrade):
                    unit = self.session.query(Unit).filter(Unit.id == task[1].unit_id).first()
                    player = self.session.query(Player).filter(Player.id == unit.player_id).first()
                    self.queue.put_nowait((1, player))
                self.queue.task_done()
            elif task[0] == 2:
                # TODO: depending on the model, delete or edit the dossier message, statistic message, or both
                self.queue.task_done()
            elif task[0] == 4:
                break # graceful termination signal


    async def set_bot_nick(self, nick: str):
        for guild in self.guilds:
            await guild.me.edit(nick=nick)

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        await self.set_bot_nick("Meta Campaign Bot")
        asyncio.create_task(self.queue_consumer())

    async def close(self):
        await self.queue.put((4, None))
        await super().close()

    async def setup_hook(self):
        async def is_owner(interaction: Interaction):
            print(f"Checking if {interaction.user.id} is in {self.owner_ids}")
            valid = interaction.user.id in self.owner_ids
            if not valid:
                print(f"{interaction.user.id} is not in {self.owner_ids}")
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
            await self.close()

        @self.tree.command(name="query", description="Query the database")
        @app_commands.describe(query="The SQL query to run")
        @app_commands.check(is_owner)
        async def query(interaction: Interaction, query: str):
            try:
                result = self.session.execute(text(query))
                await interaction.response.send_message(f"Query result: {result.fetchall()}", ephemeral=use_ephemeral)
            except Exception as e:
                await interaction.response.send_message(f"Error: {e}", ephemeral=use_ephemeral)

        @self.tree.command(name="setnick", description="Set the bot's nickname")
        async def setnick(interaction: Interaction, nick: str):
            if is_owner(interaction):
                await self.set_bot_nick(nick)
                await interaction.response.send_message(f"Bot nickname globally set to {nick}", ephemeral=use_ephemeral)
            elif interaction.user.guild_permissions.manage_nicknames:
                await interaction.guild.me.edit(nick=nick)
                await interaction.response.send_message(f"Bot nickname in {interaction.guild.name} set to {nick}", ephemeral=use_ephemeral)
            else:
                await interaction.response.send_message("You don't have permission to set the bot's nickname", ephemeral=use_ephemeral)

        @self.tree.command(name="setdossier", description="Set the dossier channel to the current channel")
        #@app_commands.checks.has_any_role(self.mod_roles)
        async def setdossier(interaction: Interaction):
            self.config["dossier_channel_id"] = interaction.channel.id
            _Config = self.session.query(Config).filter(Config.key == "BOT_CONFIG").first()
            _Config.value = self.config
            self.session.commit()
            await interaction.response.send_message(f"Dossier channel set to {interaction.channel.mention}", ephemeral=use_ephemeral)

        @self.tree.command(name="setstatistics", description="Set the statistics channel to the current channel")
        #@app_commands.checks.has_any_role(self.mod_roles)
        async def setstatistics(interaction: Interaction):
            self.config["statistics_channel_id"] = interaction.channel.id
            _Config = self.session.query(Config).filter(Config.key == "BOT_CONFIG").first()
            _Config.value = self.config
            self.session.commit()
            await interaction.response.send_message(f"Statistics channel set to {interaction.channel.mention}", ephemeral=use_ephemeral)

        # join command
        @self.tree.command(name="createcompany", description="Create a new Meta Campaign company")
        async def createcompany(interaction: Interaction):
            # check if the user already has a company
            await interaction.response.defer(ephemeral=True)
            player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
            if player:
                await interaction.followup.send("You already have a Meta Campaign company", ephemeral=use_ephemeral)
                return
            
            # create a new Player in the database
            player = Player(discord_id=interaction.user.id, name=interaction.user.name, rec_points=2)
            self.session.add(player)
            self.session.commit()
            await interaction.followup.send("You have joined Meta Campaign", ephemeral=use_ephemeral)
        
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
            await interaction.response.defer(ephemeral=True)
            # find the player by discord id
            player = self.session.query(Player).filter(Player.discord_id == player.id).first()
            if not player:
                await interaction.followup.send("User doesn't have a Meta Campaign company", ephemeral=use_ephemeral)
                return
            
            # update the player's rec points
            player.rec_points += points
            self.session.commit()
            
            await interaction.followup.send(f"{player.name} now has {player.rec_points} requisition points", ephemeral=use_ephemeral)

        @self.tree.command(name="bonuspay", description="Give or remove a number of bonus pay from a player")
        @app_commands.describe(player="The player to give or remove bonus pay from")
        @app_commands.describe(points="The number of bonus pay to give or remove")
        @app_commands.describe(reason="The reason for giving or removing the bonus pay")
        async def bonuspay(interaction: Interaction, player: Member, points: int, reason: str):
            await interaction.response.defer(ephemeral=True)
            # find the player by discord id
            player = self.session.query(Player).filter(Player.discord_id == player.id).first()
            if not player:
                await interaction.followup.send("User doesn't have a Meta Campaign company", ephemeral=use_ephemeral)
                return
            
            # update the player's bonus pay
            player.bonus_pay += points
            self.session.commit()
            
            await interaction.followup.send(f"{player.name} now has {player.bonus_pay} bonus pay", ephemeral=use_ephemeral)

        @self.tree.command(name="createunit", description="Create a new unit for a player")
        async def createunit(interaction: Interaction, unit_name: str):
            await interaction.response.defer(ephemeral=True) # deferral is always ephemeral
            # we need to make a modal for this, as we need a dropdown for the unit type
            class UnitSelect(ui.Select):
                def __init__(self):
                    options = [SelectOption(label=unit_type.name, value=unit_type.value) for unit_type in UnitType]
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
                        await interaction.followup.send("You don't have a Meta Campaign company", ephemeral=use_ephemeral)
                        return
                    
                    # create the unit in the database
                    unit = Unit(player_id=player.id, name=unit_name, unit_type=self.children[1].values[0])
                    self.session.add(unit)
                    self.session.commit()
                    await interaction.followup.send(f"Unit {unit.name} created", ephemeral=use_ephemeral)

            view = CreateUnitView(self.session)
            await interaction.response.send_message("Please select the unit type and enter the unit name", view=view, ephemeral=use_ephemeral)

        await self.tree.sync()
        
    async def start(self, *args, **kwargs):
        self.start_time = datetime.now()
        await super().start(getenv("BOT_TOKEN"), *args, **kwargs)