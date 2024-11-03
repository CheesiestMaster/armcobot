from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, ButtonStyle, SelectOption
from discord.ui import View
from models import Player, Unit as Unit_model, ActiveUnit, UnitStatus
from customclient import CustomClient

logger = getLogger(__name__)

class Unit(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.session = bot.session

    @ac.command(name="create", description="Create a new unit for a player")
    @ac.describe(unit_name="The name of the unit to create")
    async def createunit(self, interaction: Interaction, unit_name: str):
            # we need to make a modal for this, as we need a dropdown for the unit type
            class UnitSelect(ui.Select):
                def __init__(self):
                    options = [SelectOption(label=unit_type, value=unit_type) for unit_type in bot.config["unit_types"]]
                    super().__init__(placeholder="Select the type of unit to create", options=options)

                async def callback(self, interaction: Interaction):
                    await interaction.response.defer(ephemeral=True)

            class CreateUnitView(ui.View):
                def __init__(self):
                    super().__init__()
                    self.session = CustomClient().session # can't use self.session because this is a nested class, so we use the singleton reference
                    self.add_item(UnitSelect())

                @ui.button(label="Create Unit", style=ButtonStyle.primary)
                async def create_unit_callback(self, interaction: Interaction, button: ui.Button):
                    # get the player id from the database
                    player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
                    if not player:
                        await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
                        return

                    # Check for 3 proposed Unit limit
                    units = self.session.query(Unit_model).filter(Unit_model.player_id == player.id).filter(Unit_model.status == "PROPOSED").all()
                    logger.debug(f"Number of proposed units: {len(units)}")
                    if len(units) >= 3:
                        await interaction.response.send_message("You already have 3 proposed Units, which is the maximum allowed", ephemeral=CustomClient().use_ephemeral)
                        return
                    # create the unit in the database
                    unit_type = self.children[1].values[0]
                    logger.debug(f"Unit type selected: {unit_type}")
                    # check if the unit name is already taken
                    if self.session.query(Unit_model).filter(Unit_model.name == unit_name, Unit_model.player_id == player.id).first():
                        await interaction.response.send_message("You already have a unit with that name", ephemeral=CustomClient().use_ephemeral)
                        return
                    unit = Unit_model(player_id=player.id, name=unit_name, unit_type=unit_type)
                    self.session.add(unit)
                    self.session.commit()
                    logger.debug(f"Unit {unit.name} created for player {player.name}")
                    button.disabled = True
                    await interaction.response.send_message(f"Unit {unit.name} created", ephemeral=CustomClient().use_ephemeral)

            view = CreateUnitView()
            await interaction.response.send_message("Please select the unit type and enter the unit name", view=view, ephemeral=CustomClient().use_ephemeral)

    @ac.command(name="activate", description="Activate a unit")
    @ac.describe(callsign="The callsign of the unit to activate, must be globally unique")
    async def activateunit(self, interaction: Interaction, callsign: str):
        # get the list of units for the author
        if len(callsign) > 8:
            await interaction.response.send_message("Callsign is too long, please use a shorter callsign", ephemeral=CustomClient().use_ephemeral)
            return
        logger.debug(f"Activating unit for {interaction.user.id}")
        player: Player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return
        units = self.session.query(Unit_model).filter(Unit_model.player_id == player.id).all()
        if not units:
            await interaction.response.send_message("You don't have any units", ephemeral=CustomClient().use_ephemeral)
            return
        active_unit = self.session.query(ActiveUnit).filter(ActiveUnit.player_id == player.id).first()
        if active_unit:
            await interaction.response.send_message("You already have an active unit", ephemeral=CustomClient().use_ephemeral)
            return
        # check if the callsign is already taken
        if self.session.query(ActiveUnit).filter(ActiveUnit.callsign == callsign).first():
            await interaction.response.send_message("That callsign is already taken", ephemeral=CustomClient().use_ephemeral)
            return
        # create a dropdown for the units
        class UnitSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=unit.name, value=unit.name) for unit in units]
                self.session = CustomClient().session
                super().__init__(placeholder="Select the unit to activate", options=options)

            async def callback(self, interaction: Interaction):
                # create an ActiveUnit object for the unit, for now just set the player_id and unit_id
                unit: Unit_model = self.session.query(Unit_model).filter(Unit_model.name == self.values[0]).first()
                if not unit.status == UnitStatus.INACTIVE:
                    await interaction.response.send_message("That unit is not inactive", ephemeral=CustomClient().use_ephemeral)
                    return
                logger.debug(f"Activating unit {unit.name}")
                active_unit = ActiveUnit(player_id=player.id, unit_id=unit.id, callsign=callsign)
                self.session.add(active_unit)
                self.session.commit()
                await interaction.response.send_message(f"Unit {unit.name} activated", ephemeral=CustomClient().use_ephemeral)

        view = View()
        view.add_item(UnitSelect())
        await interaction.response.send_message("Please select the unit to activate", view=view, ephemeral=CustomClient().use_ephemeral)

    @ac.command(name="remove_unit", description="Remove a proposed unit from your company")
    async def remove_unit(self, interaction: Interaction):

        player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return
        units = self.session.query(Unit_model).filter(Unit_model.player_id == player.id).filter(Unit_model.status == UnitStatus.PROPOSED).all()
        if not units:
            await interaction.response.send_message("You don't have any proposed units", ephemeral=CustomClient().use_ephemeral)
            return
        # create a dropdown for the units
        class UnitSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=unit.name, value=unit.name) for unit in units]
                self.session = CustomClient().session
                super().__init__(placeholder="Select the unit to remove", options=options)

            async def callback(self, interaction: Interaction):
                # create an ActiveUnit object for the unit, for now just set the player_id and unit_id
                unit: Unit_model = self.session.query(Unit_model).filter(Unit_model.name == self.values[0]).first()
                logger.debug(f"Removing unit {unit.name}")
                self.session.delete(unit)
                self.session.commit()
                self.session.queue.put_nowait((1, player)) # make the bot think the player was edited, using nowait to avoid yielding control
                await interaction.response.send_message(f"Unit {unit.name} activated", ephemeral=CustomClient().use_ephemeral)

        view = View()
        view.add_item(UnitSelect())
        await interaction.response.send_message("Please select the unit to remove", view=view, ephemeral=CustomClient().use_ephemeral)
bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Unit cog")
    await bot.add_cog(Unit(bot))

async def teardown():
    logger.info("Tearing down Unit cog")
    bot.remove_cog(Unit.__name__) # remove_cog takes a string, not a class
