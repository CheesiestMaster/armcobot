from logging import getLogger
from typing import Callable
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, TextStyle, app_commands as ac, ui, SelectOption, ButtonStyle, Embed
from models import Player, Unit, UnitStatus, ShopUpgrade, ShopUpgradeUnitTypes, PlayerUpgrade, UnitType, UpgradeType
from customclient import CustomClient
from utils import inject, uses_db, string_to_list, Paginator, error_reporting
from sqlalchemy.orm import Session
from MessageManager import MessageManager
import templates as tmpl
logger = getLogger(__name__)

async def is_mod(interaction: Interaction):
    """
    Check if the user is a moderator with the necessary role.
    """
    valid = any(interaction.user.get_role(role) for role in CustomClient().mod_roles)
    if not valid:
        await interaction.response.send_message(tmpl.no_permission, ephemeral=True)
        logger.warning(f"{interaction.user.name} tried to use shop admin commands")
    return valid

class Shop(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
    
    @ac.command(name="open", description="View the shop")
    @uses_db(CustomClient().sessionmaker)
    async def shop(self, interaction: Interaction, session: Session):
        """
        Main shop command that opens the shop interface for players.
        
        This command:
        - Validates that the player has a Meta Campaign company
        - Creates the initial shop home view
        - Displays available units and currency conversion options
        """
        logger.triage(f"Shop command initiated by user {interaction.user.name} (ID: {interaction.user.id})")
        
        # Check if player has a Meta Campaign company
        player_id = session.query(Player.id).filter(Player.discord_id == interaction.user.id).scalar()
        if not player_id:
            logger.triage(f"User {interaction.user.name} attempted to access shop without a Meta Campaign company")
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=CustomClient().use_ephemeral)
            return

        logger.triage(f"Creating MessageManager for player {player_id}")
        message_manager = MessageManager(interaction)

        # Generate the shop home interface
        view, embed = await self.shop_home_view_factory(player_id, message_manager)
        logger.triage(f"Generated shop home view for player {player_id}")

        # Send the shop interface to the player
        await message_manager.send_message(view=view, embed=embed, ephemeral=CustomClient().use_ephemeral)
        logger.triage(f"Shop interface sent to user {interaction.user.name}")

    @uses_db(CustomClient().sessionmaker)
    async def shop_home_view_factory(self, player_id: int, message_manager: MessageManager, session: Session):
        """
        Creates the main shop home interface showing available units and currency options.
        
        This method:
        - Displays player's currency (requisition points and bonus pay)
        - Shows a dropdown of available units
        - Provides a button to convert bonus pay to requisition points
        - Handles unit selection navigation
        """
        logger.triage(f"Creating shop home view for player {player_id}")
        view = ui.View()
        embed = Embed(title=tmpl.shop_title, color=0xc06335)
        
        # Get player's currency information
        rec_points, bonus_pay = session.query(Player.rec_points, Player.bonus_pay).filter(Player.id == player_id).first()

        # Get all units belonging to the player
        units = session.query(Unit).filter(Unit.player_id == player_id).all()
        logger.triage(f"Found {len(units)} units for player {player_id}: {[unit.name for unit in units]}")
        
        # Create unit selection dropdown
        if not units:
            logger.triage(f"No units found for player {player_id}, creating disabled select")
            select_options = [SelectOption(label=tmpl.shop_no_units_option, value="no_units", default=True)]
        else:
            logger.triage(f"Creating select options for {len(units)} units")
            select_options = [SelectOption(label=unit.name, value=str(unit.id)) for unit in units]
        
        select = ui.Select(placeholder=tmpl.shop_select_unit_placeholder, options=select_options, disabled=not units)
        logger.triage(f"Created unit select menu with {len(select_options)} options")

        # Create bonus pay to requisition points conversion button
        bonus_button = ui.Button(label=tmpl.shop_convert_bp_button, style=ButtonStyle.success, disabled=bonus_pay < 10)
        logger.triage(f"Created BP to RP conversion button. Player has {bonus_pay} BP")

        @uses_db(CustomClient().sessionmaker)
        async def bonus_button_callback(interaction: Interaction, session: Session):
            """
            Callback for converting bonus pay to requisition points.
            
            Converts 10 bonus pay to 1 requisition point.
            Updates the button state based on remaining bonus pay.
            """
            logger.triage(f"BP to RP conversion initiated by player {player_id}")
            _player = session.query(Player).filter(Player.id == player_id).first()
            
            # Validate sufficient bonus pay
            if _player.bonus_pay < 10:
                logger.triage(f"Invalid BP to RP conversion attempt - insufficient BP: {_player.bonus_pay}")
                bonus_button.disabled = True
                await message_manager.update_message(content=tmpl.not_enough_bonus_pay)
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for BP to RP conversion for player {player_id}")
                return
                
            # Perform the conversion (10 BP = 1 RP)
            _player.bonus_pay -= 10
            _player.rec_points += 1
            logger.triage(f"Converted 10 BP to 1 RP. New balance: {_player.bonus_pay} BP, {_player.rec_points} RP")
            
            # Update button state and commit changes
            bonus_button.disabled = _player.bonus_pay < 10
            session.commit()
            self.bot.queue.put_nowait((1, _player, 0))
            await message_manager.update_message()
            await interaction.response.defer(thinking=False, ephemeral=True)
            
        bonus_button.callback = bonus_button_callback

        @uses_db(CustomClient().sessionmaker)
        async def select_callback(interaction: Interaction, session: Session):
            """
            Callback for when a player selects a unit from the dropdown.
            
            Navigates to the unit-specific shop view for purchasing upgrades.
            """
            selected_unit_id = int(select.values[0])
            unit_id, unit_name = session.query(Unit.id, Unit.name).filter(Unit.id == selected_unit_id).first()
            logger.triage(f"Unit selected: {unit_name} (ID: {unit_id})")

            # Validate unit exists
            if not unit_id:
                logger.triage(f"Selected unit {selected_unit_id} not found")
                embed.description = tmpl.unit_doesnt_exist
                return view, embed

            await interaction.response.defer(thinking=False, ephemeral=True)
            logger.triage(f"Deferred response for unit selection {unit_name}")
            logger.triage(f"Generating unit view for {unit_name}")
            
            # Navigate to unit-specific shop view
            unit_view, unit_embed = await self.shop_unit_view_factory(unit_id, player_id, message_manager)
            await message_manager.update_message(embed=unit_embed, view=unit_view)
            

        select.callback = select_callback

        # Add UI elements to the view
        view.add_item(select)
        view.add_item(bonus_button)
        
        # Set embed description and footer
        embed.description = tmpl.select_unit_to_buy.format(rec_points=rec_points)
        embed.set_footer(text=tmpl.shop_footer)
        logger.triage(f"Completed shop home view creation for player {player_id}")
        return view, embed

    @uses_db(CustomClient().sessionmaker)
    async def shop_unit_view_factory(self, unit_id: int, player_id: int, message_manager: MessageManager, session: Session):
        """
        Creates the shop interface for a specific unit based on its status.
        
        This method handles different unit states:
        - STOCKPILE: No upgrades available
        - PROPOSED: Can purchase the unit itself
        - MIA/KIA/ACTIVE: No upgrades available
        - INACTIVE: Can purchase upgrades
        
        Args:
            unit_id: ID of the unit to create shop for
            player_id: ID of the player
            message_manager: Manager for updating messages
            session: Database session
        """
        logger.triage(f"Creating shop unit view for unit {unit_id} and player {player_id}")
        
        # Get player's requisition points
        rec_points = session.query(Player.rec_points).filter(Player.id == player_id).scalar()
        
        # Get unit details
        unit_name, unit_type, unit_status, active = session.query(
            Unit.name, Unit.unit_type, Unit.status, Unit.active
        ).filter(Unit.id == unit_id).first()
        logger.triage(f"Creating shop view for unit: {unit_name} with status: {unit_status}")
        
        view = ui.View()
        embed = Embed(title=tmpl.shop_unit_title.format(unit_name=unit_name), color=0xc06335)
        
        # Create back button to return to shop home
        leave_button = ui.Button(label=tmpl.shop_back_to_home_button, style=ButtonStyle.danger)
        @uses_db(CustomClient().sessionmaker)
        async def leave_button_callback(interaction: Interaction, session: Session):
            """Callback to return to the main shop home view"""
            logger.triage(f"Returning to shop home view for player {player_id}")
            _player = session.query(Player).filter(Player.id == player_id).first()
            view, embed = await self.shop_home_view_factory(_player.id, message_manager)
            await message_manager.update_message(view=view, embed=embed)
            await interaction.response.defer(thinking=False, ephemeral=True)
            logger.triage(f"Deferred response for returning to shop home view for player {player_id}")
        leave_button.callback = leave_button_callback
        view.add_item(leave_button)

        # Handle STOCKPILE units (no upgrades available)
        if unit_type == "STOCKPILE":
            logger.triage(f"Unit {unit_name} is stockpile, no upgrades available")
            embed.description = tmpl.cant_buy_upgrades_stockpile
            return view, embed

        # Handle PROPOSED units (can purchase the unit itself)
        if unit_status.name == "PROPOSED":
            logger.triage(f"Unit {unit_name} is proposed, checking requisition points")
            buy_button = ui.Button(label=tmpl.shop_buy_unit_button, style=ButtonStyle.success, disabled=rec_points < 1)
            
            @uses_db(CustomClient().sessionmaker)
            async def buy_button_callback(interaction: Interaction, session: Session):
                """
                Callback for purchasing a proposed unit.
                
                This process:
                - Validates sufficient requisition points
                - Adds free upgrades that come with the unit type
                - Changes unit status to INACTIVE
                - Deducts requisition points
                """
                _player = session.query(Player).filter(Player.id == player_id).first()
                _unit = session.query(Unit).filter(Unit.id == unit_id).first()
                logger.triage(f"Buying unit {_unit.name}")
                
                # Validate sufficient requisition points
                if _player.rec_points < 1:
                    logger.triage(f"Player {interaction.user.name} attempted to buy unit without sufficient RP")
                    embed.description = tmpl.not_enough_req_points_unit
                    await message_manager.update_message()
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    return
                    
                # Add free upgrades that come with this unit type
                if _unit.type_info.free_upgrade_1:
                    logger.triage(f"Adding free upgrade 1: {_unit.type_info.free_upgrade_1_info.name}")
                    free_upgrade_1 = PlayerUpgrade(
                        unit_id=_unit.id, 
                        name=_unit.type_info.free_upgrade_1_info.name, 
                        type=_unit.type_info.free_upgrade_1_info.type, 
                        original_price=0, 
                        non_transferable=True, 
                        shop_upgrade_id=_unit.type_info.free_upgrade_1
                    )
                    session.add(free_upgrade_1)
                if _unit.type_info.free_upgrade_2:
                    logger.triage(f"Adding free upgrade 2: {_unit.type_info.free_upgrade_2_info.name}")
                    free_upgrade_2 = PlayerUpgrade(
                        unit_id=_unit.id, 
                        name=_unit.type_info.free_upgrade_2_info.name, 
                        type=_unit.type_info.free_upgrade_2_info.type, 
                        original_price=0, 
                        non_transferable=True, 
                        shop_upgrade_id=_unit.type_info.free_upgrade_2
                    )
                    session.add(free_upgrade_2)
                    
                # Activate the unit and deduct cost
                _unit.status = UnitStatus.INACTIVE
                _player.rec_points -= 1
                logger.triage(f"Unit {_unit.name} purchased. New RP balance: {_player.rec_points}")
                
                # Commit changes and update player
                session.commit()
                self.bot.queue.put_nowait((1, _player, 0))
                
                # Refresh the shop view for the newly purchased unit
                view, embed = await self.shop_unit_view_factory(_unit.id, _player.id, message_manager)
                await message_manager.update_message(view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for unit purchase {_unit.name}")
            buy_button.callback = buy_button_callback
            view.add_item(buy_button)
            return view, embed

        # Handle units that are MIA, KIA, or currently active in a campaign
        elif unit_status.name in {"MIA", "KIA"} or active:
            logger.triage(f"Unit {unit_name} is {unit_status.name} or in a campaign, no upgrades available")
            embed.description = tmpl.cant_buy_upgrades_active
            return view, embed

        # Handle INACTIVE units (can purchase upgrades)
        elif unit_status.name == "INACTIVE":
            logger.triage(f"Unit {unit_name} is inactive, generating upgrade options")
            return await self.shop_inactive_view_factory(unit_id, player_id, message_manager, embed, view)
        
        # Handle unexpected unit status
        logger.triage(f"Invalid end state for Shop Unit View - unit {unit_name} has unexpected status: {unit_status}")
        return view, embed

    @uses_db(CustomClient().sessionmaker)
    async def shop_inactive_view_factory(self, unit_id: int, player_id: int, message_manager: MessageManager, embed: Embed, view: ui.View, session: Session):
        """
        Creates the shop interface for inactive units that can purchase upgrades.
        
        This method handles:
        - Fetching available upgrades for the unit
        - Pagination of upgrade options
        - Filtering upgrades based on unit requisition and ownership
        - Creating navigation buttons for browsing upgrades
        """
        logger.triage(f"Creating inactive view for unit {unit_id} and player {player_id}")
        
        # Get player's requisition points for purchasing upgrades
        rec_points = session.query(Player.rec_points).filter(Player.id == player_id).scalar()
        
        # Get unit details including name, type, and unit requisition
        _unit = session.query(Unit).filter(Unit.id == unit_id).first()
        logger.triage(f"Unit {_unit.name} has {_unit.unit_req} unit requisition")
        unit_req = _unit.unit_req
        unit_name = _unit.name
        
        # Get all upgrades compatible with this unit type
        available_upgrades = _unit.available_upgrades
        
        # Check if any upgrades are available for this unit type
        if not available_upgrades:
            logger.triage(f"No compatible upgrades found for unit type {_unit.unit_type}")
            embed.description = tmpl.no_upgrades_available
            embed.color = 0xff0000  # Red color for error state
            return view, embed
            
        logger.triage(f"Found {len(available_upgrades)} compatible upgrades for unit type {_unit.unit_type}")
        
        # Create paginator to handle large numbers of upgrades (25 per page)
        paginator = Paginator([upgrade.id for upgrade in available_upgrades], 25)
        page = paginator.current()
        
        # Create the dropdown select menu for upgrade selection
        select = ui.Select(placeholder=tmpl.shop_select_upgrade_placeholder)
        button_template = tmpl.shop_upgrade_button_template
        
        # Initialize navigation buttons (disabled by default)
        previous_button = ui.Button(label=tmpl.shop_previous_button, style=ButtonStyle.secondary)
        previous_button.disabled = True
        next_button = ui.Button(label=tmpl.shop_next_button, style=ButtonStyle.secondary)
        next_button.disabled = True

        def populate_select_options(upgrade_ids: list[int], current_unit_req: int, current_rec_points: int):
            """
            Helper function to populate the select dropdown with available upgrades.
            
            This function handles:
            - Filtering out disabled upgrades
            - Checking unit requisition compatibility
            - Filtering out already owned non-repeatable upgrades
            - Calculating currency and affordability indicators
            - Formatting upgrade display with emojis and cost indicators
            
            Args:
                upgrade_ids: List of upgrade IDs to process
                current_unit_req: Current unit requisition points
                current_rec_points: Current player requisition points
                
            Returns:
                The currency amount used for the current page
            """
            select.options.clear()
            
            for upgrade_id in upgrade_ids:
                logger.triage(f"Processing upgrade ID {upgrade_id} for display")
                _upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == upgrade_id).first()
                logger.triage(f"Adding upgrade {_upgrade.name} of type {_upgrade.type} to select")
                
                # Skip disabled upgrades
                if _upgrade.disabled:
                    logger.triage(f"Skipping disabled upgrade {_upgrade.name}")
                    continue
                    
                # Skip upgrades without valid upgrade type
                if not _upgrade.upgrade_type:
                    logger.error(f"Skipping upgrade ID:{_upgrade.id} Name:{_upgrade.name} Type:{_upgrade.type} - no valid upgrade type")
                    continue
                    
                # Skip upgrades that can't use unit requisition when unit has unit_req
                if not _upgrade.upgrade_type.can_use_unit_req and current_unit_req > 0:
                    logger.triage(f"Skipping upgrade {_upgrade.name} for unit {unit_name} because it has unit requisition")
                    continue
                # we need to reacquire the _unit object in this scope, from the unit_id argument of the parent function
                _unit = session.query(Unit).filter(Unit.id == unit_id).first()
                # Check if upgrade is already owned and not repeatable
                owned_upgrade = session.query(PlayerUpgrade).filter(
                    PlayerUpgrade.unit_id == _unit.id,
                    PlayerUpgrade.shop_upgrade_id == _upgrade.id
                ).first()
                if not _upgrade.repeatable and owned_upgrade:
                    logger.triage(f"Skipping non-repeatable upgrade {_upgrade.name} as it is already owned")
                    continue

                # Determine which currency to use (unit requisition or player requisition points)
                currency = current_unit_req if _upgrade.upgrade_type.can_use_unit_req and current_unit_req > 0 else current_rec_points
                
                # Add ❌ indicator if player can't afford the upgrade
                insufficient = "❌" if _upgrade.cost > currency else ""
                
                # Get emoji for upgrade type display
                utype = _upgrade.upgrade_type.emoji
                
                # Add option to select dropdown with formatted label
                select.add_option(
                    label=button_template.format(
                        type=utype, 
                        insufficient=insufficient, 
                        name=_upgrade.name, 
                        cost=_upgrade.cost
                    ), 
                    value=str(_upgrade.id)
                )
            return currency

        # Populate the initial page of upgrades
        currency = populate_select_options(page, unit_req, rec_points)
        
        # Add previous page button if there are previous pages
        if paginator.has_previous():
            previous_button.disabled = False
            
        @uses_db(CustomClient().sessionmaker)
        async def previous_button_callback(interaction: Interaction, session: Session):
            """Callback for navigating to the previous page of upgrades"""
            # Get fresh data from database
            unit_name, unit_req = session.query(Unit.name, Unit.unit_req).filter(Unit.id == unit_id).first()
            rec_points = session.query(Player.rec_points).filter(Player.id == player_id).scalar()
            
            logger.triage(f"Navigating to previous page of upgrades for unit {unit_name}")
            await interaction.response.defer(thinking=False, ephemeral=True)
            
            # Update page and repopulate options
            nonlocal page, select, previous_button, next_button
            page = paginator.previous()
            currency = populate_select_options(page, unit_req, rec_points)
            
            # Update button states based on pagination
            previous_button.disabled = not paginator.has_previous()
            if next_button:
                next_button.disabled = not paginator.has_next()
                
            await message_manager.update_message(embed=embed)
            #await interaction.response.defer(thinking=False, ephemeral=True)
            logger.triage(f"Deferred response for previous page navigation for unit {unit_name}")
            
        previous_button.callback = previous_button_callback
        view.add_item(previous_button)
        
        # Add the main upgrade selection dropdown
        view.add_item(select)
        
        # Add next page button if there are more pages
        if paginator.has_next():
            next_button.disabled = False
            
            @uses_db(CustomClient().sessionmaker)
            async def next_button_callback(interaction: Interaction, session: Session):
                """Callback for navigating to the next page of upgrades"""
                # Get fresh data from database
                unit_name, unit_req = session.query(Unit.name, Unit.unit_req).filter(Unit.id == unit_id).first()
                rec_points = session.query(Player.rec_points).filter(Player.id == player_id).scalar()
                
                logger.triage(f"Navigating to next page of upgrades for unit {unit_name}")
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for next page navigation for unit {unit_name}")
                
                # Update page and repopulate options
                nonlocal page, select, previous_button, next_button
                page = paginator.next()
                currency = populate_select_options(page, unit_req, rec_points)
                
                # Update button states based on pagination
                if previous_button:
                    previous_button.disabled = not paginator.has_previous()
                next_button.disabled = not paginator.has_next()
                
                await message_manager.update_message(view=view)
                
            next_button.callback = next_button_callback
        view.add_item(next_button)
        
        # Set the embed description with currency information
        embed.description = tmpl.select_upgrade_to_buy.format(
            req_points=currency, 
            req_type=("unit " if _unit.unit_req > 0 else "") + tmpl.MAIN_CURRENCY.lower()
        )

        @error_reporting()
        @uses_db(CustomClient().sessionmaker)
        async def select_callback(interaction: Interaction, session: Session):
            """
            Callback function for when a user selects an upgrade to purchase.
            
            This function handles:
            - Validation of upgrade availability and affordability
            - Checking required upgrades
            - Processing different upgrade types (refit vs regular upgrades)
            - Handling non-purchaseable upgrades
            - Database updates and player notification
            """
            nonlocal embed
            
            # Get the selected upgrade ID from the dropdown
            upgrade_id = int(select.values[0])
            logger.triage(f"Selected upgrade ID: {upgrade_id}")

            # Fetch the upgrade details from database
            upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == upgrade_id).first()
            if not upgrade:
                logger.triage(f"Upgrade with ID {upgrade_id} not found")
                embed.description = tmpl.upgrade_not_found
                embed.color = 0xff0000  # Red for error
                await message_manager.update_message()
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for upgrade not found error for upgrade ID {upgrade_id}")
                return

            # Get fresh player and unit data for validation
            _player = session.query(Player).filter(Player.id == player_id).first()
            _unit = session.query(Unit).filter(Unit.id == unit_id).first()
            logger.triage(f"Processing upgrade purchase for player {_player.name} and unit {_unit.name}")

            # Check if player has enough currency to purchase the upgrade
            if upgrade.cost > (_unit.unit_req if _unit.unit_req > 0 else _player.rec_points):
                logger.triage(f"Player {interaction.user.name} does not have enough requisition points. Required: {upgrade.cost}, Available: {_unit.unit_req if _unit.unit_req > 0 else _player.rec_points}")
                embed.description = tmpl.not_enough_req_points_upgrade
                embed.color = 0xff0000  # Red for error
                await message_manager.update_message()
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for insufficient RP error for upgrade {upgrade.name}")
                return
            
            # Check if upgrade has required prerequisites
            if upgrade.required_upgrade_id:
                required_upgrade = session.query(PlayerUpgrade).filter(
                    PlayerUpgrade.unit_id == _unit.id, 
                    PlayerUpgrade.shop_upgrade_id == upgrade.required_upgrade_id
                ).first()
                if not required_upgrade:
                    logger.triage(f"Player {interaction.user.name} does not have the required upgrade: {upgrade.required_upgrade_id}")
                    embed.description = tmpl.dont_have_required_upgrade
                    embed.color = 0xff0000  # Red for error
                    await message_manager.update_message()
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    logger.triage(f"Deferred response for missing required upgrade error for upgrade {upgrade.name}")
                    return
                
            # Handle non-purchaseable upgrades (e.g., free upgrades, campaign rewards)
            if upgrade.upgrade_type.non_purchaseable:
                logger.triage(f"Upgrade {upgrade.name} is non-purchaseable")
                embed.description = tmpl.upgrade_non_purchaseable
                embed.color = 0xff0000  # Red for error
                await message_manager.update_message()
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for non-purchaseable upgrade error for upgrade {upgrade.name}")
                return
            
            # Handle refit upgrades (change unit type)
            if upgrade.upgrade_type.is_refit:
                logger.triage(f"Starting refit purchase workflow for unit {_unit.name} to {upgrade.refit_target}")
                refit_target = upgrade.refit_target
                refit_cost = upgrade.cost
                
                # Get current upgrades on the unit
                current_upgrades: list[PlayerUpgrade] = _unit.upgrades
                logger.triage(f"Current upgrades for unit: {[upgrade.name for upgrade in current_upgrades]}")
                
                # Determine which upgrades are incompatible with the new unit type
                current_upgrade_set: set[ShopUpgrade] = {upgrade.shop_upgrade for upgrade in current_upgrades}
                compatible_upgrades: set[ShopUpgrade] = set(upgrade.target_type_info.compatible_upgrades)
                incompatible_upgrades = current_upgrade_set - compatible_upgrades
                logger.triage(f"Incompatible upgrades that will be moved to stockpile: {[upgrade.name for upgrade in incompatible_upgrades]}")

                # Get player's stockpile unit for storing incompatible upgrades
                stockpile = _player.stockpile
                if not stockpile:
                    logger.triage(f"Player {interaction.user.name} does not have a stockpile unit")
                    await interaction.response.send_message(tmpl.dont_have_stockpile, ephemeral=True)
                    return
                logger.triage(f"Found stockpile unit: {stockpile.name}")

                # Move incompatible upgrades to stockpile
                for _upgrade in current_upgrades:
                    if _upgrade.shop_upgrade in incompatible_upgrades:
                        logger.triage(f"Moving upgrade {_upgrade.name} to stockpile")
                        _upgrade.unit_id = stockpile.id

                # Change unit type and deduct cost
                logger.triage(f"Changing unit type from {_unit.unit_type} to {refit_target}")
                _unit.unit_type = refit_target
                _player.rec_points -= refit_cost
                logger.triage(f"Deducted {refit_cost} RP from player. New balance: {_player.rec_points}")
                
                # Add free upgrades that come with the new unit type
                if upgrade.target_type_info.free_upgrade_1:
                    logger.triage(f"Adding free upgrade 1: {upgrade.target_type_info.free_upgrade_1_info.name}")
                    free_upgrade_1 = PlayerUpgrade(
                        unit_id=_unit.id, 
                        name=upgrade.target_type_info.free_upgrade_1_info.name, 
                        type=upgrade.target_type_info.free_upgrade_1_info.type, 
                        original_price=0, 
                        non_transferable=True, 
                        shop_upgrade_id=upgrade.target_type_info.free_upgrade_1
                    )
                    session.add(free_upgrade_1)
                if upgrade.target_type_info.free_upgrade_2:
                    logger.triage(f"Adding free upgrade 2: {upgrade.target_type_info.free_upgrade_2_info.name}")
                    free_upgrade_2 = PlayerUpgrade(
                        unit_id=_unit.id, 
                        name=upgrade.target_type_info.free_upgrade_2_info.name, 
                        type=upgrade.target_type_info.free_upgrade_2_info.type, 
                        original_price=0, 
                        non_transferable=True, 
                        shop_upgrade_id=upgrade.target_type_info.free_upgrade_2
                    )
                    session.add(free_upgrade_2)

                # Commit changes and update player
                session.commit()
                logger.triage("Committed changes to database")
                self.bot.queue.put_nowait((1, _player, 0))
                logger.triage("Added player update to queue")
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for refit purchase workflow for unit {_unit.name}")
                
                # Update interface and show success message
                view, embed = await self.shop_unit_view_factory(_unit.id, _player.id, message_manager)
                embed.description = tmpl.you_have_bought_refit.format(refit_target=refit_target, refit_cost=refit_cost)
                embed.color = 0x00ff00  # Green for success
                await message_manager.update_message(view=view, embed=embed)
                if not interaction.response.is_done():
                    await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for successful refit purchase for unit {_unit.name}")
                return

            # Handle regular upgrades (non-refit)
            # Check if upgrade is already owned and not repeatable
            existing = session.query(PlayerUpgrade).filter(
                PlayerUpgrade.unit_id == _unit.id, 
                PlayerUpgrade.shop_upgrade_id == upgrade.id
            ).first()
            logger.triage(f"Checking if upgrade is repeatable: {upgrade.repeatable}")
            if existing and not upgrade.repeatable:
                logger.triage(f"Player {interaction.user.name} already has this upgrade: {upgrade.name}")
                embed.description = tmpl.already_have_upgrade
                embed.color = 0xff0000  # Red for error
                await message_manager.update_message()
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for duplicate upgrade error for upgrade {upgrade.name}")
                return

            # Create the new player upgrade record
            new_upgrade = PlayerUpgrade(
                unit_id=_unit.id, 
                shop_upgrade_id=upgrade.id, 
                type=upgrade.type, 
                name=upgrade.name, 
                original_price=upgrade.cost
            )
            session.add(new_upgrade)
            logger.triage(f"Player {interaction.user.name} bought upgrade: {upgrade.name} for {upgrade.cost} Req")
            
            # Store values for success message
            upgrade_name = upgrade.name
            upgrade_cost = upgrade.cost
            
            # Deduct cost from appropriate currency source
            if _unit.unit_req > 0:
                # Use unit requisition if available
                _unit.unit_req -= upgrade_cost
                new_upgrade.original_price = 0  # Mark as free since unit_req is free currency
            else:
                # Use player requisition points
                _player.rec_points -= upgrade_cost
                
            # Commit changes and update player
            session.commit()
            self.bot.queue.put_nowait((1, _player, 0))
            
            # Update interface and show success message
            view, embed = await self.shop_unit_view_factory(_unit.id, _player.id, message_manager)
            embed.description = tmpl.you_have_bought_upgrade.format(upgrade_name=upgrade_name, upgrade_cost=upgrade_cost)
            embed.color = 0x00ff00  # Green for success
            await message_manager.update_message(view=view, embed=embed)
            await interaction.response.defer(thinking=False, ephemeral=True)
            logger.triage(f"Deferred response for successful upgrade purchase {upgrade_name}")

            
        select.callback = select_callback
        return view, embed
    
    @ac.command(name="replace_stockpile", description="Create a new stockpile unit if you don't have one")
    @uses_db(CustomClient().sessionmaker)
    async def replace_stockpile(self, interaction: Interaction, session: Session):
        """
        Command to create a stockpile unit for players who don't have one.
        
        Stockpile units are used to store incompatible upgrades when units are refitted.
        Each player can only have one stockpile unit.
        """
        # Get player information
        _player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not _player:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=self.bot.use_ephemeral)
            return
            
        # Check if player already has a stockpile unit
        stockpile = session.query(Unit).filter(Unit.player_id == _player.id, Unit.unit_type == "STOCKPILE").first()
        if stockpile:
            await interaction.response.send_message(tmpl.already_have_stockpile, ephemeral=self.bot.use_ephemeral)
            return
            
        # Create new stockpile unit
        new_stockpile = Unit(
            name="Stockpile", 
            player_id=_player.id, 
            status=UnitStatus.INACTIVE, 
            unit_type="STOCKPILE"
        )
        session.add(new_stockpile)
        await interaction.response.send_message(tmpl.created_stockpile_unit, ephemeral=self.bot.use_ephemeral)

    ## Shop management

    def original_author(self, original: Interaction) -> Callable[[Interaction], bool]:
        author = original.user
        def predicate(interaction: Interaction) -> bool:
            return interaction.user == author
        return predicate

    @ac.command(name="manage", description="Manage the shop")
    @uses_db(CustomClient().sessionmaker)
    async def manage(self, interaction: Interaction, session: Session):
        """
        Command to manage the shop.
        """
        logger.info(f"Manage command invoked by {interaction.user.id} ({interaction.user.name})")
        
        # just like the shop command, we need to make a MessageManager, and send 3 buttons, Unit Type, Upgrade Type, and Upgrade
        logger.debug("Creating manage interface")
        message_manager = MessageManager(interaction)
        view = ui.View()
        predicate = self.original_author(interaction)
        injector = inject(message_manager=message_manager)

        unittype_button = ui.Button(label=tmpl.shop_unit_type_button, style=ButtonStyle.primary)
        view.add_item(unittype_button)
        unittype_button.callback = ac.check(predicate)(injector(self.unittype_button_callback))

        upgradetype_button = ui.Button(label=tmpl.shop_upgrade_type_button, style=ButtonStyle.primary)
        view.add_item(upgradetype_button)
        upgradetype_button.callback = ac.check(predicate)(injector(self.upgradetype_button_callback))

        upgrade_button = ui.Button(label=tmpl.shop_upgrade_button, style=ButtonStyle.primary)
        view.add_item(upgrade_button)
        upgrade_button.callback = ac.check(predicate)(injector(self.upgrade_button_callback))

        logger.debug("Sending manage interface")
        await message_manager.send_message(content=tmpl.shop_manage_select_content, view=view, ephemeral=True)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def unittype_button_callback(self, interaction: Interaction, message_manager: MessageManager, session: Session):
        logger.info(f"Unit type management accessed by {interaction.user.id} ({interaction.user.name})")
        
        # send a dropdown with all the unit types and an option for adding a new unit type, we may need to handle the existence of more than 25 unit types which means we need to paginate
        logger.debug("Querying unit types for pagination")
        unit_types = session.query(UnitType.unit_type).all()
        # Add the "Add New" option to the list so pagination handles it naturally
        unit_types.append(("\0Add New Unit Type",))
        paginator: Paginator[tuple] = Paginator(unit_types, 25)
        logger.debug(f"Found {len(unit_types)-1} unit types + add option, {len(paginator)} pages")
        view = ui.View()
        select = ui.Select(placeholder=tmpl.shop_unit_type_select_placeholder)
        previous_button = ui.Button(label=tmpl.shop_previous_button, style=ButtonStyle.secondary, disabled=True)
        next_button = ui.Button(label=tmpl.shop_next_button, style=ButtonStyle.secondary, disabled=not paginator.has_next())
        predicate = self.original_author(interaction)
        check = ac.check(predicate)
        view.add_item(previous_button)
        view.add_item(select)
        view.add_item(next_button)

        for unit_type in paginator.current():
            select.add_option(label=unit_type[0], value=unit_type[0])
        
        @check
        @error_reporting(True)
        async def previous_button_callback(interaction: Interaction):
            nonlocal paginator
            logger.debug("Previous button clicked")
            paginator.previous()
            logger.debug(f"Paginator moved to previous page: {paginator.index}")
            select.options.clear()
            for unit_type in paginator.current():
                select.add_option(label=unit_type[0], value=unit_type[0])
            if not paginator.has_next():
                next_button.disabled = True
                logger.debug("Next button disabled")
            else:
                next_button.disabled = False
                logger.debug("Next button enabled")
            if not paginator.has_previous():
                previous_button.disabled = True
                logger.debug("Previous button disabled")
            else:
                previous_button.disabled = False
                logger.debug("Previous button enabled")
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        previous_button.callback = previous_button_callback

        @check
        @error_reporting(True)
        async def next_button_callback(interaction: Interaction):
            nonlocal paginator
            logger.debug("Next button clicked")
            paginator.next()
            logger.debug(f"Paginator moved to next page: {paginator.index}")
            select.options.clear()
            for unit_type in paginator.current():
                select.add_option(label=unit_type[0], value=unit_type[0])
            if not paginator.has_next():
                next_button.disabled = True
                logger.debug("Next button disabled")
            else:
                next_button.disabled = False
                logger.debug("Next button enabled")
            if not paginator.has_previous():
                previous_button.disabled = True
                logger.debug("Previous button disabled")
            else:
                previous_button.disabled = False
                logger.debug("Previous button enabled")
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        next_button.callback = next_button_callback
        
        @check
        @error_reporting(True)
        @uses_db(CustomClient().sessionmaker)
        async def select_callback(interaction: Interaction, session: Session):
            # here is the complicated part, we have two cases, either the data is "\0add_new_unit_type" or it's a valid unit type id
            target = interaction.data["values"][0]
            logger.info(f"Unit type selection: {target} by {interaction.user.id}")
            logger.debug(f"Selected unit type: {target}")
            if target == "\0Add New Unit Type":
                logger.info(f"Adding new unit type by {interaction.user.id}")
                # send a modal to add a new unit type, we just need to get the name, we can get the rest of the data using subsequent dropdowns (because dropdowns are not allowed in modals)
                modal = ui.Modal(title=tmpl.shop_add_new_unit_type_modal_title)
                modal.add_item(ui.TextInput(label=tmpl.shop_unit_type_name_label, placeholder=tmpl.shop_unit_type_name_placeholder, style=TextStyle.short, required=True, max_length=15))
                await interaction.response.send_modal(modal)

                @check
                @error_reporting(True)
                async def modal_submit(interaction: Interaction):
                    logger.debug(f"Modal submitted: {interaction.data}")
                    new_unit_type = UnitType(unit_type=interaction.data["components"][0]["components"][0]["value"])
                    view = ui.View()
                    is_base_unit = ui.Select(placeholder=tmpl.shop_is_base_placeholder, options=[SelectOption(label="Yes", value="y"), SelectOption(label="No", value="n")])
                    # we are skipping the free upgrades for now, we can deal with that later
                    unit_req_amount = ui.Select(placeholder=tmpl.shop_unit_req_amount_placeholder, options=[
                        SelectOption(label=str(i), value=str(i)) for i in range(0, 4)
                    ])
                    done_button = ui.Button(label=tmpl.shop_done_button, style=ButtonStyle.primary)
                    view.add_item(is_base_unit)
                    view.add_item(unit_req_amount)
                    view.add_item(done_button)
                    # we are not yet using the template system for this, so we are just sending a hardcoded message
                    await message_manager.update_message(content=tmpl.shop_please_setup_unit_type, view=view)
                    await interaction.response.defer(thinking=False, ephemeral=True)

                    @check
                    @error_reporting(True)
                    async def base_unit_callback(interaction: Interaction):
                        nonlocal new_unit_type
                        logger.debug(f"Base unit callback: {interaction.data}")
                        new_unit_type.is_base = interaction.data["values"][0] == "y"
                        await interaction.response.defer(thinking=False, ephemeral=True)
                    is_base_unit.callback = base_unit_callback

                    @check
                    @error_reporting(True)
                    async def unit_req_amount_callback(interaction: Interaction):
                        nonlocal new_unit_type
                        logger.debug(f"Unit req amount callback: {interaction.data}")
                        new_unit_type.unit_req = int(interaction.data["values"][0])
                        await interaction.response.defer(thinking=False, ephemeral=True)
                    unit_req_amount.callback = unit_req_amount_callback

                    @check
                    @error_reporting(True)
                    async def done_button_callback(interaction: Interaction):
                        nonlocal new_unit_type
                        logger.debug(f"Done button callback: {interaction.data}")
                        session.add(new_unit_type)
                        session.commit()
                        await interaction.response.defer(thinking=False, ephemeral=True)
                        await message_manager.update_message(content=tmpl.shop_unit_type_added, view=ui.View())
                    done_button.callback = done_button_callback
                modal.on_submit = modal_submit

            else:
                unit_type_ = session.query(UnitType).filter(UnitType.unit_type == target).first()
                # we need an embed with the unit type's data, a rename button, a delete button, dropdowns for is_base and unit_req, and a save button, we should use a factory so we can rebuild after saving
                def ui_factory(unit_type: UnitType) -> tuple[ui.View, Embed]:
                    nonlocal target
                    view = ui.View()
                    embed = Embed(title=tmpl.shop_unit_type_title.format(unit_type=unit_type.unit_type))
                    embed.add_field(name="Is Base", value="Yes" if unit_type.is_base else "No")
                    embed.add_field(name="Unit Req", value=str(unit_type.unit_req))
                    
                    rename_button = ui.Button(label=tmpl.shop_rename_button, style=ButtonStyle.primary)
                    delete_button = ui.Button(label=tmpl.shop_delete_button, style=ButtonStyle.danger)
                    view.add_item(rename_button)
                    view.add_item(delete_button)

                    is_base_unit = ui.Select(placeholder=tmpl.shop_is_base_placeholder, options=[SelectOption(label="Yes", value="y", default=unit_type.is_base), SelectOption(label="No", value="n", default=not unit_type.is_base)])
                    unit_req_amount = ui.Select(placeholder=tmpl.shop_unit_req_amount_placeholder, options=[
                        SelectOption(label=str(i), value=str(i), default=(i == unit_type.unit_req)) for i in range(0, 4)
                    ])
                    view.add_item(is_base_unit)
                    view.add_item(unit_req_amount)
        
                    unit_type_ = unit_type.unit_type # we can't use closure scoped instances, so we need to make a closure scoped PK of the instance instead

                    @check
                    @error_reporting(True)
                    async def rename_button_callback(interaction: Interaction):
                        # Create modal for new name
                        modal = ui.Modal(title=tmpl.shop_rename_unit_type_modal_title)
                        new_name_input = ui.TextInput(
                            label=tmpl.shop_new_name_label,
                            placeholder=tmpl.shop_new_name_placeholder,
                            default=unit_type_,
                            min_length=1,
                            max_length=15
                        )
                        modal.add_item(new_name_input)
                        
                        @check
                        @error_reporting(True)
                        @uses_db(CustomClient().sessionmaker)
                        async def modal_submit(interaction: Interaction, session: Session):
                            nonlocal target
                            new_name = new_name_input.value.strip().upper()
                            
                            # Get the current unit type
                            unit_type = session.query(UnitType).filter(UnitType.unit_type == unit_type_).first()
                            
                            # Validate new name
                            if not new_name:
                                await interaction.response.send_message(tmpl.shop_name_cannot_be_empty, ephemeral=True)
                                return
                            
                            # Check if new name already exists
                            existing = session.query(UnitType).filter(UnitType.unit_type == new_name).first()
                            if existing:
                                await interaction.response.send_message(tmpl.shop_unit_type_already_exists.format(name=new_name), ephemeral=True)
                                return
                            
                            logger.info(f"Starting rename operation: '{unit_type.unit_type}' -> '{new_name}'")
                            
                            # Create new UnitType with same properties
                            new_unit_type = UnitType(
                                unit_type=new_name,
                                is_base=unit_type.is_base,
                                free_upgrade_1=unit_type.free_upgrade_1,
                                free_upgrade_2=unit_type.free_upgrade_2,
                                unit_req=unit_type.unit_req
                            )
                            session.add(new_unit_type)
                            logger.info(f"Created new UnitType: {new_name}")
                            
                            # Migrate all Units that reference this type
                            units_count = len(unit_type.units)
                            for unit in unit_type.units:
                                unit.unit_type = new_name
                            logger.info(f"Migrated {units_count} Units from '{unit_type.unit_type}' to '{new_name}'")
                            
                            # Migrate Units that have this as original_type
                            original_units_count = len(unit_type.original_units)
                            for unit in unit_type.original_units:
                                unit.original_type = new_name
                            logger.info(f"Migrated {original_units_count} Units with original_type from '{unit_type.unit_type}' to '{new_name}'")
                            
                            # Migrate ShopUpgrades that have this as refit_target
                            refit_count = len(unit_type.refit_targets)
                            for upgrade in unit_type.refit_targets:
                                upgrade.refit_target = new_name
                            logger.info(f"Migrated {refit_count} ShopUpgrades with refit_target from '{unit_type.unit_type}' to '{new_name}'")
                            
                            # Migrate ShopUpgradeUnitTypes associations
                            upgrade_types_count = len(unit_type.upgrade_types)
                            for upgrade_type in unit_type.upgrade_types:
                                upgrade_type.unit_type = new_name
                            logger.info(f"Migrated {upgrade_types_count} ShopUpgradeUnitTypes associations from '{unit_type.unit_type}' to '{new_name}'")
                            
                            # Commit migration changes before deletion
                            session.commit()
                            logger.info(f"Committed migration changes for '{unit_type.unit_type}' -> '{new_name}'")
                            
                            # Delete the old UnitType
                            session.delete(unit_type)
                            logger.info(f"Deleted old UnitType: '{unit_type.unit_type}'")
                            
                            # Commit the deletion
                            session.commit()
                            logger.info(f"Successfully completed rename operation: '{unit_type.unit_type}' -> '{new_name}'")
                            
                            # Update the target variable for subsequent operations
                            target = new_name
                            
                            await interaction.response.send_message(tmpl.shop_unit_type_renamed.format(old=unit_type.unit_type, new=new_name), ephemeral=True)
                            
                            # Refresh the UI with the new name
                            updated_unit_type = session.query(UnitType).filter(UnitType.unit_type == new_name).first()
                            new_view, new_embed = ui_factory(updated_unit_type)
                            await message_manager.update_message(content="Please set up the unit type", view=new_view, embed=new_embed)
                        
                        modal.on_submit = modal_submit
                        await interaction.response.send_modal(modal)

                    rename_button.callback = rename_button_callback

                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def delete_button_callback(interaction: Interaction, session: Session):
                        unit_type = session.query(UnitType).filter(UnitType.unit_type == unit_type_).first()
                        if unit_type.units:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_units, ephemeral=True)
                            return
                        if unit_type.original_units:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_original_units, ephemeral=True)
                            return
                        if unit_type.refit_targets:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_refit_targets, ephemeral=True)
                            return
                        if unit_type.compatible_upgrades:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_compatible_upgrades, ephemeral=True)
                            return
                        session.delete(unit_type)
                        session.commit()
                        await interaction.response.send_message(tmpl.shop_unit_type_deleted, ephemeral=True)
                        await message_manager.delete_message()
                    delete_button.callback = delete_button_callback
                    
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def base_unit_callback(interaction: Interaction, session: Session):
                        unit_type = session.query(UnitType).filter(UnitType.unit_type == unit_type_).first()
                        unit_type.is_base = interaction.data["values"][0] == "y"
                        session.commit()
                        await interaction.response.defer(thinking=False, ephemeral=True)
                        await message_manager.update_message(content=tmpl.shop_unit_type_updated)

                    is_base_unit.callback = base_unit_callback

                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def unit_req_callback(interaction: Interaction, session: Session):
                        unit_type = session.query(UnitType).filter(UnitType.unit_type == unit_type_).first()
                        unit_type.unit_req = int(interaction.data["values"][0])
                        session.commit()
                        await interaction.response.defer(thinking=False, ephemeral=True)
                        await message_manager.update_message(content=tmpl.shop_unit_type_updated)
                    unit_req_amount.callback = unit_req_callback

                    # we need to check if the unit type is currently a Parent, and if so, we disable the delete button and add a warning to the embed
                    if unit_type.units:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a unit type that has units assigned to it", inline=False)
                    if unit_type.original_units:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a unit type that has original units assigned to it", inline=False)
                    if unit_type.refit_targets:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a unit type that has refit targets assigned to it", inline=False)
                    if unit_type.compatible_upgrades:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a unit type that has compatible upgrades assigned to it", inline=False)

                    return view, embed

                view, embed = ui_factory(unit_type_)
                await message_manager.update_message(content=tmpl.shop_please_setup_unit_type, view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)


        select.callback = select_callback
        await interaction.response.defer(thinking=False, ephemeral=True)
        await message_manager.update_message(content=tmpl.shop_please_select_unit_type, view=view)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def upgradetype_button_callback(self, interaction: Interaction, message_manager: MessageManager, session: Session):
        logger.info(f"Upgrade type management accessed by {interaction.user.id} ({interaction.user.name})")
        
        # send a dropdown with all the upgrade types and an option for adding a new upgrade type, we may need to handle the existence of more than 25 upgrade types which means we need to paginate
        logger.debug("Querying upgrade types for pagination")
        upgrade_types = session.query(UpgradeType.name).all()
        # Add the "Add New" option to the list so pagination handles it naturally
        upgrade_types.append(("\0Add New Upgrade Type",))
        paginator: Paginator[tuple] = Paginator(upgrade_types, 25)
        logger.debug(f"Found {len(upgrade_types)-1} upgrade types + add option, {len(paginator)} pages")
        view = ui.View()
        select = ui.Select(placeholder=tmpl.shop_upgrade_type_select_placeholder)
        previous_button = ui.Button(label=tmpl.shop_previous_button, style=ButtonStyle.secondary, disabled=True)
        next_button = ui.Button(label=tmpl.shop_next_button, style=ButtonStyle.secondary, disabled=not paginator.has_next())
        predicate = self.original_author(interaction)
        check = ac.check(predicate)
        view.add_item(previous_button)
        view.add_item(select)
        view.add_item(next_button)

        for upgrade_type in paginator.current():
            select.add_option(label=upgrade_type[0], value=upgrade_type[0])
        
        @check
        async def previous_button_callback(interaction: Interaction):
            nonlocal paginator
            logger.debug("Previous button clicked")
            paginator.previous()
            logger.debug(f"Paginator moved to previous page: {paginator.index}")
            select.options.clear()
            for upgrade_type in paginator.current():
                select.add_option(label=upgrade_type[0], value=upgrade_type[0])
            if not paginator.has_next():
                next_button.disabled = True
                logger.debug("Next button disabled")
            else:
                next_button.disabled = False
                logger.debug("Next button enabled")
            if not paginator.has_previous():
                previous_button.disabled = True
                logger.debug("Previous button disabled")
            else:
                previous_button.disabled = False
                logger.debug("Previous button enabled")
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        previous_button.callback = previous_button_callback

        @check
        async def next_button_callback(interaction: Interaction):
            nonlocal paginator
            logger.debug("Next button clicked")
            paginator.next()
            logger.debug(f"Paginator moved to next page: {paginator.index}")
            select.options.clear()
            for upgrade_type in paginator.current():
                select.add_option(label=upgrade_type[0], value=upgrade_type[0])
            if not paginator.has_next():
                next_button.disabled = True
                logger.debug("Next button disabled")
            else:
                next_button.disabled = False
                logger.debug("Next button enabled")
            if not paginator.has_previous():
                previous_button.disabled = True
                logger.debug("Previous button disabled")
            else:
                previous_button.disabled = False
                logger.debug("Previous button enabled")
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        next_button.callback = next_button_callback
        
        @check
        @uses_db(CustomClient().sessionmaker)
        async def select_callback(interaction: Interaction, session: Session):
            # here is the complicated part, we have two cases, either the data is "\0add_new_upgrade_type" or it's a valid upgrade type name
            target = interaction.data["values"][0]
            logger.info(f"Upgrade type selection: {target} by {interaction.user.id}")
            
            if target == "\0Add New Upgrade Type":
                logger.info(f"Adding new upgrade type by {interaction.user.id}")
                # we need to create a new upgrade type
                modal = ui.Modal(title=tmpl.shop_add_new_upgrade_type_modal_title)
                name_input = ui.TextInput(label=tmpl.shop_upgrade_type_name_label, placeholder=tmpl.shop_upgrade_type_name_placeholder, min_length=1, max_length=30)
                emoji_input = ui.TextInput(label=tmpl.shop_emoji_label, placeholder=tmpl.shop_emoji_placeholder, max_length=4, required=False)
                is_refit_input = ui.TextInput(label=tmpl.shop_is_refit_label, placeholder=tmpl.shop_yn_placeholder, min_length=1, max_length=1)
                non_purchaseable_input = ui.TextInput(label=tmpl.shop_non_purchaseable_label, placeholder=tmpl.shop_yn_placeholder, min_length=1, max_length=1)
                can_use_unit_req_input = ui.TextInput(label=tmpl.shop_can_use_unit_req_label, placeholder=tmpl.shop_yn_placeholder, min_length=1, max_length=1)
                
                modal.add_item(name_input)
                modal.add_item(emoji_input)
                modal.add_item(is_refit_input)
                modal.add_item(non_purchaseable_input)
                modal.add_item(can_use_unit_req_input)
                
                @check
                @error_reporting(True)
                async def modal_submit(interaction: Interaction):
                    logger.info(f"Adding new upgrade type by {interaction.user.id}")
                    name = name_input.value.strip().upper()
                    emoji = emoji_input.value.strip()
                    is_refit = is_refit_input.value.strip().lower() == "y"
                    non_purchaseable = non_purchaseable_input.value.strip().lower() == "y"
                    can_use_unit_req = can_use_unit_req_input.value.strip().lower() == "y"
                    
                    new_upgrade_type = UpgradeType(
                        name=name,
                        emoji=emoji,
                        is_refit=is_refit,
                        non_purchaseable=non_purchaseable,
                        can_use_unit_req=can_use_unit_req
                    )
                    session.add(new_upgrade_type)
                    session.commit()
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    await message_manager.update_message(content=tmpl.shop_upgrade_type_added, view=ui.View())
                
                modal.on_submit = modal_submit
                await interaction.response.send_modal(modal)
            else:
                upgrade_type_ = session.query(UpgradeType).filter(UpgradeType.name == target).first()
                # we need an embed with the upgrade type's data, a rename button, a delete button, and a save button
                def ui_factory(upgrade_type: UpgradeType) -> tuple[ui.View, Embed]:
                    nonlocal target
                    view = ui.View()
                    embed = Embed(title=tmpl.shop_upgrade_type_title.format(name=upgrade_type.name))
                    embed.add_field(name="Emoji", value=upgrade_type.emoji or "None")
                    embed.add_field(name="Is Refit", value="Yes" if upgrade_type.is_refit else "No")
                    embed.add_field(name="Non Purchaseable", value="Yes" if upgrade_type.non_purchaseable else "No")
                    embed.add_field(name="Can Use Unit Req", value="Yes" if upgrade_type.can_use_unit_req else "No")
                    
                    rename_button = ui.Button(label=tmpl.shop_rename_button, style=ButtonStyle.primary)
                    edit_button = ui.Button(label="Edit", style=ButtonStyle.secondary)
                    delete_button = ui.Button(label=tmpl.shop_delete_button, style=ButtonStyle.danger)
                    view.add_item(rename_button)
                    view.add_item(edit_button)
                    view.add_item(delete_button)
                    
                    upgrade_type_ = upgrade_type.name # we can't use closure scoped instances, so we need to make a closure scoped PK of the instance instead
                    
                    @check
                    @error_reporting(True)
                    async def rename_button_callback(interaction: Interaction):
                        # Create modal for new name
                        modal = ui.Modal(title=tmpl.shop_rename_upgrade_type_modal_title)
                        new_name_input = ui.TextInput(
                            label=tmpl.shop_new_name_label,
                            placeholder=tmpl.shop_new_name_placeholder,
                            default=upgrade_type_,
                            min_length=1,
                            max_length=30
                        )
                        modal.add_item(new_name_input)
                        
                        @check
                        @error_reporting(True)
                        @uses_db(CustomClient().sessionmaker)
                        async def modal_submit(interaction: Interaction, session: Session):
                            nonlocal target
                            new_name = new_name_input.value.strip().upper()
                            
                            # Get the current upgrade type
                            upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_).first()
                            
                            # Validate new name
                            if not new_name:
                                await interaction.response.send_message(tmpl.shop_name_cannot_be_empty, ephemeral=True)
                                return
                            
                            # Check if new name already exists
                            existing = session.query(UpgradeType).filter(UpgradeType.name == new_name).first()
                            if existing:
                                await interaction.response.send_message(tmpl.shop_upgrade_type_already_exists.format(name=new_name), ephemeral=True)
                                return
                            
                            logger.info(f"Starting rename operation: '{upgrade_type.name}' -> '{new_name}'")
                            
                            # Create new UpgradeType with same properties
                            new_upgrade_type = UpgradeType(
                                name=new_name,
                                emoji=upgrade_type.emoji,
                                is_refit=upgrade_type.is_refit,
                                non_purchaseable=upgrade_type.non_purchaseable,
                                can_use_unit_req=upgrade_type.can_use_unit_req
                            )
                            session.add(new_upgrade_type)
                            logger.info(f"Created new UpgradeType: {new_name}")
                            
                            # Migrate all ShopUpgrades that reference this type
                            shop_upgrades_count = len(upgrade_type.shop_upgrades)
                            for shop_upgrade in upgrade_type.shop_upgrades:
                                shop_upgrade.type = new_name
                            logger.info(f"Migrated {shop_upgrades_count} ShopUpgrades from '{upgrade_type.name}' to '{new_name}'")
                            
                            # Migrate all PlayerUpgrades that reference this type
                            player_upgrades_count = len(upgrade_type.player_upgrades)
                            for player_upgrade in upgrade_type.player_upgrades:
                                player_upgrade.type = new_name
                            logger.info(f"Migrated {player_upgrades_count} PlayerUpgrades from '{upgrade_type.name}' to '{new_name}'")
                            
                            # Commit migration changes before deletion
                            session.commit()
                            logger.info(f"Committed migration changes for '{upgrade_type.name}' -> '{new_name}'")
                            
                            # Delete the old UpgradeType
                            session.delete(upgrade_type)
                            logger.info(f"Deleted old UpgradeType: '{upgrade_type.name}'")
                            
                            # Commit the deletion
                            session.commit()
                            logger.info(f"Successfully completed rename operation: '{upgrade_type.name}' -> '{new_name}'")
                            
                            # Update the target variable for subsequent operations
                            target = new_name
                            
                            await interaction.response.send_message(tmpl.shop_upgrade_type_renamed.format(old=upgrade_type.name, new=new_name), ephemeral=True)
                            
                            # Refresh the UI with the new name
                            updated_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == new_name).first()
                            new_view, new_embed = ui_factory(updated_upgrade_type)
                            await message_manager.update_message(content="Please set up the upgrade type", view=new_view, embed=new_embed)
                        
                        modal.on_submit = modal_submit
                        await interaction.response.send_modal(modal)
                    
                    rename_button.callback = rename_button_callback
                    
                    @check
                    @error_reporting(True)
                    async def edit_button_callback(interaction: Interaction):
                        # Create edit view with selects for booleans and emoji button
                        edit_view = ui.View()
                        
                        # Create selects for the 3 booleans
                        is_refit_select = ui.Select(
                            placeholder="Is Refit",
                            options=[
                                ui.SelectOption(label="Yes", value="true", default=upgrade_type.is_refit),
                                ui.SelectOption(label="No", value="false", default=not upgrade_type.is_refit)
                            ]
                        )
                        
                        non_purchaseable_select = ui.Select(
                            placeholder="Non Purchaseable",
                            options=[
                                ui.SelectOption(label="Yes", value="true", default=upgrade_type.non_purchaseable),
                                ui.SelectOption(label="No", value="false", default=not upgrade_type.non_purchaseable)
                            ]
                        )
                        
                        can_use_unit_req_select = ui.Select(
                            placeholder="Can Use Unit Req",
                            options=[
                                ui.SelectOption(label="Yes", value="true", default=upgrade_type.can_use_unit_req),
                                ui.SelectOption(label="No", value="false", default=not upgrade_type.can_use_unit_req)
                            ]
                        )
                        
                        # Emoji button
                        emoji_button = ui.Button(label="Set Emoji", style=ButtonStyle.primary)
                        
                        edit_view.add_item(is_refit_select)
                        edit_view.add_item(non_purchaseable_select)
                        edit_view.add_item(can_use_unit_req_select)
                        edit_view.add_item(emoji_button)
                        
                        # Save button
                        save_button = ui.Button(label="Save Changes", style=ButtonStyle.success)
                        edit_view.add_item(save_button)
                        
                        @check
                        @error_reporting(True)
                        @uses_db(CustomClient().sessionmaker)
                        async def save_button_callback(interaction: Interaction, session: Session):
                            # Get the current upgrade type
                            current_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_).first()
                            
                            # Update the boolean values
                            current_upgrade_type.is_refit = is_refit_select.values[0] == "true" if is_refit_select.values else current_upgrade_type.is_refit
                            current_upgrade_type.non_purchaseable = non_purchaseable_select.values[0] == "true" if non_purchaseable_select.values else current_upgrade_type.non_purchaseable
                            current_upgrade_type.can_use_unit_req = can_use_unit_req_select.values[0] == "true" if can_use_unit_req_select.values else current_upgrade_type.can_use_unit_req
                            
                            session.commit()
                            
                            await interaction.response.send_message("Upgrade type updated successfully!", ephemeral=True)
                            
                            # Refresh the UI with updated values
                            updated_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_).first()
                            new_view, new_embed = ui_factory(updated_upgrade_type)
                            await message_manager.update_message(content="Please set up the upgrade type", view=new_view, embed=new_embed)
                        
                        save_button.callback = save_button_callback
                        
                        @check
                        @error_reporting(True)
                        async def emoji_button_callback(interaction: Interaction):
                            # Create modal for emoji input
                            emoji_modal = ui.Modal(title="Set Upgrade Type Emoji")
                            emoji_input = ui.TextInput(
                                label="Emoji",
                                placeholder="Enter emoji (e.g., ⚔️, 🛡️, 🏹)",
                                default=upgrade_type.emoji or "",
                                max_length=10
                            )
                            emoji_modal.add_item(emoji_input)
                            
                            @check
                            @error_reporting(True)
                            @uses_db(CustomClient().sessionmaker)
                            async def emoji_modal_submit(interaction: Interaction, session: Session):
                                new_emoji = emoji_input.value.strip()
                                
                                # Get the current upgrade type
                                current_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_).first()
                                
                                # Update the emoji
                                current_upgrade_type.emoji = new_emoji if new_emoji else None
                                
                                session.commit()
                                
                                await interaction.response.send_message(f"Emoji updated to: {new_emoji if new_emoji else 'None'}", ephemeral=True)
                                
                                # Refresh the UI with updated emoji
                                updated_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_).first()
                                new_view, new_embed = ui_factory(updated_upgrade_type)
                                await message_manager.update_message(content="Please set up the upgrade type", view=new_view, embed=new_embed)
                            
                            emoji_modal.on_submit = emoji_modal_submit
                            await interaction.response.send_modal(emoji_modal)
                        
                        emoji_button.callback = emoji_button_callback
                        
                        # Update the message with the edit view
                        edit_embed = Embed(title=f"Edit Upgrade Type: {upgrade_type.name}")
                        edit_embed.add_field(name="Current Emoji", value=upgrade_type.emoji or "None")
                        edit_embed.add_field(name="Current Is Refit", value="Yes" if upgrade_type.is_refit else "No")
                        edit_embed.add_field(name="Current Non Purchaseable", value="Yes" if upgrade_type.non_purchaseable else "No")
                        edit_embed.add_field(name="Current Can Use Unit Req", value="Yes" if upgrade_type.can_use_unit_req else "No")
                        
                        await message_manager.update_message(content="Edit upgrade type settings", view=edit_view, embed=edit_embed)
                    
                    edit_button.callback = edit_button_callback
                    
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def delete_button_callback(interaction: Interaction, session: Session):
                        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_).first()
                        if upgrade_type.shop_upgrades:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_shop_upgrades, ephemeral=True)
                            return
                        if upgrade_type.player_upgrades:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_player_upgrades, ephemeral=True)
                            return
                        session.delete(upgrade_type)
                        session.commit()
                        await interaction.response.send_message(tmpl.shop_upgrade_type_deleted, ephemeral=True)
                        await message_manager.delete_message()
                    
                    delete_button.callback = delete_button_callback
                    
                    # we need to check if the upgrade type is currently a Parent, and if so, we disable the delete button and add a warning to the embed
                    if upgrade_type.shop_upgrades:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete an upgrade type that has shop upgrades assigned to it", inline=False)
                    if upgrade_type.player_upgrades:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete an upgrade type that has player upgrades assigned to it", inline=False)
                    
                    return view, embed
                
                view, embed = ui_factory(upgrade_type_)
                await message_manager.update_message(content=tmpl.shop_please_setup_upgrade_type, view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
        
        select.callback = select_callback
        await interaction.response.defer(thinking=False, ephemeral=True)
        await message_manager.update_message(content=tmpl.shop_please_select_upgrade_type, view=view)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def upgrade_button_callback(self, interaction: Interaction, message_manager: MessageManager, session: Session):
        logger.info(f"Shop upgrade management accessed by {interaction.user.id} ({interaction.user.name})")
        
        # send a dropdown with all the shop upgrades and an option for adding a new shop upgrade, we may need to handle the existence of more than 25 shop upgrades which means we need to paginate
        logger.debug("Querying shop upgrades for pagination")
        shop_upgrades = session.query(ShopUpgrade.id, ShopUpgrade.name).all()
        # Add the "Add New" option to the list so pagination handles it naturally
        shop_upgrades.append(("\0Add New Shop Upgrade", "\0Add New Shop Upgrade"))
        paginator: Paginator[tuple] = Paginator(shop_upgrades, 25)
        logger.debug(f"Found {len(shop_upgrades)-1} shop upgrades + add option, {len(paginator)} pages")
        view = ui.View()
        select = ui.Select(placeholder=tmpl.shop_upgrade_select_placeholder)
        previous_button = ui.Button(label=tmpl.shop_previous_button, style=ButtonStyle.secondary, disabled=True)
        next_button = ui.Button(label=tmpl.shop_next_button, style=ButtonStyle.secondary, disabled=not paginator.has_next())
        predicate = self.original_author(interaction)
        check = ac.check(predicate)
        view.add_item(previous_button)
        view.add_item(select)
        view.add_item(next_button)

        for shop_upgrade in paginator.current():
            select.add_option(label=shop_upgrade[1], value=str(shop_upgrade[0]))
        
        @check
        @error_reporting(True)
        async def previous_button_callback(interaction: Interaction):
            nonlocal paginator
            logger.debug("Previous button clicked")
            paginator.previous()
            logger.debug(f"Paginator moved to previous page: {paginator.index}")
            select.options.clear()
            for shop_upgrade in paginator.current():
                select.add_option(label=shop_upgrade[1], value=str(shop_upgrade[0]))
            if not paginator.has_next():
                next_button.disabled = True
                logger.debug("Next button disabled")
            else:
                next_button.disabled = False
                logger.debug("Next button enabled")
            if not paginator.has_previous():
                previous_button.disabled = True
                logger.debug("Previous button disabled")
            else:
                previous_button.disabled = False
                logger.debug("Previous button enabled")
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        previous_button.callback = previous_button_callback

        @check
        @error_reporting(True)
        async def next_button_callback(interaction: Interaction):
            nonlocal paginator
            logger.debug("Next button clicked")
            paginator.next()
            logger.debug(f"Paginator moved to next page: {paginator.index}")
            select.options.clear()
            for shop_upgrade in paginator.current():
                select.add_option(label=shop_upgrade[1], value=str(shop_upgrade[0]))
            if not paginator.has_next():
                next_button.disabled = True
                logger.debug("Next button disabled")
            else:
                next_button.disabled = False
                logger.debug("Next button enabled")
            if not paginator.has_previous():
                previous_button.disabled = True
                logger.debug("Previous button disabled")
            else:
                previous_button.disabled = False
                logger.debug("Previous button enabled")
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        next_button.callback = next_button_callback
        
        @check
        @error_reporting(True)
        @uses_db(CustomClient().sessionmaker)
        async def select_callback(interaction: Interaction, session: Session):
            # here is the complicated part, we have two cases, either the data is "\0add_new_shop_upgrade" or it's a valid shop upgrade id
            target = interaction.data["values"][0]
            logger.info(f"Shop upgrade selection: {target} by {interaction.user.id}")
            
            if target == "\0Add New Shop Upgrade":
                logger.info(f"Adding new shop upgrade by {interaction.user.id}")
                # we need to create a new shop upgrade
                upgrade_types = session.query(UpgradeType).all()
                unit_types = session.query(UnitType).all()
                
                # Create view with dropdowns for UpgradeType and booleans
                view = ui.View()
                
                # UpgradeType dropdown
                upgrade_type_options = [SelectOption(label=ut.name, value=ut.name) for ut in upgrade_types]
                upgrade_type_select = ui.Select(placeholder=tmpl.shop_select_upgrade_type_placeholder, options=upgrade_type_options)
                
                disabled_select = ui.Select(placeholder=tmpl.shop_disabled_placeholder, options=[
                    SelectOption(label="No", value="n"),
                    SelectOption(label="Yes", value="y")
                ])
                repeatable_select = ui.Select(placeholder=tmpl.shop_repeatable_placeholder, options=[
                    SelectOption(label="No", value="n"),
                    SelectOption(label="Yes", value="y")
                ])
                
                view.add_item(upgrade_type_select)
                view.add_item(disabled_select)
                view.add_item(repeatable_select)
                
                # Store the selected values
                selected_values = {"upgrade_type": None, "disabled": False, "repeatable": False}
                
                @check
                @error_reporting(True)
                async def upgrade_type_callback(interaction: Interaction):
                    selected_values["upgrade_type"] = upgrade_type_select.values[0] if upgrade_type_select.values else None
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    await message_manager.update_message(content=tmpl.shop_upgrade_type_status.format(type=selected_values['upgrade_type']), view=view)
                
                @check
                @error_reporting(True)
                async def disabled_callback(interaction: Interaction):
                    selected_values["disabled"] = disabled_select.values[0] == "y" if disabled_select.values else False
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    await message_manager.update_message(content=tmpl.shop_disabled_status.format(status='Yes' if selected_values['disabled'] else 'No'), view=view)
                
                @check
                @error_reporting(True)
                async def repeatable_callback(interaction: Interaction):
                    selected_values["repeatable"] = repeatable_select.values[0] == "y" if repeatable_select.values else False
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    await message_manager.update_message(content=tmpl.shop_repeatable_status.format(status='Yes' if selected_values['repeatable'] else 'No'), view=view)
                
                # Add a button to proceed to modal when all selections are made
                proceed_button = ui.Button(label=tmpl.shop_proceed_to_details_button, style=ButtonStyle.primary)
                
                @check
                @error_reporting(True)
                async def proceed_callback(interaction: Interaction):
                    if not selected_values["upgrade_type"]:
                        await interaction.response.send_message(tmpl.shop_please_select_upgrade_type, ephemeral=True)
                        return
                    
                    # Now show the modal with the remaining fields
                    modal = ui.Modal(title=tmpl.shop_add_new_shop_upgrade_modal_title)
                    name_input = ui.TextInput(label=tmpl.shop_upgrade_name_label, placeholder=tmpl.shop_upgrade_name_placeholder, min_length=1, max_length=30)
                    cost_input = ui.TextInput(label=tmpl.shop_upgrade_cost_label, placeholder=tmpl.shop_cost_placeholder, min_length=1, max_length=10)
                    refit_target_input = ui.TextInput(label=tmpl.shop_refit_target_label, placeholder=tmpl.shop_refit_target_optional_placeholder, max_length=15, required=False)
                    required_upgrade_id_input = ui.TextInput(label="Required Upgrade ID", placeholder=tmpl.shop_required_upgrade_id_placeholder, max_length=10, required=False)
                    unit_types_input = ui.TextInput(label="Compatible Unit Types", placeholder=tmpl.shop_compatible_unit_types_placeholder, style=TextStyle.paragraph, required=False)
                    
                    modal.add_item(name_input)
                    modal.add_item(cost_input)
                    modal.add_item(refit_target_input)
                    modal.add_item(required_upgrade_id_input)
                    modal.add_item(unit_types_input)
                    
                    @check
                    @error_reporting(True)
                    async def modal_submit(interaction: Interaction):
                        logger.info(f"Adding new shop upgrade by {interaction.user.id}")
                        name = name_input.value.strip()
                        cost = int(cost_input.value.strip())
                        refit_target = refit_target_input.value.strip().upper() if refit_target_input.value.strip() else None
                        required_upgrade_id = int(required_upgrade_id_input.value.strip()) if required_upgrade_id_input.value.strip() else None
                        unit_types_text = unit_types_input.value.strip()
                        
                        # Parse unit types from newline-separated text
                        compatible_unit_types = [ut.strip().upper() for ut in unit_types_text.split('\n') if ut.strip()] if unit_types_text else []
                        
                        new_shop_upgrade = ShopUpgrade(
                            name=name,
                            type=selected_values["upgrade_type"],
                            cost=cost,
                            refit_target=refit_target,
                            required_upgrade_id=required_upgrade_id,
                            disabled=selected_values["disabled"],
                            repeatable=selected_values["repeatable"]
                        )
                        session.add(new_shop_upgrade)
                        session.flush()  # Get the ID
                        
                        # Create ShopUpgradeUnitTypes associations
                        for unit_type_name in compatible_unit_types:
                            association = ShopUpgradeUnitTypes(
                                shop_upgrade_id=new_shop_upgrade.id,
                                unit_type=unit_type_name
                            )
                            session.add(association)
                        
                        session.commit()
                        await interaction.response.defer(thinking=False, ephemeral=True)
                        await message_manager.update_message(content=tmpl.shop_upgrade_added, view=ui.View())
                    
                    modal.on_submit = modal_submit
                    await interaction.response.send_modal(modal)
                
                proceed_button.callback = proceed_callback
                view.add_item(proceed_button)
                
                # Set up the individual dropdown callbacks
                upgrade_type_select.callback = upgrade_type_callback
                disabled_select.callback = disabled_callback
                repeatable_select.callback = repeatable_callback
                
                await interaction.response.send_message(tmpl.shop_please_select_boolean_options, view=view, ephemeral=True)
            else:
                shop_upgrade_ = session.query(ShopUpgrade).filter(ShopUpgrade.id == int(target)).first()
                # we need an embed with the shop upgrade's data, a rename button, a delete button, and edit fields
                def ui_factory(shop_upgrade: ShopUpgrade) -> tuple[ui.View, Embed]:
                    nonlocal target
                    view = ui.View()
                    embed = Embed(title=tmpl.shop_upgrade_title.format(name=shop_upgrade.name))
                    embed.add_field(name="Type", value=shop_upgrade.type)
                    embed.add_field(name="Cost", value=str(shop_upgrade.cost))
                    embed.add_field(name="Refit Target", value=shop_upgrade.refit_target or "None")
                    embed.add_field(name="Required Upgrade ID", value=str(shop_upgrade.required_upgrade_id) if shop_upgrade.required_upgrade_id else "None")
                    embed.add_field(name="Disabled", value="Yes" if shop_upgrade.disabled else "No")
                    embed.add_field(name="Repeatable", value="Yes" if shop_upgrade.repeatable else "No")
                    
                    # Get compatible unit types
                    compatible_unit_types = [assoc.unit_type for assoc in shop_upgrade.unit_types]
                    embed.add_field(name="Compatible Unit Types", value="\n".join(compatible_unit_types) if compatible_unit_types else "None", inline=False)
                    
                    rename_button = ui.Button(label=tmpl.shop_rename_button, style=ButtonStyle.primary)
                    delete_button = ui.Button(label=tmpl.shop_delete_button, style=ButtonStyle.danger)
                    edit_button = ui.Button(label="Edit", style=ButtonStyle.secondary)
                    view.add_item(rename_button)
                    view.add_item(delete_button)
                    view.add_item(edit_button)
                    
                    shop_upgrade_id_ = shop_upgrade.id # we can't use closure scoped instances, so we need to make a closure scoped PK of the instance instead
                    
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def rename_button_callback(interaction: Interaction, session:Session):
                        # Create modal for new name
                        modal = ui.Modal(title=tmpl.shop_edit_shop_upgrade_modal_title)
                        shop_upgrade_ = session.merge(shop_upgrade)
                        new_name_input = ui.TextInput(
                            label=tmpl.shop_new_name_label,
                            placeholder=tmpl.shop_new_name_placeholder,
                            default=shop_upgrade_.name,
                            min_length=1,
                            max_length=30
                        )
                        modal.add_item(new_name_input)
                        
                        @check
                        @error_reporting(True)
                        @uses_db(CustomClient().sessionmaker)
                        async def modal_submit(interaction: Interaction, session: Session):
                            nonlocal target
                            new_name = new_name_input.value.strip()
                            
                            # Get the current shop upgrade
                            shop_upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_id_).first()
                            
                            # Validate new name
                            if not new_name:
                                await interaction.response.send_message(tmpl.shop_name_cannot_be_empty, ephemeral=True)
                                return
                            
                            # Check if new name already exists
                            existing = session.query(ShopUpgrade).filter(ShopUpgrade.name == new_name).first()
                            if existing:
                                await interaction.response.send_message(tmpl.shop_upgrade_already_exists.format(name=new_name), ephemeral=True)
                                return
                            
                            logger.info(f"Starting rename operation: '{shop_upgrade.name}' -> '{new_name}'")
                            
                            # Update the shop upgrade name
                            shop_upgrade.name = new_name
                            logger.info(f"Renamed ShopUpgrade: '{shop_upgrade.name}' -> '{new_name}'")
                            
                            # Commit the change
                            session.commit()
                            logger.info(f"Successfully completed rename operation: '{shop_upgrade.name}' -> '{new_name}'")
                            
                            # Update the target variable for subsequent operations
                            target = str(shop_upgrade.id)
                            
                            await interaction.response.send_message(tmpl.shop_upgrade_renamed.format(old=shop_upgrade.name, new=new_name), ephemeral=True)
                            
                            # Refresh the UI with the new name
                            updated_shop_upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade.id).first()
                            new_view, new_embed = ui_factory(updated_shop_upgrade)
                            await message_manager.update_message(content=tmpl.shop_please_select_options_to_edit, view=new_view, embed=new_embed)
                        
                        modal.on_submit = modal_submit
                        await interaction.response.send_modal(modal)
                    
                    rename_button.callback = rename_button_callback
                    
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def delete_button_callback(interaction: Interaction, session: Session):
                        shop_upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_id_).first()
                        if shop_upgrade.player_upgrades:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_player_upgrades, ephemeral=True)
                            return
                        if shop_upgrade.unit_types:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_unit_type_associations, ephemeral=True)
                            return
                        session.delete(shop_upgrade)
                        session.commit()
                        await interaction.response.send_message(tmpl.shop_upgrade_deleted, ephemeral=True)
                        await message_manager.delete_message()
                    
                    delete_button.callback = delete_button_callback
                    
                    @check
                    @error_reporting(True)
                    async def edit_button_callback(interaction: Interaction):
                        # Create view with dropdowns for editing
                        shop_upgrade_ = session.merge(shop_upgrade)
                        
                        # Get current values
                        compatible_unit_types = [assoc.unit_type for assoc in shop_upgrade_.unit_types]
                        unit_types_text = "\n".join(compatible_unit_types)
                        
                        # Get all upgrade types for dropdown
                        upgrade_types = session.query(UpgradeType).all()
                        
                        view = ui.View()
                        
                        # UpgradeType dropdown with current value selected
                        upgrade_type_options = [SelectOption(label=ut.name, value=ut.name) for ut in upgrade_types]
                        upgrade_type_select = ui.Select(placeholder=tmpl.shop_select_upgrade_type_placeholder, options=upgrade_type_options)
                        # Set the current value as default
                        for option in upgrade_type_select.options:
                            if option.value == shop_upgrade_.type:
                                option.default = True
                                break
                        
                        disabled_select = ui.Select(placeholder=tmpl.shop_disabled_placeholder, options=[
                            SelectOption(label="Disabled: No", value="n", default=not shop_upgrade_.disabled),
                            SelectOption(label="Disabled: Yes", value="y", default=shop_upgrade_.disabled)
                        ])
                        repeatable_select = ui.Select(placeholder=tmpl.shop_repeatable_placeholder, options=[
                            SelectOption(label="Repeatable: No", value="n", default=not shop_upgrade_.repeatable),
                            SelectOption(label="Repeatable: Yes", value="y", default=shop_upgrade_.repeatable)
                        ])
                        
                        view.add_item(upgrade_type_select)
                        view.add_item(disabled_select)
                        view.add_item(repeatable_select)
                        
                        # Store the selected values
                        selected_values = {
                            "upgrade_type": shop_upgrade_.type,
                            "disabled": shop_upgrade_.disabled,
                            "repeatable": shop_upgrade_.repeatable,
                            "unit_types_text": unit_types_text
                        }
                        
                        @check
                        @error_reporting(True)
                        async def upgrade_type_callback(interaction: Interaction):
                            selected_values["upgrade_type"] = upgrade_type_select.values[0] if upgrade_type_select.values else shop_upgrade_.type
                            await interaction.response.defer(thinking=False, ephemeral=True)
                            await message_manager.update_message(content=tmpl.shop_upgrade_type_status.format(type=selected_values['upgrade_type']), view=view)
                        
                        @check
                        @error_reporting(True)
                        async def disabled_callback(interaction: Interaction):
                            selected_values["disabled"] = disabled_select.values[0] == "y" if disabled_select.values else shop_upgrade_.disabled
                            await interaction.response.defer(thinking=False, ephemeral=True)
                            await message_manager.update_message(content=tmpl.shop_disabled_status.format(status='Yes' if selected_values['disabled'] else 'No'), view=view)
                        
                        @check
                        @error_reporting(True)
                        async def repeatable_callback(interaction: Interaction):
                            selected_values["repeatable"] = repeatable_select.values[0] == "y" if repeatable_select.values else shop_upgrade_.repeatable
                            await interaction.response.defer(thinking=False, ephemeral=True)
                            await message_manager.update_message(content=tmpl.shop_repeatable_status.format(status='Yes' if selected_values['repeatable'] else 'No'), view=view)
                        
                        # Add a button to proceed to modal when all selections are made
                        proceed_button = ui.Button(label=tmpl.shop_proceed_to_details_button, style=ButtonStyle.primary)
                        
                        @check
                        @error_reporting(True)
                        async def proceed_callback(interaction: Interaction):
                            if not selected_values["upgrade_type"]:
                                await interaction.response.send_message(tmpl.shop_please_select_upgrade_type, ephemeral=True)
                                return
                            
                            # Now show the modal with the remaining fields
                            modal = ui.Modal(title=tmpl.shop_edit_shop_upgrade_modal_title)
                            name_input = ui.TextInput(label=tmpl.shop_upgrade_name_label, placeholder=tmpl.shop_upgrade_name_placeholder, default=shop_upgrade_.name, min_length=1, max_length=30)
                            cost_input = ui.TextInput(label=tmpl.shop_upgrade_cost_label, placeholder=tmpl.shop_cost_placeholder, default=str(shop_upgrade_.cost), min_length=1, max_length=10)
                            refit_target_input = ui.TextInput(label=tmpl.shop_refit_target_label, placeholder=tmpl.shop_refit_target_optional_placeholder, default=shop_upgrade_.refit_target or "", max_length=15, required=False)
                            required_upgrade_id_input = ui.TextInput(label="Required Upgrade ID", placeholder=tmpl.shop_required_upgrade_id_placeholder, default=str(shop_upgrade_.required_upgrade_id) if shop_upgrade_.required_upgrade_id else "", max_length=10, required=False)
                            unit_types_input = ui.TextInput(label="Compatible Unit Types", placeholder=tmpl.shop_compatible_unit_types_placeholder, default=selected_values["unit_types_text"], style=TextStyle.paragraph, required=False)
                            
                            modal.add_item(name_input)
                            modal.add_item(cost_input)
                            modal.add_item(refit_target_input)
                            modal.add_item(required_upgrade_id_input)
                            modal.add_item(unit_types_input)
                            
                            @check
                            @error_reporting(True)
                            @uses_db(CustomClient().sessionmaker)
                            async def modal_submit(interaction: Interaction, session: Session):
                                shop_upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_id_).first()
                                
                                name = name_input.value.strip()
                                cost = int(cost_input.value.strip())
                                refit_target = refit_target_input.value.strip().upper() if refit_target_input.value.strip() else None
                                required_upgrade_id = int(required_upgrade_id_input.value.strip()) if required_upgrade_id_input.value.strip() else None
                                unit_types_text = unit_types_input.value.strip()
                                
                                # Parse unit types from newline-separated text
                                new_compatible_unit_types = [ut.strip().upper() for ut in unit_types_text.split('\n') if ut.strip()] if unit_types_text else []
                                
                                # Update shop upgrade fields
                                shop_upgrade.name = name
                                shop_upgrade.type = selected_values["upgrade_type"]
                                shop_upgrade.cost = cost
                                shop_upgrade.refit_target = refit_target
                                shop_upgrade.required_upgrade_id = required_upgrade_id
                                shop_upgrade.disabled = selected_values["disabled"]
                                shop_upgrade.repeatable = selected_values["repeatable"]
                                
                                # Update unit type associations
                                # Remove existing associations
                                for assoc in shop_upgrade.unit_types:
                                    session.delete(assoc)
                                
                                # Add new associations
                                for unit_type_name in new_compatible_unit_types:
                                    association = ShopUpgradeUnitTypes(
                                        shop_upgrade_id=shop_upgrade.id,
                                        unit_type=unit_type_name
                                    )
                                    session.add(association)
                                
                                session.commit()
                                await interaction.response.defer(thinking=False, ephemeral=True)
                                await message_manager.update_message(content=tmpl.shop_upgrade_updated, view=ui.View())
                            
                            modal.on_submit = modal_submit
                            await interaction.response.send_modal(modal)
                        
                        proceed_button.callback = proceed_callback
                        view.add_item(proceed_button)
                        
                        # Set up the individual dropdown callbacks
                        upgrade_type_select.callback = upgrade_type_callback
                        disabled_select.callback = disabled_callback
                        repeatable_select.callback = repeatable_callback
                        
                        await interaction.response.send_message("Please select the options to edit, then proceed to details", view=view, ephemeral=True)
                        
                        # Refresh the UI
                        updated_shop_upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_.id).first()
                        new_view, new_embed = ui_factory(updated_shop_upgrade)
                        await message_manager.update_message(content="Please set up the shop upgrade", view=new_view, embed=new_embed)
                        
                    
                    edit_button.callback = edit_button_callback
                    
                    # we need to check if the shop upgrade is currently a Parent, and if so, we disable the delete button and add a warning to the embed
                    if shop_upgrade.player_upgrades:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a shop upgrade that has player upgrades assigned to it", inline=False)
                    if shop_upgrade.unit_types:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a shop upgrade that has unit type associations assigned to it", inline=False)
                    
                    return view, embed
                
                view, embed = ui_factory(shop_upgrade_)
                await message_manager.update_message(content="Please set up the shop upgrade", view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
        
        select.callback = select_callback
        await interaction.response.defer(thinking=False, ephemeral=True)
        await message_manager.update_message(content=tmpl.shop_please_select_unit_type, view=view)
    



bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.triage("Setting up Shop cog")
    await bot.add_cog(Shop(bot))

async def teardown():
    logger.triage("Tearing down Shop cog")
    bot.remove_cog(Shop.__name__) # remove_cog takes a string, not a class
