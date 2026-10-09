import io
from logging import getLogger
from typing import Tuple

import discord
from discord import ButtonStyle, Interaction, SelectOption, app_commands as ac, ui
from discord.ext.commands import GroupCog
from sqlalchemy import exists, func
from sqlalchemy.orm import Session
import templates as tmpl

from customclient import CustomClient
from models import Campaign, CampaignInvite, Player, Unit as Unit_model, UnitStatus, UnitType
from utils import EnvironHelpers, RecordingLayoutView, RecordingModal, error_reporting, fuzzy_autocomplete, hide_arg, maybe_decorate, uses_db

logger = getLogger(__name__)

ALLOW_BATTLE_GROUPS = EnvironHelpers.get_bool("ALLOW_NOTIFY_GROUP_COMMAND", False)
MAX_PROPOSED_UNITS = 3
MAX_UNITS = 25

STATUS_EMOJI = {
    UnitStatus.ACTIVE: "✅",
    UnitStatus.INACTIVE: "💤",
    UnitStatus.PROPOSED: "📝",
    UnitStatus.MIA: "❓",
    UnitStatus.KIA: "☠️",
    UnitStatus.LEGACY: "📜",
}

def unit_emoji(unit: Unit_model) -> str | None:
    return "📦" if unit.unit_type == "STOCKPILE" else STATUS_EMOJI.get(unit.status)

def unit_name_error(unit_name: str) -> str | None:
    """Return the template to show the user if the name is unusable, else None."""
    if len(unit_name) > 30:
        return tmpl.unit_name_too_long
    if any(char in unit_name for char in EnvironHelpers.get_str("BANNED_CHARS", "") + ":"): # : is banned to disable urls
        return tmpl.unit_name_invalid
    if not unit_name.isascii():
        return tmpl.unit_name_ascii
    return None

def callsign_error(callsign: str) -> str | None:
    """Return the template to show the user if the callsign is unusable, else None."""
    if len(callsign) > 7:
        return tmpl.callsign_too_long
    if any(char in callsign for char in EnvironHelpers.get_str("BANNED_CHARS", "")):
        return tmpl.callsign_invalid
    if not callsign.isascii():
        return tmpl.callsign_ascii
    return None

def unit_creation_error(unit_name: str, player_id: int, session: Session) -> str | None:
    """Validate a new unit name against the player's existing units and limits."""
    error = unit_name_error(unit_name)
    if error:
        return error
    if session.query(exists().where(Unit_model.name == unit_name, Unit_model.player_id == player_id)).scalar():
        return tmpl.unit_name_exists
    proposed_count = session.query(func.count(Unit_model.id)).filter(Unit_model.player_id == player_id, Unit_model.status == UnitStatus.PROPOSED).scalar()
    if proposed_count >= MAX_PROPOSED_UNITS:
        return tmpl.player_max_proposed_units
    unit_count = session.query(func.count(Unit_model.id)).filter(Unit_model.player_id == player_id, Unit_model.unit_type != "STOCKPILE").scalar()
    if unit_count >= MAX_UNITS:
        return tmpl.player_max_units
    return None

def member_role_ids(interaction: Interaction) -> frozenset[int]:
    return frozenset(role.id for role in getattr(interaction.user, "roles", []))

def campaign_eligibility(campaign: Campaign, player: Player, role_ids: frozenset[int], session: Session) -> Tuple[bool, str]:
    """Return whether the player may join the campaign, and the emoji explaining why."""
    if campaign.gm == player.discord_id:
        return False, "🧙"
    if campaign.player_limit and campaign.player_limit <= len(campaign.units):
        return False, "📦"
    if campaign.required_role and campaign.required_role not in role_ids:
        return False, "🛡️"
    if session.query(CampaignInvite).filter(CampaignInvite.campaign_id == campaign.id, CampaignInvite.player_id == player.id).first():
        return True, "✉"
    if not campaign.open:
        return False, "🔒"
    return True, "✅"

def deactivate_unit(unit: Unit_model, session: Session) -> str:
    """Deactivate a unit, returning the callsign it held."""
    original_callsign = unit.callsign
    logger.debug(f"Deactivating unit {unit.id} ({unit.name}), callsign {original_callsign}, campaign {unit.campaign_id}")
    unit.active = False
    unit.status = UnitStatus.INACTIVE if unit.status == UnitStatus.ACTIVE else unit.status
    unit.callsign = None
    unit.campaign_id = None
    unit.battle_group = None
    session.commit()
    return original_callsign

class Unit(GroupCog, description="Unit commands: menu, create, rename, activate, deactivate, remove."):
    """
    Cog for unit-related slash commands. All flows are driven by the unit menu;
    the create, rename, and activate commands are shortcuts into its submenus.
    """

    def __init__(self, bot: CustomClient):
        """Store a reference to the bot instance."""

        self.bot = bot

    @ac.command(name="menu", description="Show your units")
    @error_reporting()
    async def menu(self, interaction: Interaction):
        await interaction.response.send_message(view=UnitMenuLayoutView(interaction.user.id), ephemeral=True)

    @ac.command(name="create", description="Create a new unit for a player")
    @ac.describe(unit_name="The name of the unit to create")
    @error_reporting()
    @uses_db(CustomClient().sessionmaker)
    async def createunit(self, interaction: Interaction, unit_name: str, session: Session):
        player_id = session.query(Player.id).filter(Player.discord_id == interaction.user.id).scalar()
        if not player_id:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=True)
            return
        error = unit_creation_error(unit_name, player_id, session)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.send_message(view=UnitCreateLayoutView(interaction.user.id, unit_name), ephemeral=True)

    @ac.command(name="rename", description="Rename a unit")
    @error_reporting()
    async def rename(self, interaction: Interaction):
        await interaction.response.send_message(view=UnitRenamePickerLayoutView(interaction.user.id), ephemeral=True)

    @ac.command(name="activate", description="Activate a unit")
    @ac.describe(callsign="The callsign of the unit to activate, must be globally unique")
    @maybe_decorate(
        (not ALLOW_BATTLE_GROUPS),
        hide_arg("group", None))
    @maybe_decorate(
        ALLOW_BATTLE_GROUPS,
        ac.describe(group="The group to activate the unit in"))
    @maybe_decorate(
        ALLOW_BATTLE_GROUPS,
        ac.autocomplete(group=fuzzy_autocomplete(Unit_model.battle_group, not_null=True)))
    @uses_db(CustomClient().sessionmaker)
    async def activateunit(self, interaction: Interaction, callsign: str, group: str, session: Session):
        """
        Activate one of the player's inactive units under the given callsign.
        Presents the unit selector, then the campaign selector.
        """

        error = callsign_error(callsign)
        if error:
            logger.warning(f"Callsign {callsign} from {interaction.user.global_name} is invalid: {error}")
            await interaction.response.send_message(error, ephemeral=True)
            return
        if session.query(exists().where(Unit_model.callsign == callsign)).scalar():
            logger.warning(f"Callsign {callsign} from {interaction.user.global_name} is already in use")
            await interaction.response.send_message(tmpl.callsign_taken, ephemeral=True)
            return
        if not session.query(exists().where(Player.discord_id == interaction.user.id)).scalar():
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=True)
            return
        await interaction.response.send_message(
            view=UnitActivatePickerLayoutView(interaction.user.id, callsign, group, member_role_ids(interaction)),
            ephemeral=True
        )

    @ac.command(name="deactivate", description="Deactivate a unit")
    @error_reporting()
    @uses_db(CustomClient().sessionmaker)
    async def deactivateunit(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=True)
            return
        active_units = list(player.active_units)
        if not active_units:
            await interaction.response.send_message(tmpl.unit_no_active_units, ephemeral=True)
            return
        if len(active_units) == 1:
            original_callsign = deactivate_unit(active_units[0], session)
            self.bot.queue.put_nowait((1, player, 0))
            await interaction.response.send_message(tmpl.unit_deactivated.format(original_callsign=original_callsign), ephemeral=True)
            return
        await interaction.response.send_message(view=UnitDeactivatePickerLayoutView(interaction.user.id), ephemeral=True)

    @ac.command(name="remove_unit", description="Remove a proposed unit from your company")
    @error_reporting()
    async def remove_unit(self, interaction: Interaction):
        await interaction.response.send_message(view=UnitRemovePickerLayoutView(interaction.user.id), ephemeral=True)

    #@ac.command(name="counts_by_unit_type", description="Display the number of units by unit type, made just for Frenchboi")
    @uses_db(CustomClient().sessionmaker)
    async def counts_by_unit_type(self, interaction: Interaction, session: Session):
        counts = session.query(Unit_model.unit_type, func.count()).filter(Unit_model.unit_type != "STOCKPILE").group_by(Unit_model.unit_type).order_by(func.count().desc()).all()
        counts_tsv = "unit_type\t count\n"
        for count in counts:
            counts_tsv += f"{count[0]}\t {count[1]}\n"
        file = discord.File(io.BytesIO(counts_tsv.encode()), filename="counts_by_unit_type.tsv")
        await interaction.response.send_message(file=file, ephemeral=True)

class UnitOwnerLayoutView(RecordingLayoutView):
    """Base layout view that only the player who opened the menu may use."""

    def __init__(self, discord_id: int):
        super().__init__(timeout=None)
        self.discord_id = discord_id

    @error_reporting(True)
    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != int(self.discord_id):
            logger.warning(f"User {interaction.user.id} tried to interact with view owned by {self.discord_id}")
            await interaction.response.send_message("You are not the owner of this menu", ephemeral=True)
            return False
        return True

    def add_back_button(self):
        back_button = ui.Button(label="Back", style=ButtonStyle.secondary)
        back_button.callback = self.back_button_callback
        self.add_item(ui.ActionRow(back_button))

    @error_reporting(True)
    async def back_button_callback(self, interaction: Interaction):
        await interaction.response.edit_message(view=UnitMenuLayoutView(self.discord_id))

class UnitPickerLayoutView(UnitOwnerLayoutView):
    """
    Lists a filtered set of the player's units in select menus. Subclasses choose
    which units are listed and what happens once one is picked.
    """

    placeholder = tmpl.unit_select_unit_placeholder
    empty_message = tmpl.no_units

    @uses_db(CustomClient().sessionmaker)
    def __init__(self, discord_id: int, session: Session):
        super().__init__(discord_id)
        player = session.query(Player).filter(Player.discord_id == discord_id).first()
        if player is None:
            self.add_item(ui.TextDisplay(content=tmpl.no_meta_campaign_company))
            return
        self.add_header(player)
        options = [
            SelectOption(
                label=unit.name,
                value=str(unit.id),
                description=f"{unit.unit_type} ({unit.status.name})"[:100],
                emoji=unit_emoji(unit)
            ) for unit in self.filter_units(player)
        ]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            self.add_item(ui.TextDisplay(content=self.empty_message))
        elif len(chunks) > 19:
            self.add_item(ui.TextDisplay(content=tmpl.too_many_units))
        else:
            for chunk in chunks:
                select = ui.Select(placeholder=self.placeholder, options=chunk)
                select.callback = self.unit_select_callback
                self.add_item(ui.ActionRow(select))
        self.add_footer(player)

    def filter_units(self, player: Player) -> list[Unit_model]:
        return list(player.units)

    def add_header(self, player: Player) -> None:
        """Hook for content shown above the unit selects."""

    def add_footer(self, player: Player) -> None:
        """Hook for content shown below the unit selects."""
        self.add_back_button()

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def unit_select_callback(self, interaction: Interaction, session: Session):
        unit = session.query(Unit_model).filter(Unit_model.id == int(interaction.data["values"][0])).first()
        if unit is None or int(unit.player.discord_id) != int(self.discord_id):
            await interaction.response.send_message(tmpl.unit_not_found, ephemeral=True)
            return
        await self.on_unit_selected(interaction, unit, session)

    async def on_unit_selected(self, interaction: Interaction, unit: Unit_model, session: Session):
        await interaction.response.edit_message(view=UnitInfoLayoutView(self.discord_id, unit.id))

class UnitMenuLayoutView(UnitPickerLayoutView):
    """Root menu: every unit the player owns, plus unit creation."""

    def add_header(self, player: Player) -> None:
        units = [unit for unit in player.units if unit.unit_type != "STOCKPILE"]
        max_active = EnvironHelpers.required_int("MAX_ACTIVE_UNITS")
        self.add_item(ui.Container(
            ui.TextDisplay(content=f"# {player.name}"),
            ui.TextDisplay(content=(
                f"**Active:** {sum(1 for unit in units if unit.active)}/{max_active}\n"
                f"**Proposed:** {sum(1 for unit in units if unit.status == UnitStatus.PROPOSED)}/{MAX_PROPOSED_UNITS}\n"
                f"**Units:** {len(units)}/{MAX_UNITS}"
            ))
        ))

    def add_footer(self, player: Player) -> None:
        units = [unit for unit in player.units if unit.unit_type != "STOCKPILE"]
        at_limit = (
            sum(1 for unit in units if unit.status == UnitStatus.PROPOSED) >= MAX_PROPOSED_UNITS
            or len(units) >= MAX_UNITS
        )
        create_button = ui.Button(label=tmpl.unit_create_button_label, style=ButtonStyle.success, disabled=at_limit)
        create_button.callback = self.create_button_callback
        self.add_item(ui.ActionRow(create_button))

    @error_reporting(True)
    async def create_button_callback(self, interaction: Interaction):
        await interaction.response.send_modal(UnitCreateNameModal(self.discord_id))

class UnitRenamePickerLayoutView(UnitPickerLayoutView):
    """Shortcut view for /unit rename."""

    placeholder = tmpl.unit_select_rename_placeholder
    empty_message = tmpl.no_units

    def filter_units(self, player: Player) -> list[Unit_model]:
        return [unit for unit in player.units if unit.unit_type != "STOCKPILE"]

    async def on_unit_selected(self, interaction: Interaction, unit: Unit_model, session: Session):
        await interaction.response.send_modal(UnitRenameModal(self.discord_id, unit.id, unit.name))

class UnitDeactivatePickerLayoutView(UnitPickerLayoutView):
    """Shortcut view for /unit deactivate when several units are active."""

    placeholder = tmpl.unit_select_deactivate_placeholder
    empty_message = tmpl.unit_no_active_units

    def filter_units(self, player: Player) -> list[Unit_model]:
        return [unit for unit in player.units if unit.active]

    async def on_unit_selected(self, interaction: Interaction, unit: Unit_model, session: Session):
        if not unit.active:
            await interaction.response.send_message(tmpl.unit_not_active, ephemeral=True)
            return
        player = unit.player
        original_callsign = deactivate_unit(unit, session)
        CustomClient().queue.put_nowait((1, player, 0))
        await interaction.response.edit_message(view=UnitInfoLayoutView(self.discord_id, unit.id))
        await interaction.followup.send(tmpl.unit_deactivated.format(original_callsign=original_callsign), ephemeral=True)

class UnitRemovePickerLayoutView(UnitPickerLayoutView):
    """Shortcut view for /unit remove_unit."""

    placeholder = tmpl.unit_select_remove_placeholder
    empty_message = tmpl.unit_no_proposed_units

    def filter_units(self, player: Player) -> list[Unit_model]:
        return [unit for unit in player.units if unit.status == UnitStatus.PROPOSED]

    async def on_unit_selected(self, interaction: Interaction, unit: Unit_model, session: Session):
        if unit.unit_type == "STOCKPILE":
            await interaction.response.send_message(tmpl.stockpile_cannot_remove, ephemeral=True)
            return
        if unit.status != UnitStatus.PROPOSED:
            await interaction.response.send_message("Only proposed units can be removed", ephemeral=True)
            return
        player = unit.player
        confirmation = tmpl.unit_removed.format(unit=unit)
        logger.debug(f"Removing unit {unit.id} ({unit.name})")
        session.delete(unit)
        session.commit()
        CustomClient().queue.put_nowait((1, player, 0))
        await interaction.response.edit_message(view=UnitMenuLayoutView(self.discord_id))
        await interaction.followup.send(confirmation, ephemeral=True)

class UnitActivatePickerLayoutView(UnitPickerLayoutView):
    """Shortcut view for /unit activate: pick the unit that takes the callsign."""

    placeholder = tmpl.unit_select_unit_placeholder
    empty_message = tmpl.unit_no_units_available

    def __init__(self, discord_id: int, callsign: str, group: str | None, role_ids: frozenset[int]):
        super().__init__(discord_id)
        self.callsign = callsign
        self.group = group
        self.role_ids = role_ids

    def filter_units(self, player: Player) -> list[Unit_model]:
        return [unit for unit in player.units if unit.status == UnitStatus.INACTIVE and unit.unit_type != "STOCKPILE"]

    async def on_unit_selected(self, interaction: Interaction, unit: Unit_model, session: Session):
        await interaction.response.edit_message(
            view=UnitActivateCampaignLayoutView(self.discord_id, unit.id, self.callsign, self.group, self.role_ids)
        )

class UnitInfoLayoutView(UnitOwnerLayoutView):
    """Details for a single unit, with the actions available for its status."""

    @uses_db(CustomClient().sessionmaker)
    def __init__(self, discord_id: int, unit_id: int, session: Session):
        super().__init__(discord_id)
        self.unit_id = unit_id
        unit = session.query(Unit_model).filter(Unit_model.id == unit_id).first()
        if unit is None:
            self.add_item(ui.TextDisplay(content=tmpl.unit_not_found))
            self.add_back_button()
            return
        self.unit_name = unit.name
        upgrades = ", ".join(upgrade.name for upgrade in unit.upgrades)
        details = (
            f"**Type:** {unit.unit_type}\n"
            f"**Status:** {unit.status.name}\n"
            f"**Callsign:** {unit.callsign or '—'}\n"
            f"**Campaign:** {unit.campaign.name if unit.campaign else '—'}\n"
        )
        if ALLOW_BATTLE_GROUPS:
            details += f"**Battle Group:** {unit.battle_group or '—'}\n"
        details += f"**{tmpl.UNIT_CURRENCY}:** {unit.unit_req}"
        self.add_item(ui.Container(
            ui.TextDisplay(content=f"# {unit_emoji(unit) or ''} {unit.name}".strip()),
            ui.TextDisplay(content=details),
            ui.TextDisplay(content=f"**Upgrades:** {upgrades or 'None'}")
        ))
        if unit.unit_type != "STOCKPILE":
            buttons = []
            rename_button = ui.Button(label="Rename", style=ButtonStyle.primary)
            rename_button.callback = self.rename_button_callback
            buttons.append(rename_button)
            if unit.status == UnitStatus.INACTIVE:
                activate_button = ui.Button(label="Activate", style=ButtonStyle.success)
                activate_button.callback = self.activate_button_callback
                buttons.append(activate_button)
            if unit.active:
                deactivate_button = ui.Button(label="Deactivate", style=ButtonStyle.secondary)
                deactivate_button.callback = self.deactivate_button_callback
                buttons.append(deactivate_button)
            if unit.status == UnitStatus.PROPOSED:
                remove_button = ui.Button(label="Remove", style=ButtonStyle.danger)
                remove_button.callback = self.remove_button_callback
                buttons.append(remove_button)
            self.add_item(ui.ActionRow(*buttons))
        self.add_back_button()

    @error_reporting(True)
    async def rename_button_callback(self, interaction: Interaction):
        await interaction.response.send_modal(UnitRenameModal(self.discord_id, self.unit_id, self.unit_name))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def activate_button_callback(self, interaction: Interaction, session: Session):
        unit = session.query(Unit_model).filter(Unit_model.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message(tmpl.unit_not_found, ephemeral=True)
            return
        if unit.status != UnitStatus.INACTIVE:
            await interaction.response.send_message(tmpl.unit_not_inactive, ephemeral=True)
            return
        await interaction.response.send_modal(UnitActivateModal(self.discord_id, self.unit_id))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def deactivate_button_callback(self, interaction: Interaction, session: Session):
        unit = session.query(Unit_model).filter(Unit_model.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message(tmpl.unit_not_found, ephemeral=True)
            return
        if not unit.active:
            await interaction.response.send_message(tmpl.unit_not_active, ephemeral=True)
            return
        player = unit.player
        original_callsign = deactivate_unit(unit, session)
        CustomClient().queue.put_nowait((1, player, 0))
        await interaction.response.edit_message(view=UnitInfoLayoutView(self.discord_id, self.unit_id))
        await interaction.followup.send(tmpl.unit_deactivated.format(original_callsign=original_callsign), ephemeral=True)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def remove_button_callback(self, interaction: Interaction, session: Session):
        unit = session.query(Unit_model).filter(Unit_model.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message(tmpl.unit_not_found, ephemeral=True)
            return
        if unit.status != UnitStatus.PROPOSED:
            await interaction.response.send_message("Only proposed units can be removed", ephemeral=True)
            return
        player = unit.player
        confirmation = tmpl.unit_removed.format(unit=unit)
        logger.debug(f"Removing unit {unit.id} ({unit.name})")
        session.delete(unit)
        session.commit()
        CustomClient().queue.put_nowait((1, player, 0))
        await interaction.response.edit_message(view=UnitMenuLayoutView(self.discord_id))
        await interaction.followup.send(confirmation, ephemeral=True)

class UnitCreateLayoutView(UnitOwnerLayoutView):
    """Type selection for a new unit, whose name has already been validated."""

    @uses_db(CustomClient().sessionmaker)
    def __init__(self, discord_id: int, unit_name: str, session: Session):
        super().__init__(discord_id)
        self.unit_name = unit_name
        self.add_item(ui.Container(
            ui.TextDisplay(content=f"## {tmpl.unit_create_button_label}: {unit_name}")
        ))
        unit_types = session.query(UnitType.unit_type).filter(UnitType.is_base == True).all()
        options = [SelectOption(label=unit_type, value=unit_type) for (unit_type,) in unit_types]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            self.add_item(ui.TextDisplay(content="There are no unit types available, please contact a moderator"))
        else:
            for chunk in chunks:
                select = ui.Select(placeholder=tmpl.unit_select_type_placeholder, options=chunk)
                select.callback = self.type_select_callback
                self.add_item(ui.ActionRow(select))
        self.add_back_button()

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def type_select_callback(self, interaction: Interaction, session: Session):
        unit_type = interaction.data["values"][0]
        player_id = session.query(Player.id).filter(Player.discord_id == self.discord_id).scalar()
        if not player_id:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=True)
            return
        error = unit_creation_error(self.unit_name, player_id, session)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        unit_type_req: int | None = session.query(UnitType.unit_req).filter(UnitType.unit_type == unit_type).scalar()
        if unit_type_req is None: # can't use not because 0 is falsy
            await interaction.response.send_message(tmpl.unit_invalid_type, ephemeral=True)
            return
        unit = Unit_model(player_id=player_id, name=self.unit_name, unit_type=unit_type, active=False, unit_req=unit_type_req)
        session.add(unit)
        session.commit()
        logger.debug(f"Created unit {unit.id} ({unit.name}) of type {unit_type} for player {player_id}")

        # Guard check: verify no unexpected PlayerUpgrade records were created
        if unit.upgrades:
            logger.error(f"Unexpected PlayerUpgrade records created for unit {unit.name}: {[upgrade.name for upgrade in unit.upgrades]}")
            raise RuntimeError(f"Unexpected PlayerUpgrade records created during unit creation: {[upgrade.name for upgrade in unit.upgrades]}")

        confirmation = tmpl.unit_created.format(unit=unit)
        CustomClient().queue.put_nowait((1, unit.player, 0))
        await interaction.response.edit_message(view=UnitInfoLayoutView(self.discord_id, unit.id))
        await interaction.followup.send(confirmation, ephemeral=True)

class UnitActivateCampaignLayoutView(UnitOwnerLayoutView):
    """Campaign selection for a unit that is being activated."""

    @uses_db(CustomClient().sessionmaker)
    def __init__(self, discord_id: int, unit_id: int, callsign: str, group: str | None, role_ids: frozenset[int], session: Session):
        super().__init__(discord_id)
        self.unit_id = unit_id
        self.callsign = callsign
        self.group = group
        self.role_ids = role_ids
        unit = session.query(Unit_model).filter(Unit_model.id == unit_id).first()
        if unit is None:
            self.add_item(ui.TextDisplay(content=tmpl.unit_not_found))
            self.add_back_button()
            return
        self.add_item(ui.Container(
            ui.TextDisplay(content=f"## {unit.name}"),
            ui.TextDisplay(content=f"**Callsign:** {callsign}" + (f"\n**Battle Group:** {group}" if group else "")),
            ui.TextDisplay(content=tmpl.unit_select_campaign)
        ))
        campaigns = session.query(Campaign).all()
        options = []
        for campaign in campaigns:
            _, emoji = campaign_eligibility(campaign, unit.player, role_ids, session)
            options.append(SelectOption(label=campaign.name, value=str(campaign.id), emoji=emoji))
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            self.add_item(ui.TextDisplay(content=tmpl.campaign_not_found))
        else:
            for chunk in chunks:
                select = ui.Select(placeholder=tmpl.unit_select_campaign_placeholder, options=chunk)
                select.callback = self.campaign_select_callback
                self.add_item(ui.ActionRow(select))
        self.add_back_button()

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def campaign_select_callback(self, interaction: Interaction, session: Session):
        campaign = session.query(Campaign).filter(Campaign.id == int(interaction.data["values"][0])).first()
        if campaign is None:
            await interaction.response.send_message(tmpl.unit_campaign_invalid, ephemeral=True)
            return
        unit = session.query(Unit_model).filter(Unit_model.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message(tmpl.unit_not_found, ephemeral=True)
            return
        player = unit.player
        eligible, _ = campaign_eligibility(campaign, player, self.role_ids, session)
        if not eligible:
            logger.warning(f"Player {player.name} is not eligible to join campaign {campaign.name}")
            await interaction.response.send_message(tmpl.unit_not_eligible, ephemeral=True)
            return
        max_active_units = EnvironHelpers.required_int("MAX_ACTIVE_UNITS")
        if len(player.active_units) >= max_active_units:
            await interaction.response.send_message(
                tmpl.unit_already_active_count.format(active_count=len(player.active_units), max_active=max_active_units),
                ephemeral=True
            )
            return
        if unit.unit_type == "STOCKPILE" or unit.status != UnitStatus.INACTIVE:
            await interaction.response.send_message(tmpl.unit_not_inactive, ephemeral=True)
            return
        if session.query(exists().where(Unit_model.callsign == self.callsign)).scalar():
            logger.warning(f"Callsign {self.callsign} is already in use (race condition second check)")
            await interaction.response.send_message(tmpl.callsign_taken, ephemeral=True)
            return

        unit.status = UnitStatus.ACTIVE
        unit.active = True
        unit.campaign_id = campaign.id
        unit.callsign = self.callsign
        unit.battle_group = self.group
        session.commit()
        logger.info(f"Unit {unit.name} activated in campaign {campaign.name} as {self.callsign}")
        confirmation = tmpl.unit_selected_for_campaign.format(unit=unit, campaign_name=campaign.name)
        CustomClient().queue.put_nowait((1, player, 0))
        await interaction.response.edit_message(view=UnitInfoLayoutView(self.discord_id, unit.id))
        await interaction.followup.send(confirmation, ephemeral=True)

class UnitCreateNameModal(RecordingModal):
    def __init__(self, discord_id: int):
        super().__init__(title=tmpl.unit_create_button_label)
        self.discord_id = discord_id
        self.add_item(ui.TextInput(label="Name", placeholder="Enter the unit name", max_length=30, required=True))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        unit_name = self.children[0].value.strip()
        player_id = session.query(Player.id).filter(Player.discord_id == self.discord_id).scalar()
        if not player_id:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=True)
            return
        error = unit_creation_error(unit_name, player_id, session)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.edit_message(view=UnitCreateLayoutView(self.discord_id, unit_name))

class UnitRenameModal(RecordingModal):
    def __init__(self, discord_id: int, unit_id: int, current_name: str):
        super().__init__(title=tmpl.unit_rename_modal_title)
        self.discord_id = discord_id
        self.unit_id = unit_id
        self.add_item(ui.TextInput(label=tmpl.unit_rename_new_name_label, default=current_name, max_length=30, required=True))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        new_name = self.children[0].value.strip()
        unit = session.query(Unit_model).filter(Unit_model.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message(tmpl.unit_not_found, ephemeral=True)
            return
        if unit.unit_type == "STOCKPILE":
            await interaction.response.send_message(tmpl.stockpile_cannot_rename, ephemeral=True)
            return
        error = unit_name_error(new_name)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        if new_name != unit.name and session.query(exists().where(Unit_model.name == new_name, Unit_model.player_id == unit.player_id)).scalar():
            await interaction.response.send_message(tmpl.unit_name_exists, ephemeral=True)
            return
        unit.name = new_name
        session.commit()
        logger.info(f"Unit {unit.id} renamed to {new_name}")
        CustomClient().queue.put_nowait((1, unit.player, 0))
        await interaction.response.edit_message(view=UnitInfoLayoutView(self.discord_id, self.unit_id))
        await interaction.followup.send(tmpl.unit_renamed.format(new_name=new_name), ephemeral=True)

class UnitActivateModal(RecordingModal):
    def __init__(self, discord_id: int, unit_id: int):
        super().__init__(title="Activate Unit")
        self.discord_id = discord_id
        self.unit_id = unit_id
        self.add_item(ui.TextInput(label="Callsign", placeholder="Must be globally unique", max_length=7, required=True))
        if ALLOW_BATTLE_GROUPS:
            self.add_item(ui.TextInput(label="Battle Group", placeholder="Enter the group to activate the unit in", max_length=30, required=False))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        callsign = self.children[0].value.strip()
        group = (self.children[1].value.strip() or None) if ALLOW_BATTLE_GROUPS else None
        error = callsign_error(callsign)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        if session.query(exists().where(Unit_model.callsign == callsign)).scalar():
            await interaction.response.send_message(tmpl.callsign_taken, ephemeral=True)
            return
        await interaction.response.edit_message(
            view=UnitActivateCampaignLayoutView(self.discord_id, self.unit_id, callsign, group, member_role_ids(interaction))
        )

async def setup(_bot: CustomClient):
    logger.info("Setting up Unit cog")
    await _bot.add_cog(Unit(_bot))


async def teardown(_bot: CustomClient):
    logger.info("Tearing down Unit cog")
    _bot.remove_cog(Unit.__name__)  # remove_cog takes a string, not a class
