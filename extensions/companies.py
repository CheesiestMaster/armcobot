from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ui, TextStyle, Member, User
from models import Player, Unit, UnitStatus
from customclient import CustomClient
import templates as tmpl
import os
from utils import has_invalid_url, uses_db
from sqlalchemy.orm import Session
import asyncio
logger = getLogger(__name__)

class Company(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @ac.command(name="create", description="Create a new Meta Campaign company")
    @uses_db(CustomClient().sessionmaker)
    async def create(self, interaction: Interaction, session: Session):
        # check if the user already has a company
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if player:
            logger.debug(f"User {interaction.user.display_name} already has a Meta Campaign company")
            await interaction.response.send_message(tmpl.already_have_company, ephemeral=self.bot.use_ephemeral)
            return
        
        # create a new Player in the database
        player = Player(discord_id=interaction.user.id, name=interaction.user.name, rec_points=1)
        session.add(player)
        session.commit() # flush to get the player id
        await asyncio.sleep(0.1) # we need an awaitable here so the consumer can act on the new player
        stockpile = Unit(name="Stockpile", player_id=player.id, status=UnitStatus.INACTIVE, unit_type="STOCKPILE")
        session.add(stockpile)
        logger.debug(f"User {interaction.user.display_name} created a new Meta Campaign company")
        await interaction.response.send_message(tmpl.joined_meta_campaign, ephemeral=self.bot.use_ephemeral)
        self.bot.queue.put_nowait((0, player, 0)) # this is the only one that gets a 0, all others are 1

    @ac.command(name="edit", description="Edit your Meta Campaign company")
    @uses_db(CustomClient().sessionmaker)
    async def edit(self, interaction: Interaction, session: Session):
        # we need a long text input for this, so modal is needed
        class EditCompanyModal(ui.Modal):
            def __init__(self, player):
                super().__init__(title="Edit your Meta Campaign company")
                self.player = player
                self.add_item(ui.TextInput(label="Name", placeholder="Enter the company name", required=True, max_length=32, default=player.name))
                self.add_item(ui.TextInput(label="Lore", placeholder="Enter the company lore", max_length=1000, style=TextStyle.paragraph, default=player.lore or "", required=False))

            @uses_db(CustomClient().sessionmaker)
            async def on_submit(self, interaction: Interaction, session: Session):
                if any(char in child.value for child in self.children for char in os.getenv("BANNED_CHARS", "")):
                    # Handle the case where a value contains '<' or '>'
                    await interaction.response.send_message(tmpl.invalid_input, ephemeral=CustomClient().use_ephemeral)
                    return
                if 0 < len(self.children[0].value) > 32:
                    await interaction.response.send_message(tmpl.company_name_length, ephemeral=CustomClient().use_ephemeral)
                    return
                if len(self.children[1].value) > 1000:
                    await interaction.response.send_message(tmpl.company_lore_length, ephemeral=CustomClient().use_ephemeral)
                    return
                if has_invalid_url(self.children[1].value):
                    await interaction.response.send_message(tmpl.company_lore_urls, ephemeral=CustomClient().use_ephemeral)
                    return
                _player = session.merge(self.player)
                session.query(Player).filter(Player.id == _player.id).update({
                    Player.name: self.children[0].value,
                    Player.lore: self.children[1].value
                })
                await interaction.response.send_message(tmpl.company_updated, ephemeral=CustomClient().use_ephemeral)
                CustomClient().queue.put_nowait((1, _player, 0))

        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            logger.debug(f"User {interaction.user.display_name} does not have a Meta Campaign company and is trying to edit it")
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=CustomClient().use_ephemeral)
            return

        modal = EditCompanyModal(player)
        await interaction.response.send_modal(modal)

    @ac.command(name="show", description="Displays a Players Meta Campaign company")
    @ac.describe(member="The players Meta Campaign company to show")
    @uses_db(CustomClient().sessionmaker)
    async def show(self, interaction: Interaction, session: Session, member: Member|User):
        player = session.query(Player).filter(Player.discord_id == member.id).first()
        if not player:
            await interaction.response.send_message(tmpl.member_no_company.format(member=member), ephemeral=CustomClient().use_ephemeral)
            return

        # Generate the info message strings
        dossier_message = tmpl.Dossier.format(mention="", player=player, medals="") # don't ping in company show
        unit_message = await self.bot.generate_unit_message(player=player)
        statistic_message = tmpl.Statistics_Player.format(mention="", player=player, units=unit_message)

        await interaction.response.send_message(f"{dossier_message}\n{statistic_message}", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="refresh", description="Refresh your Meta Campaign company")
    @uses_db(CustomClient().sessionmaker)
    async def refresh(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=CustomClient().use_ephemeral)
            return
        self.bot.queue.put_nowait((1, player, 0))
        await interaction.response.send_message(tmpl.company_refreshed, ephemeral=CustomClient().use_ephemeral)

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Company cog")
    await bot.add_cog(Company(bot))

async def teardown():
    logger.info("Tearing down Company cog")
    bot.remove_cog(Company.__name__) # remove_cog takes a string, not a class