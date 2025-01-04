from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, SelectOption, ButtonStyle, Embed
from models import Player, Unit, UnitStatus, UpgradeType, ShopUpgrade, ShopUpgradeUnitTypes, PlayerUpgrade
from customclient import CustomClient
from utils import uses_db, string_to_list, Paginator
from sqlalchemy.orm import Session
from sqlalchemy import case
from MessageManager import MessageManager
logger = getLogger(__name__)
async def is_mod(interaction: Interaction):
    """
    Check if the user is a moderator with the necessary role.
    """
    valid = any(interaction.user.get_role(role) for role in CustomClient().mod_roles)
    if not valid:
        logger.warning(f"{interaction.user.name} tried to use shop admin commands")
    return valid

class Shop(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
    
    @ac.command(name="open", description="View the shop")
    @uses_db(CustomClient().sessionmaker)
    async def shop(self, interaction: Interaction, session: Session):
        _player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not _player:
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return

        # Create the MessageManager
        message_manager = MessageManager(interaction)  # You can customize the embed type if needed

        view, embed = await self.shop_home_view_factory(_player.id, message_manager)

        # Send the initial message
        await message_manager.send_message(view=view, embed=embed, ephemeral=CustomClient().use_ephemeral)

    @uses_db(CustomClient().sessionmaker)
    async def shop_home_view_factory(self, player_id: int, message_manager: MessageManager, session: Session):
        view = ui.View()
        embed = Embed(title="Shop", color=0xc06335)
        _player = session.query(Player).filter(Player.id == player_id).first()

        # Get the list of units for this player
        units = session.query(Unit).filter(Unit.player_id == _player.id).all()
        
        # Prepare options for the Select menu
        if not units:
            select_options = [SelectOption(label="Please Create a Unit before using the Shop", value="no_units", default=True)]
        else:
            select_options = [SelectOption(label=unit.name, value=str(unit.id)) for unit in units]
        
        # Create the Select menu
        select = ui.Select(placeholder="Select a unit to buy upgrades for", options=select_options, disabled=not units)

        # Create the BP to RP button
        bonus_button = ui.Button(label="Convert 10 BP to 1 RP", style=ButtonStyle.success, disabled=_player.bonus_pay < 10)

        @uses_db(CustomClient().sessionmaker)
        async def bonus_button_callback(interaction: Interaction, session: Session):
            _player = session.query(Player).filter(Player.id == player_id).first()
            if _player.bonus_pay < 10:
                bonus_button.disabled = True
                logger.warning(f"Invalid state for Bonus Button in shop home view")
                await message_manager.update_message(content="You don't have enough bonus pay to convert")
                return
            _player.bonus_pay -= 10
            _player.rec_points += 1
            bonus_button.disabled = _player.bonus_pay < 10
            await message_manager.update_message()  # Update the message manager with the new state
            await interaction.response.defer(thinking=False, ephemeral=True)
            
        bonus_button.callback = bonus_button_callback

        @uses_db(CustomClient().sessionmaker)
        async def select_callback(interaction: Interaction, session: Session):
            _player = session.query(Player).filter(Player.id == player_id).first()
            selected_unit_id = int(select.values[0])
            _unit = session.query(Unit).filter(Unit.id == selected_unit_id).first()
            logger.info(f"Selected unit: {_unit.name}")

            if not _unit:
                embed.description = "That unit doesn't exist"
                logger.warning(f"Invalid state for Select Callback in shop home view")
                return view, embed

            # Generate the unit view based on its status
            unit_view, unit_embed = await self.shop_unit_view_factory(_unit.id, _player.id, message_manager)
            
            await message_manager.update_message(embed=unit_embed, view=unit_view)  # Update the embed in the MessageManager
            await interaction.response.defer(thinking=False, ephemeral=True)

        select.callback = select_callback

        view.add_item(select)
        view.add_item(bonus_button)
        return view, embed

    @uses_db(CustomClient().sessionmaker)
    async def shop_unit_view_factory(self, unit_id: int, player_id: int, message_manager: MessageManager, session: Session):
        _player = session.query(Player).filter(Player.id == player_id).first()
        _unit = session.query(Unit).filter(Unit.id == unit_id).first()
        logger.info(f"Creating shop view for unit: {_unit.name} with status: {_unit.status}")
        view = ui.View()
        embed = Embed(title=f"Unit: {_unit.name}", color=0xc06335)
        
        # allways add a leave button
        leave_button = ui.Button(label="Back to Home", style=ButtonStyle.danger)
        @uses_db(CustomClient().sessionmaker)
        async def leave_button_callback(interaction: Interaction, session: Session):
            _player = session.query(Player).filter(Player.id == player_id).first()
            view, embed = await self.shop_home_view_factory(_player.id, message_manager)
            await message_manager.update_message(view=view, embed=embed)
            await interaction.response.defer(thinking=False, ephemeral=True)
        leave_button.callback = leave_button_callback
        view.add_item(leave_button)

        if _unit.unit_type == "STOCKPILE":
            logger.info(f"Unit is stockpile, adding no buttons at all")
            embed.description = "You can't buy upgrades for a stockpile"
            return view, embed

        if _unit.status.name == "PROPOSED":
            logger.info(f"Unit is proposed, checking requisition points")
            buy_button = ui.Button(label="Buy Unit (-1 Req)", style=ButtonStyle.success, disabled=_player.rec_points < 1)
            
            @uses_db(CustomClient().sessionmaker)
            async def buy_button_callback(interaction: Interaction, session: Session):
                _player = session.query(Player).filter(Player.id == player_id).first()
                _unit = session.query(Unit).filter(Unit.id == unit_id).first()
                logger.info(f"Buying unit {_unit.name}")
                if _player.rec_points < 1:
                    embed.description = "You don't have enough requisition points to buy this unit"
                    logger.warning(f"Invalid state for Buy Button in shop unit view")
                    await message_manager.update_message()
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    return
                _unit.status = UnitStatus.INACTIVE
                _player.rec_points -= 1
                session.commit()
                view, embed = await self.shop_unit_view_factory(_unit.id, _player.id, message_manager) # recurse
                await message_manager.update_message(view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
            buy_button.callback = buy_button_callback
            view.add_item(buy_button)
            return view, embed

        elif _unit.status.name in {"MIA", "KIA"} or _unit.active:
            embed.description = "You can't buy upgrades for an Active or MIA/KIA unit"
            return view, embed

        elif _unit.status.name == "INACTIVE":
            logger.info(f"Unit is inactive, adding upgrade options")
            return await self.shop_inactive_view_factory(_unit.id, _player.id, message_manager, embed, view)
        
        logger.warning(f"Invalid end state for Shop Unit View")
        return view, embed

    @uses_db(CustomClient().sessionmaker)
    async def shop_inactive_view_factory(self, unit_id: int, player_id: int, message_manager: MessageManager, embed: Embed, view: ui.View, session: Session):
        upgrades = session.query(ShopUpgrade).order_by(case((ShopUpgrade.type == "REFIT", 0), else_=1)).all()
        _player = session.query(Player).filter(Player.id == player_id).first()
        _unit = session.query(Unit).filter(Unit.id == unit_id).first()

        # we need to filter the upgrades based on the unit types, but we cannot do it directly in the query
        compatible_upgrades = []
        for upgrade in upgrades:
            for unit_type in upgrade.unit_types:
                if unit_type.unit_type in _unit.unit_type:
                    compatible_upgrades.append(upgrade)
        if not compatible_upgrades:
            embed.description = "No upgrades are available for this unit"
            embed.color = 0xff0000
            return view, embed
        paginator = Paginator(compatible_upgrades, 25)
        page = paginator.current()
        select = ui.Select(placeholder="Select an upgrade to buy")
        button_template = "{type} {insufficient} {name} - {cost} RP"
        for upgrade in page:
            if upgrade.disabled:
                continue
            insufficient = "❌" if upgrade.cost > _player.rec_points else ""
            utype = "🔧" if upgrade.type == UpgradeType.REFIT else "⚙️"
            select.add_option(label=button_template.format(type=utype, insufficient=insufficient, name=upgrade.name, cost=upgrade.cost), value=str(upgrade.id))
        if paginator.has_previous():
            previous_button = ui.Button(label="Previous", style=ButtonStyle.secondary)
            # TODO: actually implement the previous button
            view.add_item(previous_button)
        view.add_item(select)
        if paginator.has_next():
            next_button = ui.Button(label="Next", style=ButtonStyle.secondary)
            # TODO: actually implement the next button
            view.add_item(next_button)
        embed.description = f"Please select an upgrade to buy, you have {_player.rec_points} requisition points"

        async def select_callback(interaction: Interaction):
            nonlocal embed
            upgrade_id = int(select.values[0])
            logger.debug(f"Selected upgrade ID: {upgrade_id}")

            upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == upgrade_id).first()
            if not upgrade:
                logger.error(f"Upgrade with ID {upgrade_id} not found.")
                embed.description = "Upgrade not found."
                embed.color = 0xff0000
                await message_manager.update_message()
                await interaction.response.defer(thinking=False, ephemeral=True)
                return

            _player = session.query(Player).filter(Player.id == player_id).first()
            _unit = session.query(Unit).filter(Unit.id == unit_id).first()
            logger.debug(f"Player: {_player}, Unit: {_unit}")

            if upgrade.cost > _player.rec_points:
                logger.warning(f"Player {interaction.user.name} does not have enough requisition points. Required: {upgrade.cost}, Available: {_player.rec_points}")
                embed.description = "You don't have enough requisition points to buy this upgrade"
                embed.color = 0xff0000
                await message_manager.update_message()
                await interaction.response.defer(thinking=False, ephemeral=True)
                return
            
            if upgrade.required_upgrade_id:
                required_upgrade = session.query(PlayerUpgrade).filter(PlayerUpgrade.unit_id == _unit.id, PlayerUpgrade.shop_upgrade_id == upgrade.required_upgrade_id).first()
                if not required_upgrade:
                    logger.warning(f"Player {interaction.user.name} does not have the required upgrade: {upgrade.required_upgrade_id}")
                    embed.description = "You don't have the required upgrade"
                    embed.color = 0xff0000
                    await message_manager.update_message()
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    return

            if upgrade.type == UpgradeType.UPGRADE:
                existing = session.query(PlayerUpgrade).filter(PlayerUpgrade.unit_id == _unit.id, PlayerUpgrade.shop_upgrade_id == upgrade.id).first()
                if existing and not upgrade.repeatable:
                    logger.warning(f"Player {interaction.user.name} already has this upgrade: {upgrade.name}")
                    embed.description = "You already have this upgrade"
                    embed.color = 0xff0000
                    await message_manager.update_message()
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    return

                new_upgrade = PlayerUpgrade(unit_id=_unit.id, shop_upgrade_id=upgrade.id, type=upgrade.type, name=upgrade.name, original_price=upgrade.cost)
                session.add(new_upgrade)
                logger.info(f"Player {interaction.user.name} bought upgrade: {upgrade.name} for {upgrade.cost} Req")
                upgrade_name = upgrade.name
                upgrade_cost = upgrade.cost
                session.commit()
                view, embed = await self.shop_unit_view_factory(_unit.id, _player.id, message_manager)
                embed.description = f"You have bought {upgrade_name} for {upgrade_cost} Req"
                embed.color = 0x00ff00
                await message_manager.update_message(view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)

            elif upgrade.type == UpgradeType.REFIT:
                refit_target = upgrade.refit_target
                refit_cost = upgrade.cost
                current_upgrades = _unit.upgrades
                shop_upgrades = [upgrade.shop_upgrade_id for upgrade in current_upgrades]
                shop_upgrades = session.query(ShopUpgrade).filter(ShopUpgrade.id.in_(shop_upgrades)).all()
                incompatible_upgrades = []
                logger.debug(f"Current upgrades: {current_upgrades}, Shop upgrades: {shop_upgrades}")

                for upgrade in shop_upgrades:
                    compatible = False
                    for ut in upgrade.unit_types:
                        if ut.unit_type == refit_target:
                            compatible = True
                            break
                    if not compatible:
                        incompatible_upgrades.append(upgrade.id)

                stockpile = session.query(Unit).filter(Unit.player_id == _player.id, Unit.unit_type == "STOCKPILE").first()
                if not stockpile:
                    logger.warning(f"Player {interaction.user.name} does not have a stockpile unit.")
                    await interaction.response.send_message("You don't have a stockpile unit", ephemeral=True)
                    return

                for upgrade in current_upgrades:
                    if upgrade.shop_upgrade_id in incompatible_upgrades:
                        upgrade.unit_id = stockpile.id

                _unit.unit_type = refit_target
                session.commit()
                view, embed = await self.shop_unit_view_factory(_unit.id, _player.id, message_manager)
                embed.description = f"You have bought a refit to {refit_target} for {refit_cost} Req"
                embed.color = 0x00ff00
                await message_manager.update_message(view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
        select.callback = select_callback
        return view, embed
    
    @ac.command(name="replace_stockpile", description="Create a new stockpile unit if you don't have one")
    @uses_db(CustomClient().sessionmaker)
    async def replace_stockpile(self, interaction: Interaction, session: Session):
        _player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not _player:
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        stockpile = session.query(Unit).filter(Unit.player_id == _player.id, Unit.unit_type == "STOCKPILE").first()
        if stockpile:
            await interaction.response.send_message("You already have a stockpile unit", ephemeral=self.bot.use_ephemeral)
            return
        new_stockpile = Unit(name="Stockpile", player_id=_player.id, status=UnitStatus.INACTIVE, unit_type="STOCKPILE")
        session.add(new_stockpile)
        await interaction.response.send_message("You have created a new stockpile unit", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="add_shop_upgrade", description="Add a shop upgrade")
    @ac.check(is_mod)
    async def add_shop_upgrade(self, interaction: Interaction):
        # we start with a modal for the name, description, cost, and unit types
        # then we do a view for the upgrade types, optional required upgrade
        modal = ui.Modal(title="Add Shop Upgrade")
        name = ui.TextInput(label="Name", placeholder="Enter the name of the upgrade")
        refit_target = ui.TextInput(label="Refit Target", placeholder="Enter the refit target of the upgrade, or leave blank if it's not a refit", required=False)
        cost = ui.TextInput(label="Cost", placeholder="Enter the cost of the upgrade")
        unit_types = ui.TextInput(label="Unit Types", placeholder="Enter the unit types the upgrade is available for, comma separated")
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
            await interaction.response.send_message("Please select an upgrade type", view=view, ephemeral=self.bot.use_ephemeral)
        modal.on_submit = modal_callback
        await interaction.response.send_modal(modal)

    async def shop_upgrade_view_factory(self, upgrade_details: dict):
        view = ui.View()
        # we need a select for the upgrade types, and a select for the required upgrade
        upgrade_types = ui.Select(placeholder="Select an upgrade type", options=[SelectOption(label=upgrade_type, value=upgrade_type) for upgrade_type in ["REFIT", "UPGRADE"]])
        async def upgrade_types_callback(interaction: Interaction):
            upgrade_details["type"] = interaction.data["values"][0]
            await interaction.response.defer()
        upgrade_types.callback = upgrade_types_callback
        view.add_item(upgrade_types)
        create_button = ui.Button(label="Create Upgrade", style=ButtonStyle.success)
        @uses_db(CustomClient().sessionmaker)
        async def create_button_callback(interaction: Interaction, session: Session):
            # create the upgrade
            upgrade = ShopUpgrade(name=upgrade_details["name"], refit_target=upgrade_details["refit_target"], cost=upgrade_details["cost"], type=upgrade_details["type"])
            session.add(upgrade)
            session.commit() # need to commit to get the id
            # create the unit types
            unit_types = string_to_list(upgrade_details["unit_types"])
            for unit_type in unit_types:
                unit_type = ShopUpgradeUnitTypes(shop_upgrade_id=upgrade.id, unit_type=unit_type)
                session.add(unit_type)
            await interaction.response.send_message("Upgrade created", ephemeral=self.bot.use_ephemeral)

        create_button.callback = create_button_callback
        view.add_item(create_button)
        return view

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Shop cog")
    await bot.add_cog(Shop(bot))

async def teardown():
    logger.info("Tearing down Shop cog")
    bot.remove_cog(Shop.__name__) # remove_cog takes a string, not a class