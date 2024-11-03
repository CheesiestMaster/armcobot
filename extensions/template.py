from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac
logger = getLogger(__name__)

class CogClass(GroupCog):
    pass # this is a template file, so no code is needed here

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    await bot.add_cog(CogClass(bot))

async def teardown():
    bot.remove_cog(CogClass.__name__) # remove_cog takes a string, not a class