import io
from logging import getLogger
import discord
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, ButtonStyle, SelectOption, User
from discord.ui import View
from models import Player, Unit as Unit_model, UnitStatus, Campaign, CampaignInvite, UnitType
from customclient import CustomClient
from utils import uses_db, is_management, error_reporting
from sqlalchemy.orm import Session
from sqlalchemy import exists
from typing import Tuple
from sqlalchemy import func
import templates as tmpl

import os
logger = getLogger(__name__)

class Unit(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot

    def _deactivate_unit_by_id(self, unit_id: int, session: Session) -> str:
        """
        Helper function to deactivate a unit by its ID.
        Returns the original callsign of the deactivated unit.
        """
        logger.debug(f"Deactivating unit by ID: unit_id={unit_id}")
        
        # Find the unit by ID
        unit = session.query(Unit_model).filter(Unit_model.id == unit_id).first()
        if not unit:
            logger.warning(f"Unit not found by ID: unit_id={unit_id}")
            raise ValueError("Unit not found")
        
        logger.debug(f"Found unit: id={unit.id}, name={unit.name}, callsign={unit.callsign}, player_id={unit.player.discord_id}, active={unit.active}, status={unit.status}")
        
        # Check if the unit is active
        if not unit.active:
            logger.warning(f"Attempted to deactivate already inactive unit: unit_id={unit.id}, callsign={unit.callsign}")
            raise ValueError("Unit is not active")
        
        original_callsign = unit.callsign
        original_status = unit.status
        original_campaign_id = unit.campaign_id
        
        logger.debug(f"Deactivating unit: id={unit.id}, name={unit.name}, callsign={original_callsign}, status={original_status} -> INACTIVE, campaign_id={original_campaign_id} -> None")
        
        unit.active = False
        unit.status = UnitStatus.INACTIVE if unit.status == UnitStatus.ACTIVE else unit.status
        unit.callsign = None
        unit.campaign_id = None
        
        session.commit()
        logger.debug(f"Successfully deactivated unit: id={unit.id}, name={unit.name}, original_callsign={original_callsign}")
        
        return original_callsign

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
                super().__init__(placeholder=tmpl.unit_select_type_placeholder, options=options)

            async def callback(self, interaction: Interaction):
                logger.triage(f"Unit type selected: {self.values[0]}")
                await interaction.response.defer(ephemeral=True)

        class CreateUnitView(ui.View):
            def __init__(self):
                super().__init__()
                self.add_item(UnitSelect())
                logger.triage("Created unit creation view with type selector")

            @ui.button(label=tmpl.unit_create_button_label, style=ButtonStyle.primary)
            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def create_unit_callback(self, interaction: Interaction, button: ui.Button, session: Session):
                logger.triage(f"Create unit button pressed by {interaction.user.global_name}")
                player_id = session.query(Player.id).filter(Player.discord_id == interaction.user.id).scalar()
                if not player_id:
                    logger.triage(f"Player lookup failed for {interaction.user.global_name}")
                    await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=CustomClient().use_ephemeral)
                    return
                logger.triage("Found player")

                proposed_count = session.query(Unit_model).filter(Unit_model.player_id == player_id, Unit_model.status == "PROPOSED").count()
                logger.triage(f"Found {proposed_count} proposed units for player")
                if proposed_count >= 3:
                    logger.triage("Player already has maximum proposed units")
                    await interaction.response.send_message(tmpl.player_max_units, ephemeral=CustomClient().use_ephemeral)
                    return

                unit_type = self.children[1].values[0]
                logger.triage(f"Selected unit type: {unit_type}")

                unit_exists = session.query(exists().where(Unit_model.name == unit_name, Unit_model.player_id == player_id)).scalar()
                if unit_exists:
                    logger.triage("Unit name already exists for player")
                    await interaction.response.send_message(tmpl.unit_name_exists, ephemeral=CustomClient().use_ephemeral)
                    return

                logger.triage("Validating unit name")
                if len(unit_name) > 30:
                    logger.triage(f"Unit name is too long ({len(unit_name)} chars)")
                    await interaction.response.send_message(tmpl.unit_name_too_long, ephemeral=CustomClient().use_ephemeral)
                    return
                if any(char in unit_name for char in os.getenv("BANNED_CHARS", "")+":"):
                    logger.triage("Unit name contains banned characters")
                    await interaction.response.send_message(tmpl.unit_name_invalid, ephemeral=CustomClient().use_ephemeral)
                    return
                if not unit_name.isascii():
                    logger.triage("Unit name contains non-ASCII characters")
                    await interaction.response.send_message(tmpl.unit_name_ascii, ephemeral=CustomClient().use_ephemeral)
                    return

                logger.triage("Creating unit")
                unit = Unit_model(player_id=player_id, name=unit_name, unit_type=unit_type, active=False)
                
                unit_type_req:int|None = session.query(UnitType.unit_req).filter(UnitType.unit_type == unit_type).scalar()
                if unit_type_req is None: # can't use not because 0 is falsy
                    logger.triage("Unit type not found in database")
                    await interaction.response.send_message(tmpl.unit_invalid_type, ephemeral=CustomClient().use_ephemeral)
                    return
                logger.triage("Found unit type info")

                unit.unit_req = unit_type_req
                session.add(unit)
                logger.triage("Added unit to session")

                await interaction.response.defer(thinking=True, ephemeral=True)
                logger.triage("Deferred response")
                
                session.commit()
                logger.triage("Committed unit creation to database")
                
                await interaction.followup.send(tmpl.unit_created.format(unit=unit), ephemeral=True)
                logger.triage("Sent success message to user")
                
                player = session.query(Player).filter(Player.id == player_id).first()
                CustomClient().queue.put_nowait((1, player, 0))
                logger.triage("Added player update to queue")
                
                button.disabled = True
                logger.triage("Disabled create button")
                

        view = CreateUnitView()
        logger.triage(f"Sending unit creation view to {interaction.user.global_name}")
        await interaction.response.send_message(tmpl.unit_select_type_and_name, view=view, ephemeral=CustomClient().use_ephemeral)

    @ac.command(name="activate", description="Activate a unit")
    @ac.describe(callsign="The callsign of the unit to activate, must be globally unique")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def activateunit(self, interaction: Interaction, callsign: str, session: Session):
        """Activate a unit with the given callsign in the specified campaign"""
        logger.triage(f"Activate unit command initiated by {interaction.user.global_name} with callsign {callsign}")
        if len(callsign) > 7:
            logger.warning(f"Callsign {callsign} from {interaction.user.global_name} is too long")
            await interaction.response.send_message(tmpl.callsign_too_long, ephemeral=CustomClient().use_ephemeral)
            return
        if any(char in callsign for char in os.getenv("BANNED_CHARS", "")):
            logger.warning(f"Callsign {callsign} from {interaction.user.global_name} contains banned characters")
            await interaction.response.send_message(tmpl.callsign_invalid, ephemeral=CustomClient().use_ephemeral)
            return
        if not callsign.isascii():
            logger.warning(f"Callsign {callsign} from {interaction.user.global_name} is not ASCII")
            await interaction.response.send_message(tmpl.callsign_ascii, ephemeral=CustomClient().use_ephemeral)
            return

        logger.triage(f"Checking if callsign {callsign} is already in use")
        callsign_exists = session.query(exists().where(Unit_model.callsign == callsign)).scalar()
        if callsign_exists:
            logger.warning(f"Callsign {callsign} from {interaction.user.global_name} is already in use")
            await interaction.response.send_message(tmpl.callsign_taken, ephemeral=CustomClient().use_ephemeral)
            return

        logger.triage(f"Querying player for {interaction.user.global_name}")
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            logger.triage(f"No player found for {interaction.user.global_name}")
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=True)
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
        select = ui.Select(placeholder=tmpl.unit_select_campaign_placeholder)
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
                await interaction.response.send_message(tmpl.unit_campaign_invalid, ephemeral=True)
                return

            logger.triage(f"Re-querying player for {interaction.user.global_name}")
            _player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
            if not _player:
                logger.warning(f"Player {interaction.user.global_name} does not have a Company")
                await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=True)
                return

            valid, _ = is_valid(campaign, _player)
            if not valid:
                logger.warning(f"Player {interaction.user.global_name} is not eligible to join campaign {campaign.name}")
                await interaction.response.send_message(tmpl.unit_not_eligible, ephemeral=True)
                return

            unit_select = ui.Select(placeholder=tmpl.unit_select_unit_placeholder)
            unit_view = View(timeout=None)
            logger.triage(f"Querying inactive units for player {_player.name}")
            units = session.query(Unit_model).filter(Unit_model.player_id == _player.id, Unit_model.status == "INACTIVE", Unit_model.unit_type != "STOCKPILE").all()
            
            if not units:
                logger.warning(f"Player {interaction.user.global_name} has no units available")
                unit_select.disabled = True
                unit_select.add_option(label=tmpl.unit_no_units_option_label, value="no_units", emoji="🛑")
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
                    await interaction.response.send_message(tmpl.unit_not_found, ephemeral=True)
                    return
                _player = session.query(Player).filter(Player.id == unit.player_id).first()
                if not _player:
                    logger.warning(f"Player {unit.player_id} not found for unit {unit.name}")
                    await interaction.response.send_message(tmpl.player_not_found, ephemeral=True)
                    return

                logger.triage(f"Checking if player {_player.name} has any active units")
                max_active_units = int(os.getenv("MAX_ACTIVE_UNITS", "1"))
                if len(_player.active_units) >= max_active_units:
                    logger.warning(f"{interaction.user.global_name} already has {len(_player.active_units)} active unit(s) (max: {max_active_units})")
                    await interaction.response.send_message(tmpl.unit_already_active_count.format(active_count=len(_player.active_units), max_active=max_active_units), ephemeral=True)
                    return

                if unit.status != UnitStatus.INACTIVE:
                    logger.warning(f"{interaction.user.global_name} tried to select a unit with status {unit.status}")
                    await interaction.response.send_message(tmpl.unit_not_inactive, ephemeral=True)
                    return
                
                existing_callsign = session.query(exists().where(Unit_model.callsign == callsign)).scalar()
                if existing_callsign:
                    logger.warning(f"Callsign {callsign} is already in use (Race condition second check)")
                    await interaction.response.send_message(tmpl.callsign_taken, ephemeral=True)
                    return

                logger.triage(f"Activating unit {unit.name} for player {_player.name} in campaign {campaign_name}")
                unit.status = UnitStatus.ACTIVE
                unit.active = True
                unit.campaign_id = campaign_id
                unit.callsign = callsign
                logger.triage("Committing unit activation changes")
                session.commit()
                logger.info(f"Unit {unit.name} selected for campaign {campaign_name} by {interaction.user.global_name}")
                await interaction.response.send_message(tmpl.unit_selected_for_campaign.format(unit=unit, campaign_name=campaign_name), ephemeral=True)
                logger.triage("Adding player update to queue")
                CustomClient().queue.put_nowait((1, player, 0))

            unit_select.callback = on_unit_select
            await interaction.response.send_message(tmpl.unit_select_unit, view=unit_view, ephemeral=True)

        select.callback = on_select
        await interaction.response.send_message(tmpl.unit_select_campaign, view=view, ephemeral=True)

    @ac.command(name="remove_unit", description="Remove a proposed unit from your company")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def remove_unit(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=CustomClient().use_ephemeral)
            return
        units = session.query(Unit_model).filter(Unit_model.player_id == player.id, Unit_model.status == UnitStatus.PROPOSED).all()
        if not units:
            await interaction.response.send_message(tmpl.unit_no_proposed_units, ephemeral=CustomClient().use_ephemeral)
            return

        class UnitSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=unit.name, value=unit.name) for unit in units]
                super().__init__(placeholder=tmpl.unit_select_remove_placeholder, options=options)
                self.player_id = player.id
                session.expunge(player)
                for unit in units:
                    session.expunge(unit)

            @error_reporting(False)
            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def callback(self, interaction: Interaction, session: Session):
                await interaction.response.defer(ephemeral=CustomClient().use_ephemeral)
                unit: Unit_model = session.query(Unit_model).filter(Unit_model.name == self.values[0], Unit_model.player_id == self.player_id).first()
                if unit.unit_type == "STOCKPILE":
                    await interaction.followup.send(tmpl.stockpile_cannot_remove, ephemeral=CustomClient().use_ephemeral)
                    return
                logger.debug(f"Removing unit {unit.name}")
                session.delete(unit)
                session.commit()
                CustomClient().queue.put_nowait((1, player, 0)) # this is a nested class, so we have to invoke the singleton instead of using self.bot.queue
                await interaction.followup.send(tmpl.unit_removed.format(unit=unit), ephemeral=CustomClient().use_ephemeral)

        view = View()
        try:
            view.add_item(UnitSelect())
        except Exception as e:
            logger.error(f"Error adding unit select to view: {e}")
            await interaction.response.send_message(tmpl.unexpected_error, ephemeral=CustomClient().use_ephemeral)
            return
        await interaction.response.send_message(tmpl.unit_select_to_remove, view=view, ephemeral=CustomClient().use_ephemeral)
        
    @ac.command(name="deactivate", description="Deactivate a unit")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    @error_reporting(False)
    async def deactivateunit(self, interaction: Interaction, session: Session):
        logger.debug(f"Deactivate unit request: user_id={interaction.user.id}, user_name={interaction.user.global_name}")
        
        # Find the player and their active units
        player = session.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
        if not player:
            logger.warning(f"Player not found: user_id={interaction.user.id}")
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=CustomClient().use_ephemeral)
            return
        
        active_units = player.active_units
        logger.debug(f"Found {len(active_units)} active units for player: player_id={player.id}")
        
        if not active_units:
            logger.warning(f"No active units found for player: player_id={player.id}")
            await interaction.response.send_message(tmpl.unit_no_active_units, ephemeral=CustomClient().use_ephemeral)
            return
        
        if len(active_units) == 1:
            # Single active unit - deactivate it directly
            unit = active_units[0]
            logger.debug(f"Single active unit found, deactivating directly: unit_id={unit.id}, callsign={unit.callsign}")
            
            original_callsign = self._deactivate_unit_by_id(unit.id, session)
            await interaction.response.send_message(tmpl.unit_deactivated.format(original_callsign=original_callsign), ephemeral=CustomClient().use_ephemeral)
            
            # Queue notification
            self.bot.queue.put_nowait((1, player, 0))
            logger.debug(f"Queued notification for deactivated unit: player_id={player.discord_id}, unit_callsign={original_callsign}")
        else:
            # Multiple active units - show dropdown
            logger.debug(f"Multiple active units found, showing dropdown: count={len(active_units)}")
            cog = self
            
            class UnitDeactivateSelect(ui.Select):
                def __init__(self, units: list[Unit_model]):
                    options = [
                        SelectOption(
                            label=f"{unit.name} ({unit.callsign})", 
                            value=str(unit.id),
                            description=f"Unit Type: {unit.unit_type}"
                        ) for unit in units
                    ]
                    super().__init__(placeholder=tmpl.unit_select_deactivate_placeholder, options=options)

                @error_reporting(False)
                @uses_db(sessionmaker=CustomClient().sessionmaker)
                async def callback(self, interaction: Interaction, session: Session):
                    unit_id = int(self.values[0])
                    logger.debug(f"Unit selected for deactivation: unit_id={unit_id}")
                    
                    # Use closure scoping to access the parent cog
                    original_callsign = cog._deactivate_unit_by_id(unit_id, session)
                    await interaction.response.send_message(tmpl.unit_deactivated.format(original_callsign=original_callsign), ephemeral=CustomClient().use_ephemeral)
                    
                    # Queue notification
                    player = session.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                    if player:
                        cog.bot.queue.put_nowait((1, player, 0))
                        logger.debug(f"Queued notification for deactivated unit: player_id={player.discord_id}, unit_callsign={original_callsign}")

            class DeactivateUnitView(ui.View):
                def __init__(self, units: list[Unit_model]):
                    super().__init__()
                    select = UnitDeactivateSelect(units)
                    self.add_item(select)

            view = DeactivateUnitView(active_units)
            await interaction.response.send_message(
                tmpl.unit_multiple_active_units.format(count=len(active_units)),
                view=view,
                ephemeral=CustomClient().use_ephemeral
            )

    @ac.command(name="units", description="Display a list of all Units for a Player")
    @ac.describe(player="The player to deliver results for")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def units(self, interaction: Interaction, player: User, session: Session):
        player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not player:
            await interaction.response.send_message(tmpl.unit_user_no_company, ephemeral=CustomClient().use_ephemeral)
            return
        
        units = session.query(Unit_model).filter(Unit_model.player_id == player.id).all()
        if not units:
            await interaction.response.send_message(tmpl.player_no_units, ephemeral=CustomClient().use_ephemeral)
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
        await interaction.response.send_message(tmpl.unit_player_units_display.format(player=player, unit_table=unit_table), ephemeral=CustomClient().use_ephemeral)

    @ac.command(name="rename", description="Rename a unit")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def rename(self, interaction: Interaction, session: Session):
        logger.info("rename command invoked")
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            logger.error("Player not found for rename command")
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=CustomClient().use_ephemeral)
            return
        units = session.query(Unit_model).filter(Unit_model.player_id == player.id).all()
        if not units:
            logger.error("No units found for rename command")
            await interaction.response.send_message(tmpl.player_no_units, ephemeral=CustomClient().use_ephemeral)
            return

        class UnitSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=unit.name, value=unit.name) for unit in units]
                super().__init__(placeholder=tmpl.unit_select_rename_placeholder, options=options)

            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def callback(self, interaction: Interaction, session: Session):
                unit: Unit_model = session.query(Unit_model).filter(Unit_model.name == self.values[0]).first()
                if not unit:
                    logger.error("Unit not found for rename command")
                    await interaction.response.send_message(tmpl.unit_not_found, ephemeral=CustomClient().use_ephemeral)
                    return
                if unit.unit_type == "STOCKPILE":
                    logger.error("Stockpile units cannot be renamed")
                    await interaction.response.send_message(tmpl.stockpile_cannot_rename, ephemeral=CustomClient().use_ephemeral)
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
                        await interaction.response.send_message(tmpl.unit_name_exists, ephemeral=CustomClient().use_ephemeral)
                        return
                    if len(new_name) > 30:
                        logger.error("Unit name is too long for rename command")
                        await interaction.response.send_message(tmpl.unit_name_too_long, ephemeral=CustomClient().use_ephemeral)
                        return
                    if any(char in new_name for char in os.getenv("BANNED_CHARS", "")+":"): # : is banned to disable urls
                        logger.error("Unit name contains banned characters for rename command")
                        await interaction.response.send_message(tmpl.unit_name_invalid, ephemeral=CustomClient().use_ephemeral)
                        return
                    if not new_name.isascii():
                        logger.error("Unit name is not ASCII for rename command")
                        await interaction.response.send_message(tmpl.unit_name_ascii, ephemeral=CustomClient().use_ephemeral)
                        return
                    _unit.name = new_name
                    session.commit()
                    CustomClient().queue.put_nowait((1, player, 0))

                    logger.info(f"Unit renamed to {new_name}")
                    await interaction.response.send_message(tmpl.unit_renamed.format(new_name=new_name), ephemeral=CustomClient().use_ephemeral)


                modal = ui.Modal(title=tmpl.unit_rename_modal_title, custom_id="rename_unit")
                modal.add_item(ui.TextInput(label=tmpl.unit_rename_new_name_label, custom_id="new_name", placeholder=unit.name, max_length=32))
                modal.on_submit = rename_modal_callback
                await interaction.response.send_modal(modal)

                

        view = View()
        view.add_item(UnitSelect())
        await interaction.response.send_message(tmpl.unit_select_to_rename, view=view, ephemeral=CustomClient().use_ephemeral)

    @ac.command(name="transfer_unit", description="Transfer a proposed unit from your company")
    @ac.check(is_management)  # only management can transfer units
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def transfer_unit(self, interaction: Interaction, campaign: str, session: Session):
        if not await campaign.is_management(interaction):
            await interaction.response.send_message(tmpl.no_permission, ephemeral=True)
            return
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=CustomClient().use_ephemeral)
            return
        units = session.query(Unit_model).filter(Unit_model.player_id == player.id, Unit_model.status == UnitStatus.PROPOSED).all()
        if not units:
            await interaction.response.send_message(tmpl.unit_no_proposed_units, ephemeral=CustomClient().use_ephemeral)
            return
    
        class UnitSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=unit.name, value=unit.name) for unit in units]
                super().__init__(placeholder=tmpl.unit_select_transfer_placeholder, options=options)
                self.player_id = player.id
                session.expunge(player)
                for unit in units:
                    session.expunge(unit)
    
            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def callback(self, interaction: Interaction, session: Session):
                unit: Unit_model = session.query(Unit_model).filter(Unit_model.name == self.values[0], Unit_model.player_id == self.player_id).first()
                if unit.unit_type == "STOCKPILE":
                    await interaction.response.send_message(tmpl.stockpile_cannot_remove, ephemeral=CustomClient().use_ephemeral)
                    return
                await interaction.response.send_message(tmpl.unit_transfer_mention_player, ephemeral=CustomClient().use_ephemeral)
    
                def check(m):
                    return m.author == interaction.user and m.mentions
    
                msg = await self.bot.wait_for('message', check=check, timeout=60.0)
                target_player = session.query(Player).filter(Player.discord_id == msg.mentions[0].id).first()
                if not target_player:
                    await interaction.followup.send(tmpl.unit_transfer_target_no_company, ephemeral=CustomClient().use_ephemeral)
                    return
                unit.player_id = target_player.id
                session.commit()
                await interaction.followup.send(tmpl.unit_transfer_success.format(unit=unit, target_player=target_player), ephemeral=CustomClient().use_ephemeral)

    
        view = View()
        try:
            view.add_item(UnitSelect())
        except Exception as e:
            logger.error(f"Error adding unit select to view: {e}")
            await interaction.response.send_message(tmpl.unexpected_error, ephemeral=CustomClient().use_ephemeral)
            return
        await interaction.response.send_message(tmpl.unit_select_to_transfer, view=view, ephemeral=CustomClient().use_ephemeral)

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
