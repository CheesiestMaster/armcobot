from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, Member, TextStyle
from discord.ui import Modal, TextInput
from models import Player, Unit, ActiveUnit
logger = getLogger(__name__)

class Admin(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.session = bot.session
        # self.interaction_check = self.is_mod # disabled for development, as those roles don't exist on the dev guild

    async def is_mod(self, interaction: Interaction):
        valid = any(interaction.user.has_role(role) for role in self.bot.mod_roles)
        if not valid:
            logger.warning(f"{interaction.user.name} tried to use admin commands")
        return valid
    
    @ac.command(name="recpoint", description="Give or remove a number of requisition points from a player")
    @ac.describe(player="The player to give or remove points from")
    @ac.describe(points="The number of points to give or remove")
    async def recpoint(self, interaction: Interaction, player: Member, points: int):
        # find the player by discord id
        player = self.session.query(Player).filter(Player.discord_id == player.id).first()
        if not player:
            await interaction.response.send_message("User doesn't have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        
        # update the player's rec points
        player.rec_points += points
        self.session.commit()
        logger.debug(f"User {player.name} now has {player.rec_points} requisition points")
        await interaction.response.send_message(f"{player.name} now has {player.rec_points} requisition points", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="bonuspay", description="Give or remove a number of bonus pay from a player")
    @ac.describe(player="The player to give or remove bonus pay from")
    @ac.describe(points="The number of bonus pay to give or remove")
    async def bonuspay(self, interaction: Interaction, player: Member, points: int):
        # find the player by discord id
        player = self.session.query(Player).filter(Player.discord_id == player.id).first()
        if not player:
            await interaction.response.send_message("User doesn't have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        
        # update the player's bonus pay
        player.bonus_pay += points
        self.session.commit()
        logger.debug(f"User {player.name} now has {player.bonus_pay} bonus pay")
        await interaction.response.send_message(f"{player.name} now has {player.bonus_pay} bonus pay", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="activateunits", description="Activate multiple units")
    async def activateunits(self, interaction: Interaction):
        # we need a modal with a paragraph input for the unit names
        # we identify if a newline is in the first 40 characters, if so, we split on that, otherwise we split on commas
        # we then check if the units exist, and if they do, we activate them
        # we send a response in the end saying which units were activated, and which ones didn't exist
        modal = Modal(title="Activate Units", custom_id="activate_units")
        modal.add_item(TextInput(label="Unit names", custom_id="unit_names", style=TextStyle.long))
        async def modal_callback(interaction: Interaction):
            unit_names = interaction.data["components"][0]["components"][0]["value"]
            logger.debug(f"Received unit names: {unit_names}")
            if "\n" in unit_names[:40]:
                unit_names = unit_names.split("\n")
            else:
                unit_names = unit_names.split(",")
            logger.debug(f"Parsed unit names: {unit_names}")
            activated = []
            not_found = []
            for unit_name in unit_names:
                unit = self.session.query(Unit).filter(Unit.name == unit_name).first()
                if unit:
                    activated.append(unit.name)
                    active_unit = ActiveUnit(unit_id=unit.id, player_id=unit.player_id)
                    self.session.add(active_unit)
                    logger.debug(f"Activated unit: {unit.name}")
                else:
                    not_found.append(unit_name)
                    logger.debug(f"Unit not found: {unit_name}")
                try:
                    self.session.commit()
                except Exception as e:
                    logger.error(f"Error committing to database: {e}")
                    await interaction.response.send_message(f"Error committing to database: {e}", ephemeral=self.bot.use_ephemeral)
            await interaction.response.send_message(f"Activated {activated}, not found {not_found}", ephemeral=self.bot.use_ephemeral)
            logger.debug(f"Activation results - Activated: {activated}, Not found: {not_found}")
        modal.on_submit = modal_callback
                
        await interaction.response.send_modal(modal)

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Admin cog")
    await bot.add_cog(Admin(bot))

async def teardown():
    logger.info("Tearing down Admin cog")
    bot.remove_cog(Admin.__name__) # remove_cog takes a string, not a class
