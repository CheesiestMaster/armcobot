from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, Member, ui, ButtonStyle, SelectOption
from discord.ui import View
from models import Player, Unit as Unit_model, UnitStatus
from customclient import CustomClient

logger = getLogger(__name__)

class Unit(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.session = bot.session

    @ac.command(name="create", description="Create a new unit for a player")
    @ac.describe(unit_name="The name of the unit to create")
    async def createunit(self, interaction: Interaction, unit_name: str):
        class UnitSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=unit_type, value=unit_type) for unit_type in bot.config["unit_types"]]
                super().__init__(placeholder="Select the type of unit to create", options=options)

            async def callback(self, interaction: Interaction):
                await interaction.response.defer(ephemeral=True)

        class CreateUnitView(ui.View):
            def __init__(self):
                super().__init__()
                self.session = CustomClient().session
                self.add_item(UnitSelect())

            @ui.button(label="Create Unit", style=ButtonStyle.primary)
            async def create_unit_callback(self, interaction: Interaction, button: ui.Button):
                player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
                if not player:
                    await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
                    return

                units = self.session.query(Unit_model).filter(Unit_model.player_id == player.id, Unit_model.status == "PROPOSED").all()
                logger.debug(f"Number of proposed units: {len(units)}")
                if len(units) >= 3:
                    await interaction.response.send_message("You already have 3 proposed Units, which is the maximum allowed", ephemeral=CustomClient().use_ephemeral)
                    return

                unit_type = self.children[1].values[0]
                logger.debug(f"Unit type selected: {unit_type}")

                if self.session.query(Unit_model).filter(Unit_model.name == unit_name, Unit_model.player_id == player.id).first():
                    await interaction.response.send_message("You already have a unit with that name", ephemeral=CustomClient().use_ephemeral)
                    return

                unit = Unit_model(player_id=player.id, name=unit_name, unit_type=unit_type, active=False)
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
        active_unit = self.session.query(Unit_model).filter(Unit_model.player_id == player.id, Unit_model.active == True).first()
        if active_unit:
            await interaction.response.send_message("You already have an active unit", ephemeral=CustomClient().use_ephemeral)
            return
        if self.session.query(Unit_model).filter(Unit_model.callsign == callsign).first():
            await interaction.response.send_message("That callsign is already taken", ephemeral=CustomClient().use_ephemeral)
            return

        class UnitSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=unit.name, value=unit.name) for unit in units]
                self.session = CustomClient().session
                super().__init__(placeholder="Select the unit to activate", options=options)

            async def callback(self, interaction: Interaction):
                unit: Unit_model = self.session.query(Unit_model).filter(Unit_model.name == self.values[0]).first()
                if not unit.status == UnitStatus.INACTIVE:
                    await interaction.response.send_message("That unit is not inactive", ephemeral=CustomClient().use_ephemeral)
                    return
                logger.debug(f"Activating unit {unit.name}")
                unit.active = True
                unit.callsign = callsign
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
        units = self.session.query(Unit_model).filter(Unit_model.player_id == player.id, Unit_model.status == UnitStatus.PROPOSED).all()
        if not units:
            await interaction.response.send_message("You don't have any proposed units", ephemeral=CustomClient().use_ephemeral)
            return

        class UnitSelect(ui.Select):
            def __init__(self):
                options = [SelectOption(label=unit.name, value=unit.name) for unit in units]
                self.session = CustomClient().session
                super().__init__(placeholder="Select the unit to remove", options=options)

            async def callback(self, interaction: Interaction):
                unit: Unit_model = self.session.query(Unit_model).filter(Unit_model.name == self.values[0]).first()
                logger.debug(f"Removing unit {unit.name}")
                self.session.delete(unit)
                self.session.commit()
                CustomClient().queue.put_nowait((1, player))
                await interaction.response.send_message(f"Unit {unit.name} removed", ephemeral=CustomClient().use_ephemeral)

        view = View()
        view.add_item(UnitSelect())
        await interaction.response.send_message("Please select the unit to remove", view=view, ephemeral=CustomClient().use_ephemeral)
        
    @ac.command(name="deactivate", description="Deactivate a unit")
    async def deactivateunit(self, interaction: Interaction):
        logger.debug(f"Deactivating unit for {interaction.user.id}")
        player: Player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return
        
        active_unit = self.session.query(Unit_model).filter(Unit_model.player_id == player.id, Unit_model.active == True).first()
        if not active_unit:
            await interaction.response.send_message("You don't have any active units", ephemeral=CustomClient().use_ephemeral)
            return
                
        logger.debug(f"Deactivating unit with callsign {active_unit.callsign}")
        active_unit.active = False
        active_unit.status = UnitStatus.INACTIVE if active_unit.status == UnitStatus.ACTIVE else active_unit.status
        active_unit.callsign = None
        self.session.commit()
        await interaction.response.send_message(f"Unit with callsign {active_unit.callsign} deactivated", ephemeral=CustomClient().use_ephemeral)

    @ac.command(name="units", description="Display a list of all Units for a Player")
    @ac.describe(player="The player to deliver results for")
    async def units(self, interaction: Interaction, player: Member):
        player = self.session.query(Player).filter(Player.discord_id == player.id).first()
        if not player:
            await interaction.response.send_message("User doesn't have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        
        units = self.session.query(Unit_model).filter(Unit_model.player_id == player.id).all()
        if not units:
            await interaction.response.send_message("User doesn't have any Units", ephemeral=CustomClient().use_ephemeral)
            return
        
        # Create a table with unit details
        unit_table = "| Unit Name | Callsign | Unit Type | Status |\n"
        unit_table += "|-----------|-----------|-----------|--------|\n"
        for unit in units:
            unit_table += f"| {unit.name} | {unit.callsign} | {unit.unit_type} | {unit.status} |\n"

        # Send the table to the user
        await interaction.response.send_message(f"Here are {player.name}'s Units:\n\n{unit_table}", ephemeral=CustomClient().use_ephemeral)

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Unit cog")
    await bot.add_cog(Unit(bot))

async def teardown():
    logger.info("Tearing down Unit cog")
    bot.remove_cog(Unit.__name__) # remove_cog takes a string, not a class
