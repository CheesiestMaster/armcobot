from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, SelectOption, ButtonStyle
from models import Player, Unit
from customclient import CustomClient
logger = getLogger(__name__)

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
        # if the unit is PROPOSED, add a "Buy Unit" button, disable the button if the player doesn't have enough rec_points based on a mapping not yet defined
        if unit.status.name == "PROPOSED":
            logger.info(f"Unit is proposed, checking rec_points")
            buy_button = ui.Button(label="Buy Unit", style=ButtonStyle.success, disabled=player.rec_points < 1)
            async def buy_button_callback(interaction: Interaction):
                # set the unit status to INACTIVE
                logger.info(f"Buying unit {unit.name}")
                if player.rec_points < 1:
                    await interaction.response.send_message("You don't have enough requisition points to buy this unit", ephemeral=CustomClient().use_ephemeral)
                    return
                if unit.status.name != "PROPOSED":
                    await interaction.response.send_message("Unit is not proposed, cannot buy", ephemeral=CustomClient().use_ephemeral)
                    return
                unit.status = "INACTIVE"
                player.rec_points -= 1
                
                self.session.commit()
                await interaction.response.send_message(f"You have bought {unit.name}", ephemeral=CustomClient().use_ephemeral)
                buy_button.disabled = True
                await interaction.edit_original_response(content=f"You have bought {unit.name}", view=view)
            buy_button.callback = buy_button_callback
            view.add_item(buy_button)
        elif unit.status.name in {"MIA", "KIA"}:
            logger.info(f"Unit is MIA or KIA, adding reform button")
            reform_button = ui.Button(label="Reform Unit", style=ButtonStyle.success, disabled=player.rec_points < 1)
            async def reform_button_callback(interaction: Interaction):
                logger.info(f"Reforming unit {unit.name}")
                unit.status = "INACTIVE"
                player.rec_points -= 1
                self.session.commit()
                await interaction.response.send_message(f"You have reformed {unit.name}", ephemeral=CustomClient().use_ephemeral)
            reform_button.callback = reform_button_callback
            view.add_item(reform_button)
        else:
            logger.info(f"Unit is not proposed, not adding buy button")
            nothing_to_buy = ui.Button(label="Nothing to buy", style=ButtonStyle.secondary, disabled=True)
            view.add_item(nothing_to_buy)
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