from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, SelectOption, ButtonStyle, Embed
from models import Player, Unit, UnitStatus, ShopUpgrade, ShopUpgradeUnitTypes, PlayerUpgrade
from customclient import CustomClient
from utils import uses_db, string_to_list, Paginator, error_reporting
from sqlalchemy.orm import Session, raiseload
from sqlalchemy import case
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
        logger.triage(f"Shop command initiated by user {interaction.user.name} (ID: {interaction.user.id})")
        player_id = session.query(Player.id).filter(Player.discord_id == interaction.user.id).scalar()
        if not player_id:
            logger.triage(f"User {interaction.user.name} attempted to access shop without a Meta Campaign company")
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=CustomClient().use_ephemeral)
            return

        logger.triage(f"Creating MessageManager for player {player_id}")
        message_manager = MessageManager(interaction)

        view, embed = await self.shop_home_view_factory(player_id, message_manager)
        logger.triage(f"Generated shop home view for player {player_id}")

        await message_manager.send_message(view=view, embed=embed, ephemeral=CustomClient().use_ephemeral)
        logger.triage(f"Shop interface sent to user {interaction.user.name}")

    @uses_db(CustomClient().sessionmaker)
    async def shop_home_view_factory(self, player_id: int, message_manager: MessageManager, session: Session):
        logger.triage(f"Creating shop home view for player {player_id}")
        view = ui.View()
        embed = Embed(title=tmpl.shop_title, color=0xc06335)
        rec_points, bonus_pay = session.query(Player.rec_points, Player.bonus_pay).filter(Player.id == player_id).first()

        units = session.query(Unit).filter(Unit.player_id == player_id).all()
        logger.triage(f"Found {len(units)} units for player {player_id}: {[unit.name for unit in units]}")
        
        if not units:
            logger.triage(f"No units found for player {player_id}, creating disabled select")
            select_options = [SelectOption(label=tmpl.shop_no_units_option, value="no_units", default=True)]
        else:
            logger.triage(f"Creating select options for {len(units)} units")
            select_options = [SelectOption(label=unit.name, value=str(unit.id)) for unit in units]
        
        select = ui.Select(placeholder=tmpl.shop_select_unit_placeholder, options=select_options, disabled=not units)
        logger.triage(f"Created unit select menu with {len(select_options)} options")

        bonus_button = ui.Button(label=tmpl.shop_convert_bp_button, style=ButtonStyle.success, disabled=bonus_pay < 10)
        logger.triage(f"Created BP to RP conversion button. Player has {bonus_pay} BP")

        @uses_db(CustomClient().sessionmaker)
        async def bonus_button_callback(interaction: Interaction, session: Session):
            logger.triage(f"BP to RP conversion initiated by player {player_id}")
            _player = session.query(Player).filter(Player.id == player_id).first()
            if _player.bonus_pay < 10:
                logger.triage(f"Invalid BP to RP conversion attempt - insufficient BP: {_player.bonus_pay}")
                bonus_button.disabled = True
                await message_manager.update_message(content=tmpl.not_enough_bonus_pay)
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for BP to RP conversion for player {player_id}")
                return
            _player.bonus_pay -= 10
            _player.rec_points += 1
            logger.triage(f"Converted 10 BP to 1 RP. New balance: {_player.bonus_pay} BP, {_player.rec_points} RP")
            bonus_button.disabled = _player.bonus_pay < 10
            session.commit()
            self.bot.queue.put_nowait((1, _player, 0))
            await message_manager.update_message()
            await interaction.response.defer(thinking=False, ephemeral=True)
            
        bonus_button.callback = bonus_button_callback

        @uses_db(CustomClient().sessionmaker)
        async def select_callback(interaction: Interaction, session: Session):
            selected_unit_id = int(select.values[0])
            unit_id, unit_name = session.query(Unit.id, Unit.name).filter(Unit.id == selected_unit_id).first()
            logger.triage(f"Unit selected: {unit_name} (ID: {unit_id})")

            if not unit_id:
                logger.triage(f"Selected unit {selected_unit_id} not found")
                embed.description = tmpl.unit_doesnt_exist
                return view, embed

            await interaction.response.defer(thinking=False, ephemeral=True)
            logger.triage(f"Deferred response for unit selection {unit_name}")
            logger.triage(f"Generating unit view for {unit_name}")
            unit_view, unit_embed = await self.shop_unit_view_factory(unit_id, player_id, message_manager)
            
            await message_manager.update_message(embed=unit_embed, view=unit_view)
            

        select.callback = select_callback

        view.add_item(select)
        view.add_item(bonus_button)
        embed.description = tmpl.select_unit_to_buy.format(rec_points=rec_points)
        embed.set_footer(text=tmpl.shop_footer)
        logger.triage(f"Completed shop home view creation for player {player_id}")
        return view, embed

    @uses_db(CustomClient().sessionmaker)
    async def shop_unit_view_factory(self, unit_id: int, player_id: int, message_manager: MessageManager, session: Session):
        logger.triage(f"Creating shop unit view for unit {unit_id} and player {player_id}")
        rec_points = session.query(Player.rec_points).filter(Player.id == player_id).scalar()
        unit_name, unit_type, unit_status, active = session.query(Unit.name, Unit.unit_type, Unit.status, Unit.active).filter(Unit.id == unit_id).first()
        logger.triage(f"Creating shop view for unit: {unit_name} with status: {unit_status}")
        view = ui.View()
        embed = Embed(title=tmpl.shop_unit_title.format(unit_name=unit_name), color=0xc06335)
        
        leave_button = ui.Button(label=tmpl.shop_back_to_home_button, style=ButtonStyle.danger)
        @uses_db(CustomClient().sessionmaker)
        async def leave_button_callback(interaction: Interaction, session: Session):
            logger.triage(f"Returning to shop home view for player {player_id}")
            _player = session.query(Player).filter(Player.id == player_id).first()
            view, embed = await self.shop_home_view_factory(_player.id, message_manager)
            await message_manager.update_message(view=view, embed=embed)
            await interaction.response.defer(thinking=False, ephemeral=True)
            logger.triage(f"Deferred response for returning to shop home view for player {player_id}")
        leave_button.callback = leave_button_callback
        view.add_item(leave_button)

        if unit_type == "STOCKPILE":
            logger.triage(f"Unit {unit_name} is stockpile, no upgrades available")
            embed.description = tmpl.cant_buy_upgrades_stockpile
            return view, embed

        if unit_status.name == "PROPOSED":
            logger.triage(f"Unit {unit_name} is proposed, checking requisition points")
            buy_button = ui.Button(label=tmpl.shop_buy_unit_button, style=ButtonStyle.success, disabled=rec_points < 1)
            
            @uses_db(CustomClient().sessionmaker)
            async def buy_button_callback(interaction: Interaction, session: Session):
                _player = session.query(Player).filter(Player.id == player_id).first()
                _unit = session.query(Unit).filter(Unit.id == unit_id).first()
                logger.triage(f"Buying unit {_unit.name}")
                if _player.rec_points < 1:
                    logger.triage(f"Player {interaction.user.name} attempted to buy unit without sufficient RP")
                    embed.description = tmpl.not_enough_req_points_unit
                    await message_manager.update_message()
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    return
                if _unit.type_info.free_upgrade_1:
                    logger.triage(f"Adding free upgrade 1: {_unit.type_info.free_upgrade_1_info.name}")
                    free_upgrade_1 = PlayerUpgrade(unit_id=_unit.id, name=_unit.type_info.free_upgrade_1_info.name, type=_unit.type_info.free_upgrade_1_info.type, original_price=0, non_transferable=True, shop_upgrade_id=_unit.type_info.free_upgrade_1)
                    session.add(free_upgrade_1)
                if _unit.type_info.free_upgrade_2:
                    logger.triage(f"Adding free upgrade 2: {_unit.type_info.free_upgrade_2_info.name}")
                    free_upgrade_2 = PlayerUpgrade(unit_id=_unit.id, name=_unit.type_info.free_upgrade_2_info.name, type=_unit.type_info.free_upgrade_2_info.type, original_price=0, non_transferable=True, shop_upgrade_id=_unit.type_info.free_upgrade_2)
                    session.add(free_upgrade_2)
                _unit.status = UnitStatus.INACTIVE
                _player.rec_points -= 1
                logger.triage(f"Unit {_unit.name} purchased. New RP balance: {_player.rec_points}")
                session.commit()
                self.bot.queue.put_nowait((1, _player, 0))
                view, embed = await self.shop_unit_view_factory(_unit.id, _player.id, message_manager)
                await message_manager.update_message(view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for unit purchase {_unit.name}")
            buy_button.callback = buy_button_callback
            view.add_item(buy_button)
            return view, embed

        elif unit_status.name in {"MIA", "KIA"} or active:
            logger.triage(f"Unit {unit_name} is {unit_status.name} or in a campaign, no upgrades available")
            embed.description = tmpl.cant_buy_upgrades_active
            return view, embed

        elif unit_status.name == "INACTIVE":
            logger.triage(f"Unit {unit_name} is inactive, generating upgrade options")
            return await self.shop_inactive_view_factory(unit_id, player_id, message_manager, embed, view)
        
        logger.triage(f"Invalid end state for Shop Unit View - unit {unit_name} has unexpected status: {unit_status}")
        return view, embed

    @uses_db(CustomClient().sessionmaker)
    async def shop_inactive_view_factory(self, unit_id: int, player_id: int, message_manager: MessageManager, embed: Embed, view: ui.View, session: Session):
        logger.triage(f"Creating inactive view for unit {unit_id} and player {player_id}")
        rec_points = session.query(Player.rec_points).filter(Player.id == player_id).scalar()
        _unit = session.query(Unit).filter(Unit.id == unit_id).first()
        logger.triage(f"Unit {_unit.name} has {_unit.unit_req} unit requisition")
        unit_req = _unit.unit_req
        unit_name = _unit.name
        available_upgrades = _unit.available_upgrades
        if not available_upgrades:
            logger.triage(f"No compatible upgrades found for unit type {_unit.unit_type}")
            embed.description = tmpl.no_upgrades_available
            embed.color = 0xff0000
            return view, embed
        logger.triage(f"Found {len(available_upgrades)} compatible upgrades for unit type {_unit.unit_type}")
        paginator = Paginator([upgrade.id for upgrade in available_upgrades], 25)
        page = paginator.current()
        select = ui.Select(placeholder=tmpl.shop_select_upgrade_placeholder)
        button_template = tmpl.shop_upgrade_button_template
        
        # Declare buttons before their callbacks
        previous_button = ui.Button(label=tmpl.shop_previous_button, style=ButtonStyle.secondary)
        previous_button.disabled = True
        next_button = ui.Button(label=tmpl.shop_next_button, style=ButtonStyle.secondary)
        next_button.disabled = True
        
        for upgrade in page:
            logger.triage(f"Processing upgrade ID {upgrade} for display")
            _upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == upgrade).first()
            logger.triage(f"Adding upgrade {_upgrade.name} of type {_upgrade.type} to select (current page)")
            if _upgrade.disabled:
                logger.triage(f"Skipping disabled upgrade {_upgrade.name}")
                continue
            if _upgrade.type == "REFIT":
                logger.triage(f"Upgrade is a Refit, checking if unit has unit requisition")
                if unit_req > 0:
                    logger.triage(f"Skipping refit upgrade {_upgrade.name} for unit {_unit.name} because it has unit requisition")
                    continue # we don't want to show refit upgrades if the unit has unit requisition
            insufficient = "❌" if _upgrade.cost > (unit_req if unit_req > 0 else rec_points) else ""
            utype = "🔧" if _upgrade.type == "REFIT" else "🚀" if _upgrade.type == "HULL" else "⚙️"
            select.add_option(label=button_template.format(type=utype, insufficient=insufficient, name=_upgrade.name, cost=_upgrade.cost), value=str(_upgrade.id))
        
        if paginator.has_previous():
            previous_button.disabled = False
            @uses_db(CustomClient().sessionmaker)
            async def previous_button_callback(interaction: Interaction, session: Session):
                unit_name, unit_req = session.query(Unit.name, Unit.unit_req).filter(Unit.id == unit_id).first()
                rec_points = session.query(Player.rec_points).filter(Player.id == player_id).scalar()
                logger.triage(f"Navigating to previous page of upgrades for unit {unit_name}")
                await interaction.response.defer(thinking=False, ephemeral=True)
                nonlocal page, select, previous_button, next_button
                page = paginator.previous()
                select.options.clear()
                for upgrade in page:
                    logger.triage(f"Processing upgrade ID {upgrade} for display")
                    _upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == upgrade).first()
                    logger.triage(f"Adding upgrade {_upgrade.name} of type {_upgrade.type} to select (previous page)")
                    if _upgrade.disabled:
                        logger.triage(f"Skipping disabled upgrade {_upgrade.name}")
                        continue
                    if _upgrade.type == "REFIT":
                        logger.triage(f"Upgrade is a Refit, checking if unit has unit requisition")
                        if unit_req > 0:
                            logger.triage(f"Skipping refit upgrade {_upgrade.name} for unit {unit_name} because it has unit requisition")
                            continue
                    insufficient = "❌" if _upgrade.cost > (unit_req if unit_req > 0 else rec_points) else ""
                    utype = "🔧" if _upgrade.type == "REFIT" else "🚀" if _upgrade.type == "HULL" else "⚙️"
                    select.add_option(label=button_template.format(type=utype, insufficient=insufficient, name=_upgrade.name, cost=_upgrade.cost), value=str(_upgrade.id))
                previous_button.disabled = not paginator.has_previous() # we don't need to check if previous_button is None, because we are in it's callback
                if next_button:
                    next_button.disabled = not paginator.has_next()
                await message_manager.update_message(embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for previous page navigation for unit {unit_name}")
            previous_button.callback = previous_button_callback
        view.add_item(previous_button)
        
        view.add_item(select)
        
        if paginator.has_next():
            next_button.disabled = False
            @uses_db(CustomClient().sessionmaker)
            async def next_button_callback(interaction: Interaction, session: Session):
                unit_name, unit_req = session.query(Unit.name, Unit.unit_req).filter(Unit.id == unit_id).first()
                rec_points = session.query(Player.rec_points).filter(Player.id == player_id).scalar()
                logger.triage(f"Navigating to next page of upgrades for unit {unit_name}")
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for next page navigation for unit {unit_name}")
                nonlocal page, select, previous_button, next_button
                page = paginator.next()
                select.options.clear()
                for upgrade in page:
                    logger.triage(f"Processing upgrade ID {upgrade} for display")
                    _upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == upgrade).first()
                    logger.triage(f"Adding upgrade {_upgrade.name} of type {_upgrade.type} to select (next page)")
                    if _upgrade.disabled:
                        logger.triage(f"Skipping disabled upgrade {_upgrade.name}")
                        continue
                    if _upgrade.type == "REFIT":
                        logger.triage(f"Upgrade is a Refit, checking if unit has unit requisition")
                        if unit_req > 0:
                            logger.triage(f"Skipping refit upgrade {_upgrade.name} for unit {unit_name} because it has unit requisition")
                            continue
                    insufficient = "❌" if _upgrade.cost > (unit_req if unit_req > 0 else rec_points) else ""
                    utype = "🔧" if _upgrade.type == "REFIT" else "🚀" if _upgrade.type == "HULL" else "⚙️"
                    select.add_option(label=button_template.format(type=utype, insufficient=insufficient, name=_upgrade.name, cost=_upgrade.cost), value=str(_upgrade.id))
                if previous_button:
                    previous_button.disabled = not paginator.has_previous()
                next_button.disabled = not paginator.has_next() # we don't need to check if next_button is None, because we are in it's callback
                await message_manager.update_message(view=view)
            next_button.callback = next_button_callback
        view.add_item(next_button)
        embed.description = tmpl.select_upgrade_to_buy.format(req_points=_unit.unit_req if _unit.unit_req > 0 else rec_points, req_type=f"unit {tmpl.MAIN_CURRENCY.lower()}" if _unit.unit_req > 0 else tmpl.MAIN_CURRENCY.lower())

        @error_reporting()
        @uses_db(CustomClient().sessionmaker)
        async def select_callback(interaction: Interaction, session: Session):
            nonlocal embed
            upgrade_id = int(select.values[0])
            logger.triage(f"Selected upgrade ID: {upgrade_id}")

            upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == upgrade_id).first()
            if not upgrade:
                logger.triage(f"Upgrade with ID {upgrade_id} not found")
                embed.description = tmpl.upgrade_not_found
                embed.color = 0xff0000
                await message_manager.update_message()
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for upgrade not found error for upgrade ID {upgrade_id}")
                return

            _player = session.query(Player).filter(Player.id == player_id).first()
            _unit = session.query(Unit).filter(Unit.id == unit_id).first()
            logger.triage(f"Processing upgrade purchase for player {_player.name} and unit {_unit.name}")

            if upgrade.cost > (_unit.unit_req if _unit.unit_req > 0 else _player.rec_points):
                logger.triage(f"Player {interaction.user.name} does not have enough requisition points. Required: {upgrade.cost}, Available: {_unit.unit_req if _unit.unit_req > 0 else _player.rec_points}")
                embed.description = tmpl.not_enough_req_points_upgrade
                embed.color = 0xff0000
                await message_manager.update_message()
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for insufficient RP error for upgrade {upgrade.name}")
                return
            
            if upgrade.required_upgrade_id:
                required_upgrade = session.query(PlayerUpgrade).filter(PlayerUpgrade.unit_id == _unit.id, PlayerUpgrade.shop_upgrade_id == upgrade.required_upgrade_id).first()
                if not required_upgrade:
                    logger.triage(f"Player {interaction.user.name} does not have the required upgrade: {upgrade.required_upgrade_id}")
                    embed.description = tmpl.dont_have_required_upgrade
                    embed.color = 0xff0000
                    await message_manager.update_message()
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    logger.triage(f"Deferred response for missing required upgrade error for upgrade {upgrade.name}")
                    return

            if upgrade.type in {"UPGRADE", "MECH_CHASSIS", "HULL"}:
                existing = session.query(PlayerUpgrade).filter(PlayerUpgrade.unit_id == _unit.id, PlayerUpgrade.shop_upgrade_id == upgrade.id).first()
                logger.triage(f"Checking if upgrade is repeatable: {upgrade.repeatable}")
                if existing and not upgrade.repeatable:
                    logger.triage(f"Player {interaction.user.name} already has this upgrade: {upgrade.name}")
                    embed.description = tmpl.already_have_upgrade
                    embed.color = 0xff0000
                    await message_manager.update_message()
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    logger.triage(f"Deferred response for duplicate upgrade error for upgrade {upgrade.name}")
                    return

                new_upgrade = PlayerUpgrade(unit_id=_unit.id, shop_upgrade_id=upgrade.id, type=upgrade.type, name=upgrade.name, original_price=upgrade.cost)
                session.add(new_upgrade)
                logger.triage(f"Player {interaction.user.name} bought upgrade: {upgrade.name} for {upgrade.cost} Req")
                upgrade_name = upgrade.name
                upgrade_cost = upgrade.cost
                if _unit.unit_req > 0:
                    _unit.unit_req -= upgrade_cost
                    new_upgrade.original_price = 0 # it's technically free, because unit_req is free req given to certain units
                else:
                    _player.rec_points -= upgrade_cost
                session.commit()
                self.bot.queue.put_nowait((1, _player, 0))
                view, embed = await self.shop_unit_view_factory(_unit.id, _player.id, message_manager)
                embed.description = tmpl.you_have_bought_upgrade.format(upgrade_name=upgrade_name, upgrade_cost=upgrade_cost)
                embed.color = 0x00ff00
                await message_manager.update_message(view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for successful upgrade purchase {upgrade_name}")

            elif upgrade.type == "REFIT":
                logger.triage(f"Starting refit purchase workflow for unit {_unit.name} to {upgrade.refit_target}")
                refit_target = upgrade.refit_target
                refit_cost = upgrade.cost
                current_upgrades: list[PlayerUpgrade] = _unit.upgrades
                logger.triage(f"Current upgrades for unit: {[upgrade.name for upgrade in current_upgrades]}")
                
                current_upgrade_set: set[ShopUpgrade] = {upgrade.shop_upgrade for upgrade in current_upgrades}
                compatible_upgrades: set[ShopUpgrade] = set(upgrade.target_type_info.compatible_upgrades)
                incompatible_upgrades = current_upgrade_set - compatible_upgrades
                logger.triage(f"Incompatible upgrades that will be moved to stockpile: {[upgrade.name for upgrade in incompatible_upgrades]}")

                stockpile = _player.stockpile
                if not stockpile:
                    logger.triage(f"Player {interaction.user.name} does not have a stockpile unit")
                    await interaction.response.send_message(tmpl.dont_have_stockpile, ephemeral=True)
                    return
                logger.triage(f"Found stockpile unit: {stockpile.name}")

                for _upgrade in current_upgrades:
                    if _upgrade.shop_upgrade in incompatible_upgrades:
                        logger.triage(f"Moving upgrade {_upgrade.name} to stockpile")
                        _upgrade.unit_id = stockpile.id

                logger.triage(f"Changing unit type from {_unit.unit_type} to {refit_target}")
                _unit.unit_type = refit_target
                _player.rec_points -= refit_cost
                logger.triage(f"Deducted {refit_cost} RP from player. New balance: {_player.rec_points}")
                
                if upgrade.target_type_info.free_upgrade_1:
                    logger.triage(f"Adding free upgrade 1: {upgrade.target_type_info.free_upgrade_1_info.name}")
                    free_upgrade_1 = PlayerUpgrade(unit_id=_unit.id, name=upgrade.target_type_info.free_upgrade_1_info.name, type=upgrade.target_type_info.free_upgrade_1_info.type, original_price=0, non_transferable=True, shop_upgrade_id=upgrade.target_type_info.free_upgrade_1)
                    session.add(free_upgrade_1)
                if upgrade.target_type_info.free_upgrade_2:
                    logger.triage(f"Adding free upgrade 2: {upgrade.target_type_info.free_upgrade_2_info.name}")
                    free_upgrade_2 = PlayerUpgrade(unit_id=_unit.id, name=upgrade.target_type_info.free_upgrade_2_info.name, type=upgrade.target_type_info.free_upgrade_2_info.type, original_price=0, non_transferable=True, shop_upgrade_id=upgrade.target_type_info.free_upgrade_2)
                    session.add(free_upgrade_2)

                session.commit()
                logger.triage("Committed changes to database")
                self.bot.queue.put_nowait((1, _player, 0))
                logger.triage("Added player update to queue")
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for refit purchase workflow for unit {_unit.name}")
                
                view, embed = await self.shop_unit_view_factory(_unit.id, _player.id, message_manager)
                embed.description = tmpl.you_have_bought_refit.format(refit_target=refit_target, refit_cost=refit_cost)
                embed.color = 0x00ff00
                await message_manager.update_message(view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
                logger.triage(f"Deferred response for successful refit purchase for unit {_unit.name}")
        select.callback = select_callback
        return view, embed
    
    @ac.command(name="replace_stockpile", description="Create a new stockpile unit if you don't have one")
    @uses_db(CustomClient().sessionmaker)
    async def replace_stockpile(self, interaction: Interaction, session: Session):
        _player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not _player:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=self.bot.use_ephemeral)
            return
        stockpile = session.query(Unit).filter(Unit.player_id == _player.id, Unit.unit_type == "STOCKPILE").first()
        if stockpile:
            await interaction.response.send_message(tmpl.already_have_stockpile, ephemeral=self.bot.use_ephemeral)
            return
        new_stockpile = Unit(name="Stockpile", player_id=_player.id, status=UnitStatus.INACTIVE, unit_type="STOCKPILE")
        session.add(new_stockpile)
        await interaction.response.send_message(tmpl.created_stockpile_unit, ephemeral=self.bot.use_ephemeral)

    @ac.command(name="add_shop_upgrade", description="Add a shop upgrade")
    @ac.check(is_mod)
    async def add_shop_upgrade(self, interaction: Interaction):
        # we start with a modal for the name, description, cost, and unit types
        # then we do a view for the upgrade types, optional required upgrade
        modal = ui.Modal(title=tmpl.shop_add_upgrade_modal_title)
        name = ui.TextInput(label=tmpl.shop_upgrade_name_label, placeholder=tmpl.shop_upgrade_name_placeholder)
        refit_target = ui.TextInput(label=tmpl.shop_refit_target_label, placeholder=tmpl.shop_refit_target_placeholder, required=False)
        cost = ui.TextInput(label=tmpl.shop_upgrade_cost_label, placeholder=tmpl.shop_upgrade_cost_placeholder)
        unit_types = ui.TextInput(label=tmpl.shop_unit_types_label, placeholder=tmpl.shop_unit_types_placeholder)
        modal.add_item(name)
        modal.add_item(refit_target)
        modal.add_item(cost)
        modal.add_item(unit_types)
        upgrade_details = {}
        async def modal_callback(interaction: Interaction):
            name = interaction.data["components"][0]["components"][0]["value"]
            refit_target = interaction.data["components"][1]["components"][0]["value"]
            cost = interaction.data["components"][2]["components"][0]["value"]
            unit_types = interaction.data["components"][3]["components"][0]["value"]
            upgrade_details = {
                "name": name,
                "refit_target": refit_target,
                "cost": cost,
                "unit_types": unit_types
            }
            view = await self.shop_upgrade_view_factory(upgrade_details)
            await interaction.response.send_message(tmpl.shop_select_upgrade_type_message, view=view, ephemeral=self.bot.use_ephemeral)
        modal.on_submit = modal_callback
        await interaction.response.send_modal(modal)

    async def shop_upgrade_view_factory(self, upgrade_details: dict):
        view = ui.View()
        # we need a select for the upgrade types, and a select for the required upgrade
        upgrade_types = ui.Select(placeholder=tmpl.shop_select_upgrade_type_placeholder, options=[SelectOption(label=upgrade_type, value=upgrade_type) for upgrade_type in ["REFIT", "UPGRADE"]])
        logger.triage("Created upgrade type select with options: REFIT, UPGRADE")
        async def upgrade_types_callback(interaction: Interaction):
            upgrade_details["type"] = interaction.data["values"][0]
            await interaction.response.defer()
        upgrade_types.callback = upgrade_types_callback
        view.add_item(upgrade_types)
        create_button = ui.Button(label=tmpl.shop_create_upgrade_button, style=ButtonStyle.success)
        @uses_db(CustomClient().sessionmaker)
        async def create_button_callback(interaction: Interaction, session: Session):
            # create the upgrade
            logger.triage(f"Creating new shop upgrade: {upgrade_details['name']}")
            upgrade = ShopUpgrade(name=upgrade_details["name"], refit_target=upgrade_details["refit_target"], cost=upgrade_details["cost"], type=upgrade_details["type"])
            session.add(upgrade)
            logger.triage("Committing to get upgrade ID")
            session.commit() # need to commit to get the id
            # create the unit types
            unit_types = string_to_list(upgrade_details["unit_types"])
            logger.triage(f"Processing {len(unit_types)} unit types for new upgrade")
            for unit_type in unit_types:
                logger.triage(f"Adding unit type {unit_type} to upgrade")
                unit_type = ShopUpgradeUnitTypes(shop_upgrade_id=upgrade.id, unit_type=unit_type)
                session.add(unit_type)
            logger.triage(f"Committing final changes for upgrade {upgrade_details['name']}")
            session.commit()
            await interaction.response.send_message(tmpl.upgrade_created, ephemeral=self.bot.use_ephemeral)

        create_button.callback = create_button_callback
        view.add_item(create_button)
        return view

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.triage("Setting up Shop cog")
    await bot.add_cog(Shop(bot))

async def teardown():
    logger.triage("Tearing down Shop cog")
    bot.remove_cog(Shop.__name__) # remove_cog takes a string, not a class
