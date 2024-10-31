from logging import getLogger
from discord.ext.commands import Cog
from discord import Client
logger = getLogger(__name__)

class CogClass(Cog):
    pass # this is a template file, so no code is needed here

bot: Client = None
async def setup(_bot: Client):
    global bot
    bot = _bot
    await bot.add_cog(CogClass(bot))

async def teardown():
    bot.remove_cog(CogClass.__name__) # remove_cog takes a string, not a class