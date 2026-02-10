from logging import getLogger
from typing import Callable

from discord import Interaction, TextStyle, app_commands as ac, ui, SelectOption, ButtonStyle, Embed
from discord.ext.commands import GroupCog
from sqlalchemy.orm import Session
import templates as tmpl

from customclient import CustomClient
from MessageManager import MessageManager
from models import Player, Unit, UnitStatus, ShopUpgrade, ShopUpgradeUnitTypes, PlayerUpgrade, UnitType, UpgradeType
from utils import uses_db, Paginator, error_reporting

logger = getLogger(__name__)

class Shop(GroupCog, description="View and purchase upgrades for units."):
    """
    Cog for the shop slash command: view and purchase upgrades for units.
    Uses paginated views and MessageManager for the shop interface.
    """

    def __init__(self, bot: CustomClient):
        """Store a reference to the bot instance."""

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
            """
            Callback when the user clicks the button to return to the main
            shop home view. Rebuilds and sends the home message.
            """

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

            @error_reporting(False)
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
        if not _unit:
            logger.error(f"Unit {unit_id} not found")
            raise ValueError(f"Unit {unit_id} not found")
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
            select.disabled = False
            select.options.clear()

            using_unit_req = current_unit_req > 0

            currency = current_unit_req if using_unit_req else current_rec_points

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

        if not select.options:
            logger.error(f"No options found for select menu for unit {unit_name}")
            select.add_option(label="There's nothing here, You might not be allowed to buy the upgrades that would have been on this page", value="0")
            select.disabled = True

        # Add the main upgrade selection dropdown
        view.add_item(select)

        # Add next page button if there are more pages
        if paginator.has_next():
            next_button.disabled = False

            @error_reporting(False)
            @uses_db(CustomClient().sessionmaker)
            async def next_button_callback(interaction: Interaction, session: Session):
                """
                Callback when the user clicks the next-page button. Loads
                fresh data and sends the next page of upgrades.
                """

                logger.debug(f"Next button callback triggered by user {interaction.user.global_name}")

                # Get fresh data from database
                unit_name, unit_req = session.query(Unit.name, Unit.unit_req).filter(Unit.id == unit_id).first()
                logger.debug(f"Retrieved unit data: name={unit_name}, unit_req={unit_req}")

                rec_points = session.query(Player.rec_points).filter(Player.id == player_id).scalar()
                logger.debug(f"Retrieved player rec_points: {rec_points}")

                logger.triage(f"Navigating to next page of upgrades for unit {unit_name}")
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for next page navigation for unit {unit_name}")

                # Update page and repopulate options
                nonlocal page, select, previous_button, next_button
                old_page = page
                page = paginator.next()
                logger.debug(f"Page navigation: {old_page} -> {page}")

                currency = populate_select_options(page, unit_req, rec_points)
                logger.debug(f"Populated select options with currency: {currency}")

                # Update button states based on pagination
                if previous_button:
                    previous_button.disabled = not paginator.has_previous()
                    logger.debug(f"Previous button disabled: {previous_button.disabled}")
                next_button.disabled = not paginator.has_next()
                logger.debug(f"Next button disabled: {next_button.disabled}")

                logger.debug("Updating message with new view")
                await message_manager.update_message(view=view)
                logger.debug("Message update completed")

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

                # if original_type is None, set it to the current unit type, if it is not None, add an upgrade of the type SPECIAL with the name of the current unit type
                if _unit.original_type is None:
                    _unit.original_type = _unit.unit_type
                else:
                    new_upgrade = PlayerUpgrade(
                        unit_id=_unit.id,
                        name=_unit.unit_type,
                        type="SPECIAL",
                        original_price=0,
                        non_transferable=True,
                        shop_upgrade_id=None
                    )
                    session.add(new_upgrade)

                _unit.unit_type = refit_target
                _unit.unit_req = upgrade.target_type_info.unit_req
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
                embed.description = tmpl.you_have_bought_refit.format(refit_target=refit_target, refit_cost=refit_cost) + (tmpl.refit_unit_req.format(unit_req=_unit.unit_req) if _unit.unit_req > 0 else "")
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


async def setup(_bot: CustomClient):
    logger.triage("Setting up Shop cog")
    await _bot.add_cog(Shop(_bot))


async def teardown(_bot: CustomClient):
    logger.triage("Tearing down Shop cog")
    _bot.remove_cog(Shop.__name__)  # remove_cog takes a string, not a class
