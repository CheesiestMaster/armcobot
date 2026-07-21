from logging import getLogger

from discord import ButtonStyle, Interaction, app_commands as ac, ui
import discord
from discord.ext.commands import GroupCog
from sqlalchemy.orm import Session

from customclient import CustomClient
from models import Player, PlayerUpgrade, ShopUpgrade, Unit, UnitStatus
from utils import RecordingLayoutView, error_reporting, uses_db
import templates as tmpl

logger = getLogger(__name__)

class Shop(GroupCog, description="View and purchase upgrades for units."):
    """
    Cog for the shop slash command: view and purchase upgrades for units.
    Uses paginated views and MessageManager for the shop interface.
    """

    def __init__(self, bot: CustomClient):
        """Store a reference to the bot instance."""

        self.bot = bot

    @ac.command(name="open", description="View the shop")
    async def open(self, interaction: Interaction):
        layout_view = ShopUnitSelectLayoutView(interaction.user.id)
        await interaction.response.send_message(view=layout_view, ephemeral=True)

class AuthorizedUserLayoutView(RecordingLayoutView):
    discord_id: int

    @error_reporting(True)
    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != int(self.discord_id):
            logger.warning(f"User {interaction.user.id} tried to interact with view owned by {self.discord_id}")
            await interaction.response.send_message("You are not the owner of this view", ephemeral=True)
            return False
        return True

class ShopUnitSelectLayoutView(AuthorizedUserLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, discord_id: int, session: Session):
        super().__init__(timeout=None)
        self.discord_id = discord_id
        user = session.query(Player).filter(Player.discord_id == discord_id).first()
        if user is None:
            self.add_item(ui.TextDisplay(content=tmpl.player_not_found))
            return
        options = [discord.SelectOption(label=unit.name, value=str(unit.id)) for unit in user.units]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if not chunks:
            self.add_item(ui.TextDisplay(content=tmpl.no_units))
            return
        if len(chunks) > 19:
            self.add_item(ui.TextDisplay(content=tmpl.too_many_units))
            return
        for chunk in chunks:
            select = ui.Select(placeholder=tmpl.shop_select_unit_placeholder, options=chunk)
            select.callback = self.unit_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)
        info_button = ui.Button(label=f"You have {user.rec_points}{tmpl.MAIN_CURRENCY_SHORT} and {user.bonus_pay}{tmpl.SECONDARY_CURRENCY_SHORT}", style=ButtonStyle.grey, disabled=True)
        convert_button = ui.Button(label=tmpl.shop_convert_bp_button, style=ButtonStyle.success, disabled=user.bonus_pay < 10)
        convert_button.callback = self.convert_button_callback
        action_row = ui.ActionRow(info_button, convert_button)
        self.add_item(action_row)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def convert_button_callback(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.discord_id == self.discord_id).first()
        if player is None:
            await interaction.response.send_message(tmpl.player_not_found, ephemeral=True)
            return
        if player.bonus_pay < 10:
            await interaction.response.send_message(tmpl.not_enough_bonus_pay, ephemeral=True)
            return
        player.bonus_pay -= 10
        player.rec_points += 1
        session.commit()
        await interaction.response.send_message("You have converted your bonus pay to requisition points", ephemeral=True)
        layout_view = self.__class__(player.discord_id)
        await interaction.message.edit(view=layout_view)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def unit_select_callback(self, interaction: Interaction, session: Session):
        unit = session.query(Unit).filter(Unit.id == int(interaction.data['values'][0])).first()
        if unit is None:
            await interaction.response.send_message(tmpl.unit_not_found, ephemeral=True)
            return
        if unit.status == UnitStatus.INACTIVE:
            layout_view = ShopInactiveUnitLayoutView(interaction.user.id, unit.id)
        elif unit.status == UnitStatus.PROPOSED:
            layout_view = ShopProposedUnitLayoutView(interaction.user.id, unit.id)
        elif unit.status in {UnitStatus.MIA, UnitStatus.KIA}:
            layout_view = ShopDeadUnitLayoutView(interaction.user.id, unit.id)
        else:
            await interaction.response.send_message(tmpl.unit_not_inactive, ephemeral=True)
            return
        await interaction.response.send_message(view=layout_view, ephemeral=True)

class ShopInactiveUnitLayoutView(AuthorizedUserLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, discord_id: int, unit_id: int, session: Session):
        super().__init__(timeout=None)
        self.discord_id = discord_id
        self.unit_id = unit_id
        unit = session.query(Unit).filter(Unit.id == unit_id).first()
        if unit is None:
            self.add_item(ui.TextDisplay(content=tmpl.unit_not_found))
            return
        container = ui.Container(
            ui.TextDisplay(content=tmpl.shop_unit_title.format(unit_name=unit.name)),
            ui.TextDisplay(content=f"Player {tmpl.MAIN_CURRENCY_SHORT}: {unit.player.rec_points}"),
            ui.TextDisplay(content=f"{tmpl.UNIT_CURRENCY}: {unit.unit_req}" + (" Which must be spent first" if bool(unit.unit_req) else "")))
        self.add_item(container)
        upgrades, currency = self.populate_select_options(unit.available_upgrades, unit)
        if not upgrades:
            self.add_item(ui.TextDisplay(content=tmpl.no_upgrades_available))
            return
        options = [discord.SelectOption(label=upgrade["label"], value=upgrade["value"]) for upgrade in upgrades]
        chunks = [options[i:i+25] for i in range(0, len(options), 25)]
        if len(chunks) >=19:
            self.add_item(ui.TextDisplay(content=tmpl.too_many_upgrades))
            return
        for chunk in chunks:
            select = ui.Select(placeholder=tmpl.shop_select_upgrade_placeholder, options=chunk)
            select.callback = self.upgrade_select_callback
            action_row = ui.ActionRow(select)
            self.add_item(action_row)

    def populate_select_options(self, upgrades: list[ShopUpgrade], unit: Unit):
        """
        Fill the select menu options with available upgrades, respecting
        currency availability, upgrade disabled state, type filtering, and per-unit limits.
        Returns: currency (int)
        """
        current_unit_req = unit.unit_req
        current_rec_points = unit.player.rec_points
        select = []
        currency = current_unit_req if current_unit_req > 0 else current_rec_points

        for upgrade in upgrades:
            if upgrade.disabled:
                continue
            if not upgrade.upgrade_type:
                continue
            if not upgrade.upgrade_type.can_use_unit_req and current_unit_req > 0:
                continue
            if upgrade.repeatable != 0: # 0 = unlimited, else max count
                owned_count = sum(1 for _upgrade in unit.upgrades if _upgrade.shop_upgrade_id == upgrade.id)
                if owned_count >= upgrade.repeatable:
                    continue

            insufficient = "(❌)" if upgrade.cost > currency else ""
            utype = upgrade.upgrade_type.emoji if hasattr(upgrade.upgrade_type, "emoji") else ""
            label = f"{utype} {insufficient}{upgrade.name} ({upgrade.cost})"
            select.append({"label": label, "value": str(upgrade.id)})
        return select, currency
        
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def upgrade_select_callback(self, interaction: Interaction, session: Session):
        upgrade_id = int(interaction.data['values'][0])
        unit = session.query(Unit).filter(Unit.id == self.unit_id).first()
        currency = unit.unit_req if unit.unit_req > 0 else unit.player.rec_points
        if unit is None:
            await interaction.response.send_message(tmpl.unit_not_found, ephemeral=True)
            return
        upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == upgrade_id).first()
        if upgrade is None:
            await interaction.response.send_message(tmpl.upgrade_not_found, ephemeral=True)
            return
        if upgrade.upgrade_type.non_purchaseable:
            await interaction.response.send_message(tmpl.upgrade_non_purchaseable, ephemeral=True)
            return
        if upgrade.disabled:
            await interaction.response.send_message(tmpl.upgrade_disabled, ephemeral=True)
            return
        if upgrade.cost > currency:
            await interaction.response.send_message(tmpl.not_enough_req_points_upgrade, ephemeral=True)
            return
        if upgrade.repeatable != 0:
            owned_count = sum(1 for _upgrade in unit.upgrades if _upgrade.shop_upgrade_id == upgrade.id)
            if owned_count >= upgrade.repeatable:
                await interaction.response.send_message(tmpl.already_have_upgrade, ephemeral=True)
                return
        if upgrade.required_upgrade_id:
            required_upgrade = session.query(PlayerUpgrade).filter(PlayerUpgrade.unit_id == unit.id, PlayerUpgrade.shop_upgrade_id == upgrade.required_upgrade_id).first()
            if required_upgrade is None:
                await interaction.response.send_message(tmpl.dont_have_required_upgrade, ephemeral=True)
                return
        if not upgrade.upgrade_type.is_refit:
            new_upgrade = PlayerUpgrade(
                unit_id=unit.id,
                shop_upgrade_id=upgrade.id,
                type=upgrade.type,
                name=upgrade.name,
                original_price=upgrade.cost if unit.unit_req > 0 else 0,
                non_transferable=unit.unit_req > 0
            )
            session.add(new_upgrade)
            if unit.unit_req > 0:
                unit.unit_req -= upgrade.cost
            else:
                unit.player.rec_points -= upgrade.cost
            session.commit()
            CustomClient().queue.put_nowait((1, unit.player, 0))
            await interaction.response.send_message(tmpl.you_have_bought_upgrade.format(upgrade_name=upgrade.name, upgrade_cost=upgrade.cost), ephemeral=True)
        else:
            refit_target = upgrade.refit_target
            refit_cost = upgrade.cost
            current_upgrades = unit.upgrades
            current_upgrade_set = {upgrade.shop_upgrade for upgrade in current_upgrades}
            compatible_upgrades = set(upgrade.target_type_info.compatible_upgrades) | {None,}
            incompatible_upgrades = current_upgrade_set - compatible_upgrades
            stockpile = unit.player.stockpile
            if not stockpile:
                await interaction.response.send_message(tmpl.dont_have_stockpile, ephemeral=True)
                return
            for _upgrade in current_upgrades:
                if _upgrade.shop_upgrade in incompatible_upgrades:
                    _upgrade.unit_id = stockpile.id
            if unit.original_type is None:
                unit.original_type = unit.unit_type
            unit.unit_type = refit_target
            unit.unit_req = upgrade.target_type_info.unit_req
            unit.player.rec_points -= refit_cost

            if upgrade.target_type_info.free_upgrade_1:
                free_upgrade_1 = PlayerUpgrade(
                    unit_id=unit.id,
                    shop_upgrade_id=upgrade.target_type_info.free_upgrade_1,
                    type=upgrade.target_type_info.free_upgrade_1_info.type,
                    name=upgrade.target_type_info.free_upgrade_1_info.name,
                    original_price=0,
                    non_transferable=True
                )
                session.add(free_upgrade_1)
            if upgrade.target_type_info.free_upgrade_2:
                free_upgrade_2 = PlayerUpgrade(
                    unit_id=unit.id,
                    shop_upgrade_id=upgrade.target_type_info.free_upgrade_2,
                    type=upgrade.target_type_info.free_upgrade_2_info.type,
                    name=upgrade.target_type_info.free_upgrade_2_info.name,
                    original_price=0,
                    non_transferable=True
                )
                session.add(free_upgrade_2)
            session.commit()
            CustomClient().queue.put_nowait((1, unit.player, 0))
            await interaction.response.send_message(tmpl.you_have_bought_refit.format(refit_target=refit_target, refit_cost=refit_cost), ephemeral=True)
            layout_view = ShopInactiveUnitLayoutView(unit.player.discord_id, unit.id)
            await interaction.message.edit(view=layout_view)

        layout_view = ShopInactiveUnitLayoutView(unit.player.discord_id, unit.id)
        await interaction.message.edit(view=layout_view)

class ShopProposedUnitLayoutView(AuthorizedUserLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, discord_id: int, unit_id: int, session: Session):
        super().__init__(timeout=None)
        self.discord_id = discord_id
        self.unit_id = unit_id
        unit = session.query(Unit).filter(Unit.id == unit_id).first()
        if unit is None:
            self.add_item(ui.TextDisplay(content=tmpl.unit_not_found))
            return
        container = ui.Container(
            ui.TextDisplay(content=tmpl.shop_unit_title.format(unit_name=unit.name)),
            ui.TextDisplay(content=f"Player {tmpl.MAIN_CURRENCY_SHORT}: {unit.player.rec_points}"),
            ui.TextDisplay(content=f"{tmpl.UNIT_CURRENCY}: {unit.unit_req}"))
        self.add_item(container)
        buy_button = ui.Button(label=tmpl.shop_buy_unit_button, style=ButtonStyle.success, disabled=unit.player.rec_points < 1)
        buy_button.callback = self.buy_button_callback
        self.add_item(ui.ActionRow(buy_button))
        
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def buy_button_callback(self, interaction: Interaction, session: Session):
        unit = session.query(Unit).filter(Unit.id == self.unit_id).first()
        if unit is None:
            await interaction.response.send_message(tmpl.unit_not_found, ephemeral=True)
            return
        if unit.player.rec_points < 1:
            await interaction.response.send_message(tmpl.not_enough_req_points_unit, ephemeral=True)
            return
        unit.status = UnitStatus.INACTIVE
        unit.player.rec_points -= 1
        session.commit()
        await interaction.response.send_message(tmpl.you_have_bought_unit.format(unit_name=unit.name), ephemeral=True)
        layout_view = ShopInactiveUnitLayoutView(unit.player.discord_id, unit.id)
        await interaction.message.edit(view=layout_view)


class ShopDeadUnitLayoutView(AuthorizedUserLayoutView):
    @uses_db(CustomClient().sessionmaker)
    def __init__(self, discord_id: int, unit_id: int, session: Session):
        super().__init__(timeout=None)
        self.discord_id = discord_id
        self.unit_id = unit_id
        unit = session.query(Unit).filter(Unit.id == unit_id).first()
        if unit is None:
            self.add_item(ui.TextDisplay(content=tmpl.unit_not_found))
            return
        container = ui.Container(
            ui.TextDisplay(content=tmpl.shop_unit_title.format(unit_name=unit.name)),
            ui.TextDisplay(content=f"Player {tmpl.MAIN_CURRENCY_SHORT}: {unit.player.rec_points}"),
            ui.TextDisplay(content=f"{tmpl.UNIT_CURRENCY}: {unit.unit_req}"),
            ui.TextDisplay(content=tmpl.unit_is_dead))
        self.add_item(container)
        
async def setup(_bot: CustomClient):
    await _bot.add_cog(Shop(_bot))


async def teardown(_bot: CustomClient):
    _bot.remove_cog(Shop.__name__)  # remove_cog takes a string, not a class