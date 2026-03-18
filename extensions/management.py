from logging import getLogger
from typing import Callable

from discord import ButtonStyle, Embed, Interaction, Member, SelectOption, TextStyle, app_commands as ac, ui
from discord.ext.commands import GroupCog
from sqlalchemy import or_
from sqlalchemy.orm import Session
import templates as tmpl

from customclient import CustomClient
from MessageManager import MessageManager
from models import Campaign, Player, Unit, UnitStatus, PlayerUpgrade, UnitType, UpgradeType, ShopUpgrade, ShopUpgradeUnitTypes
from utils import error_reporting, is_management, uses_db, inject, Paginator, fuzzy_autocomplete, RecordingView

logger = getLogger(__name__)

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

    @ac.command(name="company", description="Manage a company")
    @ac.describe(player="The player to manage the company of")
    @error_reporting(False)
    @uses_db(CustomClient().sessionmaker)
    async def company(self, interaction: Interaction, player: Member, session: Session):
        company = session.query(Player).filter(Player.discord_id == player.id).first()
        if not company:
            await interaction.response.send_message(f"Player {player.name} does not have a company", ephemeral=True)
            return
        message_manager = MessageManager(interaction)
        embed = self.EditCompanyEmbed(company, player)
        view = RecordingView()
        btn = ui.Button(label="Edit Company", style=ButtonStyle.primary, custom_id="edit_company")
        view.add_item(btn)
        @error_reporting(False)
        @uses_db(CustomClient().sessionmaker)
        async def btn_callback(_interaction: Interaction, session: Session):
            if _interaction.user.id != interaction.user.id:
                await _interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                return
            _company = session.merge(company)
            modal = self.EditCompanyModal(_company, message_manager)
            await _interaction.response.send_modal(modal)
        btn.callback = btn_callback
        await message_manager.send_message(embed=embed, view=view, ephemeral=CustomClient().use_ephemeral)

    class EditCompanyEmbed(Embed):
        def __init__(self, company: Player, member: Member):
            super().__init__(title=company.name, description=company.lore[:250] + ("..." if len(company.lore) > 250 else ""), color=0x00ff00)
            self.set_thumbnail(url=member.display_avatar.url) \
                .add_field(name="Player", value=member.mention, inline=True) \
                .add_field(name=tmpl.MAIN_CURRENCY, value=company.rec_points, inline=True) \
                .add_field(name=tmpl.SECONDARY_CURRENCY, value=company.bonus_pay, inline=True) \
                .set_footer(text=f"Player ID: {company.id}", icon_url=member.display_avatar.url)

        def update(self, company: Player):
            self.title = company.name
            self.description = company.lore[:250] + ("..." if len(company.lore) > 250 else "")
            self.set_field_at(index=0, name=tmpl.MAIN_CURRENCY, value=company.rec_points, inline=True)
            self.set_field_at(index=1, name=tmpl.SECONDARY_CURRENCY, value=company.bonus_pay, inline=True)

    class EditCompanyModal(ui.Modal):
        def __init__(self, company: Player, message_manager: MessageManager):
            super().__init__(title="Edit Company")
            self.company = company
            self.message_manager = message_manager
            self.add_item(ui.TextInput(label="Name", placeholder="Enter the company name", required=False, max_length=255, default=company.name))
            self.add_item(ui.TextInput(label="Lore", placeholder="Enter the company lore", required=False, max_length=1000, style=TextStyle.paragraph, default=company.lore or ""))
            self.add_item(ui.TextInput(label=tmpl.MAIN_CURRENCY, placeholder=f"Enter the company {tmpl.MAIN_CURRENCY.lower()}", required=False, max_length=20, default=str(company.rec_points)))
            self.add_item(ui.TextInput(label=tmpl.SECONDARY_CURRENCY, placeholder=f"Enter the company {tmpl.SECONDARY_CURRENCY.lower()}", required=False, max_length=20, default=str(company.bonus_pay)))

        @error_reporting(False)
        @uses_db(CustomClient().sessionmaker)
        async def on_submit(self, interaction: Interaction, session: Session):
            _company = session.merge(self.company)
            _company.name = self.children[0].value or _company.name
            _company.lore = self.children[1].value or _company.lore
            try:
                _company.rec_points = int(self.children[2].value) or _company.rec_points
                _company.bonus_pay = int(self.children[3].value) or _company.bonus_pay
            except ValueError:
                await interaction.response.send_message("Invalid input: currency values must be numerical", ephemeral=True)
                return
            await interaction.response.send_message("Company updated", ephemeral=True)
            self.message_manager.embed.update(_company)
            await self.message_manager.update_message()
            CustomClient().queue.put_nowait((1, _company, 0))

    def _shop_original_author(self, original: Interaction) -> Callable[[Interaction], bool]:
        author = original.user
        def predicate(interaction: Interaction) -> bool:
            return interaction.user == author
        return predicate

    @ac.command(name="shop", description="Manage the shop")
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def shop(self, interaction: Interaction, session: Session):
        logger.info(f"Manage shop command invoked by {interaction.user.id} ({interaction.user.name})")
        message_manager = MessageManager(interaction)
        view = RecordingView()
        predicate = self._shop_original_author(interaction)
        injector = inject(message_manager=message_manager)
        unittype_button = ui.Button(label=tmpl.shop_unit_type_button, style=ButtonStyle.primary)
        view.add_item(unittype_button)
        unittype_button.callback = ac.check(predicate)(injector(self._shop_unittype_callback))
        upgradetype_button = ui.Button(label=tmpl.shop_upgrade_type_button, style=ButtonStyle.primary)
        view.add_item(upgradetype_button)
        upgradetype_button.callback = ac.check(predicate)(injector(self._shop_upgradetype_callback))
        upgrade_button = ui.Button(label=tmpl.shop_upgrade_button, style=ButtonStyle.primary)
        view.add_item(upgrade_button)
        upgrade_button.callback = ac.check(predicate)(injector(self._shop_upgrade_callback))
        await message_manager.send_message(content=tmpl.shop_manage_select_content, view=view, ephemeral=CustomClient().use_ephemeral)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def _shop_unittype_callback(self, interaction: Interaction, message_manager: MessageManager, session: Session):
        logger.info(f"Unit type management accessed by {interaction.user.id} ({interaction.user.name})")
        unit_types = session.query(UnitType.unit_type).all()
        unit_types.append(("\0Add New Unit Type",))
        paginator: Paginator[tuple] = Paginator(unit_types, 25)
        #await interaction.response.defer(thinking=False, ephemeral=True)
        view = RecordingView()
        select = ui.Select(placeholder=tmpl.shop_unit_type_select_placeholder)
        previous_button = ui.Button(label=tmpl.shop_previous_button, style=ButtonStyle.secondary, disabled=True)
        next_button = ui.Button(label=tmpl.shop_next_button, style=ButtonStyle.secondary, disabled=not paginator.has_next())
        predicate = self._shop_original_author(interaction)
        check = ac.check(predicate)
        view.add_item(previous_button)
        view.add_item(select)
        view.add_item(next_button)
        for unit_type in paginator.current():
            select.add_option(label=unit_type[0], value=unit_type[0])
        @check
        @error_reporting(True)
        async def previous_button_callback(interaction: Interaction):
            nonlocal paginator
            paginator.previous()
            select.options.clear()
            for unit_type in paginator.current():
                select.add_option(label=unit_type[0], value=unit_type[0])
            next_button.disabled = paginator.has_next()
            previous_button.disabled = not paginator.has_previous()
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        previous_button.callback = previous_button_callback
        @check
        @error_reporting(True)
        async def next_button_callback(interaction: Interaction):
            nonlocal paginator
            paginator.next()
            select.options.clear()
            for unit_type in paginator.current():
                select.add_option(label=unit_type[0], value=unit_type[0])
            next_button.disabled = not paginator.has_next()
            previous_button.disabled = not paginator.has_previous()
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        next_button.callback = next_button_callback
        @check
        @error_reporting(True)
        @uses_db(CustomClient().sessionmaker)
        async def select_callback(interaction: Interaction, session: Session):
            target = interaction.data["values"][0]
            if target == "\0Add New Unit Type":
                modal = ui.Modal(title=tmpl.shop_add_new_unit_type_modal_title)
                modal.add_item(ui.TextInput(label=tmpl.shop_unit_type_name_label, placeholder=tmpl.shop_unit_type_name_placeholder, style=TextStyle.short, required=True, max_length=15))
                await interaction.response.send_modal(modal)
                new_unit_type_data = {"unit_type": None, "is_base": False, "unit_req": 0}
                @check
                @error_reporting(True)
                async def modal_submit(interaction: Interaction):
                    new_unit_type_data["unit_type"] = interaction.data["components"][0]["components"][0]["value"]
                    view = RecordingView()
                    is_base_unit = ui.Select(placeholder=tmpl.shop_is_base_placeholder, options=[SelectOption(label="Yes", value="y"), SelectOption(label="No", value="n")])
                    unit_req_amount = ui.Select(placeholder=tmpl.shop_unit_req_amount_placeholder, options=[SelectOption(label=str(i), value=str(i)) for i in range(0, 4)])
                    done_button = ui.Button(label=tmpl.shop_done_button, style=ButtonStyle.primary)
                    view.add_item(is_base_unit)
                    view.add_item(unit_req_amount)
                    view.add_item(done_button)
                    await message_manager.update_message(content=tmpl.shop_please_setup_unit_type, view=view)
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    @check
                    @error_reporting(True)
                    async def base_unit_callback(interaction: Interaction):
                        new_unit_type_data["is_base"] = interaction.data["values"][0] == "y"
                        await interaction.response.defer(thinking=False, ephemeral=True)
                    is_base_unit.callback = base_unit_callback
                    @check
                    @error_reporting(True)
                    async def unit_req_amount_callback(interaction: Interaction):
                        new_unit_type_data["unit_req"] = int(interaction.data["values"][0])
                        await interaction.response.defer(thinking=False, ephemeral=True)
                    unit_req_amount.callback = unit_req_amount_callback
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def done_button_callback(interaction: Interaction, session: Session):
                        new_unit_type = UnitType(unit_type=new_unit_type_data["unit_type"], is_base=new_unit_type_data["is_base"], unit_req=new_unit_type_data["unit_req"])
                        session.add(new_unit_type)
                        await interaction.response.defer(thinking=False, ephemeral=True)
                        await message_manager.update_message(content=tmpl.shop_unit_type_added, view=RecordingView())
                    done_button.callback = done_button_callback
                modal.on_submit = modal_submit
            else:
                unit_type_ = session.query(UnitType).filter(UnitType.unit_type == target).first()
                def ui_factory(unit_type: UnitType) -> tuple[RecordingView, Embed]:
                    nonlocal target
                    view = RecordingView()
                    embed = Embed(title=tmpl.shop_unit_type_title.format(unit_type=unit_type.unit_type))
                    embed.add_field(name="Is Base", value="Yes" if unit_type.is_base else "No")
                    embed.add_field(name="Unit Req", value=str(unit_type.unit_req))
                    rename_button = ui.Button(label=tmpl.shop_rename_button, style=ButtonStyle.primary)
                    delete_button = ui.Button(label=tmpl.shop_delete_button, style=ButtonStyle.danger)
                    view.add_item(rename_button)
                    view.add_item(delete_button)
                    is_base_unit = ui.Select(placeholder=tmpl.shop_is_base_placeholder, options=[SelectOption(label="Yes", value="y", default=unit_type.is_base), SelectOption(label="No", value="n", default=not unit_type.is_base)])
                    unit_req_amount = ui.Select(placeholder=tmpl.shop_unit_req_amount_placeholder, options=[SelectOption(label=str(i), value=str(i), default=(i == unit_type.unit_req)) for i in range(0, 4)])
                    view.add_item(is_base_unit)
                    view.add_item(unit_req_amount)
                    unit_type_pk = unit_type.unit_type
                    @check
                    @error_reporting(True)
                    async def rename_button_callback(interaction: Interaction):
                        modal = ui.Modal(title=tmpl.shop_rename_unit_type_modal_title)
                        new_name_input = ui.TextInput(label=tmpl.shop_new_name_label, placeholder=tmpl.shop_new_name_placeholder, default=unit_type_pk, min_length=1, max_length=15)
                        modal.add_item(new_name_input)
                        @check
                        @error_reporting(True)
                        @uses_db(CustomClient().sessionmaker)
                        async def modal_submit(interaction: Interaction, session: Session):
                            nonlocal target
                            new_name = interaction.data["components"][0]["components"][0]["value"].strip().upper()
                            unit_type = session.query(UnitType).filter(UnitType.unit_type == unit_type_pk).first()
                            if not new_name:
                                await interaction.response.send_message(tmpl.shop_name_cannot_be_empty, ephemeral=True)
                                return
                            if session.query(UnitType).filter(UnitType.unit_type == new_name).first():
                                await interaction.response.send_message(tmpl.shop_unit_type_already_exists.format(name=new_name), ephemeral=True)
                                return
                            new_unit_type = UnitType(unit_type=new_name, is_base=unit_type.is_base, free_upgrade_1=unit_type.free_upgrade_1, free_upgrade_2=unit_type.free_upgrade_2, unit_req=unit_type.unit_req)
                            session.add(new_unit_type)
                            for unit in unit_type.units:
                                unit.unit_type = new_name
                            for unit in unit_type.original_units:
                                unit.original_type = new_name
                            for upgrade in unit_type.refit_targets:
                                upgrade.refit_target = new_name
                            for upgrade_type in unit_type.upgrade_types:
                                upgrade_type.unit_type = new_name
                            session.commit()
                            session.delete(unit_type)
                            session.commit()
                            target = new_name
                            await interaction.response.send_message(tmpl.shop_unit_type_renamed.format(old=unit_type.unit_type, new=new_name), ephemeral=True)
                            updated_unit_type = session.query(UnitType).filter(UnitType.unit_type == new_name).first()
                            new_view, new_embed = ui_factory(updated_unit_type)
                            await message_manager.update_message(content="Please set up the unit type", view=new_view, embed=new_embed, ephemeral=CustomClient().use_ephemeral)
                        modal.on_submit = modal_submit
                        await interaction.response.send_modal(modal)
                    rename_button.callback = rename_button_callback
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def delete_button_callback(interaction: Interaction, session: Session):
                        unit_type = session.query(UnitType).filter(UnitType.unit_type == unit_type_pk).first()
                        if unit_type.units:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_units, ephemeral=True)
                            return
                        if unit_type.original_units:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_original_units, ephemeral=True)
                            return
                        if unit_type.refit_targets:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_refit_targets, ephemeral=True)
                            return
                        if unit_type.compatible_upgrades:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_compatible_upgrades, ephemeral=True)
                            return
                        session.delete(unit_type)
                        await interaction.response.send_message(tmpl.shop_unit_type_deleted, ephemeral=True)
                        await message_manager.delete_message()
                    delete_button.callback = delete_button_callback
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def base_unit_callback(interaction: Interaction, session: Session):
                        unit_type = session.query(UnitType).filter(UnitType.unit_type == unit_type_pk).first()
                        unit_type.is_base = interaction.data["values"][0] == "y"
                        session.commit()
                        await interaction.response.defer(thinking=False, ephemeral=True)
                        await message_manager.update_message(content=tmpl.shop_unit_type_updated)
                    is_base_unit.callback = base_unit_callback
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def unit_req_callback(interaction: Interaction, session: Session):
                        unit_type = session.query(UnitType).filter(UnitType.unit_type == unit_type_pk).first()
                        unit_type.unit_req = int(interaction.data["values"][0])
                        session.commit()
                        await interaction.response.defer(thinking=False, ephemeral=True)
                        await message_manager.update_message(content=tmpl.shop_unit_type_updated)
                    unit_req_amount.callback = unit_req_callback
                    if unit_type.units:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a unit type that has units assigned to it", inline=False)
                    if unit_type.original_units:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a unit type that has original units assigned to it", inline=False)
                    if unit_type.refit_targets:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a unit type that has refit targets assigned to it", inline=False)
                    if unit_type.compatible_upgrades:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a unit type that has compatible upgrades assigned to it", inline=False)
                    return view, embed
                view, embed = ui_factory(unit_type_)
                await message_manager.update_message(content=tmpl.shop_please_setup_unit_type, view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
        select.callback = select_callback
        await interaction.response.defer(thinking=False, ephemeral=True)
        await message_manager.update_message(content=tmpl.shop_please_select_unit_type, view=view)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def _shop_upgradetype_callback(self, interaction: Interaction, message_manager: MessageManager, session: Session):
        logger.info(f"Upgrade type management accessed by {interaction.user.id} ({interaction.user.name})")
        upgrade_types = session.query(UpgradeType.name).all()
        upgrade_types.append(("\0Add New Upgrade Type",))
        paginator: Paginator[tuple] = Paginator(upgrade_types, 25)
        view = RecordingView()
        select = ui.Select(placeholder=tmpl.shop_upgrade_type_select_placeholder)
        previous_button = ui.Button(label=tmpl.shop_previous_button, style=ButtonStyle.secondary, disabled=True)
        next_button = ui.Button(label=tmpl.shop_next_button, style=ButtonStyle.secondary, disabled=not paginator.has_next())
        predicate = self._shop_original_author(interaction)
        check = ac.check(predicate)
        view.add_item(previous_button)
        view.add_item(select)
        view.add_item(next_button)
        for upgrade_type in paginator.current():
            select.add_option(label=upgrade_type[0], value=upgrade_type[0])
        @check
        @error_reporting(True)
        async def previous_button_callback(interaction: Interaction):
            nonlocal paginator
            paginator.previous()
            select.options.clear()
            for upgrade_type in paginator.current():
                select.add_option(label=upgrade_type[0], value=upgrade_type[0])
            next_button.disabled = not paginator.has_next()
            previous_button.disabled = not paginator.has_previous()
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        previous_button.callback = previous_button_callback
        @check
        @error_reporting(True)
        async def next_button_callback(interaction: Interaction):
            nonlocal paginator
            paginator.next()
            select.options.clear()
            for upgrade_type in paginator.current():
                select.add_option(label=upgrade_type[0], value=upgrade_type[0])
            next_button.disabled = not paginator.has_next()
            previous_button.disabled = not paginator.has_previous()
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        next_button.callback = next_button_callback
        @check
        @error_reporting(True)
        @uses_db(CustomClient().sessionmaker)
        async def select_callback(interaction: Interaction, session: Session):
            target = interaction.data["values"][0]
            if target == "\0Add New Upgrade Type":
                modal = ui.Modal(title=tmpl.shop_add_new_upgrade_type_modal_title)
                name_input = ui.TextInput(label=tmpl.shop_upgrade_type_name_label, placeholder=tmpl.shop_upgrade_type_name_placeholder, min_length=1, max_length=30)
                emoji_input = ui.TextInput(label=tmpl.shop_emoji_label, placeholder=tmpl.shop_emoji_placeholder, max_length=4, required=False)
                is_refit_input = ui.TextInput(label=tmpl.shop_is_refit_label, placeholder=tmpl.shop_yn_placeholder, min_length=1, max_length=1)
                non_purchaseable_input = ui.TextInput(label=tmpl.shop_non_purchaseable_label, placeholder=tmpl.shop_yn_placeholder, min_length=1, max_length=1)
                can_use_unit_req_input = ui.TextInput(label=tmpl.shop_can_use_unit_req_label, placeholder=tmpl.shop_yn_placeholder, min_length=1, max_length=1)
                modal.add_item(name_input)
                modal.add_item(emoji_input)
                modal.add_item(is_refit_input)
                modal.add_item(non_purchaseable_input)
                modal.add_item(can_use_unit_req_input)
                @check
                @error_reporting(True)
                @uses_db(CustomClient().sessionmaker)
                async def modal_submit(interaction: Interaction, session: Session):
                    name = name_input.value.strip().upper()
                    emoji = emoji_input.value.strip()
                    is_refit = is_refit_input.value.strip().lower() == "y"
                    non_purchaseable = non_purchaseable_input.value.strip().lower() == "y"
                    can_use_unit_req = can_use_unit_req_input.value.strip().lower() == "y"
                    new_upgrade_type = UpgradeType(name=name, emoji=emoji, is_refit=is_refit, non_purchaseable=non_purchaseable, can_use_unit_req=can_use_unit_req)
                    session.add(new_upgrade_type)
                    session.commit()
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    await message_manager.update_message(content=tmpl.shop_upgrade_type_added, view=RecordingView())
                modal.on_submit = modal_submit
                await interaction.response.send_modal(modal)
            else:
                upgrade_type_ = session.query(UpgradeType).filter(UpgradeType.name == target).first()
                def ui_factory(upgrade_type: UpgradeType) -> tuple[RecordingView, Embed]:
                    nonlocal target
                    view = RecordingView()
                    embed = Embed(title=tmpl.shop_upgrade_type_title.format(name=upgrade_type.name))
                    embed.add_field(name="Emoji", value=upgrade_type.emoji or "None")
                    embed.add_field(name="Is Refit", value="Yes" if upgrade_type.is_refit else "No")
                    embed.add_field(name="Non Purchaseable", value="Yes" if upgrade_type.non_purchaseable else "No")
                    embed.add_field(name="Can Use Unit Req", value="Yes" if upgrade_type.can_use_unit_req else "No")
                    embed.add_field(name="Sort Order", value=str(upgrade_type.sort_order))
                    rename_button = ui.Button(label=tmpl.shop_rename_button, style=ButtonStyle.primary)
                    edit_button = ui.Button(label="Edit", style=ButtonStyle.secondary)
                    sort_order_button = ui.Button(label="Set Sort Order", style=ButtonStyle.secondary)
                    delete_button = ui.Button(label=tmpl.shop_delete_button, style=ButtonStyle.danger)
                    view.add_item(rename_button)
                    view.add_item(edit_button)
                    view.add_item(sort_order_button)
                    view.add_item(delete_button)
                    upgrade_type_pk = upgrade_type.name
                    @check
                    @error_reporting(True)
                    async def rename_button_callback(interaction: Interaction):
                        modal = ui.Modal(title=tmpl.shop_rename_upgrade_type_modal_title)
                        new_name_input = ui.TextInput(label=tmpl.shop_new_name_label, placeholder=tmpl.shop_new_name_placeholder, default=upgrade_type_pk, min_length=1, max_length=30)
                        modal.add_item(new_name_input)
                        @check
                        @error_reporting(True)
                        @uses_db(CustomClient().sessionmaker)
                        async def modal_submit(interaction: Interaction, session: Session):
                            nonlocal target
                            new_name = new_name_input.value.strip().upper()
                            upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_pk).first()
                            if not new_name:
                                await interaction.response.send_message(tmpl.shop_name_cannot_be_empty, ephemeral=True)
                                return
                            if session.query(UpgradeType).filter(UpgradeType.name == new_name).first():
                                await interaction.response.send_message(tmpl.shop_upgrade_type_already_exists.format(name=new_name), ephemeral=True)
                                return
                            new_upgrade_type = UpgradeType(name=new_name, emoji=upgrade_type.emoji, is_refit=upgrade_type.is_refit, non_purchaseable=upgrade_type.non_purchaseable, can_use_unit_req=upgrade_type.can_use_unit_req, sort_order=upgrade_type.sort_order)
                            session.add(new_upgrade_type)
                            for shop_upgrade in upgrade_type.shop_upgrades:
                                shop_upgrade.type = new_name
                            for player_upgrade in upgrade_type.player_upgrades:
                                player_upgrade.type = new_name
                            session.commit()
                            session.delete(upgrade_type)
                            session.commit()
                            target = new_name
                            await interaction.response.send_message(tmpl.shop_upgrade_type_renamed.format(old=upgrade_type.name, new=new_name), ephemeral=True)
                            updated_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == new_name).first()
                            new_view, new_embed = ui_factory(updated_upgrade_type)
                            await message_manager.update_message(content="Please set up the upgrade type", view=new_view, embed=new_embed)
                        modal.on_submit = modal_submit
                        await interaction.response.send_modal(modal)
                    rename_button.callback = rename_button_callback
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def edit_button_callback(interaction: Interaction, session: Session):
                        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_pk).first()
                        if not upgrade_type:
                            await interaction.response.send_message(tmpl.unexpected_error, ephemeral=True)
                            return
                        edit_view = RecordingView()
                        is_refit_select = ui.Select(placeholder="Is Refit", options=[SelectOption(label="Yes", value="true", default=upgrade_type.is_refit), SelectOption(label="No", value="false", default=not upgrade_type.is_refit)])
                        non_purchaseable_select = ui.Select(placeholder="Non Purchaseable", options=[SelectOption(label="Yes", value="true", default=upgrade_type.non_purchaseable), SelectOption(label="No", value="false", default=not upgrade_type.non_purchaseable)])
                        can_use_unit_req_select = ui.Select(placeholder="Can Use Unit Req", options=[SelectOption(label="Yes", value="true", default=upgrade_type.can_use_unit_req), SelectOption(label="No", value="false", default=not upgrade_type.can_use_unit_req)])
                        @check
                        async def select_cb(interaction: Interaction):
                            await interaction.response.defer(thinking=False, ephemeral=True)
                        is_refit_select.callback = select_cb
                        non_purchaseable_select.callback = select_cb
                        can_use_unit_req_select.callback = select_cb
                        emoji_button = ui.Button(label="Set Emoji", style=ButtonStyle.primary)
                        save_button = ui.Button(label="Save Changes", style=ButtonStyle.success)
                        edit_view.add_item(is_refit_select)
                        edit_view.add_item(non_purchaseable_select)
                        edit_view.add_item(can_use_unit_req_select)
                        edit_view.add_item(emoji_button)
                        edit_view.add_item(save_button)
                        @check
                        @error_reporting(True)
                        @uses_db(CustomClient().sessionmaker)
                        async def save_button_callback(interaction: Interaction, session: Session):
                            current_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_pk).first()
                            current_upgrade_type.is_refit = is_refit_select.values[0] == "true" if is_refit_select.values else current_upgrade_type.is_refit
                            current_upgrade_type.non_purchaseable = non_purchaseable_select.values[0] == "true" if non_purchaseable_select.values else current_upgrade_type.non_purchaseable
                            current_upgrade_type.can_use_unit_req = can_use_unit_req_select.values[0] == "true" if can_use_unit_req_select.values else current_upgrade_type.can_use_unit_req
                            session.commit()
                            await interaction.response.send_message("Upgrade type updated successfully!", ephemeral=True)
                            updated_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_pk).first()
                            new_view, new_embed = ui_factory(updated_upgrade_type)
                            await message_manager.update_message(content="Please set up the upgrade type", view=new_view, embed=new_embed)
                        save_button.callback = save_button_callback
                        @check
                        @error_reporting(True)
                        @uses_db(CustomClient().sessionmaker)
                        async def emoji_button_callback(interaction: Interaction, session: Session):
                            emoji_modal = ui.Modal(title="Set Upgrade Type Emoji")
                            emoji_input = ui.TextInput(label="Emoji", placeholder="Enter emoji", default=upgrade_type.emoji or "", max_length=10)
                            emoji_modal.add_item(emoji_input)
                            @check
                            @error_reporting(True)
                            @uses_db(CustomClient().sessionmaker)
                            async def emoji_modal_submit(interaction: Interaction, session: Session):
                                current_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_pk).first()
                                current_upgrade_type.emoji = emoji_input.value.strip() or None
                                session.commit()
                                await interaction.response.send_message(f"Emoji updated to: {emoji_input.value.strip() or 'None'}", ephemeral=True)
                                updated_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_pk).first()
                                new_view, new_embed = ui_factory(updated_upgrade_type)
                                await message_manager.update_message(content="Please set up the upgrade type", view=new_view, embed=new_embed)
                            emoji_modal.on_submit = emoji_modal_submit
                            await interaction.response.send_modal(emoji_modal)
                        emoji_button.callback = emoji_button_callback
                        edit_embed = Embed(title=f"Edit Upgrade Type: {upgrade_type.name}")
                        edit_embed.add_field(name="Current Emoji", value=upgrade_type.emoji or "None")
                        edit_embed.add_field(name="Current Is Refit", value="Yes" if upgrade_type.is_refit else "No")
                        edit_embed.add_field(name="Current Non Purchaseable", value="Yes" if upgrade_type.non_purchaseable else "No")
                        edit_embed.add_field(name="Current Can Use Unit Req", value="Yes" if upgrade_type.can_use_unit_req else "No")
                        await message_manager.update_message(content="Edit upgrade type settings", view=edit_view, embed=edit_embed)
                    edit_button.callback = edit_button_callback
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def sort_order_button_callback(interaction: Interaction, session: Session):
                        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_pk).first()
                        sort_order_modal = ui.Modal(title="Set Upgrade Type Sort Order")
                        sort_order_input = ui.TextInput(label="Sort Order", placeholder="Enter sort order", default=str(upgrade_type.sort_order), max_length=10)
                        sort_order_modal.add_item(sort_order_input)
                        @check
                        @error_reporting(True)
                        @uses_db(CustomClient().sessionmaker)
                        async def sort_order_modal_submit(interaction: Interaction, session: Session):
                            try:
                                new_sort_order = int(sort_order_input.value.strip())
                                current_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_pk).first()
                                current_upgrade_type.sort_order = new_sort_order
                                session.commit()
                                await interaction.response.send_message(f"Sort order updated to: {new_sort_order}", ephemeral=True)
                                updated_upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_pk).first()
                                new_view, new_embed = ui_factory(updated_upgrade_type)
                                await message_manager.update_message(content="Please set up the upgrade type", view=new_view, embed=new_embed)
                            except ValueError:
                                await interaction.response.send_message("Please enter a valid integer for sort order", ephemeral=True)
                        sort_order_modal.on_submit = sort_order_modal_submit
                        await interaction.response.send_modal(sort_order_modal)
                    sort_order_button.callback = sort_order_button_callback
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def delete_button_callback(interaction: Interaction, session: Session):
                        upgrade_type = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type_pk).first()
                        if upgrade_type.shop_upgrades:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_shop_upgrades, ephemeral=True)
                            return
                        if upgrade_type.player_upgrades:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_player_upgrades, ephemeral=True)
                            return
                        session.delete(upgrade_type)
                        session.commit()
                        await interaction.response.send_message(tmpl.shop_upgrade_type_deleted, ephemeral=True)
                        await message_manager.delete_message()
                    delete_button.callback = delete_button_callback
                    if upgrade_type.shop_upgrades:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete an upgrade type that has shop upgrades assigned to it", inline=False)
                    if upgrade_type.player_upgrades:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete an upgrade type that has player upgrades assigned to it", inline=False)
                    return view, embed
                view, embed = ui_factory(upgrade_type_)
                await message_manager.update_message(content=tmpl.shop_please_setup_upgrade_type, view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
        select.callback = select_callback
        await interaction.response.defer(thinking=False, ephemeral=True)
        await message_manager.update_message(content=tmpl.shop_please_select_upgrade_type, view=view)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def _shop_upgrade_callback(self, interaction: Interaction, message_manager: MessageManager, session: Session):
        logger.info(f"Shop upgrade management accessed by {interaction.user.id} ({interaction.user.name})")
        shop_upgrades = session.query(ShopUpgrade.id, ShopUpgrade.name).order_by(ShopUpgrade.sort_key, ShopUpgrade.id).all()
        shop_upgrades.append(("\0Add New Shop Upgrade", "\0Add New Shop Upgrade"))
        paginator: Paginator[tuple] = Paginator(shop_upgrades, 25)
        view = RecordingView()
        select = ui.Select(placeholder=tmpl.shop_upgrade_select_placeholder)
        previous_button = ui.Button(label=tmpl.shop_previous_button, style=ButtonStyle.secondary, disabled=True)
        next_button = ui.Button(label=tmpl.shop_next_button, style=ButtonStyle.secondary, disabled=not paginator.has_next())
        predicate = self._shop_original_author(interaction)
        check = ac.check(predicate)
        view.add_item(previous_button)
        view.add_item(select)
        view.add_item(next_button)
        for shop_upgrade in paginator.current():
            select.add_option(label=shop_upgrade[1], value=str(shop_upgrade[0]))
        @check
        @error_reporting(True)
        async def previous_button_callback(interaction: Interaction):
            nonlocal paginator
            paginator.previous()
            select.options.clear()
            for shop_upgrade in paginator.current():
                select.add_option(label=shop_upgrade[1], value=str(shop_upgrade[0]))
            next_button.disabled = not paginator.has_next()
            previous_button.disabled = not paginator.has_previous()
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        previous_button.callback = previous_button_callback
        @check
        @error_reporting(True)
        async def next_button_callback(interaction: Interaction):
            nonlocal paginator
            paginator.next()
            select.options.clear()
            for shop_upgrade in paginator.current():
                select.add_option(label=shop_upgrade[1], value=str(shop_upgrade[0]))
            next_button.disabled = not paginator.has_next()
            previous_button.disabled = not paginator.has_previous()
            await interaction.response.defer(thinking=False, ephemeral=True)
            await message_manager.update_message(view=view)
        next_button.callback = next_button_callback
        @check
        @error_reporting(True)
        @uses_db(CustomClient().sessionmaker)
        async def select_callback(interaction: Interaction, session: Session):
            target = interaction.data["values"][0]
            if target == "\0Add New Shop Upgrade":
                upgrade_types = session.query(UpgradeType).all()
                add_view = RecordingView()
                upgrade_type_options = [SelectOption(label=ut.name, value=ut.name) for ut in upgrade_types]
                upgrade_type_select = ui.Select(placeholder=tmpl.shop_select_upgrade_type_placeholder, options=upgrade_type_options)
                disabled_select = ui.Select(placeholder=tmpl.shop_disabled_placeholder, options=[SelectOption(label="No", value="n"), SelectOption(label="Yes", value="y")])
                repeatable_options = [SelectOption(label="Unlimited", value="0")] + [SelectOption(label=str(n), value=str(n)) for n in range(1, 11)]
                repeatable_select = ui.Select(placeholder=tmpl.shop_repeatable_placeholder, options=repeatable_options)
                add_view.add_item(upgrade_type_select)
                add_view.add_item(disabled_select)
                add_view.add_item(repeatable_select)
                selected_values = {"upgrade_type": None, "disabled": False, "repeatable": 0}
                @check
                @error_reporting(True)
                async def upgrade_type_callback(interaction: Interaction):
                    selected_values["upgrade_type"] = upgrade_type_select.values[0] if upgrade_type_select.values else None
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    await message_manager.update_message(content=tmpl.shop_upgrade_type_status.format(type=selected_values['upgrade_type']), view=add_view)
                @check
                @error_reporting(True)
                async def disabled_callback(interaction: Interaction):
                    selected_values["disabled"] = disabled_select.values[0] == "y" if disabled_select.values else False
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    await message_manager.update_message(content=tmpl.shop_disabled_status.format(status='Yes' if selected_values['disabled'] else 'No'), view=add_view)
                @check
                @error_reporting(True)
                async def repeatable_callback(interaction: Interaction):
                    selected_values["repeatable"] = int(repeatable_select.values[0]) if repeatable_select.values else 0
                    await interaction.response.defer(thinking=False, ephemeral=True)
                    status = "Unlimited" if selected_values["repeatable"] == 0 else f"Max: {selected_values['repeatable']}"
                    await message_manager.update_message(content=tmpl.shop_repeatable_status.format(status=status), view=add_view)
                proceed_button = ui.Button(label=tmpl.shop_proceed_to_details_button, style=ButtonStyle.primary)
                @check
                @error_reporting(True)
                @uses_db(CustomClient().sessionmaker)
                async def proceed_callback(interaction: Interaction, session: Session):
                    if not selected_values["upgrade_type"]:
                        await interaction.response.send_message(tmpl.shop_please_select_upgrade_type, ephemeral=True)
                        return
                    modal = ui.Modal(title=tmpl.shop_add_new_shop_upgrade_modal_title)
                    name_input = ui.TextInput(label=tmpl.shop_upgrade_name_label, placeholder=tmpl.shop_upgrade_name_placeholder, min_length=1, max_length=30)
                    cost_input = ui.TextInput(label=tmpl.shop_upgrade_cost_label, placeholder=tmpl.shop_cost_placeholder, min_length=1, max_length=10)
                    refit_target_input = ui.TextInput(label=tmpl.shop_refit_target_label, placeholder=tmpl.shop_refit_target_optional_placeholder, max_length=15, required=False)
                    required_upgrade_id_input = ui.TextInput(label="Required Upgrade ID", placeholder=tmpl.shop_required_upgrade_id_placeholder, max_length=10, required=False)
                    unit_types_input = ui.TextInput(label="Compatible Unit Types", placeholder=tmpl.shop_compatible_unit_types_placeholder, style=TextStyle.paragraph, required=False)
                    modal.add_item(name_input)
                    modal.add_item(cost_input)
                    modal.add_item(refit_target_input)
                    modal.add_item(required_upgrade_id_input)
                    modal.add_item(unit_types_input)
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def modal_submit(interaction: Interaction, session: Session):
                        name = name_input.value.strip()
                        cost = int(cost_input.value.strip())
                        refit_target = refit_target_input.value.strip().upper() if refit_target_input.value.strip() else None
                        required_upgrade_id = int(required_upgrade_id_input.value.strip()) if required_upgrade_id_input.value.strip() else None
                        unit_types_text = unit_types_input.value.strip()
                        compatible_unit_types = [ut.strip().upper() for ut in unit_types_text.split('\n') if ut.strip()] if unit_types_text else []
                        new_shop_upgrade = ShopUpgrade(name=name, type=selected_values["upgrade_type"], cost=cost, refit_target=refit_target, required_upgrade_id=required_upgrade_id, disabled=selected_values["disabled"], repeatable=selected_values["repeatable"])
                        session.add(new_shop_upgrade)
                        session.flush()
                        for unit_type_name in compatible_unit_types:
                            session.add(ShopUpgradeUnitTypes(shop_upgrade_id=new_shop_upgrade.id, unit_type=unit_type_name))
                        session.commit()
                        await interaction.response.defer(thinking=False, ephemeral=True)
                        await message_manager.update_message(content=tmpl.shop_upgrade_added, view=RecordingView())
                    modal.on_submit = modal_submit
                    await interaction.response.send_modal(modal)
                proceed_button.callback = proceed_callback
                add_view.add_item(proceed_button)
                upgrade_type_select.callback = upgrade_type_callback
                disabled_select.callback = disabled_callback
                repeatable_select.callback = repeatable_callback
                await interaction.response.send_message(tmpl.shop_please_select_boolean_options, view=add_view, ephemeral=True)
            else:
                shop_upgrade_ = session.query(ShopUpgrade).filter(ShopUpgrade.id == int(target)).first()
                def ui_factory(shop_upgrade: ShopUpgrade) -> tuple[RecordingView, Embed]:
                    nonlocal target
                    view = RecordingView()
                    embed = Embed(title=tmpl.shop_upgrade_title.format(name=shop_upgrade.name))
                    embed.add_field(name="Type", value=shop_upgrade.type)
                    embed.add_field(name="Cost", value=str(shop_upgrade.cost))
                    embed.add_field(name="Refit Target", value=shop_upgrade.refit_target or "None")
                    embed.add_field(name="Required Upgrade ID", value=str(shop_upgrade.required_upgrade_id) if shop_upgrade.required_upgrade_id else "None")
                    embed.add_field(name="Disabled", value="Yes" if shop_upgrade.disabled else "No")
                    embed.add_field(name="Repeatable", value="Unlimited" if shop_upgrade.repeatable == 0 else f"Max: {shop_upgrade.repeatable}")
                    compatible_unit_types = [assoc.unit_type for assoc in shop_upgrade.unit_types]
                    embed.add_field(name="Compatible Unit Types", value="\n".join(compatible_unit_types) if compatible_unit_types else "None", inline=False)
                    rename_button = ui.Button(label=tmpl.shop_rename_button, style=ButtonStyle.primary)
                    delete_button = ui.Button(label=tmpl.shop_delete_button, style=ButtonStyle.danger)
                    edit_button = ui.Button(label="Edit", style=ButtonStyle.secondary)
                    view.add_item(rename_button)
                    view.add_item(delete_button)
                    view.add_item(edit_button)
                    shop_upgrade_id_ = shop_upgrade.id
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def rename_button_callback(interaction: Interaction, session: Session):
                        modal = ui.Modal(title=tmpl.shop_edit_shop_upgrade_modal_title)
                        shop_upgrade_obj = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_id_).first()
                        new_name_input = ui.TextInput(label=tmpl.shop_new_name_label, placeholder=tmpl.shop_new_name_placeholder, default=shop_upgrade_obj.name, min_length=1, max_length=30)
                        modal.add_item(new_name_input)
                        @check
                        @error_reporting(True)
                        @uses_db(CustomClient().sessionmaker)
                        async def modal_submit(interaction: Interaction, session: Session):
                            nonlocal target
                            new_name = interaction.data["components"][0]["components"][0]["value"].strip()
                            shop_upgrade_obj = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_id_).first()
                            if not new_name:
                                await interaction.response.send_message(tmpl.shop_name_cannot_be_empty, ephemeral=True)
                                return
                            if session.query(ShopUpgrade).filter(ShopUpgrade.name == new_name).first():
                                await interaction.response.send_message(tmpl.shop_upgrade_already_exists.format(name=new_name), ephemeral=True)
                                return
                            shop_upgrade_obj.name = new_name
                            session.commit()
                            target = str(shop_upgrade_obj.id)
                            await interaction.response.send_message(tmpl.shop_upgrade_renamed.format(old=shop_upgrade_obj.name, new=new_name), ephemeral=True)
                            updated_shop_upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_id_).first()
                            new_view, new_embed = ui_factory(updated_shop_upgrade)
                            await message_manager.update_message(content=tmpl.shop_please_select_options_to_edit, view=new_view, embed=new_embed)
                        modal.on_submit = modal_submit
                        await interaction.response.send_modal(modal)
                    rename_button.callback = rename_button_callback
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def delete_button_callback(interaction: Interaction, session: Session):
                        shop_upgrade_obj = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_id_).first()
                        if shop_upgrade_obj.player_upgrades:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_player_upgrades, ephemeral=True)
                            return
                        if shop_upgrade_obj.unit_types:
                            await interaction.response.send_message(tmpl.shop_cannot_delete_has_unit_type_associations, ephemeral=True)
                            return
                        session.delete(shop_upgrade_obj)
                        session.commit()
                        await interaction.response.send_message(tmpl.shop_upgrade_deleted, ephemeral=True)
                        await message_manager.delete_message()
                    delete_button.callback = delete_button_callback
                    @check
                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def edit_button_callback(interaction: Interaction, session: Session):
                        shop_upgrade_obj = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_id_).first()
                        compatible_unit_types = [assoc.unit_type for assoc in shop_upgrade_obj.unit_types]
                        unit_types_text = "\n".join(compatible_unit_types)
                        upgrade_types = session.query(UpgradeType).all()
                        edit_view = RecordingView()
                        upgrade_type_options = [SelectOption(label=ut.name, value=ut.name) for ut in upgrade_types]
                        upgrade_type_select = ui.Select(placeholder=tmpl.shop_select_upgrade_type_placeholder, options=upgrade_type_options)
                        for option in upgrade_type_select.options:
                            if option.value == shop_upgrade_obj.type:
                                option.default = True
                                break
                        disabled_select = ui.Select(placeholder=tmpl.shop_disabled_placeholder, options=[SelectOption(label="Disabled: No", value="n", default=not shop_upgrade_obj.disabled), SelectOption(label="Disabled: Yes", value="y", default=shop_upgrade_obj.disabled)])
                        repeatable_options = [SelectOption(label="Unlimited", value="0"), *[SelectOption(label=str(n), value=str(n)) for n in range(1, 11)]]
                        if shop_upgrade_obj.repeatable > 10:
                            repeatable_options.append(SelectOption(label=str(shop_upgrade_obj.repeatable), value=str(shop_upgrade_obj.repeatable)))
                        for opt in repeatable_options:
                            opt.default = (opt.value == str(shop_upgrade_obj.repeatable))
                        repeatable_select = ui.Select(placeholder=tmpl.shop_repeatable_placeholder, options=repeatable_options)
                        edit_view.add_item(upgrade_type_select)
                        edit_view.add_item(disabled_select)
                        edit_view.add_item(repeatable_select)
                        selected_values = {"upgrade_type": shop_upgrade_obj.type, "disabled": shop_upgrade_obj.disabled, "repeatable": shop_upgrade_obj.repeatable, "unit_types_text": unit_types_text}
                        @check
                        @error_reporting(True)
                        async def upgrade_type_cb(interaction: Interaction):
                            selected_values["upgrade_type"] = upgrade_type_select.values[0] if upgrade_type_select.values else shop_upgrade_obj.type
                            await interaction.response.defer(thinking=False, ephemeral=True)
                            await message_manager.update_message(content=tmpl.shop_upgrade_type_status.format(type=selected_values['upgrade_type']), view=edit_view)
                        @check
                        @error_reporting(True)
                        async def disabled_cb(interaction: Interaction):
                            selected_values["disabled"] = disabled_select.values[0] == "y" if disabled_select.values else shop_upgrade_obj.disabled
                            await interaction.response.defer(thinking=False, ephemeral=True)
                            await message_manager.update_message(content=tmpl.shop_disabled_status.format(status='Yes' if selected_values['disabled'] else 'No'), view=edit_view)
                        @check
                        @error_reporting(True)
                        async def repeatable_cb(interaction: Interaction):
                            selected_values["repeatable"] = int(repeatable_select.values[0]) if repeatable_select.values else shop_upgrade_obj.repeatable
                            await interaction.response.defer(thinking=False, ephemeral=True)
                            status = "Unlimited" if selected_values["repeatable"] == 0 else f"Max: {selected_values['repeatable']}"
                            await message_manager.update_message(content=tmpl.shop_repeatable_status.format(status=status), view=edit_view)
                        proceed_button = ui.Button(label=tmpl.shop_proceed_to_details_button, style=ButtonStyle.primary)
                        @check
                        @error_reporting(True)
                        @uses_db(CustomClient().sessionmaker)
                        async def proceed_cb(interaction: Interaction, session: Session):
                            _shop_upgrade_obj = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_id_).first()
                            if not selected_values["upgrade_type"]:
                                await interaction.response.send_message(tmpl.shop_please_select_upgrade_type, ephemeral=True)
                                return
                            modal = ui.Modal(title=tmpl.shop_edit_shop_upgrade_modal_title)
                            name_input = ui.TextInput(label=tmpl.shop_upgrade_name_label, placeholder=tmpl.shop_upgrade_name_placeholder, default=_shop_upgrade_obj.name, min_length=1, max_length=30)
                            cost_input = ui.TextInput(label=tmpl.shop_upgrade_cost_label, placeholder=tmpl.shop_cost_placeholder, default=str(_shop_upgrade_obj.cost), min_length=1, max_length=10)
                            refit_target_input = ui.TextInput(label=tmpl.shop_refit_target_label, placeholder=tmpl.shop_refit_target_optional_placeholder, default=_shop_upgrade_obj.refit_target or "", max_length=15, required=False)
                            required_upgrade_id_input = ui.TextInput(label="Required Upgrade ID", placeholder=tmpl.shop_required_upgrade_id_placeholder, default=str(_shop_upgrade_obj.required_upgrade_id) if _shop_upgrade_obj.required_upgrade_id else "", max_length=10, required=False)
                            unit_types_input = ui.TextInput(label="Compatible Unit Types", placeholder=tmpl.shop_compatible_unit_types_placeholder, default="\n".join([assoc.unit_type for assoc in _shop_upgrade_obj.unit_types]), style=TextStyle.paragraph, required=False)
                            modal.add_item(name_input)
                            modal.add_item(cost_input)
                            modal.add_item(refit_target_input)
                            modal.add_item(required_upgrade_id_input)
                            modal.add_item(unit_types_input)
                            @check
                            @error_reporting(True)
                            @uses_db(CustomClient().sessionmaker)
                            async def modal_submit(interaction: Interaction, session: Session):
                                shop_upgrade_obj = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_id_).first()
                                name = name_input.value.strip()
                                cost = int(cost_input.value.strip())
                                refit_target = refit_target_input.value.strip().upper() if refit_target_input.value.strip() else None
                                required_upgrade_id = int(required_upgrade_id_input.value.strip()) if required_upgrade_id_input.value.strip() else None
                                unit_types_text = unit_types_input.value.strip()
                                new_compatible_unit_types = {ut.strip().upper() for ut in unit_types_text.split('\n') if ut.strip()} if unit_types_text else set()
                                shop_upgrade_obj.name = name
                                shop_upgrade_obj.type = selected_values["upgrade_type"]
                                shop_upgrade_obj.cost = cost
                                shop_upgrade_obj.refit_target = refit_target
                                shop_upgrade_obj.required_upgrade_id = required_upgrade_id
                                shop_upgrade_obj.disabled = selected_values["disabled"]
                                shop_upgrade_obj.repeatable = selected_values["repeatable"]
                                for assoc in shop_upgrade_obj.unit_types:
                                    session.delete(assoc)
                                session.flush()
                                for unit_type_name in new_compatible_unit_types:
                                    session.add(ShopUpgradeUnitTypes(shop_upgrade_id=shop_upgrade_obj.id, unit_type=unit_type_name))
                                session.commit()
                                await interaction.response.defer(thinking=False, ephemeral=True)
                                await message_manager.update_message(content=tmpl.shop_upgrade_updated, view=RecordingView())
                            modal.on_submit = modal_submit
                            await interaction.response.send_modal(modal)
                        proceed_button.callback = proceed_cb
                        edit_view.add_item(proceed_button)
                        upgrade_type_select.callback = upgrade_type_cb
                        disabled_select.callback = disabled_cb
                        repeatable_select.callback = repeatable_cb
                        await interaction.response.send_message("Please select the options to edit, then proceed to details", view=edit_view, ephemeral=True)
                        updated_shop_upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.id == shop_upgrade_id_).first()
                        new_view, new_embed = ui_factory(updated_shop_upgrade)
                        await message_manager.update_message(content="Please set up the shop upgrade", view=new_view, embed=new_embed)
                    edit_button.callback = edit_button_callback
                    if shop_upgrade.player_upgrades:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a shop upgrade that has player upgrades assigned to it", inline=False)
                    if shop_upgrade.unit_types:
                        delete_button.disabled = True
                        embed.add_field(name="Warning", value="You cannot delete a shop upgrade that has unit type associations assigned to it", inline=False)
                    return view, embed
                view, embed = ui_factory(shop_upgrade_)
                await message_manager.update_message(content="Please set up the shop upgrade", view=view, embed=embed)
                await interaction.response.defer(thinking=False, ephemeral=True)
        select.callback = select_callback
        await interaction.response.defer(thinking=False, ephemeral=True)
        await message_manager.update_message(content="Please select a shop upgrade", view=view)

    @ac.command(name="mass_manage", description="Give a unit type all upgrades of a specific type")
    @ac.autocomplete(unit_type=fuzzy_autocomplete(UnitType.unit_type), upgrade_type=fuzzy_autocomplete(UpgradeType.name))
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def mass_manage(self, interaction: Interaction, session: Session, unit_type: str, upgrade_type: str):
        unit_type_ = session.query(UnitType).filter(UnitType.unit_type == unit_type).first()
        upgrade_type_ = session.query(UpgradeType).filter(UpgradeType.name == upgrade_type).first()
        if not unit_type_ or not upgrade_type_:
            await interaction.response.send_message(tmpl.shop_unit_type_or_upgrade_type_not_found, ephemeral=True)
            return
        for upgrade in upgrade_type_.shop_upgrades:
            unit_type_.compatible_upgrades.append(upgrade)
        session.commit()
        await interaction.response.send_message(tmpl.shop_unit_type_given_all_upgrades_of_type.format(unit_type=unit_type, upgrade_type=upgrade_type), ephemeral=True)

    @ac.command(name="units", description="Manage units for a player")
    @ac.describe(player="The player to manage units for")
    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def units(self, interaction: Interaction, player: Member, session: Session):
        player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not player:
            await interaction.response.send_message("The player doesn't have a Meta Campaign company", ephemeral=True)
            return
        view = RecordingView()
        select = ui.Select(placeholder="Select the unit you want to manage")
        if not player.units:
            select.disabled = True
            select.add_option(label="No units", value="no_units", emoji="🛑", default=True)
        [select.add_option(label=unit.name, value=unit.id) for unit in player.units] # side effect comprehension
        select.callback = self.manage_units_callback
        view.add_item(select)
        await interaction.response.send_message(f"Please select the unit you want to manage for {player.name}", view=view, ephemeral=True)

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def manage_units_callback(self, interaction: Interaction, session: Session):
        if interaction.data["values"][0] == "no_units":
            await interaction.response.send_message("No unit selected", ephemeral=True)
            return
        unit = session.query(Unit).filter(Unit.id == int(interaction.data["values"][0])).first()
        if not unit:
            await interaction.response.send_message("Unit not found", ephemeral=True)
            return
        message_manager = MessageManager(interaction)
        member = interaction.guild.get_member(int(unit.player.discord_id)) if interaction.guild else None
        embed = self.UnitManageEmbed(unit, member)
        view = self.UnitManageView(unit, message_manager, interaction.user.id)
        await message_manager.send_message(embed=embed, view=view, ephemeral=CustomClient().use_ephemeral)

    class UnitManageEmbed(Embed):
        def __init__(self, unit: Unit, member: Member | None):
            super().__init__(title=unit.name, description=f"Unit type: {unit.unit_type}", color=0x00ff00)
            if member:
                self.set_thumbnail(url=member.display_avatar.url)
            self.add_field(name="Callsign", value=unit.callsign or "—", inline=True)
            self.add_field(name="Status", value=unit.status.name if unit.status else "—", inline=True)
            self.set_footer(text=f"Unit ID: {unit.id}")

    class UnitManageView(RecordingView):
        def __init__(self, unit: Unit, message_manager: MessageManager, original_user_id: int):
            super().__init__()
            self.unit = unit
            self.message_manager = message_manager
            self.original_user_id = original_user_id
            self._add_buttons()

        def _add_buttons(self):
            special_btn = ui.Button(label="Special Upgrade", style=ButtonStyle.primary)
            special_btn.callback = self._special_upgrade_callback
            self.add_item(special_btn)

            deactivate_btn = ui.Button(label="Deactivate", style=ButtonStyle.secondary)
            deactivate_btn.callback = self._deactivate_callback
            deactivate_btn.disabled = not self.unit.active
            self.add_item(deactivate_btn)

            callsign_btn = ui.Button(label="Change Callsign", style=ButtonStyle.secondary)
            callsign_btn.callback = self._callsign_callback
            callsign_btn.disabled = not self.unit.callsign
            self.add_item(callsign_btn)

            status_btn = ui.Button(label="Change Status", style=ButtonStyle.secondary)
            status_btn.callback = self._status_callback
            self.add_item(status_btn)

        @ui.button(label="Remove Unit", style=ButtonStyle.danger)
        @error_reporting(True)
        @uses_db(CustomClient().sessionmaker)
        async def remove_unit_btn(self, interaction: Interaction, button: ui.Button, session: Session):
            if interaction.user.id != self.original_user_id:
                await interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                return
            unit = session.merge(self.unit)
            self.message_manager.embed.title = f"Remove {unit.name}?"
            self.message_manager.embed.description = "Are you sure you want to remove this unit? Click Confirm below to proceed to final confirmation."
            confirm_view = RecordingView()
            confirm_btn = ui.Button(label="Confirm", style=ButtonStyle.primary, custom_id="remove_confirm_1")
            cancel_btn = ui.Button(label="Cancel", style=ButtonStyle.secondary, custom_id="remove_cancel_1")
            unit_id = unit.id
            unit_name = unit.name

            @error_reporting(True)
            async def confirm_cb(_interaction: Interaction):
                if _interaction.user.id != self.original_user_id:
                    await _interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                    return
                await _interaction.response.defer(ephemeral=True)
                second_view = RecordingView()
                final_btn = ui.Button(label="Permanently Remove Unit", style=ButtonStyle.danger, custom_id="remove_confirm_2")
                cancel2_btn = ui.Button(label="Cancel", style=ButtonStyle.secondary, custom_id="remove_cancel_2")

                @error_reporting(True)
                @uses_db(CustomClient().sessionmaker)
                async def final_confirm_cb(_interaction2: Interaction, session: Session):
                    if _interaction2.user.id != self.original_user_id:
                        await _interaction2.response.send_message("You are not the person who ran the command", ephemeral=True)
                        return
                    _unit = session.query(Unit).filter(Unit.id == unit_id).first()
                    if not _unit:
                        await _interaction2.response.send_message("Unit not found", ephemeral=True)
                        return
                    unit_name = _unit.name
                    player = _unit.player
                    for upgrade in _unit.upgrades:
                        session.delete(upgrade)
                    session.flush()
                    session.delete(_unit)
                    CustomClient().queue.put_nowait((1, player, 0))
                    await _interaction2.response.send_message(f"Unit {unit_name} has been removed", ephemeral=True)

                @error_reporting(True)
                async def cancel2_cb(_interaction2: Interaction):
                    if _interaction2.user.id != self.original_user_id:
                        await _interaction2.response.send_message("You are not the person who ran the command", ephemeral=True)
                        return
                    await _interaction2.response.send_message("Removal cancelled", ephemeral=True)

                final_btn.callback = final_confirm_cb
                cancel2_btn.callback = cancel2_cb
                second_view.add_item(final_btn)
                second_view.add_item(cancel2_btn)
                await _interaction.followup.send(
                    f"**Final confirmation:** Click the button below to permanently remove **{unit_name}**. This action cannot be undone.",
                    view=second_view,
                    ephemeral=CustomClient().use_ephemeral,
                )

            @error_reporting(True)
            async def cancel_cb(_interaction: Interaction):
                if _interaction.user.id != self.original_user_id:
                    await _interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                    return
                self.message_manager.embed.title = self.unit.name
                self.message_manager.embed.description = f"Unit type: {self.unit.unit_type}"
                self.message_manager.view = self
                await self.message_manager.update_message()
                await _interaction.response.send_message("Removal cancelled", ephemeral=True)

            confirm_btn.callback = confirm_cb
            cancel_btn.callback = cancel_cb
            confirm_view.add_item(confirm_btn)
            confirm_view.add_item(cancel_btn)
            await interaction.response.defer(ephemeral=True)
            self.message_manager.view = confirm_view
            await self.message_manager.update_message()

        @error_reporting(True)
        @uses_db(CustomClient().sessionmaker)
        async def _special_upgrade_callback(self, interaction: Interaction, session: Session):
            if interaction.user.id != self.original_user_id:
                await interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                return
            _unit = session.merge(self.unit)
            unit_id = _unit.id
            modal = ui.Modal(title="Special Upgrade")
            modal.add_item(ui.TextInput(label="Item name", placeholder="Enter the name of the special/relic item", required=True, max_length=30))

            @error_reporting(True)
            @uses_db(CustomClient().sessionmaker)
            async def on_submit(_interaction: Interaction, session: Session):
                if _interaction.user.id != self.original_user_id:
                    await _interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                    return
                name = _interaction.data["components"][0]["components"][0]["value"].strip()
                if not name:
                    await _interaction.response.send_message("Name cannot be empty", ephemeral=True)
                    return
                if len(name) > 30:
                    await _interaction.response.send_message("Name is too long", ephemeral=True)
                    return
                _unit = session.query(Unit).filter(Unit.id == unit_id).first()
                if not _unit:
                    await _interaction.response.send_message("Unit not found", ephemeral=True)
                    return
                upgrade = PlayerUpgrade(name=name, type="SPECIAL", unit_id=unit_id)
                session.add(upgrade)
                CustomClient().queue.put_nowait((1, _unit.player, 0))
                self.message_manager.embed.set_field_at(0, name="Callsign", value=_unit.callsign or "—", inline=True)
                self.message_manager.embed.set_field_at(1, name="Status", value=_unit.status.name if _unit.status else "—", inline=True)
                await self.message_manager.update_message()
                await _interaction.response.send_message(f"Special upgrade {name} given to {_unit.name}", ephemeral=True)
            modal.on_submit = on_submit
            await interaction.response.send_modal(modal)

        @error_reporting(True)
        @uses_db(CustomClient().sessionmaker)
        async def _deactivate_callback(self, interaction: Interaction, session: Session):
            if interaction.user.id != self.original_user_id:
                await interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                return
            unit = session.merge(self.unit)
            if not unit.active:
                await interaction.response.send_message("Unit is not active", ephemeral=True)
                return
            unit.active = False
            unit.status = UnitStatus.INACTIVE if unit.status == UnitStatus.ACTIVE else unit.status
            unit.callsign = None
            CustomClient().queue.put_nowait((1, unit.player, 0))
            self.message_manager.embed.set_field_at(0, name="Callsign", value="—", inline=True)
            self.message_manager.embed.set_field_at(1, name="Status", value=unit.status.name if unit.status else "—", inline=True)
            await self.message_manager.update_message()
            await interaction.response.send_message(f"Unit {unit.name} deactivated", ephemeral=True)

        @error_reporting(True)
        @uses_db(CustomClient().sessionmaker)
        async def _callsign_callback(self, interaction: Interaction, session: Session):
            if interaction.user.id != self.original_user_id:
                await interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                return
            unit = session.merge(self.unit)
            unit_id = unit.id
            default_callsign = unit.callsign or ""
            modal = ui.Modal(title="Change Callsign")
            modal.add_item(ui.TextInput(label="New callsign", placeholder="Enter callsign", required=True, max_length=15, default=default_callsign))

            @error_reporting(True)
            @uses_db(CustomClient().sessionmaker)
            async def on_submit(_interaction: Interaction, session: Session):
                if _interaction.user.id != self.original_user_id:
                    await _interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                    return
                new_callsign = _interaction.data["components"][0]["components"][0]["value"].strip()
                if len(new_callsign) > 15:
                    await _interaction.response.send_message("Callsign is too long", ephemeral=True)
                    return
                if session.query(Unit).filter(Unit.callsign == new_callsign, Unit.id != unit_id).first():
                    await _interaction.response.send_message("Callsign is already taken", ephemeral=True)
                    return
                _unit = session.query(Unit).filter(Unit.id == unit_id).first()
                if not _unit:
                    await _interaction.response.send_message("Unit not found", ephemeral=True)
                    return
                _unit.callsign = new_callsign
                CustomClient().queue.put_nowait((1, _unit.player, 0))
                self.message_manager.embed.set_field_at(0, name="Callsign", value=new_callsign, inline=True)
                await self.message_manager.update_message()
                await _interaction.response.send_message(f"Unit {_unit.name} callsign changed to {new_callsign}", ephemeral=True)
            modal.on_submit = on_submit
            await interaction.response.send_modal(modal)

        @error_reporting(True)
        @uses_db(CustomClient().sessionmaker)
        async def _status_callback(self, interaction: Interaction, session: Session):
            if interaction.user.id != self.original_user_id:
                await interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                return
            unit = session.merge(self.unit)
            status_select = ui.Select(
                placeholder="Select new status",
                options=[SelectOption(label=s.name, value=s.value, default=unit.status == s) for s in UnitStatus]
            )
            status_view = RecordingView()
            status_view.add_item(status_select)

            unit_id = unit.id

            @error_reporting(True)
            @uses_db(CustomClient().sessionmaker)
            async def status_select_cb(_interaction: Interaction, session: Session):
                if _interaction.user.id != self.original_user_id:
                    await _interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                    return
                _unit = session.query(Unit).filter(Unit.id == unit_id).first()
                if not _unit:
                    await _interaction.response.send_message("Unit not found", ephemeral=True)
                    return
                new_status = UnitStatus(_interaction.data["values"][0])
                if new_status == UnitStatus.ACTIVE:
                    callsign_modal = ui.Modal(title="Enter callsign and campaign")
                    callsign_modal.add_item(ui.TextInput(label="Callsign", placeholder="Enter callsign for unit", required=True, max_length=15))
                    callsign_modal.add_item(ui.TextInput(label="Campaign (name or id)", placeholder="Campaign name or numeric id", required=True, max_length=30))

                    @error_reporting(True)
                    @uses_db(CustomClient().sessionmaker)
                    async def callsign_submit(cs_interaction: Interaction, session: Session):
                        if cs_interaction.user.id != self.original_user_id:
                            await cs_interaction.response.send_message("You are not the person who ran the command", ephemeral=True)
                            return
                        new_callsign = cs_interaction.data["components"][0]["components"][0]["value"].strip()
                        campaign_input = cs_interaction.data["components"][1]["components"][0]["value"].strip()
                        if len(new_callsign) > 15:
                            await cs_interaction.response.send_message("Callsign too long", ephemeral=True)
                            return
                        if session.query(Unit).filter(Unit.callsign == new_callsign, Unit.id != unit_id).first():
                            await cs_interaction.response.send_message("Callsign already taken", ephemeral=True)
                            return
                        campaign_conds = [Campaign.name == campaign_input]
                        if campaign_input.isdigit():
                            campaign_conds.append(Campaign.id == int(campaign_input))
                        campaign = session.query(Campaign).filter(or_(*campaign_conds)).first()
                        if not campaign:
                            await cs_interaction.response.send_message("Campaign not found", ephemeral=True)
                            return
                        _u = session.query(Unit).filter(Unit.id == unit_id).first()
                        if not _u:
                            await cs_interaction.response.send_message("Unit not found", ephemeral=True)
                            return
                        _u.callsign = new_callsign
                        _u.campaign_id = campaign.id
                        _u.active = True
                        _u.status = UnitStatus.ACTIVE
                        CustomClient().queue.put_nowait((1, _u.player, 0))
                        self.message_manager.embed.set_field_at(0, name="Callsign", value=new_callsign, inline=True)
                        self.message_manager.embed.set_field_at(1, name="Status", value=UnitStatus.ACTIVE.name, inline=True)
                        await self.message_manager.update_message()
                        await cs_interaction.response.send_message(f"Unit {_u.name} activated with callsign {new_callsign}", ephemeral=True)
                    callsign_modal.on_submit = callsign_submit
                    await _interaction.response.send_modal(callsign_modal)
                elif new_status == UnitStatus.LEGACY:
                    _unit.legacy = True
                    _unit.status = UnitStatus.LEGACY
                    CustomClient().queue.put_nowait((1, _unit.player, 0))
                    self.message_manager.embed.set_field_at(1, name="Status", value=UnitStatus.LEGACY.name, inline=True)
                    await self.message_manager.update_message()
                    await _interaction.response.send_message(f"Unit {_unit.name} status changed to {new_status.name}", ephemeral=True)
                else:
                    _unit.status = new_status
                    CustomClient().queue.put_nowait((1, _unit.player, 0))
                    self.message_manager.embed.set_field_at(1, name="Status", value=new_status.name, inline=True)
                    await self.message_manager.update_message()
                    await _interaction.response.send_message(f"Unit {_unit.name} status changed to {new_status.name}", ephemeral=True)
            status_select.callback = status_select_cb
            await interaction.response.send_message("Select the new status:", view=status_view, ephemeral=True)

async def setup(_bot: CustomClient):
    await _bot.add_cog(Manage(_bot))

async def teardown(_bot: CustomClient):
    await _bot.remove_cog(Manage.__name__)