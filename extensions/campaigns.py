from io import BytesIO
from logging import getLogger
from typing import List, Optional
from asyncio import gather
import random

from discord import Interaction, app_commands as ac, Member, Role, Embed, File, TextStyle
from discord.ext.commands import GroupCog
from discord.ui import Modal, TextInput
from sqlalchemy import text, not_, func
from sqlalchemy.orm import Session
from templates import Statistics_Unit, notify_no_players

from customclient import CustomClient
from models import Campaign, UnitHistory, UnitStatus, CampaignInvite, Player, Unit
from utils import EnvironHelpers, maybe_decorate, uses_db, is_dm, check_notify, fuzzy_autocomplete, chunked_join

logger = getLogger(__name__)


class Campaigns(GroupCog, description="Campaign commands: list, join, leave, view. GM and management checks apply."):
    """
    Cog for campaign-related slash commands: list campaigns, join, leave,
    and view campaign details. GM and management checks apply where needed.
    """

    def __init__(self, bot: CustomClient):
        """Store a reference to the bot instance."""

        self.bot = bot

    @staticmethod
    async def is_management(interaction: Interaction):
        logger.debug(f"Checking if {interaction.user.name} is management")
        if await is_dm(interaction):
            return False
        valid = any(role in interaction.user.roles for role in [interaction.guild.get_role(role_id) for role_id in CustomClient().mod_roles])
        logger.info(f"{interaction.user.name} is management: {valid}")
        return valid

    @staticmethod
    @check_notify(message="You are not a Game Master, and cannot run this command")
    async def is_gm(interaction: Interaction):
        logger.debug(f"Checking if {interaction.user.name} is GM")
        if await is_dm(interaction):
            await interaction.response.send_message("This command cannot be run in a DM", ephemeral=True)
            return False
        is_management = await Campaigns.is_management(interaction)
        is_gm = interaction.guild.get_role(CustomClient().gm_role) in interaction.user.roles
        logger.info(f"{interaction.user.name} is management: {is_management}, is gm: {is_gm}")
        valid = is_gm or is_management
        if not valid:
            await interaction.response.send_message("You don't have permission to run this command", ephemeral=True)
        return valid

    @ac.command(name="create", description="Create a campaign")
    @ac.check(is_gm)
    @uses_db(CustomClient().sessionmaker)
    async def create(self, interaction: Interaction, name: str, session: Session, gm: Member|None = None, ):
        if gm is None:
            gm = interaction.user
        if gm != interaction.user:
            if not await self.is_management(interaction):
                logger.error(f"{interaction.user.name} is not management, cannot create campaign for {gm.name}")
                await interaction.response.send_message(f"GMs cannot create campaigns for other GMs, ask a bot Manager to do this", ephemeral=True)
                return
        # check if the gm has either management or GM role, bot.mod_roles is a set, bot.gm_role is an int
        is_gm = interaction.guild.get_role(self.bot.gm_role) in gm.roles
        management_roles = [interaction.guild.get_role(role_id) for role_id in self.bot.mod_roles if role_id != self.bot.gm_role]
        if not any(role in interaction.user.roles for role in management_roles) and not is_gm:
            logger.error(f"{gm.name} doesn't have the GM role, and is not in the management role list")
            await interaction.response.send_message(f"{gm.mention} doesn't have permission to be a GM", ephemeral=True)
            return
        if len(name) > 30:
            logger.error(f"Campaign name {name} is too long")
            await interaction.response.send_message("Campaign name must be less than 30 characters", ephemeral=True)
            return
        if '#' in name:
            logger.error(f"Campaign name {name} contains a '#'")
            await interaction.response.send_message("Campaign name cannot contain a '#' due to discord autocompletion", ephemeral=True)
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
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
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
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
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
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
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
            unit.battle_group = None
            unit.unit_history.append(UnitHistory(campaign_name=campaign))
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
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
    async def payout(self, interaction: Interaction, campaign: str, session: Session, base_req: int=0, survivor_req: int=0, base_bp: int=0, survivor_bp: int=0):
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
        logger.info(f"Paying out campaign {campaign} with base_req={base_req}, survivor_req={survivor_req}, base_bp={base_bp}, survivor_bp={survivor_bp}")

        # Get all players and live players using the new relationships
        all_players = _campaign.players
        live_players = _campaign.live_players
        dead_players = all_players - live_players  # Set algebra to get players with no active units

        logger.debug(f"Campaign {campaign}: {len(all_players)} total players, {len(live_players)} live players, {len(dead_players)} dead players")

        # Payout base rewards to all players in the campaign
        for player in all_players:
            logger.debug(f"Paying out base rewards to {player.name} for {campaign}")
            player.rec_points += base_req
            player.bonus_pay += base_bp

        # Payout survivor rewards only to players with active units
        for player in live_players:
            logger.debug(f"Paying out survivor rewards to {player.name} for {campaign}")
            player.rec_points += survivor_req
            player.bonus_pay += survivor_bp

        session.commit()
        await interaction.response.defer(ephemeral=True)

        # Queue updates for all affected players
        for player in all_players:
            logger.debug(f"Putting {player.name} in update queue for {campaign}")
            self.bot.queue.put_nowait((1, player, 0))

        await interaction.followup.send(f"Campaign {campaign} payout complete", ephemeral=True)

    @ac.command(name="invite", description="Invite a player to a campaign")
    @ac.check(is_gm)
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
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
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
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
            unit.battle_group = None
        logger.info(f"Player {player.name} deactivated from {campaign}")
        await interaction.response.send_message(f"Player {player.mention} deactivated from {campaign}", ephemeral=True)
        self.bot.queue.put_nowait((1, _player, 0))

    @ac.command(name="list", description="List all campaigns")
    @uses_db(CustomClient().sessionmaker)
    async def list(self, interaction: Interaction, session: Session):
        # no checks, return the list of all campaigns, their status, and the mention of the GM
        campaigns = session.query(Campaign).all()
        embed = Embed(title="Campaigns", type="rich")
        if not interaction.guild:
            await interaction.response.send_message("This command can only be run in a server", ephemeral=True)
            return
        for campaign in campaigns:
            gm: Member|None = await interaction.guild.fetch_member(campaign.gm)
            if campaign.required_role:
                required_role: Role|None = interaction.guild.get_role(campaign.required_role)
            else:
                required_role = None
            player_count = session.query(func.count(Unit.id)).filter(Unit.campaign_id == campaign.id).scalar()
            logger.debug(f"Campaign '{campaign.name}' has {player_count} players")
            embed.add_field(name=campaign.name, value=f"Status: {'Open' if campaign.open else 'Closed'}, "
                            f"GM: {gm.mention if gm else 'Unknown'}, "
                            f"Players: {player_count}, "
                            f"Required Role: {required_role.mention if required_role else 'None'}")
        if len(campaigns) == 0:
            embed.add_field(name="No campaigns", value="There are no campaigns")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ac.command(name="kill", description="Kill a unit")
    @uses_db(CustomClient().sessionmaker)
    async def kill(self, interaction: Interaction, session: Session, callsign: str, is_mia: bool = False):
        # do gm checks, then kill the unit, if is_mia is true, set the status to MIA, otherwise set the status to KIA
        _unit = session.query(Unit).filter(Unit.callsign == callsign).first()
        if not _unit:
            logger.error(f"Unit {callsign} not found")
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        # check if the user has permission, either management or this campaign's GM
        if not await self.is_management(interaction) and interaction.user.id != int(_unit.campaign.gm):
            logger.error(f"{interaction.user.name} does not have permission to kill unit {callsign}")
            await interaction.response.send_message("You don't have permission to kill this unit", ephemeral=True)
            return
        # check if the unit is Active, if not fail
        if _unit.status != UnitStatus.ACTIVE:
            logger.error(f"Unit {callsign} is not active")
            await interaction.response.send_message("Unit is not active", ephemeral=True)
            return
        # kill the unit
        _unit.status = UnitStatus.KIA if not is_mia else UnitStatus.MIA
        logger.info(f"Unit {callsign} killed" + (" as MIA" if is_mia else ""))
        await interaction.response.send_message(f"Unit {callsign} killed" + (" as MIA" if is_mia else ""), ephemeral=True)

    @ac.command(name="raffle", description="Bring the unit count down through random selection")
    @ac.check(is_gm)
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
    async def raffle(self, interaction: Interaction, session: Session, campaign: str, count: int):
        # do gm checks, then bring the unit count down through random selection
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        # check if the user has permission, either management or this campaign's GM
        if not await self.is_management(interaction) and interaction.user.id != int(_campaign.gm):
            logger.error(f"{interaction.user.name} does not have permission to raffle units from campaign {campaign}")
            await interaction.response.send_message("You don't have permission to raffle units", ephemeral=True)
            return
        # raffle the units
        units: list[Unit] = [unit for unit in _campaign.units if unit.status == UnitStatus.ACTIVE]
        units: set[Unit] = set(units)
        if len(units) < count:
            logger.error(f"Campaign {campaign} has less than {count} active units but a raffle was attempted")
            await interaction.response.send_message("Campaign has less than the requested number of active units", ephemeral=True)
            return
        if count <= 0:
            logger.error(f"Raffle count {count} is less than 0")
            await interaction.response.send_message("Raffle count must be greater than 0", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        dropped_units = random.sample(units, len(units) - count)
        kept_units = units - set(dropped_units)
        dropped_players = set([unit.player for unit in dropped_units])
        for unit in dropped_units:
            unit.status = UnitStatus.INACTIVE
            unit.callsign = None
            unit.campaign_id = None
            unit.active = False
        logger.info(f"Raffled {count} units from {campaign}")
        await interaction.followup.send(f"Raffled {count} units from {campaign}", ephemeral=True)
        for unit in kept_units:
            try:
                player: Player = unit.player
                member: Member|None = await interaction.guild.fetch_member(player.discord_id)
                if member:
                    await member.send(f"Your unit {unit.callsign} was kept in the campaign {campaign}")
                else:
                    logger.error(f"Player {player.discord_id} not found")
            except Exception as e:
                logger.error(f"Error sending message to player {player.discord_id}: {e}")
        for unit in dropped_units:
            try:
                player: Player = unit.player
                member: Member|None = await interaction.guild.fetch_member(player.discord_id)
                if member:
                    await member.send(f"Your unit {unit.name} was dropped from the campaign {campaign}")
                else:
                    logger.error(f"Player {player.discord_id} not found")
            except Exception as e:
                logger.error(f"Error sending message to player {player.discord_id}: {e}")
        session.commit()
        for player in dropped_players:
            self.bot.queue.put_nowait((1, player, 0))

    @ac.command(name="list_players", description="List all players in a campaign")
    @ac.check(is_gm)
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
    async def list_players(self, interaction: Interaction, session: Session, campaign: str):

        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        logger.debug(f"Listing players for campaign {campaign}")
        units = _campaign.units
        logger.debug(f"Found {len(units)} units")
        text = ""
        await interaction.response.defer(ephemeral=True)
        async def make_text(unit: Unit):
            player: Player = unit.player
            member: Member|None = interaction.guild.get_member(int(player.discord_id))
            if member:
                return f"{member.display_name} - {unit.callsign} - {unit.unit_type}\n"
            else:
                return f"{player.discord_id} - {unit.callsign} - {unit.unit_type}\n"
        texts = await gather(*[make_text(unit) for unit in units])
        text = "".join(texts)
        logger.debug(f"Text generated")
        file = BytesIO(text.encode())
        attachment = File(file, filename="players.txt")
        await interaction.followup.send("Here are the players in the campaign", ephemeral=True, file=attachment)

    @ac.command(name="counts_by_unit_type", description="List the number of units by unit type")
    #@ac.check(is_gm)
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
    async def counts_by_unit_type(self, interaction: Interaction, session: Session, campaign: str):
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        query = text("""
        SELECT
            u.unit_type,
            COUNT(*) AS unit_count,
            COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () AS percentage
        FROM units u
        JOIN campaigns c ON u.campaign_id = c.id
        WHERE c.name = :campaign_name
        GROUP BY u.unit_type;
    """)
        result = session.execute(query, {"campaign_name": campaign})
        columns = result.keys()
        rows = result.fetchall()
        ouptput = "\n".join(['\t '.join(columns)] + ["\t ".join(map(str, row)) for row in rows])
        file = BytesIO(ouptput.encode())
        attachment = File(file, filename="counts_by_unit_type.txt")
        await interaction.response.send_message("Here are the counts by unit type", ephemeral=True, file=attachment)

    @ac.command(name="limit_types", description="Limit the types of units that can be used in a campaign")
    @ac.check(is_gm)
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
    async def limit_types(self, interaction: Interaction, session: Session, campaign: str):
        # do checks, then give a modal to take the list of unit types as a NSV string
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        # check if you are the GM or a bot manager
        if not await self.is_management(interaction) and interaction.user.id != int(_campaign.gm):
            logger.error(f"{interaction.user.name} does not have permission to limit types for campaign {campaign}")
            await interaction.response.send_message("You don't have permission to limit types for this campaign", ephemeral=True)
            return
        modal = Modal(title="Limit Types", custom_id="limit_types")
        modal.add_item(TextInput(label="Instructions", style=TextStyle.short, placeholder="Delete the types you don't want to allow, There is no need to edit this text", max_length=1)) # only allow 1 character because it's just instructions
        type_list = session.query(Unit.unit_type).filter(Unit.campaign_id == _campaign.id).distinct().all()
        type_list = [unit_type[0] for unit_type in type_list]
        modal.add_item(TextInput(label="Unit Types", style=TextStyle.paragraph, custom_id="unit_types", default="\n".join(type_list)))
        async def on_submit(interaction: Interaction):
            await interaction.response.defer(ephemeral=True)
            campaign_id = session.query(Campaign.id).filter(Campaign.name == campaign).scalar()
            if not campaign_id:
                logger.error(f"Campaign {campaign} not found")
                await interaction.followup.send("Campaign not found", ephemeral=True)
                return
            unit_types = interaction.data["components"][0]["components"][1]["value"]
            logger.debug(f"Unit types: {unit_types}")
            # unit_types is a NSV string, split it into a list of types for the query
            unit_types = unit_types.split("\n")
            unit_types = [unit_type.strip() for unit_type in unit_types if unit_type.strip()]
            # use not_ in_ to get all invalid units
            invalid_units = session.query(Unit).filter(not_(Unit.unit_type.in_(unit_types)), Unit.campaign_id == campaign_id).all()
            for unit in invalid_units:
                unit.status = UnitStatus.INACTIVE
                unit.callsign = None
                unit.campaign_id = None
                unit.active = False
                self.bot.queue.put_nowait((1, unit.player, 0))
            await interaction.followup.send(f"Unit types: {unit_types}", ephemeral=True)
            logger.info(f"Limited unit types for campaign {campaign}")
            for unit in invalid_units:
                try:
                    player: Player = unit.player
                    member: Member|None = await interaction.guild.fetch_member(player.discord_id)
                    if member:
                        await member.send(f"Your unit {unit.name} was dropped from the campaign {campaign} because it is not one of the allowed types")
                    else:
                        logger.error(f"Player {player.discord_id} not found")
                except Exception as e:
                    logger.error(f"Error sending message to player {player.discord_id}: {e}")

        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

    @ac.command(name="merge", description="Merge two campaigns")
    @ac.check(is_gm)
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name), other_campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
    async def merge(self, interaction: Interaction, session: Session, campaign: str, other_campaign: str):
        # do checks, then merge the two campaigns
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        _other_campaign = session.query(Campaign).filter(Campaign.name == other_campaign).first()
        if not _other_campaign:
            logger.error(f"Campaign {other_campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        # check if the user has permission, either management or this campaign's GM
        if not await self.is_management(interaction):
            if interaction.user.id != int(_campaign.gm) or interaction.user.id != int(_other_campaign.gm):
                logger.error(f"{interaction.user.name} does not have permission to merge campaigns {campaign} and {other_campaign}")
                await interaction.response.send_message("You don't have permission to merge these campaigns", ephemeral=True)
                return
        # merge the two campaigns
        units = _other_campaign.units
        for unit in units:
            unit.campaign_id = _campaign.id
        invites = _other_campaign.invites
        for invite in invites:
            session.delete(invite)
        session.delete(_other_campaign)
        session.commit()
        logger.info(f"Merged campaigns {campaign} and {other_campaign}")
        await interaction.response.send_message(f"Merged campaigns {campaign} and {other_campaign}", ephemeral=True)

    @ac.command(name="unit_lookup", description="Lookup a unit by callsign")
    @uses_db(CustomClient().sessionmaker)
    async def unit_lookup(self, interaction: Interaction, session: Session, callsign: Optional[str] = None):
        # if the callsign is None, send a modal to take an NSV of callsigns
        if callsign is None:
            modal = Modal(title="Unit Lookup", custom_id="unit_lookup")
            modal.add_item(TextInput(label="Callsigns", style=TextStyle.paragraph, custom_id="callsigns"))
            async def on_submit(interaction: Interaction):
                await interaction.response.defer(ephemeral=True)
                callsigns = interaction.data["components"][0]["components"][0]["value"]
                callsigns = callsigns.split("\n")
                callsigns = [callsign.strip() for callsign in callsigns if callsign.strip()]
                if len(callsigns) == 0:
                    await interaction.followup.send("No callsigns provided", ephemeral=True)
                    return
                messages = await self._unit_lookup(session, callsigns)
                if not messages:
                    await interaction.followup.send("No units found", ephemeral=True)
                    return
                if not messages:
                    await interaction.followup.send("No units found", ephemeral=True)
                    return
                if len(messages) > 2000:
                    file = BytesIO(messages.encode())
                    attachment = File(file, filename="units.txt")
                    await interaction.followup.send("Here are the units", ephemeral=True, file=attachment)
                else:
                    await interaction.followup.send(messages, ephemeral=True)
            modal.on_submit = on_submit
            await interaction.response.send_modal(modal)
        else:
            callsigns = [callsign]
            messages = await self._unit_lookup(session, callsigns)
            if not messages:
                await interaction.response.send_message("No units found", ephemeral=True)
                return
            if len(messages) > 2000:
                file = BytesIO(messages.encode())
                attachment = File(file, filename="units.txt")
                await interaction.response.send_message("Here are the units", ephemeral=True, file=attachment)
            else:
                await interaction.response.send_message(messages, ephemeral=True)

    async def _unit_lookup(self, session: Session, callsigns: List[str]) -> str:
        # do checks, then lookup the units by callsign
        units = session.query(Unit).filter(Unit.callsign.in_(callsigns)).all()
        messages = []
        for unit in units:
            upgrade_list = ", ".join([upgrade.name for upgrade in unit.upgrades])
            messages.append(Statistics_Unit.format(unit=unit, upgrades=upgrade_list, callsign=('\"' + unit.callsign + '\"') if unit.callsign else "", campaign_name=f"In {unit.campaign.name}" if unit.campaign else ""))
        return "\n".join(messages)

    @ac.command(name="notify", description="Notify all players in a campaign")
    @ac.check(is_gm)
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name))
    @uses_db(CustomClient().sessionmaker)
    async def notify(self, interaction: Interaction, session: Session, campaign: str, message: str = None):
        # do checks, then do '<@' || discord_id || '>' for each player in the campaign
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        if not await self.is_management(interaction) and interaction.user.id != int(_campaign.gm):
            logger.error(f"{interaction.user.name} does not have permission to notify players in campaign {campaign}")
            await interaction.response.send_message("You don't have permission to notify players in this campaign", ephemeral=True)
            return
        chunks = chunked_join(
            (m for (m,) in session.query(Player.mention).join(Unit).filter(Unit.campaign_id == _campaign.id).distinct().yield_per(100)),
            separator=" " # we want to space them, not newline them, so it takes up less discord ui space
        )
        if message:
            chunks.append(message)
        first = next(chunks, None)
        if first:
            await interaction.response.send_message(first, ephemeral=False)
            for chunk in chunks:
                await interaction.followup.send(chunk)
            logger.info(f"Notified players in campaign {campaign}")
        else:
            logger.info(f"No players found in campaign {campaign}")
            await interaction.response.send_message(notify_no_players, ephemeral=True)

    @maybe_decorate(EnvironHelpers.get_bool("ALLOW_NOTIFY_GROUP_COMMAND"), ac.command(name="notify_group", description="Notify a group of players within a campaign"))
    @maybe_decorate(EnvironHelpers.get_bool("RESTRICT_NOTIFY_GROUP_COMMAND"), ac.check(is_gm))
    @ac.autocomplete(campaign=fuzzy_autocomplete(Campaign.name), group=fuzzy_autocomplete(Unit.battle_group))
    @ac.describe(campaign="The campaign that the group is in", group="The group to notify")
    @uses_db(CustomClient().sessionmaker)
    async def notify_group(self, interaction: Interaction, session: Session, campaign: str, group: str, message: str = None):
        # do checks, then notify the group of players in the campaign
        _campaign = session.query(Campaign).filter(Campaign.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        # no need for permission checks, because we have the check decorator, and it's either public or any GM
        # this is almost identical to the notify command, but with an additional filter on Unit.group
        chunks = chunked_join(
            (m for (m,) in session.query(Player.mention).join(Unit).filter(Unit.battle_group == group, Unit.campaign_id == _campaign.id).distinct().yield_per(100)),
            separator=" " # we want to space them, not newline them, so it takes up less discord ui space
        )
        if message:
            chunks.append(message)
        first = next(chunks, None)
        if first:
            await interaction.response.send_message(first, ephemeral=False)
            for chunk in chunks:
                await interaction.followup.send(chunk)
            logger.info(f"Notified group {group} in campaign {campaign}")
        else:
            logger.info(f"No players found in group {group} in campaign {campaign}")
            await interaction.response.send_message(notify_no_players, ephemeral=True)

async def setup(_bot: CustomClient):
    await _bot.add_cog(Campaigns(_bot))


async def teardown(_bot: CustomClient):
    _bot.remove_cog(Campaigns.__name__)  # remove_cog takes a string, not a class
