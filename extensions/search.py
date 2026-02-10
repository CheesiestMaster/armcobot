from logging import getLogger
from typing import Optional

from discord import Interaction, Member, app_commands as ac
from discord.ext.commands import GroupCog
from sqlalchemy.orm import Session
import templates as tmpl

from customclient import CustomClient
from models import Campaign, Player, PlayerUpgrade, Unit, UnitType, ShopUpgrade
from utils import error_reporting, uses_db, fuzzy_autocomplete

logger = getLogger(__name__)

class Search(GroupCog, description="Search units by name, player, callsign, type, upgrade, or campaign."):
    """
    Cog for the search slash command: search units by name, player, callsign,
    unit type, upgrade, or campaign. Uses fuzzy autocomplete for criteria.
    """

    def __init__(self, bot: CustomClient):
        """Store a reference to the bot instance."""

        self.bot = bot



    @ac.command(name="unit", description="Search for one or more units based on various criteria")
    @ac.describe(name="The name of the unit to search for")
    @ac.describe(player="The player to search for") # don't need to specify that it needs to be exact, because :Member already does enforce that
    @ac.describe(callsign="The callsign of the unit to search for")
    @ac.describe(unit_type="The type of the unit to search for (This must be the exact name, use the autocomplete)")
    @ac.describe(upgrade="The upgrade to search for")
    @ac.describe(campaign="The campaign to search for (This must be the exact name, use the autocomplete)")
    @ac.autocomplete(name=fuzzy_autocomplete(Unit.name),
                     callsign=fuzzy_autocomplete(Unit.callsign),
                     unit_type=fuzzy_autocomplete(UnitType.unit_type),
                     upgrade=fuzzy_autocomplete(ShopUpgrade.name),
                     campaign=fuzzy_autocomplete(Campaign.name)) # we don't need to autocomplete Player, because Member gets client side autocomplete anyway
    @uses_db(CustomClient().sessionmaker)
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

async def setup(_bot: CustomClient):
    """
    Asynchronous setup function to add the Search cog to the bot.

    Args:
        _bot (CustomClient): The bot instance to add this cog to.
    """
    logger.info("Setting up Search cog")
    await _bot.add_cog(Search(_bot))


async def teardown(_bot: CustomClient):
    """
    Asynchronous teardown function to remove the Search cog from the bot.
    """
    logger.info("Tearing down Search cog")
    _bot.remove_cog(Search.__name__)  # remove_cog takes a string, not a class
