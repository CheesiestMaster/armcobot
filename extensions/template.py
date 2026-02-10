from logging import getLogger

from discord import Interaction, app_commands as ac
from discord.ext.commands import GroupCog

from customclient import CustomClient

logger = getLogger(__name__)

class CogClass(GroupCog, description="Template cog; copy to create a new extension."):
    """
    Template cog with no commands. Copy this file to create a new extension.
    """

    pass  # this is a template file, so no code is needed here

async def setup(_bot: CustomClient):
    await _bot.add_cog(CogClass(_bot))


async def teardown(_bot: CustomClient):
    _bot.remove_cog(CogClass.__name__)  # remove_cog takes a string, not a class