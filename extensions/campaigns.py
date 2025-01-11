from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, Member, Role, Embed
from models import Campaign, UnitStatus, CampaignInvite, Player
from utils import uses_db
from sqlalchemy.orm import Session
from customclient import CustomClient
logger = getLogger(__name__)
class Campaigns(GroupCog):
    def __init__(self, bot: CustomClient):
        self.bot = bot
    
    @staticmethod
    async def is_management(interaction: Interaction):
        valid = any(role in interaction.user.roles for role in [interaction.guild.get_role(role_id) for role_id in CustomClient().mod_roles])
        logger.info(f"{interaction.user.name} is management: {valid}")
        return valid
    
    @staticmethod
    async def is_gm(interaction: Interaction):
        is_management = await Campaigns.is_management(interaction)
        is_gm = interaction.guild.get_role(CustomClient().gm_role) in interaction.user.roles
        logger.info(f"{interaction.user.name} is management: {is_management}, is gm: {is_gm}")
        valid = is_gm or is_management
        if not valid:
            await interaction.response.send_message("You don't have permission to run this command", ephemeral=True)
        return valid

    @ac.command(name="create", description="Create a campaign")
    @ac.check(is_gm)  
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def create(self, interaction: Interaction, name: str, session: Session, gm: Member|None = None, ):
        if gm is None:
            gm = interaction.user
        if gm != interaction.user:
            if not await self.is_management(interaction):
                logger.error(f"{interaction.user.name} is not management, cannot create campaign for {gm.name}")
                await interaction.response.send_message(f"GMs cannot create campaigns for other GMs, ask a bot Manager to do this", ephemeral=True)
                return
        # check if the gm has either management or GM role, bot.mod_roles is a set, bot.gm_role is an int
        is_gm = interaction.guild.get_role(self.bot.gm_role) in interaction.user.roles
        management_roles = [interaction.guild.get_role(role_id) for role_id in self.bot.mod_roles if role_id != self.bot.gm_role]
        if not any(role in interaction.user.roles for role in management_roles) and not is_gm:
            logger.error(f"{gm.name} doesn't have the GM role, and is not in the management role list")
            await interaction.response.send_message(f"{gm.mention} doesn't have permission to be a GM", ephemeral=True)
            return
        if len(name) > 30:
            logger.error(f"Campaign name {name} is too long")
            await interaction.response.send_message("Campaign name must be less than 30 characters", ephemeral=True)
            return
        # check if the campaign name is already taken
        if session.query(Campaign).filter(Campaign.name == name).first():
            logger.error(f"Campaign name {name} already taken")
            await interaction.response.send_message("Campaign name already taken", ephemeral=True)
            return
        # create the campaign
        campaign = Campaign(name=name, gm=gm.id)
        session.add(campaign)
        logger.info(f"Campaign {name} created by {gm.name}")
        await interaction.response.send_message(f"Campaign {name} created", ephemeral=True)
        
    @ac.command(name="open", description="Open a campaign for signups")
    @ac.check(is_gm)
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def open(self, interaction: Interaction, campaign: str, session: Session, role: Role|None = None, limit: int|None = None):
        # do checks, then set open to true, and if specified set the role and limit
        # check if the campaign exists
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        # check if the user has permission, either management or this campaign's GM
        if not await self.is_management(interaction) and interaction.user.id != int(_campaign.gm):
            logger.error(f"{interaction.user.name} does not have permission to open campaign {campaign}")
            await interaction.response.send_message("You don't have permission to open this campaign", ephemeral=True)
            return
        # set the campaign to open
        _campaign.open = True
        if role:
            _campaign.required_role = role.id
        else:
            _campaign.required_role = None
        if limit:
            _campaign.player_limit = limit
        else:
            _campaign.player_limit = None
        logger.info(f"Campaign {campaign} opened")
        await interaction.response.send_message(f"Campaign {campaign} opened", ephemeral=True)

    @ac.command(name="close", description="Close a campaign for signups")
    @ac.check(is_gm)
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def close(self, interaction: Interaction, campaign: str, session: Session):
        # do checks, then set open to false and clear the role and limit fields
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        # check if the user has permission, either management or this campaign's GM
        if not await self.is_management(interaction) and interaction.user.id != int(_campaign.gm):
            logger.error(f"{interaction.user.name} does not have permission to close campaign {campaign}")
            await interaction.response.send_message("You don't have permission to close this campaign", ephemeral=True)
            return
        _campaign.open = False
        _campaign.required_role = None
        _campaign.player_limit = None
        logger.info(f"Campaign {campaign} closed")
        await interaction.response.send_message(f"Campaign {campaign} closed", ephemeral=True)

    @ac.command(name="remove", description="Remove a campaign")
    @ac.check(is_gm)
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def remove(self, interaction: Interaction, campaign: str, session: Session):
        # do checks, deactivate all players, delete the campaign
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        # check if the user has permission, either management or this campaign's GM
        if not await self.is_management(interaction) and interaction.user.id != int(_campaign.gm):
            logger.error(f"{interaction.user.name} does not have permission to remove campaign {campaign}")
            await interaction.response.send_message("You don't have permission to remove this campaign", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        # deactivate all units
        for unit in _campaign.units:
            unit.active = False
            unit.callsign = None
            unit.campaign_id = None
            unit.status = UnitStatus.INACTIVE if unit.status == UnitStatus.ACTIVE else unit.status
            self.bot.queue.put_nowait((1, unit.player, 0))
        # delete all invites because they are no longer valid
        invites = session.query(CampaignInvite).filter(CampaignInvite.campaign_id == _campaign.id).all()
        for invite in invites:
            session.delete(invite)
        session.flush()
        # delete the campaign
        session.delete(_campaign)
        session.flush()
        logger.info(f"Campaign {campaign} removed")
        await interaction.followup.send(f"Campaign {campaign} removed", ephemeral=True)

    @ac.command(name="payout", description="Payout a campaign")
    @ac.check(is_gm)
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def payout(self, interaction: Interaction, campaign: str, session: Session, base: int, survivor: int):
        # do checks, then payout all players in the campaign
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        # check if the user has permission, either management or this campaign's GM
        if not await self.is_management(interaction) and interaction.user.id != int(_campaign.gm):
            logger.error(f"{interaction.user.name} does not have permission to payout campaign {campaign}")
            await interaction.response.send_message("You don't have permission to payout this campaign", ephemeral=True)
            return
        # payout all players in the campaign
        for unit in _campaign.units:
            unit.player.rec_points += base
            if unit.status == UnitStatus.ACTIVE:
                unit.player.rec_points += survivor
            self.bot.queue.push_nowait((1, unit.player, 0))
        await interaction.response.send_message(f"Campaign {campaign} payout complete", ephemeral=True)

    @ac.command(name="invite", description="Invite a player to a campaign")
    @ac.check(is_gm)
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def invite(self, interaction: Interaction, campaign: str, session: Session, player: Member):
        # do checks, then add an invite to the campaign for the player
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        # check if the user has permission, either management or this campaign's GM
        if not await self.is_management(interaction) and interaction.user.id != int(_campaign.gm):
            logger.error(f"{interaction.user.name} does not have permission to invite to campaign {campaign}")
            await interaction.response.send_message("You don't have permission to invite to this campaign", ephemeral=True)
            return
        _player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not _player:
            logger.error(f"Player {player.name} doesn't have a Meta Campaign company")
            await interaction.response.send_message("Player doesn't have a Meta Campaign company", ephemeral=True)
            return
        session.add(CampaignInvite(campaign_id=_campaign.id, player_id=_player.id))
        logger.info(f"Player {player.name} invited to {campaign}")
        await interaction.response.send_message(f"Player {player.mention} invited to {campaign}", ephemeral=False) # don't hide this so the recipient gets a ping

    @ac.command(name="deactivate", description="Remove a player from a campaign")
    @ac.check(is_gm)
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def deactivate(self, interaction: Interaction, campaign: str, session: Session, player: Member):
        # do checks, then deactivate the unit just like how payout does
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        # check if the user has permission, either management or this campaign's GM
        if not await self.is_management(interaction) and interaction.user.id != int(_campaign.gm):
            logger.error(f"{interaction.user.name} does not have permission to deactivate player from campaign {campaign}")
            await interaction.response.send_message("You don't have permission to deactivate this player", ephemeral=True)
            return
        _player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not _player:
            logger.error(f"Player {player.name} doesn't have a Meta Campaign company")
            await interaction.response.send_message("Player doesn't have a Meta Campaign company", ephemeral=True)
            return
        # deactivate the unit
        # find the intersection between _player.units and _campaign.units
        units_to_deactivate = [unit for unit in _player.units if unit in _campaign.units]
        for unit in units_to_deactivate:
            unit.active = False
            unit.callsign = None
            unit.campaign_id = None
            unit.status = UnitStatus.INACTIVE if unit.status == UnitStatus.ACTIVE else unit.status
        logger.info(f"Player {player.name} deactivated from {campaign}")
        await interaction.response.send_message(f"Player {player.mention} deactivated from {campaign}", ephemeral=True)
        self.bot.queue.put_nowait((1, _player, 0))

    @ac.command(name="list", description="List all campaigns")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def list(self, interaction: Interaction, session: Session):
        # no checks, return the list of all campaigns, their status, and the mention of the GM
        campaigns = session.query(Campaign).all()
        embed = Embed(title="Campaigns", type="rich")
        for campaign in campaigns:
            gm: Member|None = await interaction.guild.fetch_member(campaign.gm)
            if campaign.required_role:
                required_role: Role|None = interaction.guild.get_role(campaign.required_role)
            else:
                required_role = None
            logger.debug(f"Campaign '{campaign.name}' has {len(campaign.units)} players")
            embed.add_field(name=campaign.name, value=f"Status: {campaign.open}, "
                            f"GM: {gm.mention if gm else 'Unknown'}, "
                            f"Players: {len(campaign.units)}, "
                            f"Required Role: {required_role.mention if required_role else 'None'}")
        if len(campaigns) == 0:
            embed.add_field(name="No campaigns", value="There are no campaigns")
        await interaction.response.send_message(embed=embed, ephemeral=True)

bot: Bot = None
async def setup(_bot: CustomClient):
    global bot
    bot = _bot
    await bot.add_cog(Campaigns(bot))

async def teardown():
    bot.remove_cog(Campaigns.__name__) # remove_cog takes a string, not a class

"""
you need either GM or Management to run any campaign commands
/campaign create name: gm:self - only Management can input a GM, for GMs it's always self
/campaign open role: limit: - allows the campaign to be selected in unit activate, role if specified requires that role to sign up, limit if specified limits the player count
/campaign invite member: - sends someone an invite
/campaign deactivate member: - removes a player from the campaign
/campaign close - blocks signups
/campaign payout base: survivor: - pays out all active units {base} req and all living active units an additional {survivor} req
/campaign remove - deletes a campaign
/campaign list - lists all campaigns
all commands give a dropdown with the valid campaigns, if you have management valid is all campaigns, otherwise it's only campaigns you are the GM"""