from functools import lru_cache
from logging import getLogger
from typing import Optional, Type
from discord.ext import tasks
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, Member, app_commands as ac, ui, ButtonStyle, SelectOption
from sqlalchemy import ColumnElement
from sqlalchemy.orm import Session
from models import Campaign, Player, PlayerUpgrade, Unit, UnitType, ShopUpgrade
from customclient import CustomClient
from utils import error_reporting, uses_db
import templates as tmpl

logger = getLogger(__name__)

caches = list() # list of all the caches for the autocompletes. which we only ever add to, never remove from

class Search(GroupCog):
    def __init__(self, bot: Bot):
        """
                Initializes the Search cog.

                Args:
                    bot (Bot): The bot instance the cog will be added to.
                """
        self.bot = bot
        self.clear_caches.start()

    def cog_unload(self):
        self.clear_caches.cancel()

    @tasks.loop(hours=1)
    async def clear_caches(self):
        logger.info("Clearing search caches")
        for cache in caches:
            cache.cache_clear() # clear each cache one by one, so they don't go stale
        logger.info("Search caches cleared")

    @staticmethod
    def _fuzzy_autocomplete(column: ColumnElement[str], *union_columns: ColumnElement[str]):
        
        lookup = lru_cache(maxsize=100)(
            uses_db(CustomClient().sessionmaker)(
                lambda current, session: tuple(
                    row[0] for row in (
                        session.query(column.label("value"))
                        .union_all(*(session.query(union_column.label("value")) for union_column in union_columns))
                        .distinct()
                        .limit(25)
                        .all()
                     if not current else
                        session.query(column.label("value"))
                        .filter(column.ilike(f"%{current}%"))
                        .union_all(*(session.query(union_column.label("value")).filter(union_column.ilike(f"%{current}%")) for union_column in union_columns))
                        .distinct()
                        .limit(25)
                        .all()))))
        
        async def autocomplete(interaction: Interaction, current: str):
            return [ac.Choice(name=item, value=item) for item in lookup(current.strip().lower())]
        
        caches.append(lookup)
        return autocomplete



    @ac.command(name="unit", description="Search for one or more units based on various criteria")
    @ac.describe(name="The name of the unit to search for")
    @ac.describe(player="The player to search for") # don't need to specify that it needs to be exact, because :Member already does enforce that
    @ac.describe(callsign="The callsign of the unit to search for")
    @ac.describe(unit_type="The type of the unit to search for (This must be the exact name, use the autocomplete)")
    @ac.describe(upgrade="The upgrade to search for")
    @ac.describe(campaign="The campaign to search for (This must be the exact name, use the autocomplete)")
    @ac.autocomplete(name=_fuzzy_autocomplete(Unit.name), 
                     callsign=_fuzzy_autocomplete(Unit.callsign), 
                     unit_type=_fuzzy_autocomplete(UnitType.unit_type), 
                     upgrade=_fuzzy_autocomplete(ShopUpgrade.name),
                     campaign=_fuzzy_autocomplete(Campaign.name)) # we don't need to autocomplete Player, because Member gets client side autocomplete anyway
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    @error_reporting(False)
    async def unit(self, interaction: Interaction, session: Session, name: Optional[str] = None, player: Optional[Member] = None, callsign: Optional[str] = None, unit_type: Optional[str] = None, upgrade: Optional[str] = None, campaign: Optional[str] = None) -> None:
        query = session.query(Unit)
        if name:
            query = query.filter(Unit.name.ilike(f"%{name}%"))
        if player:
            query = query.filter(Unit.player.has(Player.user == player))
        if callsign:
            query = query.filter(Unit.callsign.ilike(f"%{callsign}%"))
        if unit_type:
            query = query.filter(Unit.unit_type == unit_type)
        if upgrade:
            query = query.filter(Unit.upgrades.any(PlayerUpgrade.name.ilike(f"%{upgrade}%"))) # upgrade and unit_type filter on different tables than they autocomplete, because the autocomplete is on the superset, while the filter is on the Unit table
        if campaign:
            query = query.filter(Unit.campaign.has(Campaign.name == campaign))
        units = query.all()
        if not units:
            await interaction.response.send_message(tmpl.search_no_units_found, ephemeral=CustomClient().use_ephemeral)
            return
        #we need to build the output line by line, ensuring the output doesn't exceed 2000 characters
        output = ""
        for unit in units:
            line = tmpl.search_unit_output.format(unit=unit, campaign_name=f"in {unit.campaign.name}" if unit.campaign else "", callsign=f'"{unit.callsign}"' if unit.callsign else "")
            if len(output) + len(line) + 5 > 2000: 
                output += "\n..."
                break
            output += "\n" + line
        await interaction.response.send_message(output, ephemeral=CustomClient().use_ephemeral)

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
