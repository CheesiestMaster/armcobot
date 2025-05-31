from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac
from discord.ui import Select, View
from utils import uses_db
from customclient import CustomClient
from MessageManager import MessageManager
from sqlalchemy.orm import Session
from models import Player, Unit, PlayerUpgrade
logger = getLogger(__name__)
bot: Bot = None
class Stockpile(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @ac.command(name="store", description="Store an upgrade in your stockpile")
    @uses_db(CustomClient().sessionmaker)
    async def store(self, interaction: Interaction, session: Session):
        logger.info(f"{interaction.user.name} <{interaction.user.id}> is storing an upgrade")
        message_manager = MessageManager(interaction)
        unit_select = Select(placeholder="Select a unit")
        view = View()
        _player: Player = session.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
        logger.debug(f"Player: {_player}")
        if _player is None:
            await message_manager.send_message(view=view, content="You don't have a company yet, please create one with `/company create`", ephemeral=self.bot.use_ephemeral)
            return
        for unit in _player.units:
            unit_select.add_option(label=unit.name, value=unit.id)
        
        view.add_item(unit_select)
        await message_manager.send_message(view=view, ephemeral=self.bot.use_ephemeral)
        @uses_db(CustomClient().sessionmaker) # we need a second session to get the upgrades, because the first session has already left scope
        async def unit_select_callback(interaction: Interaction, session: Session):
            _player: Player = session.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            if _player is None:
                await message_manager.update_message(content="Something went wrong, please try again or contact Cheese")
                await interaction.response.defer(thinking=False)
                return
            upgrade_select = Select(placeholder="Select an upgrade")
            unit = session.query(Unit).filter(Unit.id == unit_select.values[0]).first()
            if unit is None:
                await message_manager.update_message(content="Something went wrong, please try again or contact Cheese")
                await interaction.response.defer(thinking=False)
                return
            if unit.unit_type == "STOCKPILE": 
                await message_manager.update_message(content="To move upgrades from your stockpile, use the `/stockpile retrieve` command")
                await interaction.response.defer(thinking=False)
                return
            if unit.player != _player:
                await interaction.response.defer(thinking=False)
                return
            if unit.upgrades:
                for upgrade in unit.upgrades:
                    upgrade_select.add_option(label=upgrade.name, value=upgrade.id)
            else:
                upgrade_select.add_option(label="This unit has no upgrades", value="None", default=True)
                upgrade_select.disabled = True
            _view = View()
            _view.add_item(unit_select)
            _view.add_item(upgrade_select)
            await message_manager.update_message(view=_view)
            await interaction.response.defer(thinking=False) # suppress the "This interaction failed" error message
            @uses_db(CustomClient().sessionmaker)
            async def upgrade_select_callback(interaction: Interaction, session: Session):
                _player: Player = session.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                if _player is None:
                    await message_manager.update_message(content="Something went wrong, please try again or contact Cheese")
                    await interaction.response.defer(thinking=False)
                    return
                upgrade = session.query(PlayerUpgrade).filter(PlayerUpgrade.id == upgrade_select.values[0]).first()
                if upgrade is None:
                    await message_manager.update_message(content="Something went wrong, please try again or contact Cheese")
                    await interaction.response.defer(thinking=False)
                    return
                if upgrade.unit.player != _player:
                    await interaction.response.defer(thinking=False)
                    return
                stockpile = _player.stockpile
                if stockpile is None:
                    await message_manager.update_message(content="Something went wrong, please try again or contact Cheese")
                    await interaction.response.defer(thinking=False)
                    return
                if upgrade.unit_id == stockpile.id:
                    await message_manager.update_message(content="This upgrade is already in your stockpile")
                    await interaction.response.defer(thinking=False)
                    return
                upgrade.unit = stockpile
                session.commit()
                await message_manager.update_message(content="Upgrade stored in stockpile")
                await interaction.response.defer(thinking=False)
                self.bot.queue.put_nowait((1, _player, 0))
            upgrade_select.callback = upgrade_select_callback
        unit_select.callback = unit_select_callback

    @ac.command(name="retrieve", description="Retrieve an upgrade from your stockpile")
    @uses_db(CustomClient().sessionmaker)
    async def retrieve(self, interaction: Interaction, session):
        logger.info(f"{interaction.user.name} is retrieving an upgrade")
        message_manager = MessageManager(interaction)
        view = View()
        _player: Player = session.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
        if _player is None:
            await message_manager.send_message(view=view, content="You don't have a company yet, please create one with `/company create`", ephemeral=self.bot.use_ephemeral)
            return
        unit_select = Select(placeholder="Select a unit")
        for unit in _player.units:
            unit_select.add_option(label=unit.name, value=unit.id)
        view.add_item(unit_select)
        await message_manager.send_message(view=view, content="Select a unit to give the upgrade to", ephemeral=self.bot.use_ephemeral)
        @uses_db(CustomClient().sessionmaker)
        async def unit_select_callback(interaction: Interaction, session: Session):
            _player: Player = session.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            if _player is None:
                await message_manager.update_message(content="Something went wrong, please try again or contact Cheese")
                await interaction.response.defer(thinking=False)
                return
            _unit: Unit = session.query(Unit).filter(Unit.id == unit_select.values[0]).first()
            if _unit is None:
                await message_manager.update_message(content="Something went wrong, please try again or contact Cheese")
                await interaction.response.defer(thinking=False)
                return
            if _unit.player != _player:
                await interaction.response.defer(thinking=False)
                return
            if _unit.unit_type == "STOCKPILE":
                await message_manager.update_message(content="To move upgrades into your stockpile, use the `/stockpile store` command")
                await interaction.response.defer(thinking=False)
                return
            _stockpile = _player.stockpile
            if _stockpile is None:
                await message_manager.update_message(content="Something went wrong, please contact Cheese")
                await interaction.response.defer(thinking=False)
                return
            upgrade_select = Select(placeholder="Select an upgrade")
            for upgrade in _stockpile.upgrades:
                if upgrade.shop_upgrade in _unit.available_upgrades:
                    upgrade_select.add_option(label=upgrade.name, value=upgrade.id)
            if len(upgrade_select.options) == 0:
                upgrade_select.add_option(label="This unit has no upgrades", value="None", default=True)
                upgrade_select.disabled = True
            if len(view.children) == 2: # there is already an upgrade select, so we need to remove that one first
                view.remove_item(view.children[1])
            view.add_item(upgrade_select)
            await message_manager.update_message(view=view)
            await interaction.response.defer(thinking=False)
            unit_id = _unit.id
            @uses_db(CustomClient().sessionmaker)
            async def upgrade_select_callback(interaction: Interaction, session: Session):
                _player: Player = session.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                if _player is None:
                    await message_manager.update_message(content="Something went wrong, please try again or contact Cheese")
                    await interaction.response.defer(thinking=False)
                    return
                _unit = session.query(Unit).filter(Unit.id == unit_id).first() # refresh the unit, so it's on the correct session
                if _unit is None:
                    await message_manager.update_message(content="Something went wrong, please try again or contact Cheese")
                    await interaction.response.defer(thinking=False)
                    return
                _upgrade: PlayerUpgrade = session.query(PlayerUpgrade).filter(PlayerUpgrade.id == upgrade_select.values[0]).first()
                if _upgrade is None:
                    await message_manager.update_message(content="Something went wrong, please try again or contact Cheese")
                    await interaction.response.defer(thinking=False)
                    return
                if _upgrade.unit.player != _player:
                    await interaction.response.defer(thinking=False)
                    return
                _upgrade.unit = _unit
                session.commit()
                await message_manager.update_message(content="Upgrade retrieved")
                await interaction.response.defer(thinking=False)
                self.bot.queue.put_nowait((1, _player, 0))
                
            upgrade_select.callback = upgrade_select_callback

        unit_select.callback = unit_select_callback
async def setup(_bot: Bot):
    global bot
    bot = _bot
    await bot.add_cog(Stockpile(bot))

async def teardown():
    bot.remove_cog(Stockpile.__name__) # remove_cog takes a string, not a class