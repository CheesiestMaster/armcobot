import io
from logging import getLogger
import discord
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, ButtonStyle, SelectOption, User
from discord.ui import View
from models import Player, Unit as Unit_model, UnitStatus, Campaign, CampaignInvite, UnitType
from customclient import CustomClient
from utils import uses_db, is_management
from sqlalchemy.orm import Session
from sqlalchemy import exists
from typing import Tuple
from sqlalchemy import func

import os
logger = getLogger(__name__)

class Unit(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @ac.command(name="create", description="Create a new unit for a player")
    @ac.describe(unit_name="The name of the unit to create")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def createunit(self, interaction: Interaction, unit_name: str, session: Session):
        logger.triage(f"Unit creation initiated by {interaction.user.global_name} with name: {unit_name}")
        class UnitSelect(ui.Select):
            def __init__(self):
                unit_types = session.query(UnitType.unit_type).filter(UnitType.is_base == True).all()
                logger.triage(f"Found {len(unit_types)} base unit types: {[t[0] for t in unit_types]}")
                options = [SelectOption(label=unit_type[0], value=unit_type[0]) for unit_type in unit_types]
                super().__init__(placeholder="Select the type of unit to create", options=options)

            async def callback(self, interaction: Interaction):
                logger.triage(f"Unit type selected: {self.values[0]}")
                await interaction.response.defer(ephemeral=True)

        class CreateUnitView(ui.View):
            def __init__(self):
                super().__init__()
                self.add_item(UnitSelect())
                logger.triage("Created unit creation view with type selector")

            @ui.button(label="Create Unit", style=ButtonStyle.primary)
            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def create_unit_callback(self, interaction: Interaction, button: ui.Button, session: Session):
                logger.triage(f"Create unit button pressed by {interaction.user.global_name}")
                player_id = session.query(Player.id).filter(Player.discord_id == interaction.user.id).scalar()
                if not player_id:
                    logger.triage(f"Player lookup failed for {interaction.user.global_name}")
                    await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
                    return
                logger.triage("Found player")

                proposed_count = session.query(Unit_model).filter(Unit_model.player_id == player_id, Unit_model.status == "PROPOSED").count()
                logger.triage(f"Found {proposed_count} proposed units for player")
                if proposed_count >= 3:
                    logger.triage("Player already has maximum proposed units")
                    await interaction.response.send_message("You already have 3 proposed Units, which is the maximum allowed", ephemeral=CustomClient().use_ephemeral)
                    return

                unit_type = self.children[1].values[0]
                logger.triage(f"Selected unit type: {unit_type}")

                unit_exists = session.query(exists().where(Unit_model.name == unit_name, Unit_model.player_id == player_id)).scalar()
                if unit_exists:
                    logger.triage("Unit name already exists for player")
                    await interaction.response.send_message("You already have a unit with that name", ephemeral=CustomClient().use_ephemeral)
                    return

                logger.triage("Validating unit name")
                if len(unit_name) > 30:
                    logger.triage(f"Unit name is too long ({len(unit_name)} chars)")
                    await interaction.response.send_message("Unit name is too long, please use a shorter name", ephemeral=CustomClient().use_ephemeral)
                    return
                if any(char in unit_name for char in os.getenv("BANNED_CHARS", "")+":"):
                    logger.triage("Unit name contains banned characters")
                    await interaction.response.send_message("Unit names cannot contain discord tags", ephemeral=CustomClient().use_ephemeral)
                    return
                if not unit_name.isascii():
                    logger.triage("Unit name contains non-ASCII characters")
                    await interaction.response.send_message("Unit names must be ASCII", ephemeral=CustomClient().use_ephemeral)
                    return

                logger.triage("Creating unit")
                unit = Unit_model(player_id=player_id, name=unit_name, unit_type=unit_type, active=False)
                
                unit_type_req:int|None = session.query(UnitType.unit_req).filter(UnitType.unit_type == unit_type).scalar()
                if unit_type_req is None: # can't use not because 0 is falsy
                    logger.triage("Unit type not found in database")
                    await interaction.response.send_message("Invalid unit type, something went wrong", ephemeral=CustomClient().use_ephemeral)
                    return
                logger.triage("Found unit type info")

                unit.unit_req = unit_type_req
                session.add(unit)
                logger.triage("Added unit to session")

                await interaction.response.defer(thinking=True, ephemeral=True)
                logger.triage("Deferred response")
                
                session.commit()
                logger.triage("Committed unit creation to database")
                
                await interaction.followup.send(f"Unit {unit.name} created", ephemeral=True)
                logger.triage("Sent success message to user")
                
                player = session.query(Player).filter(Player.id == player_id).first()
                CustomClient().queue.put_nowait((1, player, 0))
                logger.triage("Added player update to queue")
                
                button.disabled = True
                logger.triage("Disabled create button")
                

        view = CreateUnitView()
        logger.triage(f"Sending unit creation view to {interaction.user.global_name}")
        await interaction.response.send_message("Please select the unit type and enter the unit name", view=view, ephemeral=CustomClient().use_ephemeral)

    @ac.command(name="activate", description="Activate a unit")
    @ac.describe(callsign="The callsign of the unit to activate, must be globally unique")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def activateunit(self, interaction: Interaction, callsign: str, session: Session):
        """Activate a unit with the given callsign in the specified campaign"""
        logger.triage(f"Activate unit command initiated by {interaction.user.global_name} with callsign {callsign}")
        if len(callsign) > 7:
            logger.warning(f"Callsign {callsign} from {interaction.user.global_name} is too long")
            await interaction.response.send_message("Callsign is too long, please use a shorter callsign", ephemeral=CustomClient().use_ephemeral)
            return
        if any(char in callsign for char in os.getenv("BANNED_CHARS", "")):
            logger.warning(f"Callsign {callsign} from {interaction.user.global_name} contains banned characters")
            await interaction.response.send_message("Callsigns cannot contain discord tags", ephemeral=CustomClient().use_ephemeral)
            return
        if not callsign.isascii():
            logger.warning(f"Callsign {callsign} from {interaction.user.global_name} is not ASCII")
            await interaction.response.send_message("Callsigns must be ASCII", ephemeral=CustomClient().use_ephemeral)
            return

        logger.triage(f"Checking if callsign {callsign} is already in use")
        callsign_exists = session.query(exists().where(Unit_model.callsign == callsign)).scalar()
        if callsign_exists:
            logger.warning(f"Callsign {callsign} from {interaction.user.global_name} is already in use")
            await interaction.response.send_message("That callsign is already in use", ephemeral=CustomClient().use_ephemeral)
            return

        logger.triage(f"Querying player for {interaction.user.global_name}")
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            logger.triage(f"No player found for {interaction.user.global_name}")
            await interaction.response.send_message("You do not have a Company", ephemeral=True)
            return

        # get the list of campaigns from the database
        logger.triage("Querying all campaigns")
        campaigns = session.query(Campaign).all()
        def is_valid(campaign: Campaign, player: Player) -> Tuple[bool, str]:
            logger.triage(f"Checking validity of campaign {campaign.name} for player {player.name}")
            if campaign.gm == player.discord_id:
                return False, "🧙"
            if campaign.player_limit and campaign.player_limit <= len(campaign.units):
                return False, "📦"
            if campaign.required_role and not any(role.id == campaign.required_role for role in interaction.user.roles):
                return False, "🛡️"
            if session.query(CampaignInvite).filter(CampaignInvite.campaign_id == campaign.id, CampaignInvite.player_id == player.id).first():
                return True, "✉"
            if not campaign.open:
                return False, "🔒"
            return True, "✅"

        view = View(timeout=None)
        select = ui.Select(placeholder="Select a campaign")
        logger.triage(f"Creating campaign select with {len(campaigns)} options")
        for campaign in campaigns:
            _, emojis = is_valid(campaign, player)
            select.add_option(label=campaign.name, value=str(campaign.id), emoji=emojis)
        view.add_item(select)

        @uses_db(sessionmaker=CustomClient().sessionmaker)
        async def on_select(interaction: Interaction, session: Session):
            logger.triage(f"Campaign selection made by {interaction.user.global_name}: {select.values[0]}")
            campaign = session.query(Campaign).filter(Campaign.id == select.values[0]).first()
            if not campaign:
                logger.warning(f"Invalid campaign {select.values[0]} from {interaction.user.global_name}")
                await interaction.response.send_message("Invalid campaign", ephemeral=True)
                return

            logger.triage(f"Re-querying player for {interaction.user.global_name}")
            _player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
            if not _player:
                logger.warning(f"Player {interaction.user.global_name} does not have a Company")
                await interaction.response.send_message("You do not have a Company", ephemeral=True)
                return

            valid, _ = is_valid(campaign, _player)
            if not valid:
                logger.warning(f"Player {interaction.user.global_name} is not eligible to join campaign {campaign.name}")
                await interaction.response.send_message("You are not eligible to join this campaign", ephemeral=True)
                return

            unit_select = ui.Select(placeholder="Select a unit")
            unit_view = View(timeout=None)
            logger.triage(f"Querying inactive units for player {_player.name}")
            units = session.query(Unit_model).filter(Unit_model.player_id == _player.id, Unit_model.status == "INACTIVE", Unit_model.unit_type != "STOCKPILE").all()
            
            if not units:
                logger.warning(f"Player {interaction.user.global_name} has no units available")
                unit_select.disabled = True
                unit_select.add_option(label="No units available", value="no_units", emoji="🛑")
            else:
                logger.triage(f"Found {len(units)} inactive units for player {_player.name}")
                for unit in units:
                    unit_select.add_option(label=f"{unit.name} ({unit.unit_type})", value=str(unit.id))
            unit_view.add_item(unit_select)

            campaign_id = campaign.id
            campaign_name = campaign.name

            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def on_unit_select(interaction: Interaction, session: Session):
                logger.triage(f"Unit selection made by {interaction.user.global_name}: {unit_select.values[0]}")
                unit = session.query(Unit_model).filter(Unit_model.id == unit_select.values[0]).first()
                if not unit:
                    logger.warning(f"Invalid unit {unit_select.values[0]} from {interaction.user.global_name}")
                    await interaction.response.send_message("Invalid unit", ephemeral=True)
                    return
                _player = session.query(Player).filter(Player.id == unit.player_id).first()
                if not _player:
                    logger.warning(f"Player {unit.player_id} not found for unit {unit.name}")
                    await interaction.response.send_message("Player not found", ephemeral=True)
                    return

                logger.triage(f"Checking if player {_player.name} has any active units")
                has_active_unit = session.query(exists().where(Unit_model.player_id == _player.id, Unit_model.active == True)).scalar()
                if has_active_unit:
                    logger.warning(f"{interaction.user.global_name} already has an active unit")
                    await interaction.response.send_message("You already have an active unit", ephemeral=True)
                    return

                if unit.status != UnitStatus.INACTIVE:
                    logger.warning(f"{interaction.user.global_name} tried to select a unit with status {unit.status}")
                    await interaction.response.send_message("That unit is not inactive", ephemeral=True)
                    return
                
                existing_callsign = session.query(exists().where(Unit_model.callsign == callsign)).scalar()
                if existing_callsign:
                    logger.warning(f"Callsign {callsign} is already in use (Race condition second check)")
                    await interaction.response.send_message("That callsign is already in use", ephemeral=True)
                    return

                logger.triage(f"Activating unit {unit.name} for player {_player.name} in campaign {campaign_name}")
                unit.status = UnitStatus.ACTIVE
                unit.active = True
                unit.campaign_id = campaign_id
                unit.callsign = callsign
                logger.triage("Committing unit activation changes")
                session.commit()
                logger.info(f"Unit {unit.name} selected for campaign {campaign_name} by {interaction.user.global_name}")
                await interaction.response.send_message(f"Unit {unit.name} selected for campaign {campaign_name}", ephemeral=True)
                logger.triage("Adding player update to queue")
                CustomClient().queue.put_nowait((1, player, 0))

            unit_select.callback = on_unit_select
            await interaction.response.send_message("Select a unit", view=unit_view, ephemeral=True)

        select.callback = on_select
        await interaction.response.send_message("Select a campaign", view=view, ephemeral=True)

    @ac.command(name="remove_unit", description="Remove a proposed unit from your company")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def remove_unit(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return
        units = session.query(Unit_model).filter(Unit_model.player_id == player.id, Unit_model.status == UnitStatus.PROPOSED).all()
        if not units:
            await interaction.response.send_message("You don't have any proposed units", ephemeral=CustomClient().use_ephemeral)
            return

        class UnitSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=unit.name, value=unit.name) for unit in units]
                super().__init__(placeholder="Select the unit to remove", options=options)
                self.player_id = player.id
                session.expunge(player)
                for unit in units:
                    session.expunge(unit)

            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def callback(self, interaction: Interaction, session: Session):
                unit: Unit_model = session.query(Unit_model).filter(Unit_model.name == self.values[0], Unit_model.player_id == self.player_id).first()
                if unit.unit_type == "STOCKPILE":
                    await interaction.response.send_message("Stockpile units cannot be removed", ephemeral=CustomClient().use_ephemeral)
                    return
                logger.debug(f"Removing unit {unit.name}")
                session.delete(unit)
                session.commit()
                CustomClient().queue.put_nowait((1, player, 0)) # this is a nested class, so we have to invoke the singleton instead of using self.bot.queue
                await interaction.response.send_message(f"Unit {unit.name} removed", ephemeral=CustomClient().use_ephemeral)

        view = View()
        try:
            view.add_item(UnitSelect())
        except Exception as e:
            logger.error(f"Error adding unit select to view: {e}")
            await interaction.response.send_message("Unexpected error, please tell Cheese", ephemeral=CustomClient().use_ephemeral)
            return
        await interaction.response.send_message("Please select the unit to remove", view=view, ephemeral=CustomClient().use_ephemeral)
        
    @ac.command(name="deactivate", description="Deactivate a unit")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def deactivateunit(self, interaction: Interaction, session: Session):
        logger.debug(f"Deactivating unit for {interaction.user.id}")
        player: Player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return
        
        active_unit = session.query(Unit_model).filter(Unit_model.player_id == player.id, Unit_model.active == True).first()
        if not active_unit:
            await interaction.response.send_message("You don't have any active units", ephemeral=CustomClient().use_ephemeral)
            return
        
        original_callsign = active_unit.callsign
        logger.debug(f"Deactivating unit with callsign {active_unit.callsign}")
        active_unit.active = False
        active_unit.status = UnitStatus.INACTIVE if active_unit.status == UnitStatus.ACTIVE else active_unit.status
        active_unit.callsign = None
        active_unit.campaign_id = None

        await interaction.response.send_message(f"Unit with callsign {original_callsign} deactivated", ephemeral=CustomClient().use_ephemeral)
        self.bot.queue.put_nowait((1, player, 0))

    @ac.command(name="units", description="Display a list of all Units for a Player")
    @ac.describe(player="The player to deliver results for")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def units(self, interaction: Interaction, player: User, session: Session):
        player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not player:
            await interaction.response.send_message("User doesn't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return
        
        units = session.query(Unit_model).filter(Unit_model.player_id == player.id).all()
        if not units:
            await interaction.response.send_message("User doesn't have any Units", ephemeral=CustomClient().use_ephemeral)
            return
        
        # Create a table with unit details
        # The {str : {padding}^ int} format allows you to pad both sides of the string using padding until the desired width of (int) characters is achieved
        # ``` is used to use discord markdown to turn it into a codeblock, for monospaced font.

        unit_table = f"```| {'Unit Name':^30} | {'Callsign':^8} | {'Unit Type':^10} | {'Status':^8} |\n"
        unit_table += f"|-{'-' * 30}-|-{'-' * 8}-|-{'-' * 10}-|-{'-' * 8}-|\n"
        for unit in units:
            unit_table += f"| {unit.name:^30} | {str(unit.callsign):^8} | {unit.unit_type:^10} | {unit.status.name:^8} |\n" 
        unit_table += "```"

        # Send the table to the user
        await interaction.response.send_message(f"Here are {player.name}'s Units:\n\n{unit_table}", ephemeral=CustomClient().use_ephemeral)

    @ac.command(name="rename", description="Rename a unit")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def rename(self, interaction: Interaction, session: Session):
        logger.info("rename command invoked")
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            logger.error("Player not found for rename command")
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return
        units = session.query(Unit_model).filter(Unit_model.player_id == player.id).all()
        if not units:
            logger.error("No units found for rename command")
            await interaction.response.send_message("You don't have any units", ephemeral=CustomClient().use_ephemeral)
            return

        class UnitSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=unit.name, value=unit.name) for unit in units]
                super().__init__(placeholder="Select the unit to rename", options=options)

            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def callback(self, interaction: Interaction, session: Session):
                unit: Unit_model = session.query(Unit_model).filter(Unit_model.name == self.values[0]).first()
                if not unit:
                    logger.error("Unit not found for rename command")
                    await interaction.response.send_message("Unit not found", ephemeral=CustomClient().use_ephemeral)
                    return
                if unit.unit_type == "STOCKPILE":
                    logger.error("Stockpile units cannot be renamed")
                    await interaction.response.send_message("Stockpile units cannot be renamed", ephemeral=CustomClient().use_ephemeral)
                    return
                @uses_db(sessionmaker=CustomClient().sessionmaker)
                @staticmethod
                async def rename_modal_callback(interaction: Interaction, session: Session):
                    nonlocal player
                    new_name = interaction.data["components"][0]["components"][0]["value"]
                    player = session.merge(player)
                    _unit = session.merge(unit)
                    logger.debug(f"New name: {new_name}")
                    if session.query(Unit_model).filter(Unit_model.name == new_name, Unit_model.player_id == player.id).first():
                        logger.error(f"Unit with name {new_name} already exists for rename command")
                        await interaction.response.send_message("You already have a unit with that name", ephemeral=CustomClient().use_ephemeral)
                        return
                    if len(new_name) > 30:
                        logger.error("Unit name is too long for rename command")
                        await interaction.response.send_message("Unit name is too long, please use a shorter name", ephemeral=CustomClient().use_ephemeral)
                        return
                    if any(char in new_name for char in os.getenv("BANNED_CHARS", "")+":"): # : is banned to disable urls
                        logger.error("Unit name contains banned characters for rename command")
                        await interaction.response.send_message("Unit names cannot contain discord tags", ephemeral=CustomClient().use_ephemeral)
                        return
                    if not new_name.isascii():
                        logger.error("Unit name is not ASCII for rename command")
                        await interaction.response.send_message("Unit names must be ASCII", ephemeral=CustomClient().use_ephemeral)
                        return
                    _unit.name = new_name
                    session.commit()
                    CustomClient().queue.put_nowait((1, player, 0))

                    logger.info(f"Unit renamed to {new_name}")
                    await interaction.response.send_message(f"Unit renamed to {new_name}", ephemeral=CustomClient().use_ephemeral)


                modal = ui.Modal(title="Rename Unit", custom_id="rename_unit")
                modal.add_item(ui.TextInput(label="New Name", custom_id="new_name", placeholder=unit.name, max_length=32))
                modal.on_submit = rename_modal_callback
                await interaction.response.send_modal(modal)

                

        view = View()
        view.add_item(UnitSelect())
        await interaction.response.send_message("Please select the unit to rename", view=view, ephemeral=CustomClient().use_ephemeral)

    @ac.command(name="transfer_unit", description="Transfer a proposed unit from your company")
    @ac.check(is_management)  # only management can transfer units
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def transfer_unit(self, interaction: Interaction, campaign: str, session: Session):
        if not await campaign.is_management(interaction):
            await interaction.response.send_message("You don't have permission to run this command", ephemeral=True)
            return
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return
        units = session.query(Unit_model).filter(Unit_model.player_id == player.id, Unit_model.status == UnitStatus.PROPOSED).all()
        if not units:
            await interaction.response.send_message("You don't have any proposed units", ephemeral=CustomClient().use_ephemeral)
            return
    
        class UnitSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=unit.name, value=unit.name) for unit in units]
                super().__init__(placeholder="Select the unit to transfer", options=options)
                self.player_id = player.id
                session.expunge(player)
                for unit in units:
                    session.expunge(unit)
    
            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def callback(self, interaction: Interaction, session: Session):
                unit: Unit_model = session.query(Unit_model).filter(Unit_model.name == self.values[0], Unit_model.player_id == self.player_id).first()
                if unit.unit_type == "STOCKPILE":
                    await interaction.response.send_message("Stockpile units cannot be transferred", ephemeral=CustomClient().use_ephemeral)
                    return
                await interaction.response.send_message("Please mention the player to transfer the unit to:", ephemeral=CustomClient().use_ephemeral)
    
                def check(m):
                    return m.author == interaction.user and m.mentions
    
                msg = await self.bot.wait_for('message', check=check, timeout=60.0)
                target_player = session.query(Player).filter(Player.discord_id == msg.mentions[0].id).first()
                if not target_player:
                    await interaction.followup.send("The mentioned player does not exist", ephemeral=CustomClient().use_ephemeral)
                    return
                unit.player_id = target_player.id
                session.commit()
                await interaction.followup.send(f"Unit {unit.name} transferred to {target_player.name}", ephemeral=CustomClient().use_ephemeral)

    
        view = View()
        try:
            view.add_item(UnitSelect())
        except Exception as e:
            logger.error(f"Error adding unit select to view: {e}")
            await interaction.response.send_message("Unexpected error, please tell Cheese", ephemeral=CustomClient().use_ephemeral)
            return
        await interaction.response.send_message("Please select the unit to transfer", view=view, ephemeral=CustomClient().use_ephemeral)

    @ac.command(name="counts_by_unit_type", description="Display the number of units by unit type, made just for Frenchboi")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def counts_by_unit_type(self, interaction: Interaction, session: Session):
        counts = session.query(Unit_model.unit_type, func.count()).filter(Unit_model.unit_type != "STOCKPILE").group_by(Unit_model.unit_type).order_by(func.count().desc()).all()
        counts_tsv = "unit_type\t count\n"
        for count in counts:
            counts_tsv += f"{count[0]}\t {count[1]}\n"
        file = discord.File(io.BytesIO(counts_tsv.encode()), filename="counts_by_unit_type.tsv")
        await interaction.response.send_message(file=file, ephemeral=True)

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Unit cog")
    await bot.add_cog(Unit(bot))

async def teardown():
    logger.info("Tearing down Unit cog")
    bot.remove_cog(Unit.__name__) # remove_cog takes a string, not a class
