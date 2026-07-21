from itertools import chain
from logging import getLogger
from typing import Awaitable, Callable

from discord import ButtonStyle, Guild, Interaction, SelectOption, TextStyle, app_commands as ac, User, Member, Role, Embed
from discord.ext.commands import GroupCog
from discord.ui import ActionRow, Button, RoleSelect, Section, Select, TextDisplay, TextInput, UserSelect
from sqlalchemy import func
from sqlalchemy.orm import Session
from templates import notify_no_players
import templates as tmpl

from customclient import CustomClient
from models import Campaign as CampaignModel, CampaignInvite, Player, Unit, UnitHistory, UnitStatus
from utils import EnvironHelpers, RecordingModal, error_reporting, maybe_decorate, uses_db, is_dm, check_notify, fuzzy_autocomplete, chunked_join, RecordingLayoutView

logger = getLogger(__name__)

class Campaign2(GroupCog, description="Campaign commands: list, view, and manage campaigns."):
    """
    Campaign commands: list, view, and manage campaigns.
    """

    def __init__(self, bot: CustomClient):
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
        is_management = await Campaign2.is_management(interaction)
        is_gm = interaction.guild.get_role(CustomClient().gm_role) in interaction.user.roles
        logger.info(f"{interaction.user.name} is management: {is_management}, is gm: {is_gm}")
        valid = is_gm or is_management
        if not valid:
            await interaction.response.send_message("You don't have permission to run this command", ephemeral=True)
        return valid

    @ac.command(name="menu", description="Display a menu of campaigns")
    async def menu(self, interaction: Interaction):
        await interaction.response.send_message(view=CampaignSelectLayoutView(interaction.user, await self.is_management(interaction)), ephemeral=True)

    @ac.command(name="list", description="List all campaigns")
    @uses_db(CustomClient().sessionmaker)
    async def list(self, interaction: Interaction, session: Session):
        logger = getLogger(f"{__name__}.list")
        campaigns = session.query(CampaignModel).all()
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
        logger = getLogger(f"{__name__}.kill")
        _unit = session.query(Unit).filter(Unit.callsign == callsign).first()
        if not _unit:
            logger.error(f"Unit {callsign} not found")
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        if not await self.is_management(interaction) and interaction.user.id != int(_unit.campaign.gm):
            logger.error(f"{interaction.user.name} does not have permission to kill unit {callsign}")
            await interaction.response.send_message("You don't have permission to kill this unit", ephemeral=True)
            return
        if _unit.status != UnitStatus.ACTIVE:
            logger.error(f"Unit {callsign} is not active")
            await interaction.response.send_message("Unit is not active", ephemeral=True)
            return
        _unit.status = UnitStatus.KIA if not is_mia else UnitStatus.MIA
        logger.info(f"Unit {callsign} killed" + (" as MIA" if is_mia else ""))
        await interaction.response.send_message(f"Unit {callsign} killed" + (" as MIA" if is_mia else ""), ephemeral=True)

    @maybe_decorate(EnvironHelpers.get_bool("ALLOW_NOTIFY_GROUP_COMMAND"), ac.command(name="notify_group", description="Notify a group of players within a campaign"))
    @maybe_decorate(EnvironHelpers.get_bool("RESTRICT_NOTIFY_GROUP_COMMAND"), ac.check(is_gm))
    @ac.autocomplete(campaign=fuzzy_autocomplete(CampaignModel.name), group=fuzzy_autocomplete(Unit.battle_group))
    @ac.describe(campaign="The campaign that the group is in", group="The group to notify")
    @uses_db(CustomClient().sessionmaker)
    async def notify_group(self, interaction: Interaction, session: Session, campaign: str, group: str, message: str = ""):
        logger = getLogger(f"{__name__}.notify_group")
        _campaign = session.query(CampaignModel).filter(CampaignModel.name == campaign).first()
        if not _campaign:
            logger.error(f"Campaign {campaign} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        chunks = chunked_join(
            chain((m for (m,) in session.query(Player.mention).join(Unit).filter(Unit.battle_group == group, Unit.campaign_id == _campaign.id).distinct().yield_per(100)), [message] if message else []),
            separator=" "
        )
        first = next(chunks, None)
        if first:
            await interaction.response.send_message(first, ephemeral=False)
            for chunk in chunks:
                await interaction.followup.send(chunk)
            logger.info(f"Notified group {group} in campaign {campaign}")
        else:
            logger.info(f"No players found in group {group} in campaign {campaign}")
            await interaction.response.send_message(notify_no_players, ephemeral=True)

class CampaignSelectLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, user: User | Member, management: bool, session: Session):
        super().__init__()
        campaigns = set(session.query(CampaignModel.id, CampaignModel.name, CampaignModel.gm).all())
        
        options = []
        for id, name, gm in campaigns:
            if int(gm) == user.id:
                options.append(SelectOption(label="🧙 " + name, value=str(id)))
                logger.debug(f"Adding campaign {name} to options (GM)")
            elif management:
                options.append(SelectOption(label="👑 " + name, value=str(id)))
                logger.debug(f"Adding campaign {name} to options (Management)")
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        for chunk in chunks:
            select = Select(placeholder="Select a campaign", options=chunk)
            select.callback = self.select_callback
            self.add_item(ActionRow(select))
        add_button = Button(label="Create Campaign", style=ButtonStyle.green, custom_id="create_campaign")
        add_button.callback = self.create_campaign_callback
        self.add_item(ActionRow(add_button))

    @uses_db(CustomClient().sessionmaker)
    async def select_callback(self, interaction: Interaction, session: Session):
        campaign_id = interaction.data['values'][0]
        campaign = session.query(CampaignModel).filter(CampaignModel.id == campaign_id).first()
        if not campaign:
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        await interaction.response.send_message(view=CampaignInfoLayoutView(campaign, interaction.edit_original_response), ephemeral=True)

    async def create_campaign_callback(self, interaction: Interaction):
        modal = CampaignCreateModal()
        await interaction.response.send_modal(modal)

class CampaignCreateModal(RecordingModal):
    
    def __init__(self):
        super().__init__(title="Create Campaign", custom_id="create_campaign")
        self.add_item(TextInput(label="Name", style=TextStyle.short, custom_id="name", required=True))

    async def on_submit(self, interaction: Interaction):
        view = CampaignCreateLayoutView(name=self.children[0].value, user=interaction.user, management=await Campaign2.is_management(interaction))
        await interaction.response.send_message(view=view, ephemeral=True)

class CampaignCreateLayoutView(RecordingLayoutView):
    # just needs a UserSelect, defaulting to the interaction.user
    def __init__(self, name: str, user: User | Member, management: bool):
        super().__init__()
        self.name = name
        self.select = UserSelect(placeholder="Select a GM", default=user)
        self.management = management
        self.select.callback = self.select_callback
        self.add_item(ActionRow(self.select))

    @uses_db(CustomClient().sessionmaker)
    async def select_callback(self, interaction: Interaction, session: Session):
        gm = self.select.values[0] # already a single User|Member
        if not self.management and gm.id != interaction.user.id:
            await interaction.response.send_message("You do not have permission to create a campaign for someone else", ephemeral=True)
            return
        if not await Campaign2.is_gm(gm):
            await interaction.response.send_message("The selected user is not a Game Master", ephemeral=True)
            return
        session.add(CampaignModel(name=self.name, gm=str(gm.id)))
        session.commit()
        await interaction.response.send_message(f"Campaign {self.name} created", ephemeral=True)

class CampaignInfoLayoutView(RecordingLayoutView):
    def __init__(self, campaign: CampaignModel, edit_callback: Callable[[str], Awaitable[None]]):
        super().__init__()
        self.campaign_id = campaign.id
        self.campaign_name = campaign.name
        self.open = campaign.open
        self.player_limit = campaign.player_limit
        self.required_role = campaign.required_role
        self.edit_callback = edit_callback
        id_display = TextDisplay(content=f"Campaign ID: {campaign.id}")
        name_display = TextDisplay(content=f"Campaign Name: {campaign.name}")
        name_button = Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_name")
        name_button.callback = self.edit_name_callback
        name_section = Section(name_display, accessory=name_button)
        gm_display = TextDisplay(content=f"GM: <@{campaign.gm}>")
        open_display = TextDisplay(content=f"Open: {'Yes' if campaign.open else 'No'}")
        open_button = Button(label="Toggle", style=ButtonStyle.primary, custom_id="toggle_open")
        open_button.callback = self.toggle_open_callback
        open_section = Section(open_display, accessory=open_button)
        player_limit_display = TextDisplay(content=f"Unit Limit: {campaign.player_limit}")
        player_limit_button = Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_player_limit")
        player_limit_button.callback = self.edit_player_limit_callback
        player_limit_section = Section(player_limit_display, accessory=player_limit_button)
        required_role_display = TextDisplay(content=f"Required Role: {f'<@&{campaign.required_role}>' if campaign.required_role else 'None'}")
        required_role_button = Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_required_role")
        required_role_button.callback = self.edit_required_role_callback
        required_role_section = Section(required_role_display, accessory=required_role_button)
        units_button = Button(label="Units", style=ButtonStyle.primary, custom_id="units")
        units_button.callback = self.units_button_callback
        invites_button = Button(label="Invites", style=ButtonStyle.primary, custom_id="invites")
        invites_button.callback = self.invites_button_callback
        payout_button = Button(label="Payout", style=ButtonStyle.green, custom_id="payout")
        payout_button.callback = self.payout_button_callback
        remove_button = Button(label="Remove", style=ButtonStyle.danger, custom_id="remove")
        remove_button.callback = self.remove_button_callback
        action_row = ActionRow(units_button, invites_button, payout_button, remove_button)
        self.add_item(id_display)
        self.add_item(name_section)
        self.add_item(gm_display)
        self.add_item(open_section)
        self.add_item(player_limit_section)
        self.add_item(required_role_section)
        self.add_item(action_row)

    async def edit_name_callback(self, interaction: Interaction):
        modal = CampaignEditNameModal(campaign_id=self.campaign_id, name=self.campaign_name, edit_callback=self.edit_callback)

        await interaction.response.send_modal(modal)

    @uses_db(CustomClient().sessionmaker)
    async def toggle_open_callback(self, interaction: Interaction, session: Session):
        campaign = session.query(CampaignModel).filter(CampaignModel.id == self.campaign_id).first()
        campaign.open = not campaign.open
        session.commit()
        await interaction.response.send_message(f"Campaign open status updated to {'Open' if campaign.open else 'Closed'}", ephemeral=True)
        await self.edit_callback(view=CampaignInfoLayoutView(campaign, self.edit_callback))

    async def edit_player_limit_callback(self, interaction: Interaction):
        view = CampaignEditPlayerLimitLayoutView(campaign_id=self.campaign_id, player_limit=self.player_limit, edit_callback=self.edit_callback)
        await interaction.response.send_message(view=view, ephemeral=True)

    async def edit_required_role_callback(self, interaction: Interaction):
        default = interaction.guild.get_role(self.required_role) if self.required_role else None
        view = CampaignEditRequiredRoleLayoutView(campaign_id=self.campaign_id, edit_callback=self.edit_callback, default=default)
        await interaction.response.send_message(view=view, ephemeral=True)

    async def units_button_callback(self, interaction: Interaction):
        view = CampaignUnitsLayoutView(campaign_id=self.campaign_id)
        await interaction.response.send_message(view=view, ephemeral=True)

    async def invites_button_callback(self, interaction: Interaction):
        view = CampaignInvitesLayoutView(campaign_id=self.campaign_id, guild=interaction.guild)
        await interaction.response.send_message(view=view, ephemeral=True)

    async def payout_button_callback(self, interaction: Interaction):
        modal = CampaignPayoutModal(campaign_id=self.campaign_id, campaign_name=self.campaign_name)
        await interaction.response.send_modal(modal)

    async def remove_button_callback(self, interaction: Interaction):
        view = CampaignDeleteConfirmLayoutView(campaign_id=self.campaign_id, campaign_name=self.campaign_name, edit_callback=self.edit_callback)
        await interaction.response.send_message(view=view, ephemeral=True)

class CampaignDeleteConfirmLayoutView(RecordingLayoutView):
    def __init__(self, campaign_id: str, campaign_name: str, edit_callback: Callable[[str], Awaitable[None]]):
        super().__init__()
        self.campaign_id = campaign_id
        self.campaign_name = campaign_name
        self.edit_callback = edit_callback
        self.add_item(TextDisplay(content=f"Are you sure you want to delete {campaign_name}?"))
        delete_button = Button(label="Delete", style=ButtonStyle.danger, custom_id="delete")
        cancel_button = Button(label="Cancel", style=ButtonStyle.secondary, custom_id="cancel")
        delete_button.callback = self.delete_callback
        cancel_button.callback = self.cancel_callback
        self.add_item(ActionRow(delete_button, cancel_button))

    async def cancel_callback(self, interaction: Interaction):
        await interaction.delete_original_response()

    @uses_db(CustomClient().sessionmaker)
    @error_reporting(verbose=True)
    async def delete_callback(self, interaction: Interaction, session: Session):
        remove_logger = getLogger(f"{__name__}.remove")
        campaign = session.query(CampaignModel).filter(CampaignModel.id == self.campaign_id).first()
        if not campaign:
            remove_logger.error(f"Campaign {self.campaign_name} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        if not await Campaign2.is_management(interaction) and interaction.user.id != int(campaign.gm):
            remove_logger.error(f"{interaction.user.name} does not have permission to remove campaign {self.campaign_name}")
            await interaction.response.send_message("You don't have permission to remove this campaign", ephemeral=True)
            return
        campaign_name = campaign.name
        await interaction.response.defer(ephemeral=True)
        for unit in campaign.units:
            unit.active = False
            unit.callsign = None
            unit.campaign_id = None
            unit.status = UnitStatus.INACTIVE if unit.status == UnitStatus.ACTIVE else unit.status
            unit.battle_group = None
            unit.unit_history.append(UnitHistory(campaign_name=campaign_name))
            CustomClient().queue.put_nowait((1, unit.player, 0))
        for invite in list(campaign.invites):
            session.delete(invite)
        session.flush()
        session.delete(campaign)
        session.flush()
        remove_logger.info(f"Campaign {campaign_name} removed")
        await interaction.delete_original_response()
        removed_view = RecordingLayoutView()
        removed_view.add_item(TextDisplay(content=f"Campaign {campaign_name} removed"))
        await self.edit_callback(view=removed_view)

class CampaignPayoutModal(RecordingModal):
    def __init__(self, campaign_id: str, campaign_name: str):
        super().__init__(title="Payout Campaign", custom_id="payout")
        self.campaign_id = campaign_id
        self.campaign_name = campaign_name
        self.add_item(TextInput(label=f"Base {tmpl.MAIN_CURRENCY_SHORT}", style=TextStyle.short, custom_id="base_req", required=False, default="0"))
        self.add_item(TextInput(label=f"Survivor {tmpl.MAIN_CURRENCY_SHORT}", style=TextStyle.short, custom_id="survivor_req", required=False, default="0"))
        self.add_item(TextInput(label=f"Base {tmpl.SECONDARY_CURRENCY_SHORT}", style=TextStyle.short, custom_id="base_bp", required=False, default="0"))
        self.add_item(TextInput(label=f"Survivor {tmpl.SECONDARY_CURRENCY_SHORT}", style=TextStyle.short, custom_id="survivor_bp", required=False, default="0"))

    @uses_db(CustomClient().sessionmaker)
    @error_reporting(verbose=True)
    async def on_submit(self, interaction: Interaction, session: Session):
        payout_logger = getLogger(f"{__name__}.payout")
        campaign = session.query(CampaignModel).filter(CampaignModel.id == self.campaign_id).first()
        if not campaign:
            payout_logger.error(f"Campaign {self.campaign_name} not found")
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return
        if not await Campaign2.is_management(interaction) and interaction.user.id != int(campaign.gm):
            payout_logger.error(f"{interaction.user.name} does not have permission to payout campaign {self.campaign_name}")
            await interaction.response.send_message("You don't have permission to payout this campaign", ephemeral=True)
            return
        try:
            base_req = int(self.children[0].value or 0)
            survivor_req = int(self.children[1].value or 0)
            base_bp = int(self.children[2].value or 0)
            survivor_bp = int(self.children[3].value or 0)
        except ValueError:
            await interaction.response.send_message("Payout values must be integers", ephemeral=True)
            return
        payout_logger.info(f"Paying out campaign {self.campaign_name} with base_req={base_req}, survivor_req={survivor_req}, base_bp={base_bp}, survivor_bp={survivor_bp}")
        all_players = campaign.players
        live_players = campaign.live_players
        dead_players = all_players - live_players
        payout_logger.debug(f"Campaign {self.campaign_name}: {len(all_players)} total players, {len(live_players)} live players, {len(dead_players)} dead players")
        for player in all_players:
            payout_logger.debug(f"Paying out base rewards to {player.name} for {self.campaign_name}")
            player.rec_points += base_req
            player.bonus_pay += base_bp
        for player in live_players:
            payout_logger.debug(f"Paying out survivor rewards to {player.name} for {self.campaign_name}")
            player.rec_points += survivor_req
            player.bonus_pay += survivor_bp
        session.commit()
        await interaction.response.defer(ephemeral=True)
        for player in all_players:
            payout_logger.debug(f"Putting {player.name} in update queue for {self.campaign_name}")
            CustomClient().queue.put_nowait((1, player, 0))
        await interaction.followup.send(f"Campaign {self.campaign_name} payout complete", ephemeral=True)

class CampaignInvitesLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, campaign_id: str, guild: Guild, session: Session):
        super().__init__()
        self.campaign_id = campaign_id
        self.guild = guild
        campaign = session.query(CampaignModel).filter(CampaignModel.id == campaign_id).first()
        invited_members: list[Member] = []
        self.preserved_player_ids: set[int] = set()
        for invite in campaign.invites:
            member = guild.get_member(int(invite.player.discord_id))
            if member is not None:
                invited_members.append(member)
            else:
                self.preserved_player_ids.add(invite.player_id)
        invited_members.sort(key=lambda member: (member.display_name or member.name).lower())
        chunks = [invited_members[i:i+25] for i in range(0, len(invited_members), 25)] if invited_members else [[]]
        if chunks and len(chunks[-1]) == 25:
            chunks.append([])
        self.cache: dict[str, list[str]] = {}
        for chunk in chunks:
            kwargs: dict = {"placeholder": "Select invited players", "min_values": 0, "max_values": 25}
            if chunk:
                kwargs["default_values"] = chunk
            select = UserSelect(**kwargs)
            select.callback = self.select_callback
            self.add_item(ActionRow(select))
            self.cache[select.custom_id] = [str(member.id) for member in chunk]

    @uses_db(CustomClient().sessionmaker)
    @error_reporting(verbose=True)
    async def select_callback(self, interaction: Interaction, session: Session):
        self.cache[interaction.custom_id] = interaction.data["values"]
        selected_discord_ids = {int(user_id) for choices in self.cache.values() for user_id in choices}
        players = session.query(Player).filter(Player.discord_id.in_([str(user_id) for user_id in selected_discord_ids])).all()
        selected_player_ids = {player.id for player in players} | self.preserved_player_ids
        campaign = session.query(CampaignModel).filter(CampaignModel.id == self.campaign_id).first()
        existing_player_ids = {invite.player_id for invite in campaign.invites}
        for invite in list(campaign.invites):
            if invite.player_id not in selected_player_ids:
                session.delete(invite)
        for player in players:
            if player.id not in existing_player_ids:
                session.add(CampaignInvite(campaign_id=campaign.id, player_id=player.id))
        session.commit()
        skipped = len(selected_discord_ids) - len(players)
        message = "Campaign invites updated"
        if skipped:
            message += f" ({skipped} selected user{'s' if skipped != 1 else ''} skipped — no Meta Campaign company)"
        content = RecordingLayoutView()
        content.add_item(TextDisplay(content=message))
        await interaction.response.edit_message(view=content)

class CampaignUnitsLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, campaign_id: str, session: Session):
        super().__init__()
        self.campaign_id = campaign_id
        campaign = session.query(CampaignModel).filter(CampaignModel.id == campaign_id).first()
        units = sorted(campaign.units, key=lambda unit: (unit.callsign or unit.name).lower())
        options = [SelectOption(label=unit.callsign or unit.name, value=str(unit.id)) for unit in units]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            select = Select(placeholder="No units", options=[SelectOption(label="No units", value="no_units", default=True)], disabled=True)
            self.add_item(ActionRow(select))
            return
        if len(chunks) >= 20:
            select = Select(
                placeholder="This campaign has too many units to display, please contact Cheese",
                options=[SelectOption(label="This campaign has too many units to display, please contact Cheese", value="too_many_units", default=True)],
                disabled=True,
            )
            self.add_item(ActionRow(select))
            return
        for chunk in chunks:
            select = Select(placeholder="Select a unit", options=chunk)
            select.callback = self.select_callback
            self.add_item(ActionRow(select))

    @uses_db(CustomClient().sessionmaker)
    @error_reporting(verbose=True)
    async def select_callback(self, interaction: Interaction, session: Session):
        unit = session.query(Unit).filter(Unit.id == interaction.data["values"][0]).first()
        if unit is None:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        await interaction.response.send_message(view=CampaignUnitInfoLayoutView(unit, self.campaign_id), ephemeral=True)

class CampaignUnitInfoLayoutView(RecordingLayoutView):
    def __init__(self, unit: Unit, campaign_id: str):
        super().__init__()
        self.unit_id = unit.id
        self.campaign_id = campaign_id
        self.add_item(TextDisplay(content=f"Unit ID: {unit.id}"))
        self.add_item(TextDisplay(content=f"Player: {unit.player.mention}"))
        self.add_item(TextDisplay(content=f"Name: {unit.name}"))
        self.add_item(TextDisplay(content=f"Callsign: {unit.callsign or '—'}"))
        self.add_item(TextDisplay(content=f"Unit Type: {unit.unit_type}"))
        self.add_item(TextDisplay(content=f"Status: {unit.status.name}"))
        self.add_item(TextDisplay(content=f"Battle Group: {unit.battle_group or '—'}"))
        self.add_item(TextDisplay(content=f"Unit Req: {unit.unit_req}"))
        deactivate_button = Button(label="Deactivate", style=ButtonStyle.danger, custom_id="deactivate")
        deactivate_button.callback = self.deactivate_callback
        self.add_item(ActionRow(deactivate_button))

    @uses_db(CustomClient().sessionmaker)
    @error_reporting(verbose=True)
    async def deactivate_callback(self, interaction: Interaction, session: Session):
        unit = session.query(Unit).filter(Unit.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        original_callsign = unit.callsign or unit.name
        unit.active = False
        unit.callsign = None
        unit.campaign_id = None
        unit.status = UnitStatus.INACTIVE if unit.status == UnitStatus.ACTIVE else unit.status
        unit.battle_group = None
        session.commit()
        CustomClient().queue.put_nowait((1, unit.player, 0))
        await interaction.response.send_message(f"Unit {original_callsign} deactivated", ephemeral=True)
        await interaction.followup.send(view=CampaignUnitsLayoutView(campaign_id=self.campaign_id), ephemeral=True)

class CampaignEditNameModal(RecordingModal):
    def __init__(self, campaign_id: str, name: str, edit_callback: Callable[[str], Awaitable[None]]):
        super().__init__(title="Edit Campaign Name", custom_id="edit_name")
        self.campaign_id = campaign_id
        self.edit_callback = edit_callback
        self.add_item(TextInput(label="Name", style=TextStyle.short, custom_id="name", required=True, default=name))

    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        campaign = session.query(CampaignModel).filter(CampaignModel.id == self.campaign_id).first()
        campaign.name = self.children[0].value
        session.commit()
        await interaction.response.send_message(f"Campaign name updated", ephemeral=True)
        await self.edit_callback(view=CampaignInfoLayoutView(campaign, self.edit_callback))

class CampaignEditPlayerLimitLayoutView(RecordingLayoutView):
    def __init__(self, campaign_id: str, player_limit: int, edit_callback: Callable[[int], Awaitable[None]]):
        super().__init__()
        self.campaign_id = campaign_id
        self.player_limit = player_limit
        self.edit_callback = edit_callback
        options = [SelectOption(label="None", value="0")] + [SelectOption(label=option, value=option) for option in EnvironHelpers.get_str_list("PLAYER_LIMIT_OPTIONS", separator=",")] + [SelectOption(label="Custom", value="custom")]
        self.select = Select(placeholder="Select a unit limit", options=options)
        self.select.callback = self.select_callback
        self.add_item(ActionRow(self.select))

    @uses_db(CustomClient().sessionmaker)
    @error_reporting(verbose=True)
    async def select_callback(self, interaction: Interaction, session: Session):
        player_limit = self.select.values[0]
        if player_limit == "custom":
            modal = CampaignEditPlayerLimitCustomModal(campaign_id=self.campaign_id, player_limit=player_limit, edit_callback=self.edit_callback)
            await interaction.response.send_modal(modal)
        else:
            campaign = session.query(CampaignModel).filter(CampaignModel.id == self.campaign_id).first()
            player_limit = int(player_limit) if player_limit != "0" else None
            if player_limit is not None and player_limit < 0:
                await interaction.response.send_message("Unit limit cannot be negative", ephemeral=True)
                return
            campaign.player_limit = player_limit
            session.commit()
            await interaction.response.send_message(f"Campaign unit limit updated to {player_limit if player_limit != 0 else 'None'}", ephemeral=True)
            await self.edit_callback(view=CampaignInfoLayoutView(campaign, self.edit_callback))

class CampaignEditRequiredRoleLayoutView(RecordingLayoutView):
    def __init__(self, campaign_id: str, edit_callback: Callable[[str], Awaitable[None]], default: Role | None = None):
        super().__init__()
        self.campaign_id = campaign_id
        self.edit_callback = edit_callback
        kwargs: dict = {"placeholder": "Select a required role", "min_values": 0, "max_values": 1}
        if default:
            kwargs["default_values"] = [default]
        self.select = RoleSelect(**kwargs)
        self.select.callback = self.select_callback
        self.add_item(ActionRow(self.select))

    @uses_db(CustomClient().sessionmaker)
    @error_reporting(verbose=True)
    async def select_callback(self, interaction: Interaction, session: Session):
        campaign = session.query(CampaignModel).filter(CampaignModel.id == self.campaign_id).first()
        if self.select.values:
            role = self.select.values[0]
            campaign.required_role = role.id
            message = f"Campaign required role updated to {role.mention}"
        else:
            campaign.required_role = None
            message = "Campaign required role updated to None"
        session.commit()
        await interaction.response.send_message(message, ephemeral=True)
        await self.edit_callback(view=CampaignInfoLayoutView(campaign, self.edit_callback))

class CampaignEditPlayerLimitCustomModal(RecordingModal):
    def __init__(self, campaign_id: str, player_limit: int, edit_callback: Callable[[int], Awaitable[None]]):
        super().__init__(title="Edit Campaign Unit Limit", custom_id="edit_player_limit_custom")
        self.campaign_id = campaign_id
        self.player_limit = player_limit
        self.edit_callback = edit_callback
        self.add_item(TextInput(label="Unit Limit", style=TextStyle.short, custom_id="player_limit", required=True, default=str(player_limit)))
    
    @uses_db(CustomClient().sessionmaker)
    @error_reporting(verbose=True)
    async def on_submit(self, interaction: Interaction, session: Session):
        campaign = session.query(CampaignModel).filter(CampaignModel.id == self.campaign_id).first()
        campaign.player_limit = int(self.children[0].value)
        if campaign.player_limit < 0:
            await interaction.response.send_message("Player limit cannot be negative", ephemeral=True)
            return
        session.commit()
        await interaction.response.send_message(f"Campaign player limit updated to {self.children[0].value}", ephemeral=True)
        await self.edit_callback(view=CampaignInfoLayoutView(campaign, self.edit_callback))

async def setup(_bot: CustomClient):
    await _bot.add_cog(Campaign2(_bot))


async def teardown(_bot: CustomClient):
    await _bot.remove_cog(Campaign2.__name__)
