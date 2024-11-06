from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, ButtonStyle, SelectOption
from models import Player, ActiveUnit, Unit
from customclient import CustomClient

logger = getLogger(__name__)

class Search(GroupCog):
    """
        A Discord bot cog that allows users to search for players by unit type and area of operation (AO)
        in the Meta Campaign.

        This cog provides a command (`/search`) that allows users to query players based on their specific
        unit type and area of operation, showing the list of players that match the selected criteria.

        Attributes:
            bot (Bot): The instance of the bot that this cog is attached to.
            session: The database session used for querying player, unit, and active unit information.

        Methods:
            search(interaction: Interaction)
                Responds with a UI for selecting unit type and area of operation, then provides a list of
                players who match the criteria.
    """

    def __init__(self, bot: Bot):
        """
                Initializes the Search cog.

                Args:
                    bot (Bot): The bot instance the cog will be added to.
                """
        self.bot = bot
        self.session = bot.session

    @ac.command(name="search", description="Search for players of specific unit type and AO")
    async def search(self, interaction: Interaction):
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
        player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message("You don't have a Meta Campaign company so you can't search", ephemeral=CustomClient().use_ephemeral)
            return
        player_active_unit = self.session.query(ActiveUnit).filter(ActiveUnit.player_id == player.id).first()
        unit = self.session.query(Unit).filter(Unit.id == player_active_unit.unit_id).first()
        aos = self.session.query(ActiveUnit.area_operation).distinct().all()

        class TypeSelect(ui.Select):
            """
            A dropdown UI component for selecting the type of unit to search for.

            This select dropdown populates with unit types based on the configured unit types.
            If the caller has a active unit, the menu defaults to this type.
            """
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
                self.session = CustomClient().session  # can't use self.session because this is a nested class, so we use the singleton reference
                self.add_item(TypeSelect())
                self.add_item(AOSelect())

            @ui.button(label="Search", style=ButtonStyle.primary)
            async def search_callback(self, interaction: Interaction, button: ui.Button):
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
