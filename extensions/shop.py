from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, SelectOption, ButtonStyle
from models import Player, Unit, UnitStatus, UpgradeType, ShopUpgrade, ShopUpgradeUnitTypes
from customclient import CustomClient
from utils import uses_db, string_to_list
from sqlalchemy.orm import Session
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
        self.session = bot.session

    
    
    @ac.command(name="open", description="View the shop")
    async def shop(self, interaction: Interaction):
        player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return
        # get the list of units for this player, we will use this to create a Select to pick a unit to buy upgrades for
        units = self.session.query(Unit).filter(Unit.player_id == player.id).all()
        if not units:
            await interaction.response.send_message("You don't have any units, please create one first", ephemeral=CustomClient().use_ephemeral)
            return
        # create a Select to pick a unit to buy upgrades for
        select = ui.Select(placeholder="Select a unit to buy upgrades for", options=[SelectOption(label=unit.name, value=str(unit.id)) for unit in units])
        async def select_callback(interaction: Interaction):
            unit = self.session.query(Unit).filter(Unit.id == int(select.values[0])).first()
            player = self.session.query(Player).filter(Player.id == unit.player_id).first()
            logger.info(f"Selected unit: {unit.name}")
            view = await self.shop_view_factory(unit, player)
            await interaction.response.send_message(f"You have {player.rec_points} requisition points to spend", view=view, ephemeral=CustomClient().use_ephemeral)

        select.callback = select_callback

        bonus_button = ui.Button(label="Convert 10 BP to 1 RP", style=ButtonStyle.success, disabled=player.bonus_pay < 10)
        async def bonus_button_callback(interaction: Interaction):
            if player.bonus_pay < 10:
                await interaction.response.send_message("You don't have enough bonus pay to convert", ephemeral=CustomClient().use_ephemeral)
                return
            player.bonus_pay -= 10
            player.rec_points += 1
            self.session.commit()
            bonus_button.disabled = player.bonus_pay < 10
            await interaction.response.send_message("You have converted 10 BP to 1 RP", ephemeral=CustomClient().use_ephemeral)
        bonus_button.callback = bonus_button_callback

        view = ui.View()
        view.add_item(select)
        view.add_item(bonus_button)
        await interaction.response.send_message("Please select a unit to buy upgrades for", view=view, ephemeral=CustomClient().use_ephemeral)

    async def shop_view_factory(self, unit: Unit, player: Player):
        logger.info(f"Creating shop view for unit: {unit.name} with status: {unit.status}")
        view = ui.View()
        if unit.unit_type == "STOCKPILE":
            logger.info(f"Unit is stockpile, adding no buttons at all")
            return view
        # if the unit is PROPOSED, add a "Buy Unit" button, disable the button if the player doesn't have enough rec_points based on a mapping not yet defined
        if unit.status.name == "PROPOSED":
            logger.info(f"Unit is proposed, checking rec_points")
            buy_button = ui.Button(label="Buy Unit", style=ButtonStyle.success, disabled=player.rec_points < 1)
            async def buy_button_callback(interaction: Interaction):
                # set the unit status to INACTIVE
                logger.info(f"Buying unit {unit.name}")
                if player.rec_points < 1:
                    await interaction.response.send_message("You don't have enough requisition points to buy this unit", ephemeral=self.bot.use_ephemeral)
                    return
                if unit.status.name != "PROPOSED":
                    await interaction.response.send_message("Unit is not proposed, cannot buy", ephemeral=self.bot.use_ephemeral)
                    return
                unit.status = "INACTIVE"
                player.rec_points -= 1
                
                self.session.commit()
                await interaction.response.send_message(f"You have bought {unit.name}", ephemeral=self.bot.use_ephemeral)
                buy_button.disabled = True
                await interaction.edit_original_response(content=f"You have bought {unit.name}", view=view)
            buy_button.callback = buy_button_callback
            view.add_item(buy_button)
        elif unit.status.name in {"MIA", "KIA"}:
            logger.info(f"Unit is MIA or KIA, adding reform button")
            reform_button = ui.Button(label="Reform Unit", style=ButtonStyle.success, disabled=player.rec_points < 1)
            async def reform_button_callback(interaction: Interaction):
                logger.info(f"Reforming unit {unit.name}")
                if player.rec_points < 1:
                    await interaction.response.send_message("You don't have enough requisition points to reform this unit", ephemeral=self.bot.use_ephemeral)
                    return
                unit.status = "INACTIVE"
                player.rec_points -= 1
                self.session.commit()
                await interaction.response.send_message(f"You have reformed {unit.name}", ephemeral=self.bot.use_ephemeral)
            reform_button.callback = reform_button_callback
            view.add_item(reform_button)
        else:
            logger.info(f"Unit is not proposed, not adding buy button")
            nothing_to_buy = ui.Button(label="Nothing to buy", style=ButtonStyle.secondary, disabled=True)
            view.add_item(nothing_to_buy)
        return view
    
    @ac.command(name="replace_stockpile", description="Create a new stockpile unit if you don't have one")
    async def replace_stockpile(self, interaction: Interaction):
        player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        stockpile = self.session.query(Unit).filter(Unit.player_id == player.id, Unit.unit_type == "STOCKPILE").first()
        if stockpile:
            await interaction.response.send_message("You already have a stockpile unit", ephemeral=self.bot.use_ephemeral)
            return
        new_stockpile = Unit(name="Stockpile", player_id=player.id, status=UnitStatus.INACTIVE, unit_type="STOCKPILE")
        self.session.add(new_stockpile)
        self.session.commit()
        await interaction.response.send_message("You have created a new stockpile unit", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="add_shop_upgrade", description="Add a shop upgrade")
    @ac.check(is_mod)
    async def add_shop_upgrade(self, interaction: Interaction):
        # we start with a modal for the name, description, cost, and unit types
        # then we do a view for the upgrade types, optional required upgrade
        modal = ui.Modal(title="Add Shop Upgrade")
        name = ui.TextInput(label="Name", placeholder="Enter the name of the upgrade")
        description = ui.TextInput(label="Description", placeholder="Enter the description of the upgrade")
        cost = ui.TextInput(label="Cost", placeholder="Enter the cost of the upgrade")
        unit_types = ui.TextInput(label="Unit Types", placeholder="Enter the unit types the upgrade is available for, comma separated")
        modal.add_item(name)
        modal.add_item(description)
        modal.add_item(cost)
        modal.add_item(unit_types)
        upgrade_details = {}
        async def modal_callback(interaction: Interaction):
            name = interaction.data["components"][0]["components"][0]["value"]
            description = interaction.data["components"][1]["components"][0]["value"]
            cost = interaction.data["components"][2]["components"][0]["value"]
            unit_types = interaction.data["components"][3]["components"][0]["value"]
            upgrade_details = {
                "name": name,
                "description": description,
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
            upgrade = ShopUpgrade(name=upgrade_details["name"], description=upgrade_details["description"], cost=upgrade_details["cost"], type=upgrade_details["type"])
            self.session.add(upgrade)
            self.session.commit()
            # create the unit types
            unit_types = string_to_list(upgrade_details["unit_types"])
            for unit_type in unit_types:
                unit_type = ShopUpgradeUnitTypes(upgrade_id=upgrade.id, unit_type=unit_type)
                self.session.add(unit_type)
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