from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, TextStyle, Member
from models import Player
from customclient import CustomClient
import templates

logger = getLogger(__name__)

class Company(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.session = bot.session

    @ac.command(name="create", description="Create a new Meta Campaign company")
    async def create(self, interaction: Interaction):
        # check if the user already has a company
        player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if player:
            logger.debug(f"User {interaction.user.display_name} already has a Meta Campaign company")
            await interaction.response.send_message("You already have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        
        # create a new Player in the database
        player = Player(discord_id=interaction.user.id, name=interaction.user.name, rec_points=2)
        self.session.add(player)
        self.session.commit()
        logger.debug(f"User {interaction.user.display_name} created a new Meta Campaign company")
        await interaction.response.send_message("You have joined Meta Campaign", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="edit", description="Edit your Meta Campaign company")
    async def edit(self, interaction: Interaction):
        # we need a long text input for this, so modal is needed
        class EditCompanyModal(ui.Modal):
            def __init__(self, player):
                super().__init__(title="Edit your Meta Campaign company")
                self.player = player
                self.session = CustomClient().session
                self.add_item(ui.TextInput(label="Name", placeholder="Enter the company name", required=True, max_length=255, default=player.name))
                self.add_item(ui.TextInput(label="Lore", placeholder="Enter the company lore", max_length=1000, style=TextStyle.paragraph, default=player.lore or ""))


            async def on_submit(self, interaction: Interaction):
                self.player.name = self.children[0].value
                self.player.lore = self.children[1].value
                self.session.commit()
                await interaction.response.send_message("Company updated", ephemeral=CustomClient().use_ephemeral)

        player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            logger.debug(f"User {interaction.user.display_name} does not have a Meta Campaign company and is trying to edit it")
            await interaction.response.send_message("You don't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return

        modal = EditCompanyModal(player)
        await interaction.response.send_modal(modal)

    @ac.command(name="show", description="Displays a Players Meta Campaign company")
    @ac.describe(member="The players Meta Campaign company to show")
    async def show(self, interaction: Interaction, member: Member):
        player = self.session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message(f"{member.display_name} doesn't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return

        # Generate the info message strings
        dossier_message = templates.Dossier.format(player=player)
        unit_message = CustomClient().generate_unit_message(player=player)
        statistic_message = templates.Statistics_Player.format(player=player, units=unit_message)

        await interaction.response.send_message(f"{dossier_message}\n{statistic_message}", ephemeral=self.bot.use_ephemeral)

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Company cog")
    await bot.add_cog(Company(bot))

async def teardown():
    logger.info("Tearing down Company cog")
    bot.remove_cog(Company.__name__) # remove_cog takes a string, not a class