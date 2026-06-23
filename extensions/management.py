from logging import getLogger
import logging
from typing import Callable

from discord import ButtonStyle, Interaction, SelectOption, TextStyle, app_commands as ac, ui
import discord
from discord.ext.commands import GroupCog
from sqlalchemy.orm import Session
import sqlalchemy
import templates as tmpl

from customclient import CustomClient
from models import Campaign, Player, ShopUpgrade, Unit, UnitStatus, PlayerUpgrade, UnitType, UpgradeType
from utils import RecordingModal, error_reporting, is_management, uses_db, RecordingLayoutView

logger = getLogger(__name__)

class CompanyLayoutView(RecordingLayoutView):
    def __init__(self, player: Player):
        super().__init__(timeout=None)
        self.player_id = player.id
        self.old_name = player.name
        self.old_lore = player.lore
        self.old_rec_points = player.rec_points
        self.old_bonus_pay = player.bonus_pay
        id_display = ui.TextDisplay(content=f"Player ID: {player.id}")
        user_display = ui.TextDisplay(content=f"User: {player.mention}")
        name_display = ui.TextDisplay(content=f"Player Name: {player.name}")
        name_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_name")
        name_section = ui.Section(name_display, accessory=name_button)
        lore_display = ui.TextDisplay(content=f"Lore: {player.lore[:100]}{'...' if len(player.lore) > 100 else ''}")
        lore_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_lore")
        lore_section = ui.Section(lore_display, accessory=lore_button)
        rec_points_display = ui.TextDisplay(content=f"{tmpl.MAIN_CURRENCY}: {player.rec_points}")
        rec_points_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_rec_points")
        rec_points_section = ui.Section(rec_points_display, accessory=rec_points_button)
        bonus_pay_display = ui.TextDisplay(content=f"{tmpl.SECONDARY_CURRENCY}: {player.bonus_pay}")
        bonus_pay_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_bonus_pay")
        bonus_pay_section = ui.Section(bonus_pay_display, accessory=bonus_pay_button)
        refresh_button = ui.Button(label="Refresh", style=ButtonStyle.primary, custom_id="refresh")
        units_button = ui.Button(label="Units", style=ButtonStyle.primary, custom_id="units")
        action_row = ui.ActionRow(refresh_button, units_button)
        self.add_item(id_display)
        self.add_item(user_display)
        self.add_item(name_section)
        self.add_item(lore_section)
        self.add_item(rec_points_section)
        self.add_item(bonus_pay_section)
        self.add_item(action_row)
        name_button.callback = self.edit_name_button_callback
        lore_button.callback = self.edit_lore_button_callback
        rec_points_button.callback = self.edit_rec_points_button_callback
        bonus_pay_button.callback = self.edit_bonus_pay_button_callback
        refresh_button.callback = self.refresh_button_callback
        units_button.callback = self.units_button_callback

    @error_reporting(True)
    async def edit_name_button_callback(self, interaction: Interaction):
        modal = CompanyEditNameModal(self.player_id, self.old_name)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def edit_lore_button_callback(self, interaction: Interaction):
        modal = CompanyEditLoreModal(self.player_id, self.old_lore)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def edit_rec_points_button_callback(self, interaction: Interaction):
        modal = CompanyEditRecPointsModal(self.player_id, self.old_rec_points)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def edit_bonus_pay_button_callback(self, interaction: Interaction):
        modal = CompanyEditBonusPayModal(self.player_id, self.old_bonus_pay)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def refresh_button_callback(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.id == self.player_id).first()
        if player is None:
            await interaction.response.send_message(tmpl.player_not_found, ephemeral=True)
            return
        logger.debug(f"Refreshing layout view for player {player}")
        layout_view = CompanyLayoutView(player)
        await interaction.response.edit_message(view=layout_view)
        logger.debug(f"Layout view refreshed for player {player}")

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def units_button_callback(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.id == self.player_id).first()
        if player is None:
            await interaction.response.send_message(tmpl.player_not_found, ephemeral=True)
            return
        layout_view = CompanyUnitSelectLayoutView(player)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

class CompanyEditNameModal(RecordingModal):
    def __init__(self, player_id: int, old_name: str):
        super().__init__(title="Edit Player Name")
        self.player_id = player_id
        self.add_item(ui.TextInput(label="Name", placeholder="Enter the player name", required=True, max_length=32, default=old_name))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.id == self.player_id).first()
        if player is None:
            await interaction.response.send_message(tmpl.player_not_found, ephemeral=True)
            return
        player.name = self.children[0].value
        session.commit()
        await interaction.response.send_message("Player name updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, player, 0))

class CompanyEditLoreModal(RecordingModal):
    def __init__(self, player_id: int, old_lore: str):
        super().__init__(title="Edit Player Lore")
        self.player_id = player_id
        self.add_item(ui.TextInput(label="Lore", placeholder="Enter the player lore", max_length=1000, style=TextStyle.paragraph, default=old_lore))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.id == self.player_id).first()
        if player is None:
            await interaction.response.send_message(tmpl.player_not_found, ephemeral=True)
            return
        player.lore = self.children[0].value
        session.commit()
        await interaction.response.send_message("Player lore updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, player, 0))

class CompanyEditRecPointsModal(RecordingModal):
    def __init__(self, player_id: int, old_rec_points: int):
        super().__init__(title="Edit Player Requisition Points")
        self.player_id = player_id
        self.old_rec_points = old_rec_points
        self.add_item(ui.TextInput(label="Instructions", default=tmpl.edit_rec_points_instructions, style=TextStyle.paragraph))
        self.add_item(ui.TextInput(label="Set Requisition Points", placeholder="Enter the player requisition points", max_length=10, default=str(old_rec_points)))
        self.add_item(ui.TextInput(label="Change Requisition Points", placeholder="Enter the number of points to change", max_length=10, default="0"))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.id == self.player_id).first()
        if player is None:
            await interaction.response.send_message(tmpl.player_not_found, ephemeral=True)
            return
        try:
            set_points = int(self.children[1].value)
            change_points = int(self.children[2].value)
        except ValueError:
            await interaction.response.send_message("Invalid input: currency values must be numerical", ephemeral=True)
            logger.error(f"Invalid input: currency values must be numerical: {self.children[1].value} {self.children[2].value}")
            return
        if (set_points != self.old_rec_points and change_points != 0):
            await interaction.response.send_message("You cannot alter both fields, you can only either set or change", ephemeral=True)
            return
        if set_points != self.old_rec_points:
            player.rec_points = set_points
        else:
            player.rec_points += change_points
        session.commit()
        await interaction.response.send_message("Player requisition points updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, player, 0))

class CompanyEditBonusPayModal(RecordingModal):
    def __init__(self, player_id: int, old_bonus_pay: int):
        super().__init__(title="Edit Player Bonus Pay")
        self.player_id = player_id
        self.old_bonus_pay = old_bonus_pay
        self.add_item(ui.TextInput(label="Instructions", default=tmpl.edit_bonus_pay_instructions, style=TextStyle.paragraph))
        self.add_item(ui.TextInput(label="Set Bonus Pay", placeholder="Enter the player bonus pay", max_length=10, default=str(old_bonus_pay)))
        self.add_item(ui.TextInput(label="Change Bonus Pay", placeholder="Enter the number of points to change the total by", max_length=10, default="0"))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.id == self.player_id).first()
        if player is None:
            await interaction.response.send_message(tmpl.player_not_found, ephemeral=True)
            return
        try:
            set_points = int(self.children[1].value)
            change_points = int(self.children[2].value)
        except ValueError:
            await interaction.response.send_message("Invalid input: currency values must be numerical", ephemeral=True)
            logger.error(f"Invalid input: currency values must be numerical: {self.children[1].value} {self.children[2].value}")
            return
        if (set_points != self.old_bonus_pay and change_points != 0):
            await interaction.response.send_message("You cannot alter both fields, you can only either set or change", ephemeral=True)
            return
        if set_points != self.old_bonus_pay:
            player.bonus_pay = set_points
        else:
            player.bonus_pay += change_points
        session.commit()
        await interaction.response.send_message("Player bonus pay updated", ephemeral=True)

class CompanyUnitSelectLayoutView(RecordingLayoutView):
    def __init__(self, player: Player):
        super().__init__(timeout=None)
        self.player_id = player.id
        options = [SelectOption(label=unit.name, value=unit.id) for unit in player.units]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            select = ui.Select(placeholder="No units", options=[SelectOption(label="No units", value="no_units", default=True)], disabled=True)
            select.callback = self.unit_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            add_button = ui.Button(label="Add Unit", style=ButtonStyle.green, custom_id="add_unit")
            add_button.callback = self.add_unit_button_callback
            add_action_row = ui.ActionRow(add_button)
            self.add_item(add_action_row)
            return
        if len(chunks) >= 20:
            select = ui.Select(placeholder="This player has too many units to display, please contact Cheese", options=[SelectOption(label="This player has too many units to display, please contact Cheese", value="too_many_units", default=True)], disabled=True)
            select.callback = self.unit_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for chunk in chunks:
            select = ui.Select(placeholder="Select a unit", options=chunk)
            select.callback = self.unit_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
        add_button = ui.Button(label="Add Unit", style=ButtonStyle.green, custom_id="add_unit")
        add_button.callback = self.add_unit_button_callback
        action_row = ui.ActionRow(add_button)
        self.add_item(action_row)
            
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def unit_select_callback(self, interaction: Interaction, session: Session):
        unit = session.query(Unit).filter(Unit.id == interaction.data["values"][0]).first()
        if unit is None:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        layout_view = CompanyUnitInfoLayoutView(unit)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @error_reporting(True)
    async def add_unit_button_callback(self, interaction: Interaction):
        layout_view = CompanyAddUnitLayoutView(self.player_id)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

class CompanyUnitInfoLayoutView(RecordingLayoutView):
    def __init__(self, unit: Unit):
        super().__init__(timeout=None)
        self.unit_id = unit.id
        self.old_name = unit.name
        self.old_unit_type = unit.unit_type
        self.old_status = unit.status
        self.old_campaign = unit.campaign
        self.old_callsign = unit.callsign
        self.old_battle_group = unit.battle_group
        self.old_unit_req = unit.unit_req
        id_display = ui.TextDisplay(content=f"Unit ID: {unit.id}")
        user_display = ui.TextDisplay(content=f"User: {unit.player.mention}")
        edit_name_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_name")
        name_display = ui.Section(ui.TextDisplay(content=f"Unit Name: {unit.name}"), accessory=edit_name_button)
        edit_unit_type_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_unit_type")
        unit_type_display = ui.Section(ui.TextDisplay(content=f"Unit Type: {unit.unit_type}"), accessory=edit_unit_type_button)
        edit_status_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_status")
        status_display = ui.Section(ui.TextDisplay(content=f"Status: {unit.status.name}"), accessory=edit_status_button)
        edit_campaign_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_campaign")
        campaign_display = ui.Section(ui.TextDisplay(content=f"Campaign: {unit.campaign.name if unit.campaign else '—'}"), accessory=edit_campaign_button)
        edit_callsign_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_callsign")
        callsign_display = ui.Section(ui.TextDisplay(content=f"Callsign: {unit.callsign if unit.callsign else '—'}"), accessory=edit_callsign_button)
        edit_battle_group_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_battle_group")
        battle_group_display = ui.Section(ui.TextDisplay(content=f"Battle Group: {unit.battle_group if unit.battle_group else '—'}"), accessory=edit_battle_group_button)
        original_type_display = ui.TextDisplay(content=f"Original Type: {unit.original_type if unit.original_type else '—'}") # intentionally not editable
        edit_unit_req_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_unit_req")
        unit_req_display = ui.Section(ui.TextDisplay(content=f"Unit Req: {unit.unit_req}"), accessory=edit_unit_req_button)
        refresh_button = ui.Button(label="Refresh", style=ButtonStyle.primary, custom_id="refresh")
        upgrades_button = ui.Button(label="Upgrades", style=ButtonStyle.primary, custom_id="upgrades")
        action_row = ui.ActionRow(refresh_button, upgrades_button)
        self.add_item(id_display)
        self.add_item(user_display)
        self.add_item(name_display)
        self.add_item(unit_type_display)
        self.add_item(status_display)
        self.add_item(campaign_display)
        self.add_item(callsign_display)
        self.add_item(battle_group_display)
        self.add_item(original_type_display)
        self.add_item(unit_req_display)
        self.add_item(action_row)
        edit_name_button.callback = self.edit_name_button_callback
        edit_unit_type_button.callback = self.edit_unit_type_button_callback
        edit_status_button.callback = self.edit_status_button_callback
        edit_campaign_button.callback = self.edit_campaign_button_callback
        edit_callsign_button.callback = self.edit_callsign_button_callback
        edit_battle_group_button.callback = self.edit_battle_group_button_callback
        edit_unit_req_button.callback = self.edit_unit_req_button_callback
        upgrades_button.callback = self.upgrades_button_callback
        refresh_button.callback = self.refresh_button_callback

    @error_reporting(True)
    async def edit_name_button_callback(self, interaction: Interaction):
        modal = CompanyUnitEditNameModal(self.unit_id, self.old_name)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def edit_unit_type_button_callback(self, interaction: Interaction):
        layout_view = CompanyUnitEditUnitTypeLayoutView(self.unit_id, self.old_unit_type)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @error_reporting(True)
    async def edit_status_button_callback(self, interaction: Interaction):
        layout_view = CompanyUnitEditStatusLayoutView(self.unit_id, self.old_status)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @error_reporting(True)
    async def edit_campaign_button_callback(self, interaction: Interaction):
        layout_view = CompanyUnitEditCampaignLayoutView(self.unit_id, self.old_campaign)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @error_reporting(True)
    async def edit_callsign_button_callback(self, interaction: Interaction):
        modal = CompanyUnitEditCallsignModal(self.unit_id, self.old_callsign)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def edit_battle_group_button_callback(self, interaction: Interaction):
        modal = CompanyUnitEditBattleGroupModal(self.unit_id, self.old_battle_group)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def edit_unit_req_button_callback(self, interaction: Interaction):
        modal = CompanyUnitEditUnitReqModal(self.unit_id, self.old_unit_req)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def upgrades_button_callback(self, interaction: Interaction):
        layout_view = CompanyUnitUpgradesSelectLayoutView(self.unit_id)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def refresh_button_callback(self, interaction: Interaction, session: Session):
        unit = session.query(Unit).filter(Unit.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        logger.debug(f"Refreshing layout view for unit {unit}")
        layout_view = CompanyUnitInfoLayoutView(unit)
        await interaction.response.edit_message(view=layout_view)
        logger.debug(f"Layout view refreshed for unit {unit}")

class CompanyUnitEditNameModal(RecordingModal):
    def __init__(self, unit_id: int, old_name: str):
        super().__init__(title="Edit Unit Name")
        self.unit_id = unit_id
        self.add_item(ui.TextInput(label="Name", placeholder="Enter the unit name", required=True, max_length=30, default=old_name))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        unit = session.query(Unit).filter(Unit.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        unit.name = self.children[0].value
        session.commit()
        await interaction.response.send_message("Unit name updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, unit.player, 0))

class CompanyUnitEditUnitTypeLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, unit_id: int, old_unit_type: str, session: Session):
        super().__init__(timeout=None)
        self.unit_id = unit_id
        options = [SelectOption(label=unit_type.unit_type, value=unit_type.unit_type, default=(unit_type.unit_type == old_unit_type)) for unit_type in session.query(UnitType).all()]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            select = ui.Select(placeholder="No unit types", options=[SelectOption(label="No unit types", value="no_unit_types", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        if len(chunks) >= 21:
            select = ui.Select(placeholder="Why Do you have 525 unit types?", options=[SelectOption(label="Why Do you have 525 unit types?", value="too_many_units", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for chunk in chunks:
            select = ui.Select(placeholder="Select a unit type", options=chunk)
            select.callback = self.unit_type_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def unit_type_select_callback(self, interaction: Interaction, session: Session):
        unit_type = session.query(UnitType).filter(UnitType.unit_type == interaction.data["values"][0]).first()
        if unit_type is None:
            await interaction.response.send_message("Unit type not found", ephemeral=True)
            return
        unit = session.query(Unit).filter(Unit.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        unit.unit_type = unit_type.unit_type
        session.commit()
        await interaction.response.send_message("Unit type updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, unit.player, 0))

class CompanyUnitEditStatusLayoutView(RecordingLayoutView):
    def __init__(self, unit_id: int, old_status: str):
        super().__init__(timeout=None)
        self.unit_id = unit_id
        options = [SelectOption(label=status.name, value=status.value, default=(status.value == old_status)) for status in UnitStatus]
        select = ui.Select(placeholder="Select a status", options=options)
        select.callback = self.status_select_callback
        action_row = ui.ActionRow(select)
        self.add_item(action_row)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def status_select_callback(self, interaction: Interaction, session: Session):
        status = UnitStatus(interaction.data["values"][0])
        if status is None:
            await interaction.response.send_message("Status not found", ephemeral=True)
            return
        unit = session.query(Unit).filter(Unit.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        unit.status = status
        session.commit()
        await interaction.response.send_message("Unit status updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, unit.player, 0))

class CompanyUnitEditCampaignLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, unit_id: int, old_campaign: str, session: Session):
        super().__init__(timeout=None)
        self.unit_id = unit_id
        options = [SelectOption(label=campaign.name, value=campaign.id, default=(campaign.id == old_campaign)) for campaign in session.query(Campaign).all()]
        select = ui.Select(placeholder="Select a campaign", options=options)
        select.callback = self.campaign_select_callback
        action_row = ui.ActionRow(select)
        self.add_item(action_row)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def campaign_select_callback(self, interaction: Interaction, session: Session):
        campaign = session.query(Campaign).filter(Campaign.id == interaction.data["values"][0]).first()
        if campaign is None:
            await interaction.response.send_message("Campaign not found", ephemeral=True)
            return

        unit = session.query(Unit).filter(Unit.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        unit.campaign = campaign
        session.commit()
        await interaction.response.send_message("Unit campaign updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, unit.player, 0))

class CompanyUnitEditCallsignModal(RecordingModal):
    def __init__(self, unit_id: int, old_callsign: str):
        super().__init__(title="Edit Unit Callsign")
        self.unit_id = unit_id
        self.add_item(ui.TextInput(label="Callsign", placeholder="Enter the unit callsign", required=True, max_length=15, default=old_callsign))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        unit = session.query(Unit).filter(Unit.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        unit.callsign = self.children[0].value
        try:
            session.commit()
        except sqlalchemy.exc.IntegrityError:
            await interaction.response.send_message("Callsign is already taken", ephemeral=True)
            return
        await interaction.response.send_message("Unit callsign updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, unit.player, 0))

class CompanyUnitEditBattleGroupModal(RecordingModal):
    def __init__(self, unit_id: int, old_battle_group: str):
        super().__init__(title="Edit Unit Battle Group")
        self.unit_id = unit_id
        self.add_item(ui.TextInput(label="Battle Group", placeholder="Enter the unit battle group", required=True, max_length=30, default=old_battle_group))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        unit = session.query(Unit).filter(Unit.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        unit.battle_group = self.children[0].value
        session.commit()
        await interaction.response.send_message("Unit battle group updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, unit.player, 0))

class CompanyUnitEditUnitReqModal(RecordingModal):
    def __init__(self, unit_id: int, old_unit_req: int):
        super().__init__(title="Edit Unit Requisition Points")
        self.unit_id = unit_id
        self.old_unit_req = old_unit_req
        self.add_item(ui.TextInput(label="Instructions", default=tmpl.edit_unit_req_instructions, style=TextStyle.paragraph))
        self.add_item(ui.TextInput(label="Set Unit Requisition Points", placeholder="Enter the unit requisition points", max_length=10, default=str(old_unit_req)))
        self.add_item(ui.TextInput(label="Change Unit Requisition Points", placeholder="Enter the number of points to change", max_length=10, default="0"))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        unit = session.query(Unit).filter(Unit.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        try:
            set_points = int(self.children[1].value)
            change_points = int(self.children[2].value)
        except ValueError:
            await interaction.response.send_message("Invalid input: currency values must be numerical", ephemeral=True)
            logger.error(f"Invalid input: currency values must be numerical: {self.children[1].value} {self.children[2].value}")
            return
        if (set_points != self.old_unit_req and change_points != 0):
            await interaction.response.send_message("You cannot alter both fields, you can only either set or change", ephemeral=True)
            return
        if set_points != self.old_unit_req:
            unit.unit_req = set_points
        else:
            unit.unit_req += change_points
        session.commit()
        await interaction.response.send_message("Unit requisition points updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, unit.player, 0))

class CompanyUnitUpgradesSelectLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, unit_id: int, session: Session):
        super().__init__(timeout=None)
        logger = getLogger(f"{__name__}.CompanyUnitUpgradesSelectLayoutView.__init__")
        logger.setLevel(logging.DEBUG)
        self.unit_id = unit_id
        unit = session.query(Unit).filter(Unit.id == unit_id).first()
        if unit is None:
            raise ValueError("Unit not found")
        if not unit.upgrades:
            select = ui.Select(placeholder="No upgrades", options=[SelectOption(label="No upgrades", value="no_upgrades", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        options = [SelectOption(label=upgrade.name, value=upgrade.id) for upgrade in unit.upgrades]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            logger.debug("No upgrades")
            select = ui.Select(placeholder="No upgrades", options=[SelectOption(label="No upgrades", value="no_upgrades", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            add_button = ui.Button(label="Add Special Upgrade", style=ButtonStyle.green, custom_id="add_special_upgrade")
            add_button.callback = self.add_special_upgrade_button_callback
            action_row = ui.ActionRow(add_button)
            self.add_item(action_row)
        if len(chunks) >= 20:
            select = ui.Select(placeholder="Why Do you have 500 upgrades?", options=[SelectOption(label="Why Do you have 500 upgrades?", value="too_many_upgrades", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for chunk in chunks:
            select = ui.Select(placeholder="Select an upgrade", options=chunk)
            select.callback = self.upgrade_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
        add_button = ui.Button(label="Add Special Upgrade", style=ButtonStyle.green, custom_id="add_special_upgrade")
        add_button.callback = self.add_special_upgrade_button_callback
        action_row = ui.ActionRow(add_button)
        self.add_item(action_row)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def upgrade_select_callback(self, interaction: Interaction, session: Session):
        upgrade = session.query(PlayerUpgrade).filter(PlayerUpgrade.id == interaction.data["values"][0]).first()
        if upgrade is None:
            await interaction.response.send_message("Upgrade not found", ephemeral=True)
            return
        layout_view = CompanyPlayerUpgradeInfoLayoutView(upgrade.id)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @error_reporting(True)
    async def add_special_upgrade_button_callback(self, interaction: Interaction):
        modal = CompanyAddSpecialUpgradeModal(self.unit_id)
        await interaction.response.send_modal(modal)

class CompanyPlayerUpgradeInfoLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, upgrade_id: int, session: Session):
        super().__init__(timeout=None)
        self.upgrade_id = upgrade_id
        upgrade = session.query(PlayerUpgrade).filter(PlayerUpgrade.id == upgrade_id).first()
        if upgrade is None:
            raise ValueError("Upgrade not found")
        self.old_name = upgrade.name

        id_display = ui.TextDisplay(content=f"Upgrade ID: {upgrade.id}")
        edit_name_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_name")
        name_display = ui.Section(ui.TextDisplay(content=f"Upgrade Name: {upgrade.name}"), accessory=edit_name_button)
        type_display = ui.TextDisplay(content=f"Upgrade Type: {upgrade.type}")
        original_price_display = ui.TextDisplay(content=f"Upgrade Original Price: {upgrade.original_price}")
        unit_id_display = ui.TextDisplay(content=f"Upgrade Unit ID: {upgrade.unit_id}")
        shop_upgrade_id_display = ui.TextDisplay(content=f"Upgrade Shop Upgrade ID: {upgrade.shop_upgrade_id}")
        non_transferable_display = ui.TextDisplay(content=f"Upgrade Non-Transferable: {upgrade.non_transferable}")
        refresh_button = ui.Button(label="Refresh", style=ButtonStyle.primary, custom_id="refresh")
        delete_button = ui.Button(label="Delete", style=ButtonStyle.danger, custom_id="delete")
        action_row = ui.ActionRow(refresh_button, delete_button)
        self.add_item(id_display)
        self.add_item(name_display)
        self.add_item(type_display)
        self.add_item(original_price_display)
        self.add_item(unit_id_display)
        self.add_item(shop_upgrade_id_display)
        self.add_item(non_transferable_display)
        self.add_item(action_row)
        edit_name_button.callback = self.edit_name_button_callback
        refresh_button.callback = self.refresh_button_callback
        delete_button.callback = self.delete_button_callback

    @error_reporting(True)
    async def edit_name_button_callback(self, interaction: Interaction):
        modal = CompanyPlayerUpgradeEditNameModal(self.upgrade_id, self.old_name)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def refresh_button_callback(self, interaction: Interaction, session: Session):
        upgrade = session.query(PlayerUpgrade).filter(PlayerUpgrade.id == self.upgrade_id).first()
        if upgrade is None:
            await interaction.response.send_message("Upgrade not found", ephemeral=True)
            return
        layout_view = CompanyPlayerUpgradeInfoLayoutView(upgrade.id)
        await interaction.response.edit_message(view=layout_view)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def delete_button_callback(self, interaction: Interaction, session: Session):
        upgrade = session.query(PlayerUpgrade).filter(PlayerUpgrade.id == self.upgrade_id).first()
        if upgrade is None:
            await interaction.response.send_message("Upgrade not found", ephemeral=True)
            return
        session.delete(upgrade)
        session.commit()
        await interaction.response.send_message("Upgrade deleted", ephemeral=True)
        CustomClient().queue.put_nowait((1, upgrade.unit.player, 0))

class CompanyPlayerUpgradeEditNameModal(RecordingModal):
    def __init__(self, upgrade_id: int, old_name: str):
        super().__init__(title="Edit Upgrade Name")
        self.upgrade_id = upgrade_id
        self.add_item(ui.TextInput(label="Name", placeholder="Enter the upgrade name", required=True, max_length=30, default=old_name))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        upgrade = session.query(PlayerUpgrade).filter(PlayerUpgrade.id == self.upgrade_id).first()
        if upgrade is None:
            raise ValueError("Upgrade not found")
        upgrade.name = self.children[0].value
        session.commit()
        await interaction.response.send_message("Upgrade name updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, upgrade.unit.player, 0))

class CompanyAddSpecialUpgradeModal(RecordingModal):
    def __init__(self, unit_id: int):
        super().__init__(title="Add Special Upgrade")
        self.unit_id = unit_id
        self.add_item(ui.TextInput(label="Name", placeholder="Enter the upgrade name", required=True, max_length=30))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        logger.debug(f"Starting on_submit with unit_id={self.unit_id} and input_name='{self.children[0].value}'")

        upgrade = PlayerUpgrade(name=self.children[0].value, type="SPECIAL", unit_id=self.unit_id)
        session.add(upgrade)
        logger.debug(f"PlayerUpgrade created and added to session: {upgrade}")

        session.commit()
        logger.debug(f"Session committed for new upgrade id={upgrade.id}")

        await interaction.response.send_message("Special upgrade added", ephemeral=True)
        logger.debug("Sent ephemeral response 'Special upgrade added' to user.")

        try:
            CustomClient().queue.put_nowait((1, upgrade.unit.player, 0))
            logger.debug(f"Queue updated for player={upgrade.unit.player}")
        except Exception as e:
            logger.exception("Failed to update queue for player after adding special upgrade.")

class CompanyAddUnitLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, player_id: int, session: Session):
        super().__init__(timeout=None)
        self.player_id = player_id
        unit_types = session.query(UnitType).all()
        options = [SelectOption(label=unit_type.unit_type, value=unit_type.unit_type) for unit_type in unit_types]
        if not options:
            select = ui.Select(placeholder="No unit types", options=[SelectOption(label="No unit types", value="no_unit_types", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        for chunk in chunks:
            select = ui.Select(placeholder="Select a unit type", options=chunk)
            select.callback = self.unit_type_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def unit_type_select_callback(self, interaction: Interaction, session: Session):
        unit_type = session.query(UnitType).filter(UnitType.unit_type == interaction.data["values"][0]).first()
        if unit_type is None:
            await interaction.response.send_message("Unit type not found", ephemeral=True)
            return
        modal = CompanyAddUnitModal(self.player_id, unit_type.unit_type, unit_type.unit_req)
        await interaction.response.send_modal(modal)

class CompanyAddUnitModal(RecordingModal):
    def __init__(self, player_id: int, unit_type: str, unit_req: int):
        super().__init__(title="Add Unit")
        self.player_id = player_id
        self.unit_type = unit_type
        self.unit_req = unit_req
        self.add_item(ui.TextInput(label="Name", placeholder="Enter the unit name", required=True, max_length=30))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        if session.query(Unit).filter(Unit.name == self.children[0].value, Unit.player_id == self.player_id).first():
            await interaction.response.send_message("Unit name already exists", ephemeral=True)
            return
        if len(self.children[0].value) > 30:
            await interaction.response.send_message("Unit name is too long", ephemeral=True)
        unit = Unit(name=self.children[0].value, player_id=self.player_id, unit_type=self.unit_type, unit_req=self.unit_req, status=UnitStatus.PROPOSED)
        session.add(unit)
        session.commit()
        await interaction.response.send_message("Unit added", ephemeral=True)
        CustomClient().queue.put_nowait((1, unit.player, 0))

class ShopLayoutView(RecordingLayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        
    action_row = ui.ActionRow()

    @action_row.button(label="Unit Type", style=ButtonStyle.primary, custom_id="unit_type_button")
    @error_reporting(True)
    async def unit_type_button_callback(self, interaction: Interaction, button: ui.Button):
        layout_view = ShopUnitTypeSelectLayoutView()
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @action_row.button(label="Upgrade Type", style=ButtonStyle.primary, custom_id="upgrade_type_button")
    @error_reporting(True)
    async def upgrade_type_button_callback(self, interaction: Interaction, button: ui.Button):
        layout_view = ShopUpgradeTypeSelectLayoutView()
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @action_row.button(label="Upgrade", style=ButtonStyle.primary, custom_id="upgrade_button")
    @error_reporting(True)
    async def upgrade_button_callback(self, interaction: Interaction, button: ui.Button):
        layout_view = ShopUpgradeSelectLayoutView()
        await interaction.response.send_message(view=layout_view, ephemeral=True)

class ShopUnitTypeSelectLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, session: Session):
        super().__init__(timeout=None)
        unit_types = session.query(UnitType).all()
        options = [SelectOption(label=unit_type.unit_type, value=unit_type.unit_type) for unit_type in unit_types]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            select = ui.Select(placeholder="No unit types", options=[SelectOption(label="No unit types", value="no_unit_types", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        if len(chunks) >= 20:
            select = ui.Select(placeholder="Why Do you have 500 unit types?", options=[SelectOption(label="Why Do you have 500 unit types?", value="too_many_units", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for chunk in chunks:
            select = ui.Select(placeholder="Select a unit type", options=chunk)
            select.callback = self.unit_type_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
        add_unit_type_button = ui.Button(label="Add Unit Type", style=ButtonStyle.green, custom_id="add_unit_type")
        add_unit_type_button.callback = self.add_unit_type_button_callback
        action_row = ui.ActionRow(add_unit_type_button)
        self.add_item(action_row)

    @error_reporting(True)
    async def add_unit_type_button_callback(self, interaction: Interaction):
        modal = ShopAddUnitTypeModal()
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def unit_type_select_callback(self, interaction: Interaction, session: Session):
        unit_type = session.query(UnitType).filter(UnitType.unit_type == interaction.data["values"][0]).first()
        if unit_type is None:
            await interaction.response.send_message("Unit type not found", ephemeral=True)
            return
        layout_view = ShopUnitTypeInfoLayoutView(unit_type.unit_type)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

class ShopAddUnitTypeModal(RecordingModal):
    def __init__(self):
        super().__init__(title="Add Unit Type")
        self.add_item(ui.TextInput(label="Name", placeholder="Enter the unit type name", required=True, max_length=30))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        name = self.children[0].value.strip().upper()
        unit_type = UnitType(unit_type=name)
        session.add(unit_type)
        session.commit()
        layout_view = ShopUnitTypeInfoLayoutView(unit_type.unit_type)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

class ShopUnitTypeInfoLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, unit_type:str, session: Session):
        super().__init__(timeout=None)
        unit_type_info = session.query(UnitType).filter(UnitType.unit_type == unit_type).first()
        self.unit_type = unit_type
        name_display = ui.TextDisplay(content=f"Unit Type Name: {unit_type_info.unit_type}")
        self.old_unit_req = unit_type_info.unit_req
        self.edit_unit_req_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_unit_req")
        unit_req_display = ui.Section(ui.TextDisplay(content=f"Unit Req: {unit_type_info.unit_req}"), accessory=self.edit_unit_req_button)
        self.old_is_base = unit_type_info.is_base
        self.edit_is_base_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_is_base")
        is_base_display = ui.Section(ui.TextDisplay(content=f"Is Base: {unit_type_info.is_base}"), accessory=self.edit_is_base_button)
        self.old_free_upgrade_1 = unit_type_info.free_upgrade_1
        self.edit_free_upgrade_1_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_free_upgrade_1")
        free_upgrade_1_display = ui.Section(ui.TextDisplay(content=f"Free Upgrade 1: {unit_type_info.free_upgrade_1_info.name if unit_type_info.free_upgrade_1_info else '--'} ({unit_type_info.free_upgrade_1})"), accessory=self.edit_free_upgrade_1_button)
        self.old_free_upgrade_2 = unit_type_info.free_upgrade_2
        self.edit_free_upgrade_2_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_free_upgrade_2")
        free_upgrade_2_display = ui.Section(ui.TextDisplay(content=f"Free Upgrade 2: {unit_type_info.free_upgrade_2_info.name if unit_type_info.free_upgrade_2_info else '--'} ({unit_type_info.free_upgrade_2})"), accessory=self.edit_free_upgrade_2_button)
        compatible_upgrades_button = ui.Button(label="Edit Compatible Upgrades", style=ButtonStyle.primary, custom_id="edit_compatible_upgrades")
        refresh_button = ui.Button(label="Refresh", style=ButtonStyle.primary, custom_id="refresh")
        delete_button = ui.Button(label="Delete", style=ButtonStyle.danger, custom_id="delete")
        action_row = ui.ActionRow(compatible_upgrades_button, refresh_button, delete_button)
        self.add_item(name_display)
        self.add_item(unit_req_display)
        self.add_item(is_base_display)
        self.add_item(free_upgrade_1_display)
        self.add_item(free_upgrade_2_display)
        self.add_item(action_row)
        self.edit_unit_req_button.callback = self.edit_unit_req_button_callback
        self.edit_is_base_button.callback = self.edit_is_base_button_callback
        self.edit_free_upgrade_1_button.callback = self.edit_free_upgrade_1_button_callback
        self.edit_free_upgrade_2_button.callback = self.edit_free_upgrade_2_button_callback
        compatible_upgrades_button.callback = self.compatible_upgrades_button_callback
        refresh_button.callback = self.refresh_button_callback
        delete_button.callback = self.delete_button_callback

    @error_reporting(True)
    async def refresh_button_callback(self, interaction: Interaction):
        layout_view = ShopUnitTypeInfoLayoutView(self.unit_type)
        await interaction.response.edit_message(view=layout_view)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def delete_button_callback(self, interaction: Interaction, session: Session):
        unit_type = session.query(UnitType).filter(UnitType.unit_type == self.unit_type).first()
        if unit_type is None:
            await interaction.response.send_message("Unit type not found", ephemeral=True)
            return
        if unit_type.units:
            await interaction.response.send_message("Cannot delete a unit type that has units assigned to it", ephemeral=True)
            return
        if unit_type.original_units:
            await interaction.response.send_message("Cannot delete a unit type that has original units assigned to it", ephemeral=True)
            return
        if unit_type.refit_targets:
            await interaction.response.send_message("Cannot delete a unit type that has refit targets assigned to it", ephemeral=True)
            return
        if unit_type.compatible_upgrades:
            await interaction.response.send_message("Cannot delete a unit type that has compatible upgrades assigned to it", ephemeral=True)
            return
        session.delete(unit_type)
        session.commit()
        await interaction.response.send_message("Unit type deleted", ephemeral=True)
        await interaction.message.delete()
                
    @error_reporting(True)
    async def edit_unit_req_button_callback(self, interaction: Interaction):
        modal = ShopUnitTypeEditUnitReqModal(self.unit_type, self.old_unit_req)
        await interaction.response.send_modal(modal)
                
    @error_reporting(True)
    async def edit_is_base_button_callback(self, interaction: Interaction):
        modal = ShopUnitTypeEditIsBaseModal(self.unit_type, self.old_is_base)
        await interaction.response.send_modal(modal)
                
    @error_reporting(True)
    async def edit_free_upgrade_1_button_callback(self, interaction: Interaction):
        layout_view = ShopUnitTypeEditFreeUpgrade1LayoutView(self.unit_type, self.old_free_upgrade_1)
        await interaction.response.send_message(view=layout_view, ephemeral=True)
                
    @error_reporting(True)
    async def edit_free_upgrade_2_button_callback(self, interaction: Interaction):
        layout_view = ShopUnitTypeEditFreeUpgrade2LayoutView(self.unit_type, self.old_free_upgrade_2)
        await interaction.response.send_message(view=layout_view, ephemeral=True)
                
    @error_reporting(True)
    async def compatible_upgrades_button_callback(self, interaction: Interaction):
        layout_view = ShopCompatibleUpgradesLayoutView(self.unit_type, interaction.message.edit, ShopUnitTypeInfoLayoutView)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

class ShopCompatibleUpgradesLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, unit_type: str, edit_callback: Callable, parent_class: type, session: Session):
        super().__init__(timeout=None)
        self.unit_type = unit_type
        self.edit_callback = edit_callback
        self.parent_class = parent_class
        unit_type_obj = session.query(UnitType).filter(UnitType.unit_type == unit_type).first()
        if unit_type_obj is None:
            raise ValueError("Unit type not found")
        upgrades = session.query(ShopUpgrade).all()
        # Select upgrades where this unit_type is compatible
        options = [
            SelectOption(
                label=upgrade.name,
                value=str(upgrade.id),
                default=(unit_type_obj in upgrade.compatible_unit_types)
            )
            for upgrade in upgrades
        ]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            select = ui.Select(
                placeholder="No upgrades",
                options=[SelectOption(label="No upgrades", value="no_upgrades", default=True)],
                disabled=True
            )
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        if len(chunks) >= 21:
            select = ui.Select(
                placeholder="Why Do you have 525 upgrades?",
                options=[SelectOption(label="Why Do you have 525 upgrades?", value="too_many_upgrades", default=True)],
                disabled=True
            )
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for chunk in chunks:
            select = ui.Select(
                placeholder="Select compatible upgrades",
                options=chunk,
                min_values=0,
                max_values=len(chunk)
            )
            select.callback = self.compatible_upgrade_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
        self.cache = {}
        for child in self.walk_children():
            if isinstance(child, ui.Select):
                self.cache[child.custom_id] = [option.value for option in child.options if option.default]
             
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def compatible_upgrade_select_callback(self, interaction: Interaction, session: Session):
        self.cache[interaction.custom_id] = interaction.data["values"]
        selected = [choice for choices in self.cache.values() for choice in choices]
        unit_type = session.query(UnitType).filter(UnitType.unit_type == self.unit_type).first()
        if unit_type is None:
            await interaction.response.send_message("Unit type not found", ephemeral=True)
            return
        upgrade_ids = [int(x) for x in selected]
        selected_upgrades = session.query(ShopUpgrade).filter(ShopUpgrade.id.in_(upgrade_ids)).all()
        unit_type.compatible_upgrades = selected_upgrades
        session.commit()
        await self.edit_callback(view=self.parent_class(self.unit_type))
        content = RecordingLayoutView()
        content.add_item(ui.TextDisplay(content="Compatible upgrades updated"))
        await interaction.response.edit_message(view=content)

class ShopUnitTypeEditUnitReqModal(RecordingModal):
    def __init__(self, unit_type: str, old_unit_req: int):
        super().__init__(title="Edit Unit Req")
        self.unit_type = unit_type
        self.add_item(ui.TextInput(label="Unit Req", placeholder="Enter the unit req", required=True, max_length=10, default=old_unit_req))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        unit_type = session.query(UnitType).filter(UnitType.unit_type == self.unit_type).first()
        if unit_type is None:
            await interaction.response.send_message("Unit type not found", ephemeral=True)
            return
        unit_type.unit_req = int(self.children[0].value)
        session.commit()
        await interaction.response.send_message("Unit req updated", ephemeral=True)
        CustomClient().queue.put_nowait((1, unit_type.player, 0))

class ShopUnitTypeEditIsBaseModal(RecordingModal):
    def __init__(self, unit_type: str, old_is_base: bool):
        super().__init__(title="Edit Is Base")
        self.unit_type = unit_type
        self.add_item(ui.Label(text="Is Base", component=ui.Checkbox(default=old_is_base)))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        unit_type = session.query(UnitType).filter(UnitType.unit_type == self.unit_type).first()
        if unit_type is None:
            await interaction.response.send_message("Unit type not found", ephemeral=True)
            return
        unit_type.is_base = self.children[0].component.value
        session.commit()
        await interaction.response.send_message("Is Base updated", ephemeral=True)

class ShopUnitTypeEditFreeUpgrade1LayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, unit_type: str, old_free_upgrade_1: int, session: Session):
        super().__init__(timeout=None)
        self.unit_type = unit_type
        unit_type_info = session.query(UnitType).filter(UnitType.unit_type == unit_type).first()
        options = [SelectOption(label=upgrade.name, value=upgrade.id, default=(upgrade.id == old_free_upgrade_1)) for upgrade in unit_type_info.compatible_upgrades]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            select = ui.Select(placeholder="No free upgrades", options=[SelectOption(label="No free upgrades", value="no_free_upgrades", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        if len(chunks) >= 21:
            select = ui.Select(placeholder="Why Do you have 525 free upgrades?", options=[SelectOption(label="Why Do you have 525 free upgrades?", value="too_many_free_upgrades", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for chunk in chunks:
            select = ui.Select(placeholder="Select a free upgrade", options=chunk)
            select.callback = self.free_upgrade_1_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
                    
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def free_upgrade_1_select_callback(self, interaction: Interaction, session: Session):
        free_upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == interaction.data["values"][0]).first()
        if free_upgrade is None:
            await interaction.response.send_message("Free upgrade not found", ephemeral=True)
            return
        unit_type = session.query(UnitType).filter(UnitType.unit_type == self.unit_type).first()
        unit_type.free_upgrade_1 = free_upgrade.id
        session.commit()
        await interaction.response.send_message("Free upgrade 1 updated", ephemeral=True)

class ShopUnitTypeEditFreeUpgrade2LayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, unit_type: str, old_free_upgrade_2: int, session: Session):
        super().__init__(timeout=None)
        self.unit_type = unit_type
        unit_type_info = session.query(UnitType).filter(UnitType.unit_type == unit_type).first()
        options = [SelectOption(label=upgrade.name, value=upgrade.id, default=(upgrade.id == old_free_upgrade_2)) for upgrade in unit_type_info.compatible_upgrades]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            select = ui.Select(placeholder="No free upgrades", options=[SelectOption(label="No free upgrades", value="no_free_upgrades", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        if len(chunks) >= 21:
            select = ui.Select(placeholder="Why Do you have 525 free upgrades?", options=[SelectOption(label="Why Do you have 525 free upgrades?", value="too_many_free_upgrades", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for chunk in chunks:
            select = ui.Select(placeholder="Select a free upgrade", options=chunk)
            select.callback = self.free_upgrade_2_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def free_upgrade_2_select_callback(self, interaction: Interaction, session: Session):
        free_upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == interaction.data["values"][0]).first()
        if free_upgrade is None:
            await interaction.response.send_message("Free upgrade not found", ephemeral=True)
            return
        unit_type = session.query(UnitType).filter(UnitType.unit_type == self.unit_type).first()
        unit_type.free_upgrade_2 = free_upgrade.id
        session.commit()
        await interaction.response.send_message("Free upgrade 2 updated", ephemeral=True)

class ShopUpgradeTypeSelectLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, session: Session):
        super().__init__(timeout=None)
        upgrade_types = session.query(UpgradeType).all()
        options = [SelectOption(label=upgrade_type.name, value=upgrade_type.name) for upgrade_type in upgrade_types]
        select = ui.Select(placeholder="Select a upgrade type", options=options)
        select.callback = self.upgrade_type_select_callback
        action_row = ui.ActionRow(select)
        self.add_item(action_row)
        add_upgrade_type_button = ui.Button(label="Add Upgrade Type", style=ButtonStyle.green, custom_id="add_upgrade_type")
        add_upgrade_type_button.callback = self.add_upgrade_type_button_callback
        action_row = ui.ActionRow(add_upgrade_type_button)
        self.add_item(action_row)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def upgrade_type_select_callback(self, interaction: Interaction, session: Session):
        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == interaction.data["values"][0]).first()
        if upgrade_type is None:
            await interaction.response.send_message("Upgrade type not found", ephemeral=True)
            return
        layout_view = ShopUpgradeTypeInfoLayoutView(upgrade_type.name)
        await interaction.response.send_message(view=layout_view, ephemeral=True)
            
    @error_reporting(True)
    async def add_upgrade_type_button_callback(self, interaction: Interaction):
        modal = ShopAddUpgradeTypeModal()
        await interaction.response.send_modal(modal)

class ShopAddUpgradeTypeModal(RecordingModal):
    def __init__(self):
        super().__init__(title="Add Upgrade Type")
        self.add_item(ui.TextInput(label="Name", placeholder="Enter the upgrade type name", required=True, max_length=30))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        name = self.children[0].value.strip().upper()
        upgrade_type = UpgradeType(name=name)
        session.add(upgrade_type)
        session.commit()
        layout_view = ShopUpgradeTypeInfoLayoutView(upgrade_type.name)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

class ShopUpgradeTypeInfoLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, upgrade_type: str, session: Session):
        super().__init__(timeout=None)
        upgrade_type_info = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type).first()
        self.upgrade_type = upgrade_type
        self.old_name = upgrade_type_info.name
        self.old_emoji = upgrade_type_info.emoji
        self.old_is_refit = upgrade_type_info.is_refit
        self.old_non_purchaseable = upgrade_type_info.non_purchaseable
        self.old_can_use_unit_req = upgrade_type_info.can_use_unit_req
        self.old_sort_order = upgrade_type_info.sort_order
        edit_name_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_name")
        name_display = ui.Section(ui.TextDisplay(content=f"Name: {upgrade_type_info.name}"), accessory=edit_name_button)
        edit_emoji_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_emoji")
        emoji_display = ui.Section(ui.TextDisplay(content=f"Emoji: {upgrade_type_info.emoji}"), accessory=edit_emoji_button)
        edit_is_refit_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_is_refit")
        is_refit_display = ui.Section(ui.TextDisplay(content=f"Is Refit: {upgrade_type_info.is_refit}"), accessory=edit_is_refit_button)
        edit_non_purchaseable_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_non_purchaseable")
        non_purchaseable_display = ui.Section(ui.TextDisplay(content=f"Non-Purchaseable: {upgrade_type_info.non_purchaseable}"), accessory=edit_non_purchaseable_button)
        edit_can_use_unit_req_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_can_use_unit_req")
        can_use_unit_req_display = ui.Section(ui.TextDisplay(content=f"Can Use Unit Req: {upgrade_type_info.can_use_unit_req}"), accessory=edit_can_use_unit_req_button)
        edit_sort_order_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_sort_order")
        sort_order_display = ui.Section(ui.TextDisplay(content=f"Sort Order: {upgrade_type_info.sort_order}"), accessory=edit_sort_order_button)
        refresh_button = ui.Button(label="Refresh", style=ButtonStyle.primary, custom_id="refresh")
        delete_button = ui.Button(label="Delete", style=ButtonStyle.danger, custom_id="delete")
        action_row = ui.ActionRow(refresh_button, delete_button)
        self.add_item(name_display)
        self.add_item(emoji_display)
        self.add_item(is_refit_display)
        self.add_item(non_purchaseable_display)
        self.add_item(can_use_unit_req_display)
        self.add_item(sort_order_display)
        self.add_item(action_row)
        edit_name_button.callback = self.edit_name_button_callback
        edit_emoji_button.callback = self.edit_emoji_button_callback
        edit_is_refit_button.callback = self.edit_is_refit_button_callback
        edit_non_purchaseable_button.callback = self.edit_non_purchaseable_button_callback
        edit_can_use_unit_req_button.callback = self.edit_can_use_unit_req_button_callback
        edit_sort_order_button.callback = self.edit_sort_order_button_callback
        refresh_button.callback = self.refresh_button_callback
        delete_button.callback = self.delete_button_callback

    @error_reporting(True)
    async def refresh_button_callback(self, interaction: Interaction):
        layout_view = ShopUpgradeTypeInfoLayoutView(self.upgrade_type)
        await interaction.response.edit_message(view=layout_view)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def delete_button_callback(self, interaction: Interaction, session: Session):
        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == self.upgrade_type).first()
        if upgrade_type is None:
            await interaction.response.send_message("Upgrade type not found", ephemeral=True)
            return
        if upgrade_type.shop_upgrades:
            await interaction.response.send_message("Cannot delete an upgrade type that has upgrades assigned to it", ephemeral=True)
            return
        if upgrade_type.player_upgrades:
            await interaction.response.send_message("Cannot delete an upgrade type that has player upgrades assigned to it", ephemeral=True)
            return
        session.delete(upgrade_type)
        session.commit()
        await interaction.response.send_message("Upgrade type deleted", ephemeral=True)
        await interaction.message.delete()

    @error_reporting(True)
    async def edit_name_button_callback(self, interaction: Interaction):
        modal = ShopUpgradeTypeEditNameModal(self.upgrade_type, self.old_name, interaction.edit_original_response, ShopUpgradeTypeInfoLayoutView)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def edit_emoji_button_callback(self, interaction: Interaction):
        modal = ShopUpgradeTypeEditEmojiModal(self.upgrade_type, self.old_emoji)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def edit_is_refit_button_callback(self, interaction: Interaction):
        modal = ShopUpgradeTypeEditIsRefitModal(self.upgrade_type, self.old_is_refit)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def edit_non_purchaseable_button_callback(self, interaction: Interaction):
        modal = ShopUpgradeTypeEditNonPurchaseableModal(self.upgrade_type, self.old_non_purchaseable)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def edit_can_use_unit_req_button_callback(self, interaction: Interaction):
        modal = ShopUpgradeTypeEditCanUseUnitReqModal(self.upgrade_type, self.old_can_use_unit_req)
        await interaction.response.send_modal(modal)

    @error_reporting(True)
    async def edit_sort_order_button_callback(self, interaction: Interaction):
        modal = ShopUpgradeTypeEditSortOrderModal(self.upgrade_type, self.old_sort_order)
        await interaction.response.send_modal(modal)

class ShopUpgradeTypeEditNameModal(RecordingModal):
    def __init__(self, upgrade_type: str, old_name: str, refresh_hook: Callable, view_cls: type[RecordingLayoutView]):
        super().__init__(title="Edit Name")
        self.upgrade_type = upgrade_type
        self.add_item(ui.Label(text="Name", component=ui.TextInput(max_length=30, default=old_name)))
        self.refresh_hook = refresh_hook
        self.view_cls = view_cls

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == self.upgrade_type).first()
        if upgrade_type is None:
            await interaction.response.send_message("Upgrade type not found", ephemeral=True)
            return
        new_upgrade_type = UpgradeType(name=self.children[0].component.value, emoji=upgrade_type.emoji, is_refit=upgrade_type.is_refit, non_purchaseable=upgrade_type.non_purchaseable, can_use_unit_req=upgrade_type.can_use_unit_req, sort_order=upgrade_type.sort_order)
        session.add(new_upgrade_type)
        for shop_upgrade in upgrade_type.shop_upgrades:
            shop_upgrade.type = new_upgrade_type.name
        for player_upgrade in upgrade_type.player_upgrades:
            player_upgrade.type = new_upgrade_type.name
        session.commit()
        session.delete(upgrade_type)
        session.commit()
        layout_view = self.view_cls(new_upgrade_type.name)
        await self.refresh_hook(view=layout_view)
        await interaction.response.send_message("Upgrade type renamed, view has been automatically refreshed", ephemeral=True)

class ShopUpgradeTypeEditEmojiModal(RecordingModal):
    def __init__(self, upgrade_type: str, old_emoji: str):
        super().__init__(title="Edit Emoji")
        self.upgrade_type = upgrade_type
        self.add_item(ui.Label(text="Emoji", component=ui.TextInput(max_length=4, default=old_emoji)))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == self.upgrade_type).first()
        if upgrade_type is None:
            await interaction.response.send_message("Upgrade type not found", ephemeral=True)
            return
        upgrade_type.emoji = self.children[0].component.value
        session.commit()
        await interaction.response.send_message("Emoji updated", ephemeral=True)

class ShopUpgradeTypeEditIsRefitModal(RecordingModal):
    def __init__(self, upgrade_type: str, old_is_refit: bool):
        super().__init__(title="Edit Is Refit")
        self.upgrade_type = upgrade_type
        self.add_item(ui.Label(text="Is Refit", component=ui.Checkbox(default=old_is_refit)))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == self.upgrade_type).first()
        if upgrade_type is None:
            await interaction.response.send_message("Upgrade type not found", ephemeral=True)
            return
        upgrade_type.is_refit = self.children[0].component.value
        session.commit()
        await interaction.response.send_message("Is Refit updated", ephemeral=True)

class ShopUpgradeTypeEditNonPurchaseableModal(RecordingModal):
    def __init__(self, upgrade_type: str, old_non_purchaseable: bool):
        super().__init__(title="Edit Non Purchaseable")
        self.upgrade_type = upgrade_type
        self.add_item(ui.Label(text="Non Purchaseable", component=ui.Checkbox(default=old_non_purchaseable)))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == self.upgrade_type).first()
        if upgrade_type is None:
            await interaction.response.send_message("Upgrade type not found", ephemeral=True)
            return
        upgrade_type.non_purchaseable = self.children[0].component.value
        session.commit()
        await interaction.response.send_message("Non Purchaseable updated", ephemeral=True)

class ShopUpgradeTypeEditCanUseUnitReqModal(RecordingModal):
    def __init__(self, upgrade_type: str, old_can_use_unit_req: bool):
        super().__init__(title="Edit Can Use Unit Req")
        self.upgrade_type = upgrade_type
        self.add_item(ui.Label(text="Can Use Unit Req", component=ui.Checkbox(default=old_can_use_unit_req)))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == self.upgrade_type).first()
        if upgrade_type is None:
            await interaction.response.send_message("Upgrade type not found", ephemeral=True)
            return
        upgrade_type.can_use_unit_req = self.children[0].component.value
        session.commit()
        await interaction.response.send_message("Can Use Unit Req updated", ephemeral=True)

class ShopUpgradeTypeEditSortOrderModal(RecordingModal):
    def __init__(self, upgrade_type: str, old_sort_order: int):
        super().__init__(title="Edit Sort Order")
        self.upgrade_type = upgrade_type
        self.add_item(ui.Label(text="Sort Order", component=ui.TextInput(max_length=3, default=old_sort_order)))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == self.upgrade_type).first()
        if upgrade_type is None:
            await interaction.response.send_message("Upgrade type not found", ephemeral=True)
            return
        try:
            new_sort_order = int(self.children[0].component.value)
            if new_sort_order < 0:
                await interaction.response.send_message("Sort order cannot be negative", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("Invalid input: sort order must be an integer", ephemeral=True)
            return
        upgrade_type.sort_order = new_sort_order
        session.commit()
        await interaction.response.send_message("Sort Order updated", ephemeral=True)

class ShopUpgradeSelectLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, session: Session):
        super().__init__(timeout=None)
        upgrades = session.query(ShopUpgrade).order_by(ShopUpgrade.sort_key).all()
        options = [SelectOption(label=upgrade.name, value=upgrade.id) for upgrade in upgrades]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            select = ui.Select(placeholder="No upgrades", options=[SelectOption(label="No upgrades", value="no_upgrades", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            add_button = ui.Button(label="Add Upgrade", style=ButtonStyle.green, custom_id="add_upgrade")
            add_button.callback = self.add_upgrade_button_callback
            action_row = ui.ActionRow(add_button)
            self.add_item(action_row)
            return
        if len(chunks) >= 20:
            select = ui.Select(placeholder="Why Do you have 500 upgrades?", options=[SelectOption(label="Why Do you have 500 upgrades?", value="too_many_upgrades", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for chunk in chunks:
            select = ui.Select(placeholder="Select an upgrade", options=chunk)
            select.callback = self.upgrade_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
        add_button = ui.Button(label="Add Upgrade", style=ButtonStyle.green, custom_id="add_upgrade")
        add_button.callback = self.add_upgrade_button_callback
        action_row = ui.ActionRow(add_button)
        self.add_item(action_row)

    @error_reporting(True)
    async def upgrade_select_callback(self, interaction: Interaction):
        layout_view = ShopUpgradeInfoLayoutView(interaction.data["values"][0])
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @error_reporting(True)
    async def add_upgrade_button_callback(self, interaction: Interaction):
        modal = ShopAddUpgradeModal()
        await interaction.response.send_modal(modal)

class ShopUpgradeInfoLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, upgrade_id: int, session: Session):
        super().__init__(timeout=None)
        self.upgrade_id = upgrade_id
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == upgrade_id).first()
        self.old_name = upgrade.name
        self.old_type = upgrade.type
        self.old_cost = upgrade.cost
        self.old_disabled = upgrade.disabled
        self.old_repeatable = upgrade.repeatable
        self.old_refit_target = upgrade.refit_target
        self.old_required_upgrade_id = upgrade.required_upgrade_id
        if upgrade is None:
            raise ValueError("Upgrade not found")
        id_display = ui.TextDisplay(content=f"Upgrade ID: {upgrade.id}")
        name_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_name")
        name_display = ui.Section(ui.TextDisplay(content=f"Upgrade Name: {upgrade.name}"), accessory=name_button)
        type_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_type")
        type_display = ui.Section(ui.TextDisplay(content=f"Upgrade Type: {upgrade.type}"), accessory=type_button)
        cost_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_cost")
        cost_display = ui.Section(ui.TextDisplay(content=f"Upgrade Cost: {upgrade.cost}"), accessory=cost_button)
        disabled_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_disabled")
        disabled_display = ui.Section(ui.TextDisplay(content=f"Upgrade Disabled: {upgrade.disabled}"), accessory=disabled_button)
        repeatable_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_repeatable")
        repeatable_display = ui.Section(ui.TextDisplay(content=f"Upgrade Repeatable: {upgrade.repeatable}"), accessory=repeatable_button)
        refit_target_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_refit_target")
        refit_target_display = ui.Section(ui.TextDisplay(content=f"Upgrade Refit Target: {upgrade.refit_target if upgrade.refit_target else '—'}"), accessory=refit_target_button)
        required_upgrade_id_button = ui.Button(label="Edit", style=ButtonStyle.primary, custom_id="edit_required_upgrade_id")
        required_upgrade_id_display = ui.Section(ui.TextDisplay(content=f"Upgrade Required Upgrade: {upgrade.required_upgrade.name if upgrade.required_upgrade else '—'}"), accessory=required_upgrade_id_button)
        unit_types_button = ui.Button(label="Edit Compatible Unit Types", style=ButtonStyle.primary, custom_id="edit_unit_types")
        refresh_button = ui.Button(label="Refresh", style=ButtonStyle.primary, custom_id="refresh")
        delete_button = ui.Button(label="Delete", style=ButtonStyle.danger, custom_id="delete")
        action_row = ui.ActionRow(unit_types_button, refresh_button, delete_button)
        self.add_item(id_display)
        self.add_item(name_display)
        self.add_item(type_display)
        self.add_item(cost_display)
        self.add_item(disabled_display)
        self.add_item(repeatable_display)
        self.add_item(refit_target_display)
        self.add_item(required_upgrade_id_display)
        self.add_item(action_row)
        unit_types_button.callback = self.edit_unit_types_button_callback
        refresh_button.callback = self.refresh_button_callback
        delete_button.callback = self.delete_button_callback
        name_button.callback = self.edit_name_button_callback
        type_button.callback = self.edit_type_button_callback
        cost_button.callback = self.edit_cost_button_callback
        disabled_button.callback = self.edit_disabled_button_callback
        repeatable_button.callback = self.edit_repeatable_button_callback
        refit_target_button.callback = self.edit_refit_target_button_callback
        required_upgrade_id_button.callback = self.edit_required_upgrade_id_button_callback

    @error_reporting(True)
    async def refresh_button_callback(self, interaction: Interaction):
        layout_view = ShopUpgradeInfoLayoutView(self.upgrade_id)
        await interaction.response.edit_message(view=layout_view)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def delete_button_callback(self, interaction: Interaction, session: Session):
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == self.upgrade_id).first()
        if upgrade is None:
            await interaction.response.send_message("Upgrade not found", ephemeral=True)
            return
        if upgrade.player_upgrades:
            await interaction.response.send_message("Cannot delete an upgrade that has player upgrades assigned to it", ephemeral=True)
            return
        if upgrade.unit_types:
            await interaction.response.send_message("Cannot delete an upgrade that has unit types assigned to it", ephemeral=True)
            return
        if upgrade.required_by:
            await interaction.response.send_message("Cannot delete an upgrade that is required by another upgrade", ephemeral=True)
            return
        session.delete(upgrade)
        session.commit()
        await interaction.response.send_message("Upgrade deleted", ephemeral=True)
        await interaction.message.delete()

    @error_reporting(True)
    async def edit_name_button_callback(self, interaction: Interaction):
        modal = ShopUpgradeEditNameModal(self.upgrade_id, self.old_name, ShopUpgradeInfoLayoutView)
        await interaction.response.send_modal(modal)
                
    @error_reporting(True)
    async def edit_type_button_callback(self, interaction: Interaction):
        layout_view = ShopUpgradeEditTypeLayoutView(self.upgrade_id, self.old_type, interaction.message.edit, ShopUpgradeInfoLayoutView)
        await interaction.response.send_message(view=layout_view, ephemeral=True)
                
    @error_reporting(True)
    async def edit_cost_button_callback(self, interaction: Interaction):
        modal = ShopUpgradeEditCostModal(self.upgrade_id, self.old_cost, ShopUpgradeInfoLayoutView)
        await interaction.response.send_modal(modal)
                
    @error_reporting(True)
    async def edit_disabled_button_callback(self, interaction: Interaction):
        modal = ShopUpgradeEditDisabledModal(self.upgrade_id, self.old_disabled, ShopUpgradeInfoLayoutView)
        await interaction.response.send_modal(modal)
                
    @error_reporting(True)
    async def edit_repeatable_button_callback(self, interaction: Interaction):
        modal = ShopUpgradeEditRepeatableModal(self.upgrade_id, self.old_repeatable, ShopUpgradeInfoLayoutView)
        await interaction.response.send_modal(modal)
                
    @error_reporting(True)
    async def edit_refit_target_button_callback(self, interaction: Interaction):
        layout_view = ShopUpgradeEditRefitTargetLayoutView(self.upgrade_id, self.old_refit_target, interaction.message.edit, ShopUpgradeInfoLayoutView)
        await interaction.response.send_message(view=layout_view, ephemeral=True)
                
    @error_reporting(True)
    async def edit_required_upgrade_id_button_callback(self, interaction: Interaction):
        layout_view = ShopUpgradeEditRequiredUpgradeIdLayoutView(self.upgrade_id, self.old_required_upgrade_id, interaction.message.edit, ShopUpgradeInfoLayoutView)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @error_reporting(True)
    async def edit_unit_types_button_callback(self, interaction: Interaction):
        layout_view = ShopUpgradeEditUnitTypesLayoutView(self.upgrade_id, interaction.message.edit, ShopUpgradeInfoLayoutView)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

class ShopUpgradeEditNameModal(RecordingModal):
    def __init__(self, upgrade_id: int, old_name: str, parent_class: type):
        super().__init__(title="Edit Name")
        self.upgrade_id = upgrade_id
        self.add_item(ui.Label(text="Name", component=ui.TextInput(max_length=30, default=old_name)))
        self.parent_class = parent_class

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == self.upgrade_id).first()
        if upgrade is None:
            await interaction.response.send_message("Upgrade not found", ephemeral=True)
            return
        upgrade.name = self.children[0].component.value
        session.commit()
        layout_view = self.parent_class(self.upgrade_id)
        await interaction.response.edit_message(view=layout_view)
        await interaction.followup.send("Name updated", ephemeral=True)

class ShopUpgradeEditTypeLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, upgrade_id: int, old_type: str, edit_callback: Callable, parent_class: type, session: Session):
        super().__init__(timeout=None)
        self.upgrade_id = upgrade_id
        self.old_type = old_type
        self.edit_callback = edit_callback
        self.parent_class = parent_class
        upgrade_types = session.query(UpgradeType).all()
        type_options = [SelectOption(label=upgrade_type.name, value=upgrade_type.name, default=(upgrade_type.name == old_type)) for upgrade_type in upgrade_types]
        type_chunks = [type_options[i:i+25] for i in range(0, len(type_options), 25)]
        if len(type_chunks) >= 21:
            select = ui.Select(placeholder="Why Do you have 525 upgrade types?", options=[SelectOption(label="Why Do you have 525 upgrade types?", value="too_many_upgrade_types", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for type_chunk in type_chunks:
            select = ui.Select(placeholder="Select an upgrade type", options=type_chunk)
            select.callback = self.type_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def type_select_callback(self, interaction: Interaction, session: Session):
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == self.upgrade_id).first()
        if upgrade is None:
            await interaction.response.send_message("Upgrade not found", ephemeral=True)
            return
        upgrade.type = interaction.data["values"][0]
        session.commit()
        await self.edit_callback(view=self.parent_class(self.upgrade_id))
        content = RecordingLayoutView()
        content.add_item(ui.TextDisplay(content="Type updated"))
        await interaction.response.edit_message(view=content)

class ShopUpgradeEditCostModal(RecordingModal):
    def __init__(self, upgrade_id: int, old_cost: int, parent_class: type):
        super().__init__(title="Edit Cost")
        self.upgrade_id = upgrade_id
        self.add_item(ui.Label(text="Cost", component=ui.TextInput(max_length=10, default=old_cost)))
        self.parent_class = parent_class

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == self.upgrade_id).first()
        if upgrade is None:
            await interaction.response.send_message("Upgrade not found", ephemeral=True)
            return
        try:
            new_cost = int(self.children[0].component.value)
            if new_cost < 0:
                await interaction.response.send_message("Cost cannot be negative", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("Invalid input: cost must be an integer", ephemeral=True)
            return
        upgrade.cost = new_cost
        session.commit()    
        layout_view = self.parent_class(self.upgrade_id)
        await interaction.response.edit_message(view=layout_view)
        await interaction.followup.send("Cost updated", ephemeral=True)

class ShopUpgradeEditDisabledModal(RecordingModal):
    def __init__(self, upgrade_id: int, old_disabled: bool, parent_class: type):
        super().__init__(title="Edit Disabled")
        self.upgrade_id = upgrade_id
        self.add_item(ui.Label(text="Disabled", component=ui.Checkbox(default=old_disabled)))
        self.parent_class = parent_class

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == self.upgrade_id).first()
        if upgrade is None:
            await interaction.response.send_message("Upgrade not found", ephemeral=True)
            return
        upgrade.disabled = self.children[0].component.value
        session.commit()
        layout_view = self.parent_class(self.upgrade_id)
        await interaction.response.edit_message(view=layout_view)
        await interaction.followup.send("Disabled updated", ephemeral=True)

class ShopUpgradeEditRepeatableModal(RecordingModal):
    def __init__(self, upgrade_id: int, old_repeatable: bool, parent_class: type):
        super().__init__(title="Edit Repeatable")
        self.upgrade_id = upgrade_id
        Options = [discord.RadioGroupOption(label="Unlimited", value="0", default=(old_repeatable == 0))] + [discord.RadioGroupOption(label=str(n), value=str(n), default=(old_repeatable == n)) for n in range(1, 6)]
        self.add_item(ui.Label(text="Repeatable", component=ui.RadioGroup(options=Options)))
        self.parent_class = parent_class
                    
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == self.upgrade_id).first()
        if upgrade is None:
            await interaction.response.send_message("Upgrade not found", ephemeral=True)
            return
        upgrade.repeatable = self.children[0].component.value
        session.commit()
        layout_view = self.parent_class(self.upgrade_id)
        await interaction.response.edit_message(view=layout_view)
        await interaction.followup.send("Repeatable updated", ephemeral=True)

class ShopUpgradeEditRefitTargetLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, upgrade_id: int, old_refit_target: str, edit_callback: Callable, parent_class: type, session: Session):
        super().__init__(timeout=None)
        self.upgrade_id = upgrade_id
        self.old_refit_target = old_refit_target
        self.edit_callback = edit_callback
        self.parent_class = parent_class
        unit_types = session.query(UnitType).filter(UnitType.is_base == False).all()
        refit_options = [SelectOption(label="None", value="none", default=(old_refit_target is None))] + [SelectOption(label=unit_type.unit_type, value=unit_type.unit_type, default=(unit_type.unit_type == old_refit_target)) for unit_type in unit_types]
        refit_chunks = [refit_options[i:i+25] for i in range(0, len(refit_options), 25)]
        if not refit_chunks:
            select = ui.Select(placeholder="No unit types", options=[SelectOption(label="No unit types", value="no_unit_types", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        if len(refit_chunks) >= 21:
            select = ui.Select(placeholder="Why Do you have 525 unit types?", options=[SelectOption(label="Why Do you have 525 unit types?", value="too_many_unit_types", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for refit_chunk in refit_chunks:
            select = ui.Select(placeholder="Select a unit type", options=refit_chunk)
            select.callback = self.refit_target_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
                            
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def refit_target_select_callback(self, interaction: Interaction, session: Session):
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == self.upgrade_id).first()
        if (new_refit_target := interaction.data["values"][0]) == "none":
            upgrade.refit_target = None
        else:
            upgrade.refit_target = new_refit_target
        session.commit()
        content = RecordingLayoutView()
        content.add_item(ui.TextDisplay(content="Refit target updated"))
        await interaction.response.edit_message(view=content)
        await self.edit_callback(view=self.parent_class(self.upgrade_id))

class ShopUpgradeEditRequiredUpgradeIdLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, upgrade_id: int, old_required_upgrade_id: int, edit_callback: Callable, parent_class: type, session: Session):
        super().__init__(timeout=None)
        self.upgrade_id = upgrade_id
        self.old_required_upgrade_id = old_required_upgrade_id
        self.edit_callback = edit_callback
        self.parent_class = parent_class
        shop_upgrades = session.query(ShopUpgrade).all()
        required_upgrade_options = [SelectOption(label="None", value="none", default=(old_required_upgrade_id is None))] + [SelectOption(label=shop_upgrade.name, value=shop_upgrade.id, default=(shop_upgrade.id == old_required_upgrade_id)) for shop_upgrade in shop_upgrades]
        required_upgrade_chunks = [required_upgrade_options[i:i+25] for i in range(0, len(required_upgrade_options), 25)]
        if not required_upgrade_chunks:
            select = ui.Select(placeholder="No shop upgrades", options=[SelectOption(label="No shop upgrades", value="no_shop_upgrades", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        if len(required_upgrade_chunks) >= 20:
            select = ui.Select(placeholder="Why Do you have 500 shop upgrades?", options=[SelectOption(label="Why Do you have 500 shop upgrades?", value="too_many_shop_upgrades", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        self.add_item(ui.TextDisplay(content=f"Please select the new required upgrade"))
        for required_upgrade_chunk in required_upgrade_chunks:
            select = ui.Select(placeholder="Select a shop upgrade", options=required_upgrade_chunk)
            select.callback = self.required_upgrade_id_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
                            
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def required_upgrade_id_select_callback(self, interaction: Interaction, session: Session):
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == self.upgrade_id).first()
        if (new_required_upgrade_id := int(interaction.data["values"][0])) == "none":
            upgrade.required_upgrade_id = None
        else:
            upgrade.required_upgrade_id = new_required_upgrade_id
        session.commit()
        content = RecordingLayoutView()
        content.add_item(ui.TextDisplay(content="Required upgrade updated"))
        await interaction.response.edit_message(view=content) # you can't set text content if the message had a LayoutView on it, so we must wrap the text in a layout view
        await self.edit_callback(view=self.parent_class(self.upgrade_id))

class ShopUpgradeEditUnitTypesLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, upgrade_id: int, edit_callback: Callable, parent_class: type, session: Session):
        super().__init__(timeout=None)
        self.upgrade_id = upgrade_id
        self.edit_callback = edit_callback
        self.parent_class = parent_class
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == upgrade_id).first()
        if upgrade is None:
            raise ValueError("Upgrade not found")
        unit_types = session.query(UnitType).all()
        options = [SelectOption(label=unit_type.unit_type, value=unit_type.unit_type, default=(unit_type in upgrade.compatible_unit_types)) for unit_type in unit_types]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        logger.debug([len(chunk) for chunk in chunks])
        logger.debug(len(chunks))
        if not chunks:
            select = ui.Select(placeholder="No unit types", options=[SelectOption(label="No unit types", value="no_unit_types", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        if len(chunks) >= 21:
            select = ui.Select(placeholder="Why Do you have 525 unit types?", options=[SelectOption(label="Why Do you have 525 unit types?", value="too_many_unit_types", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for chunk in chunks:
            select = ui.Select(placeholder="Select a unit type", options=chunk, max_values=len(chunk), min_values=0)
            select.callback = self.unit_type_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
        self.cache = {}
        for child in self.walk_children():
            if isinstance(child, ui.Select):
                self.cache[child.custom_id] = (option.value for option in child.options if option.default)
                            
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def unit_type_select_callback(self, interaction: Interaction, session: Session):
        self.cache[interaction.custom_id] = interaction.data["values"]
        selected = [choice for choices in self.cache.values() for choice in choices]
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == self.upgrade_id).first()
        if upgrade is None:
            await interaction.response.send_message("Upgrade not found", ephemeral=True)
            return
        selected_unit_types = session.query(UnitType).filter(UnitType.unit_type.in_(selected)).all()
        upgrade.compatible_unit_types = selected_unit_types
        session.commit()
        await self.edit_callback(view=self.parent_class(self.upgrade_id))
        content = RecordingLayoutView()
        content.add_item(ui.TextDisplay(content="Unit types updated"))
        await interaction.response.edit_message(view=content)

class ShopAddUpgradeModal(RecordingModal):
    def __init__(self):
        super().__init__(title="Add Upgrade")
        # we only need name and upgrade type, we will then just make an UpgradeTypeInfoLayoutView for the rest, but we need a view for the upgrade type, so it will be in 3 stages
        self.add_item(ui.TextInput(label="Name", placeholder="Enter the upgrade name", required=True, max_length=30))

    @error_reporting(True)
    async def on_submit(self, interaction: Interaction):
        name = self.children[0].value.strip().upper()
        await interaction.response.send_message(view=ShopAddUpgradeTypeSelectLayoutView(name), ephemeral=True)

class ShopAddUpgradeTypeSelectLayoutView(RecordingLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, name: str, session: Session):
        super().__init__(timeout=None)
        self.name = name
        upgrade_types = session.query(UpgradeType).all()
        options = [SelectOption(label=upgrade_type.name, value=upgrade_type.name) for upgrade_type in upgrade_types]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            select = ui.Select(placeholder="No upgrade types", options=[SelectOption(label="No upgrade types", value="no_upgrade_types", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        if len(chunks) >= 21:
            select = ui.Select(placeholder="Why Do you have 525 upgrade types?", options=[SelectOption(label="Why Do you have 525 upgrade types?", value="too_many_upgrade_types", default=True)], disabled=True)
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
            return
        for chunk in chunks:
            select = ui.Select(placeholder="Select a upgrade type", options=chunk)
            select.callback = self.upgrade_type_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def upgrade_type_select_callback(self, interaction: Interaction, session: Session):
        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == interaction.data["values"][0]).first()
        if upgrade_type is None:
            await interaction.response.send_message("Upgrade type not found", ephemeral=True)
            return
        upgrade = ShopUpgrade(name=self.name, type=upgrade_type.name)
        session.add(upgrade)
        session.commit()
        layout_view = ShopUpgradeInfoLayoutView(upgrade.id)
        await interaction.response.edit_message(view=layout_view)

class Manage(GroupCog, description="Management commands: company, units, and related operations. Management only."):
    """
    Cog for management slash commands: company, units, and related
    management operations. Restricted to management users.
    """

    def __init__(self, bot: CustomClient):
        """Store a reference to the bot instance."""

        self.bot = bot

    async def interaction_check(self, interaction: Interaction, /) -> bool:
        return await is_management(interaction)

    @ac.command(name="menu", description="Open the management menu")
    @error_reporting(True)
    async def menu(self, interaction: Interaction):
        layout_view = RecordingLayoutView(timeout=None)
        action_row = ui.ActionRow()
        company_button = ui.Button(label="Company", style=ButtonStyle.primary, custom_id="company_button")
        company_button.callback = self.company_button_callback
        shop_button = ui.Button(label="Shop", style=ButtonStyle.primary, custom_id="shop_button")
        shop_button.callback = self.shop_button_callback
        action_row.add_item(company_button)
        action_row.add_item(shop_button)
        layout_view.add_item(action_row)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @error_reporting(True)
    async def company_button_callback(self, interaction: Interaction):
        layout_view = RecordingLayoutView(timeout=None)
        action_row = ui.ActionRow()
        player_select = ui.UserSelect(placeholder="Select a player")
        action_row.add_item(player_select)
        layout_view.add_item(action_row)
        player_select.callback = self.player_select_callback
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def player_select_callback(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.discord_id == interaction.data["values"][0]).first()
        if player is None:
            await interaction.response.send_message(tmpl.player_not_found, ephemeral=True)
            return
        layout_view = CompanyLayoutView(player)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

    async def shop_button_callback(self, interaction: Interaction):
        layout_view = ShopLayoutView()
        await interaction.response.send_message(view=layout_view, ephemeral=True)

async def setup(_bot: CustomClient):
    await _bot.add_cog(Manage(_bot))

async def teardown(_bot: CustomClient):
    await _bot.remove_cog(Manage.__name__)