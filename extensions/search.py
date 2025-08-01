from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, ButtonStyle, SelectOption
from sqlalchemy.orm import Session
from models import Player, Unit
from customclient import CustomClient
from utils import uses_db
import templates as tmpl

logger = getLogger(__name__)

class Search(GroupCog):
    """
    A cog for searching players by unit type and area of operation in the Meta Campaign.
    """

    def __init__(self, bot: Bot):
        """
                Initializes the Search cog.

                Args:
                    bot (Bot): The bot instance the cog will be added to.
                """
        self.bot = bot
 

    @ac.command(name="search", description="Search for players of specific unit type and AO")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def search(self, interaction: Interaction, session: Session):
        """
               Handles the '/search' command for finding players based on unit type and area of operation.

               This command presents the user with a UI to select a unit type and AO. Once selected, it queries
               the database for players who match the selected criteria and sends back a list of their names.

               Args:
                   interaction (Interaction): The interaction that triggered this command.

               Internal Classes:
                   TypeSelect (ui.Select): UI component for selecting a unit type.
                   AOSelect (ui.Select): UI component for selecting an area of operation.
                   SearchView (ui.View): View to display TypeSelect and AOSelect options, along with a search button.
               """
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message(tmpl.search_no_company, ephemeral=CustomClient().use_ephemeral)
            return
        unit = session.query(Unit).filter(Unit.player_id == player.id, Unit.active == True).first()
        aos = session.query(Unit.area_operation).distinct().all()

        class TypeSelect(ui.Select):
            """
            A dropdown UI component for selecting the type of unit to search for.

            This select dropdown populates with unit types based on the configured unit types.
            If the caller has a active unit, the menu defaults to this type.
            """
            def __init__(self):
                options = []
                for unit_type in bot.config["unit_types"]:
                    if unit and unit_type == unit.type:
                        options.append(SelectOption(label=unit_type, value=unit_type, default=True))
                    else:
                        options.append(SelectOption(label=unit_type, value=unit_type))
                super().__init__(placeholder="Select the type of unit you want to search for", options=options)

            async def callback(self, interaction: Interaction):
                await interaction.response.defer(ephemeral=True)

        class AOSelect(ui.Select):
            """
            A dropdown UI component for selecting an area of operation (AO) for the search.
            """
            def __init__(self):
                options = [SelectOption(label=ao, value=ao) for ao in aos]
                super().__init__(placeholder="Select the AO in which you want to search", options=options)

            async def callback(self, interaction: Interaction):
                """
                Defers the interaction to prevent additional pop-ups after selection.

                Args:
                    interaction (Interaction): The interaction event for this selection.
                """
                await interaction.response.defer(ephemeral=True)

        class SearchView(ui.View):
            """
            A custom view that provides the interface for selecting unit type and AO,
            and performs the search upon pressing the 'Search' button.

            Attributes:
                session: The database session to access player and unit data.
            """

            def __init__(self):
                super().__init__()
                self.add_item(TypeSelect())
                self.add_item(AOSelect())

            @ui.button(label="Search", style=ButtonStyle.primary)
            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def search_callback(self, interaction: Interaction, button: ui.Button, session: Session):
                """
                Executes a search in the database for players matching the selected unit type and AO.

                Args:
                    interaction (Interaction): The interaction that triggered this button click.
                    button (ui.Button): The button component itself.
                """
                # create the unit in the database
                unit_type = self.children[1].values[0]
                ao = self.children[2].values[0]
                logger.debug(f"Unit type selected: {unit_type}")
                logger.debug(f"AO selected: {ao}")

                target_units_in_ao = session.query(Unit.player_id).filter(Unit.area_operation == ao).all()
                target_units_same_type = session.query(Unit.player_id).filter(Unit.unit_type == unit_type).all()
                targets = list(set(target_units_in_ao).intersection(target_units_same_type))
                message = ""
                for target in targets:
                    player_name = session.query(Player.name).filter(Player.discord_id == target).first()
                    message += f"{player_name}\n"

                logger.debug(f"Unit {unit.name} created for player {player.name}")
                button.disabled = True
                await interaction.response.send_message(f"The names of the players in the AO '{ao}' with a unit of type '{unit_type}\n{message}",
                                                        ephemeral=CustomClient().use_ephemeral)

        view = SearchView()
        await interaction.response.send_message(tmpl.search_select_params, view=view, ephemeral=CustomClient().use_ephemeral)

bot: Bot = None
async def setup(_bot: Bot):
    """
    Asynchronous setup function to add the Search cog to the bot.

    Args:
        _bot (Bot): The bot instance to add this cog to.
    """
    global bot
    bot = _bot
    logger.info("Setting up Search cog")
    await bot.add_cog(Search(bot))

async def teardown():
    """
    Asynchronous teardown function to remove the Search cog from the bot.
    """
    logger.info("Tearing down Search cog")
    bot.remove_cog(Search.__name__) # remove_cog takes a string, not a class
