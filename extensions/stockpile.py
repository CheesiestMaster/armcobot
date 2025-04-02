from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac
from discord.ui import Select, View
from utils import uses_db
from customclient import CustomClient
from MessageManager import MessageManager
from sqlalchemy.orm import Session
from models import Player
logger = getLogger(__name__)
bot: Bot = None
class Stockpile(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @ac.command(name="store", description="Store an upgrade in your stockpile")
    @uses_db(CustomClient().sessionmaker)
    async def store(self, interaction: Interaction, session: Session):
        logger.info(f"{interaction.user.name} is storing an upgrade")
        await interaction.response.send_message("NOT IMPLEMENTED", ephemeral=self.bot.use_ephemeral)
        return
        # This is intentionally unreachable, as it's not yet implemented
        # TODO: Implement this
        # send a view with a Select menu of their units
        # when a unit is selected, append a select of that unit's upgrades to the view
        # when an upgrade is selected, move the upgrade to the stockpile
        message_manager = MessageManager(interaction)
        unit_select = Select(placeholder="Select a unit")
        _player: Player = session.query(Player).filter(Player.id == interaction.user.id).first()
        if _player is None:
            await message_manager.send_message(content="You don't have a company yet, please create one with `/company create`", ephemeral=self.bot.use_ephemeral)
            return
        for unit in _player.units:
            unit_select.add_option(label=unit.name, value=unit.id)
        view = View()
        view.add_item(unit_select)
        await message_manager.send_message(view=view, ephemeral=self.bot.use_ephemeral)
        @uses_db(CustomClient().sessionmaker) # we need a second session to get the upgrades, because the first session has already left scope
        async def unit_select_callback(interaction: Interaction, session: Session):
            _player: Player = session.query(Player).filter(Player.id == interaction.user.id).first()
            if _player is None:
                await message_manager.send_message(content="You don't have a company yet, please create one with `/company create`", ephemeral=self.bot.use_ephemeral)
                return
            

    @ac.command(name="retrieve", description="Retrieve an upgrade from your stockpile")
    @uses_db(CustomClient().sessionmaker)
    async def retrieve(self, interaction: Interaction, session):
        logger.info(f"{interaction.user.name} is retrieving an upgrade")
        await interaction.response.send_message("NOT IMPLEMENTED", ephemeral=self.bot.use_ephemeral)
        return



async def setup(_bot: Bot):
    global bot
    bot = _bot
    await bot.add_cog(Stockpile(bot))

async def teardown():
    bot.remove_cog(Stockpile.__name__) # remove_cog takes a string, not a class