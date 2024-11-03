from cProfile import label
from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, TextStyle, Member, ButtonStyle, SelectOption
from models import Player, ActiveUnit, Unit, Upgrade
from customclient import CustomClient
import templates

logger = getLogger(__name__)

class Company(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.session = bot.session

    @ac.command(name="search", description="Search for players of specific unit type and AO")
    async def search(self, interaction: Interaction):
        player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message("You don't have a Meta Campaign company so you can't search", ephemeral=CustomClient().use_ephemeral)
            return
        player_active_unit = self.session.query(ActiveUnit).filter(ActiveUnit.player_id == player.id).first()
        unit = self.session.query(Unit).filter(Unit.id == player_active_unit.unit_id).first()
        aos = self.session.query(ActiveUnit.area_operation).distinct().all()

        class TypeSelect(ui.Select):
            def __init__(self):
                options = []
                for unit_type in bot.config["unit_types"]:
                    if unit_type == unit.type and not unit:
                        options.append(SelectOption(label=unit_type, value=unit_type, default=True))
                    else:
                        options.append(SelectOption(label=unit_type, value=unit_type))
                super().__init__(placeholder="Select the type of unit you want to search for", options=options)

            async def callback(self, interaction: Interaction):
                await interaction.response.defer(ephemeral=True)

        class AOSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=ao, value=ao) for ao in aos]
                super().__init__(placeholder="Select the AO in which you want to search", options=options)

            async def callback(self, interaction: Interaction):
                await interaction.response.defer(ephemeral=True)

        class SearchView(ui.View):
            def __init__(self):
                super().__init__()
                self.session = CustomClient().session  # can't use self.session because this is a nested class, so we use the singleton reference
                self.add_item(TypeSelect())
                self.add_item(AOSelect())

            @ui.button(label="Search", style=ButtonStyle.primary)
            async def search_callback(self, interaction: Interaction, button: ui.Button):
                # create the unit in the database
                unit_type = self.children[1].values[0]
                ao = self.children[2].values[0]
                logger.debug(f"Unit type selected: {unit_type}")
                logger.debug(f"AO selected: {ao}")

                target_units_in_ao = self.session.query(ActiveUnit.player_id).filter(ActiveUnit.area_operation == ao).all()
                target_units_same_type = self.session.query(Unit.player_id).filter(Unit.unit_type == unit_type).all()
                targets = list(set(target_units_in_ao).intersection(target_units_same_type))
                message = ""
                for target in targets:
                    player_name = self.session.query(Player.name).filter(Player.discord_id == target).first()
                    message += f"{player_name}\n"

                logger.debug(f"Unit {unit.name} created for player {player.name}")
                button.disabled = True
                await interaction.response.send_message(f"The names of the players in the AO '{ao}' with a unit of type '{unit_type}\n{message}",
                                                        ephemeral=CustomClient().use_ephemeral)

        view = SearchView()
        await interaction.response.send_message("Please select the unit type and the ao", view=view, ephemeral=CustomClient().use_ephemeral)

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Company cog")
    await bot.add_cog(Company(bot))

async def teardown():
    logger.info("Tearing down Company cog")
    bot.remove_cog(Company.__name__) # remove_cog takes a string, not a class