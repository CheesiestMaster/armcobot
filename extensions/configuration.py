from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, ChannelType
from models import Config as Config_model, Dossier, Player, Statistic
from customclient import CustomClient
from utils import uses_db
from sqlalchemy.orm import Session
import templates as tmpl
logger = getLogger(__name__)

class Config(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
 
        self.interaction_check = self.is_mod

    async def is_mod(self, interaction: Interaction):
        """
        Check if the user is a moderator with the necessary role.
        """
        valid = any(interaction.user.get_role(role) for role in self.bot.mod_roles)
        if not valid:
            logger.warning(f"{interaction.user.name} tried to use admin commands")
        return valid
    
    async def is_owner(self, interaction: Interaction):
        valid = interaction.user.id in self.bot.owner_ids
        # this is_owner is used for the setnick, and called on all uses of it, but it's only used for scoping, not for permission, so no logging
        return valid
    
    @ac.command(name="setnick", description="Set the bot's nickname")
    async def setnick(self, interaction: Interaction, nick: str):
        if self.is_owner(interaction):
            logger.info(f"Setting bot nickname to {nick} globally")
            await self.bot.set_bot_nick(nick)
            await interaction.response.send_message(f"Bot nickname globally set to {nick}", ephemeral=self.bot.use_ephemeral)
        elif interaction.user.guild_permissions.manage_nicknames:
            logger.info(f"Setting bot nickname to {nick} in {interaction.guild.name}")
            await interaction.guild.me.edit(nick=nick)
            await interaction.response.send_message(f"Bot nickname in {interaction.guild.name} set to {nick}", ephemeral=self.bot.use_ephemeral)
        else:
            logger.info(f"User {interaction.user.display_name} does not have permission to set the bot's nickname in {interaction.guild.name}")
            await interaction.response.send_message(tmpl.no_permission_set_nickname, ephemeral=self.bot.use_ephemeral)

    @ac.command(name="setdossier", description="Set the dossier channel to the current channel")
    @uses_db(CustomClient().sessionmaker)
    async def setdossier(self,interaction: Interaction, session: Session):
        if interaction.channel.type != ChannelType.text:
            await interaction.response.send_message(tmpl.text_channel_only, ephemeral=self.bot.use_ephemeral)
            return
        self.bot.config["dossier_channel_id"] = interaction.channel.id
        await self.bot.resync_config(session=session)
        logger.info(f"Dossier channel set to {interaction.channel.name}")
        old_dossiers = session.query(Dossier).all()
        for dossier in old_dossiers:
            session.delete(dossier)
        session.commit()
        for player in session.query(Player).all():
            self.bot.queue.put_nowait((0, player))
        await interaction.response.send_message(f"Dossier channel set to {interaction.channel.mention}", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="setstatistics", description="Set the statistics channel to the current channel")
    @uses_db(CustomClient().sessionmaker)
    async def setstatistics(self,interaction: Interaction, session: Session):
        if interaction.channel.type != ChannelType.text:
            await interaction.response.send_message(tmpl.text_channel_only, ephemeral=self.bot.use_ephemeral)
            return
        self.bot.config["statistics_channel_id"] = interaction.channel.id
        await self.bot.resync_config(session=session)
        logger.info(f"Statistics channel set to {interaction.channel.name}")
        old_statistics = session.query(Statistic).all()
        for statistic in old_statistics:
            session.delete(statistic)
        session.commit()
        for player in session.query(Player).all():
            self.bot.queue.put_nowait((0, player))
        await interaction.response.send_message(f"Statistics channel set to {interaction.channel.mention}", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="list_configs", description="List all configurations")
    @uses_db(CustomClient().sessionmaker)
    async def list_configs(self, interaction: Interaction, session: Session):
        configs = session.query(Config_model).all()
        config_list = [f"{config.key}: {config.value}" for config in configs]
        config_str = "\n".join(config_list)
        await interaction.response.send_message(f"Configurations:\n{config_str}", ephemeral=self.bot.use_ephemeral)

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    logger.info("Setting up Configuration cog")
    await bot.add_cog(Config(bot))

async def teardown():
    logger.info("Tearing down Configuration cog")
    bot.remove_cog(Config.__name__) # remove_cog takes a string, not a class
