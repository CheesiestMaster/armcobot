from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, Member, TextStyle, Emoji, SelectOption, ui, ButtonStyle
from discord.ui import Modal, TextInput
from models import Player, Unit, UnitStatus, PlayerUpgrade, Medals
from customclient import CustomClient
import os
from utils import has_invalid_url, uses_db, string_to_list
from sqlalchemy.orm import Session
logger = getLogger(__name__)

class Admin(GroupCog, group_name="admin", name="Admin"):
    """
    Admin commands for managing players, units, points, and medals in the bot.
    """
    def __init__(self, bot: Bot):
        """
        Initialize the Admin cog with a reference to the bot instance.
        """
        super().__init__()
        self.bot = bot
        if os.getenv("PROD", False):
            self.interaction_check = self.is_mod # disabled for development, as those roles don't exist on the dev guild

    async def is_mod(self, interaction: Interaction):
        """
        Check if the user is a moderator with the necessary role.
        """
        valid = any(interaction.user.get_role(role) for role in self.bot.mod_roles)
        if not valid:
            logger.warning(f"{interaction.user.name} tried to use admin commands")
        return valid
    
    @ac.command(name="recpoint", description="Give or remove a number of requisition points from a player")
    @ac.describe(player="The player to give or remove points from")
    @ac.describe(points="The number of points to give or remove")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def recpoint(self, interaction: Interaction, player: Member, points: int, session: Session):
        """
        Adjusts a player's requisition points by adding or removing a specified amount.
        """
        # find the player by discord id
        player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not player:
            await interaction.response.send_message("User doesn't have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        
        # update the player's rec points
        player.rec_points += points
        logger.debug(f"User {player.name} now has {player.rec_points} requisition points")
        await interaction.response.send_message(f"{player.name} now has {player.rec_points} requisition points", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="bulk_recpoint", description="Give or remove a number of requisition points from a set of players")
    @ac.describe(points="The number of points to give or remove")
    @ac.describe(status="Status of the unit (Inactive = 0, Active = 1, MIA = 2, KIA = 3)")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def bulk_recpoint(self, interaction: Interaction, status: str, points: int, session: Session):
        """
        Modify requisition points for players with units of a specific status.
        """
        # Find all units with corresponding Enum status
        status_enum = UnitStatus(status)
        units = session.query(Unit).filter(Unit.status == status_enum).all()
        for unit in units:
            # Find player of each unit and update their recpoints
            player = unit.player
            player.rec_points += points
            logger.debug(f"User {player.name} now has {player.rec_points} requisition points")
        await interaction.response.send_message(f"Players of units of the status {status} have received {points} requisition points", ephemeral=self.bot.use_ephemeral)
    
    @ac.command(name="bulk_recpoint_by_name", description="Give or remove a number of requisition points from a set of players by name")
    @ac.describe(points="The number of requisition points to give or remove")
    async def bulk_recpoint_by_name(self, interaction: Interaction, points: int):
        """
        Adjust requisition points for players by entering their names in a modal form.
        """
        brp_modal = Modal(title="Bulk Requisition Points by Name", custom_id="bulk_recpoint_by_name")
        brp_modal.add_item(TextInput(label="Player names", custom_id="player_names", style=TextStyle.paragraph))
        @uses_db(sessionmaker=CustomClient().sessionmaker) # we need to decorate the callback, as the command itself has left scope
        async def brp_modal_callback(interaction: Interaction, session: Session):
            player_names = interaction.data["components"][0]["components"][0]["value"]
            logger.debug(f"Received player names: {player_names}")
            player_names = string_to_list(player_names)
            if len(player_names) == 0:
                await interaction.response.send_message("No player names provided", ephemeral=self.bot.use_ephemeral)
                return
            logger.debug(f"Parsed player names: {player_names}")
            # we need to convert the discord names to discord ids, then convert those to Player objects
            members: list[Member] = await interaction.guild.fetch_members(limit=None).flatten()
            chosen_members = {member for member in members if member.global_name in player_names}
            discord_ids = {member.id for member in chosen_members}
            players = session.query(Player).filter(Player.discord_id.in_(discord_ids)).all()
            failed_players = []
            for player in players:
                if player.rec_points + points < 0:
                    failed_players.append(player.name)
                    continue
                player.rec_points += points
            await interaction.response.send_message(f"Players {chosen_members} have been updated, {', '.join(failed_players)} failed", ephemeral=self.bot.use_ephemeral)

        brp_modal.on_submit = brp_modal_callback
        await interaction.response.send_modal(brp_modal)

    @ac.command(name="bonuspay", description="Give or remove a number of bonus pay from a player")
    @ac.describe(player="The player to give or remove bonus pay from")
    @ac.describe(points="The number of bonus pay to give or remove")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def bonuspay(self, interaction: Interaction, player: Member, points: int, session: Session):
        """
        Modify a player's bonus pay by adding or removing a specified amount.
        """
        # find the player by discord id
        player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not player:
            await interaction.response.send_message("User doesn't have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        
        # update the player's bonus pay
        player.bonus_pay += points
        logger.debug(f"User {player.name} now has {player.bonus_pay} bonus pay")
        await interaction.response.send_message(f"{player.name} now has {player.bonus_pay} bonus pay", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="bulk_bonuspay", description="Give or remove a number of bonus pay from a set of players")
    @ac.describe(points="The number of bonus pay to give or remove")
    @ac.describe(status="Status of the unit (Inactive = 0, Active = 1, MIA = 2, KIA = 3)")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def bulk_bonus_pay(self, interaction: Interaction, status: str, points: int, session: Session):
        """
        Modify bonus pay for players with units of a specific status.
        """
        # Find all units with corresponding Enum status
        status_enum = UnitStatus(status)
        units = session.query(Unit).filter(Unit.status == status_enum).all()
        for unit in units:
            # Find player of each unit and update their bonuspay
            player = unit.player
            player.bonus_pay += points
            logger.debug(f"User {player.name} now has {player.bonus_pay} requisition points")
        await interaction.response.send_message(f"Players of units of the status {status} have received {points} bonus pay", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="bulk_bonuspay_by_name", description="Give or remove a number of bonus pay from a set of players by name")
    @ac.describe(points="The number of bonus pay to give or remove")
    async def bulk_bonuspay_by_name(self, interaction: Interaction, points: int):
        """
        Adjust bonus pay for players by entering their names in a modal form.
        """
        bbp_modal = Modal(title="Bulk Bonus Pay by Name", custom_id="bulk_bonuspay_by_name")
        bbp_modal.add_item(TextInput(label="Player names", custom_id="player_names", style=TextStyle.paragraph))
        @uses_db(sessionmaker=CustomClient().sessionmaker) # we need to decorate the callback, as the command itself has left scope
        async def bbp_modal_callback(interaction: Interaction, session: Session):
            player_names = interaction.data["components"][0]["components"][0]["value"]
            logger.debug(f"Received player names: {player_names}")
            player_names = string_to_list(player_names)
            if len(player_names) == 0:
                await interaction.response.send_message("No player names provided", ephemeral=self.bot.use_ephemeral)
                return
            logger.debug(f"Parsed player names: {player_names}")
            # we need to convert the discord names to discord ids, then convert those to Player objects
            members = [member async for member in await interaction.guild.fetch_members(limit=None)]
            chosen_members = {member for member in members if member.global_name in player_names}
            discord_ids = {member.id for member in chosen_members}
            players = session.query(Player).filter(Player.discord_id.in_(discord_ids)).all()
            failed_players = []
            for player in players:
                if player.bonus_pay + points < 0:
                    failed_players.append(player.name)
                    continue
                player.bonus_pay += points
            await interaction.response.send_message(f"Players {chosen_members} have been updated, {', '.join(failed_players)} failed", ephemeral=self.bot.use_ephemeral)

        bbp_modal.on_submit = bbp_modal_callback
        await interaction.response.send_modal(bbp_modal)

    @ac.command(name="activateunits", description="Activate multiple units")
    async def activateunits(self, interaction: Interaction):
        """
        Activates several units by name through a modal form.
        """
        modal = Modal(title="Activate Units", custom_id="activate_units")
        modal.add_item(TextInput(label="Unit names", custom_id="unit_names", style=TextStyle.long))
        @uses_db(sessionmaker=CustomClient().sessionmaker) # we need to decorate the callback, as the command itself has left scope
        async def modal_callback(interaction: Interaction, session: Session):
            unit_names = interaction.data["components"][0]["components"][0]["value"]
            logger.debug(f"Received unit names: {unit_names}")
            if "\n" in unit_names[:40]:
                unit_names = unit_names.split("\n")
            else:
                unit_names = unit_names.split(",")
            logger.debug(f"Parsed unit names: {unit_names}")
            activated = []
            not_found = []
            for unit_name in unit_names:
                unit = session.query(Unit).filter(Unit.name == unit_name).first()
                if unit:
                    activated.append(unit.name)
                    unit.active = True
                    unit.callsign = unit.name[:10]
                    unit.status = UnitStatus.ACTIVE
                    logger.debug(f"Activated unit: {unit.name}")
                else:
                    not_found.append(unit_name)
                    logger.debug(f"Unit not found: {unit_name}")
                try:
                    session.commit()
                except Exception as e:
                    logger.error(f"Error committing to database: {e}")
                    await interaction.response.send_message(f"Error committing to database: {e}", ephemeral=self.bot.use_ephemeral)
            await interaction.response.send_message(f"Activated {activated}, not found {not_found}", ephemeral=self.bot.use_ephemeral)
            logger.debug(f"Activation results - Activated: {activated}, Not found: {not_found}")
        modal.on_submit = modal_callback
                
        await interaction.response.send_modal(modal)

    @ac.command(name="create_medal", description="Create a medal")
    @ac.describe(name="The name of the medal")
    @ac.describe(left_emote="The emote id to use for the left side of the medal")
    @ac.describe(center_emote="The emote id to use for the center of the medal")
    @ac.describe(right_emote="The emote id to use for the right side of the medal")
    async def create_medal(self, interaction: Interaction, name: str, left_emote: str, center_emote: str, right_emote: str):
        """
        Add a new medal with specified emotes for left, center, and right sides.
        """
        # check if the emotes are valid
        _left_emote: Emoji = await self.bot.fetch_application_emoji(int(left_emote))
        _center_emote: Emoji = await self.bot.fetch_application_emoji(int(center_emote))
        _right_emote: Emoji = await self.bot.fetch_application_emoji(int(right_emote))
        if not all([isinstance(emote, Emoji) for emote in [_left_emote, _center_emote, _right_emote]]):
            await interaction.response.send_message("Invalid emote", ephemeral=self.bot.use_ephemeral)
            return
        # create the medal

        self.bot.medal_emotes[name] = [str(_left_emote), str(_center_emote), str(_right_emote)]
        logger.debug(f"Medal {name} created with emotes {left_emote}, {center_emote}, {right_emote}")
        await interaction.response.send_message(f"Medal {name} created", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="award_medal", description="Award a medal to a player")
    @ac.describe(player="The player to award the medal to")
    @ac.describe(medal="The name of the medal")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def award_medal(self, interaction: Interaction, player: Member, medal: str, session: Session):
        """
        Assign a specific medal to a player.
        """
        # find the player by discord id
        _player: Player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not _player:
            await interaction.response.send_message("User doesn't have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        # if the player already has a medal with that name, send a message saying so
        _medal = session.query(Medals).filter(Medals.name == medal).filter(Medals.player_id == _player.id).first()
        if _medal:
            await interaction.response.send_message(f"{player.name} already has the medal {medal}", ephemeral=self.bot.use_ephemeral)
            return
        # add the medal to the player
        _medal = Medals(name=medal, player_id=_player.id)
        session.add(_medal)
        await interaction.response.send_message(f"{player.name} has been awarded the medal {medal}", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="create_unit_type", description="Create a new unit type")
    @ac.describe(name="The name of the unit type")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def create_unit_type(self, interaction: Interaction, name: str, session: Session):
        """
        Define a new unit type that can be assigned to players' units.
        """
        if len(name) > 15:
            await interaction.response.send_message("Unit type name is too long, please use a shorter name", ephemeral=self.bot.use_ephemeral)
            return
        if not self.bot.config.get("unit_types"):
            self.bot.config["unit_types"] = {name}
        else:
            self.bot.config["unit_types"].add(name) # unit_types is a set, so we can just append
        await self.bot.resync_config(session)
        await interaction.response.send_message(f"Unit type {name} created", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="refresh_stats", description="Refresh the statistics and dossiers for all players")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def refresh_stats(self, interaction: Interaction, session: Session):
        """
        Refreshes the statistics and dossiers for all players.
        """
        await interaction.response.send_message("Refreshing statistics and dossiers for all players", ephemeral=self.bot.use_ephemeral)
        for player in session.query(Player).all():
            self.bot.queue.put_nowait((1, player)) # make the bot think the player was edited, using nowait to avoid yielding control
        await interaction.followup.send("Refreshed statistics and dossiers for all players", ephemeral=self.bot.use_ephemeral)
    
    @ac.command(name="refresh_player", description="Refresh the statistics and dossiers for a player")
    @ac.describe(player="The player to refresh the statistics and dossiers for")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def refresh_player(self, interaction: Interaction, player: Member, session: Session):
        """
        Refreshes the statistics and dossiers for a specific player.
        """
        await interaction.response.send_message(f"Refreshing statistics and dossiers for {player.name}", ephemeral=self.bot.use_ephemeral)
        _player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not _player:
            await interaction.response.send_message("Player does not have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        self.bot.queue.put_nowait((1, _player))
        #await interaction.followup.send("Refreshed statistics and dossiers for all selected players", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="specialupgrade", description="Give a player a one-off or relic item")
    @ac.describe(player="The player to give the item to")
    @ac.describe(name="The name of the item")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def specialupgrade(self, interaction: Interaction, player: Member, name: str, session: Session):
        """
        Give a unique or relic item to a player’s active unit.
        """
        _player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not _player:
            await interaction.response.send_message("Player does not have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        _unit = session.query(Unit).filter(Unit.player_id == _player.id, Unit.active == True).first()
        if not _unit:
            await interaction.response.send_message("Player does not have an active unit", ephemeral=self.bot.use_ephemeral)
            return
        # create an PlayerUpgrade with the given name, type "SPECIAL", and the unit as the parent
        if len(name) > 30:
            await interaction.response.send_message("Name is too long, please use a shorter name", ephemeral=self.bot.use_ephemeral)
            return
        upgrade = PlayerUpgrade(name=name, type="SPECIAL", unit_id=_unit.id)
        session.add(upgrade)
        await interaction.response.send_message(f"Special upgrade {name} given to {_player.name}", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="remove_unit", description="Remove a unit from a player")
    @ac.describe(player="The player to remove the unit from")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def remove_unit(self, interaction: Interaction, player: Member, session: Session):
        """
        Remove a specific unit from a player's records.
        """
        # we need to make a modal for this, as we need a dropdown for the unit type
        class UnitSelect(ui.Select):
            def __init__(self, player_units: list[Unit]):
                options = [SelectOption(label=unit.name, value=unit.id) for unit in player_units]
                super().__init__(placeholder="Select name of unit you want to removed", options=options)

            async def callback(self, interaction: Interaction):
                await interaction.response.defer(ephemeral=True)

        class RemoveUnitView(ui.View):
            def __init__(self, player_units: list[Unit]):
                super().__init__()
                self.bot = CustomClient()
                self.add_item(UnitSelect(player_units))

            @ui.button(label="Remove Unit", style=ButtonStyle.primary)
            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def remove_unit_callback(self, interaction: Interaction, button: ui.Button, session: Session):

                # create the unit in the database
                unit_id = self.children[1].values[0]
                unit: Unit = session.query(Unit).filter(Unit.id == unit_id).first()
                logger.debug(f"Unit with the id {unit_id} has been selected to remove")
                if not unit:
                    await interaction.response.send_message("Unit not found", ephemeral=self.bot.use_ephemeral)
                    return
                self.bot.queue.put_nowait((2, unit))
                session.delete(unit)
                logger.debug(f"Unit with the id {unit_id} was deleted from player {player.name}")
                await interaction.response.send_message(f"Unit {unit.name} has been removed", ephemeral=self.bot.use_ephemeral)
                

        # Checks if the Player has a Meta Company and If that company has a name
        company: Player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not company:
            await interaction.response.send_message(f"{player.name} doesn't have a Meta Campaign company", ephemeral=self.bot.use_ephemeral)
            return
        if len(company.units) == 0:
            await interaction.response.send_message(f"{player.name} doesn't have a unit to remove", ephemeral=CustomClient().use_ephemeral)
            return
        player_units = session.query(Unit).filter(Unit.player_id == company.id).all()
        view = RemoveUnitView(player_units)
        await interaction.response.send_message("Please select the unit you want to remove", view=view, ephemeral=self.bot.use_ephemeral)

    @ac.command(name="remove_unittype", description="Remove a unit type from the game")
    @ac.describe(name="The name of the unit type to remove")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def remove_unittype(self, interaction: Interaction, name: str, session: Session):
        """
        Delete a unit type and mark all related inactive units as legacy.
        """
        if name in self.bot.config.get("unit_types"):
            self.bot.config["unit_types"].remove(name)
            await self.bot.resync_config(session)
        units = session.query(Unit).filter(Unit.unit_type == name).filter(Unit.active == False).all()
        for unit in units:
            unit.legacy = True
            if unit.status == UnitStatus.INACTIVE:
                unit.status = UnitStatus.LEGACY
            logger.debug(f"Unit {unit.name} has been set to legacy")

        await interaction.response.send_message(f"Unit type {name} removed", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="deactivate_unit", description="Deactivate a unit")
    @ac.describe(callsign="The callsign of the unit to deactivate")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def deactivate_unit(self, interaction: Interaction, callsign: str, session: Session):
        # filter on the callsign
        unit = session.query(Unit).filter(Unit.callsign == callsign).first()
        if not unit:
            await interaction.response.send_message("Unit not found", ephemeral=self.bot.use_ephemeral)
            return
        unit.active = False
        unit.status = UnitStatus.INACTIVE if unit.status == UnitStatus.ACTIVE else unit.status
        unit.callsign = None
        await interaction.response.send_message(f"Unit {unit.name} deactivated", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="change_callsign", description="Change the callsign of a unit")
    @ac.describe(old_callsign="The callsign of the unit to change")
    @ac.describe(new_callsign="The new callsign for the unit")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def change_callsign(self, interaction: Interaction, old_callsign: str, new_callsign: str, session: Session):
        # change the callsign of the unit
        unit = session.query(Unit).filter(Unit.callsign == old_callsign).first()
        if not unit:
            await interaction.response.send_message("Unit not found", ephemeral=self.bot.use_ephemeral)
            return
        # check length
        if len(new_callsign) > 15:
            await interaction.response.send_message("Callsign is too long, please use a shorter callsign", ephemeral=self.bot.use_ephemeral)
            return
        # check if the callsign is already taken
        if session.query(Unit).filter(Unit.callsign == new_callsign).first():
            await interaction.response.send_message("Callsign is already taken", ephemeral=self.bot.use_ephemeral)
            return
        unit.callsign = new_callsign
        await interaction.response.send_message(f"Unit {unit.name} callsign changed to {new_callsign}", ephemeral=self.bot.use_ephemeral)

    @ac.command(name="change_status", description="Change the status of a unit")
    @ac.describe(player="The player whose unit you want to change the status of")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def change_status(self, interaction: Interaction, player: Member, session: Session):
        # create a view with a select menu for all of the player's units
        # when a unit is selected, create a view with the status options, if the status is changed to legacy, set the legacy flag, it it's changed to active, prompt for a callsign
        class UnitSelect(ui.Select):
            def __init__(self, player: Player):
                player_units = session.query(Unit).filter(Unit.player_id == player.id).all()
                options = [SelectOption(label=unit.name, value=unit.id) for unit in player_units]
                super().__init__(placeholder="Select name of unit you want to change the status of", options=options)

            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def callback(self, interaction: Interaction, session: Session):
                status_view = ui.View()
                unit = session.query(Unit).filter(Unit.id == self.values[0]).first()
                status_view.add_item(StatusSelect(unit))
                await interaction.response.send_message("Please select the new status for the unit", view=status_view, ephemeral=self.bot.use_ephemeral)

        class StatusSelect(ui.Select):
            def __init__(self, unit: Unit):
                self.unit = unit
                options = [SelectOption(label=status.value, value=status.value, default=unit.status == status) for status in UnitStatus]
                super().__init__(placeholder="Select the new status for the unit", options=options)

            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def callback(self, interaction: Interaction, session: Session):
                # if the new status is active, create a modal for the callsign, if it's either active or legacy, set the appropriate flag, if it's inactive, kia, or mia, just set the status and commit
                self.unit = session.merge(self.unit)
                new_status = UnitStatus(self.values[0])
                if new_status == UnitStatus.ACTIVE:
                    modal = ui.Modal(title="Enter the callsign for the unit", custom_id="change_callsign", components=[ui.InputText(label="New callsign", custom_id="new_callsign")])
                    modal.callback = self.change_callsign_callback
                    await interaction.response.send_modal(modal)
                elif new_status == UnitStatus.LEGACY:
                    self.unit.legacy = True
                    self.unit.status = UnitStatus.LEGACY
                else:
                    self.unit.status = new_status
                await interaction.response.send_message(f"Unit {self.unit.name} status changed to {new_status.value}", ephemeral=self.bot.use_ephemeral)

            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def change_callsign_callback(self, interaction: Interaction, session: Session):
                self.unit = session.merge(self.unit)
                new_callsign = interaction.data["components"][0]["components"][0]["value"]
                self.unit.callsign = new_callsign
                self.unit.active = True
                self.unit.status = UnitStatus.ACTIVE
                await interaction.response.send_message(f"Unit {self.unit.name} activated with callsign {new_callsign}", ephemeral=CustomClient().use_ephemeral)

        view = ui.View()
        view.add_item(UnitSelect(player))
        await interaction.response.send_message("Please select the unit you want to change the status of", view=view, ephemeral=CustomClient().use_ephemeral)

    @ac.command(name="edit_company", description="Edit a player's company")
    @ac.describe(player="The player to edit the company of")
    @uses_db(sessionmaker=CustomClient().sessionmaker)
    async def edit_company(self, interaction: Interaction, player: Member, session: Session):
        """
        Edit a player's company.
        """
        class EditCompanyModal(ui.Modal):
            def __init__(self, _player):
                super().__init__(title="Edit the player's Meta Campaign company")
                self.player = _player
                self.bot = CustomClient()
                self.add_item(ui.TextInput(label="Name", placeholder="Enter the company name", required=True, max_length=32, default=_player.name))
                self.add_item(ui.TextInput(label="Lore", placeholder="Enter the company lore", max_length=1000, style=TextStyle.paragraph, default=_player.lore or ""))

            @uses_db(sessionmaker=CustomClient().sessionmaker)
            async def on_submit(self, interaction: Interaction, session: Session):
                self.player = session.merge(self.player)
                if any(char in child.value for child in self.children for char in os.getenv("BANNED_CHARS", "")):
                    await interaction.response.send_message("Invalid input: values cannot contain discord tags or headers", ephemeral=CustomClient().use_ephemeral)
                    return
                if 0 < len(self.children[0].value) > 32:
                    await interaction.response.send_message("Name must be between 1 and 32 characters", ephemeral=self.bot.use_ephemeral)
                    return
                if len(self.children[1].value) > 1000:
                    await interaction.response.send_message("Lore must be less than 1000 characters", ephemeral=self.bot.use_ephemeral)
                    return
                if has_invalid_url(self.children[1].value):
                    await interaction.response.send_message("Lore cannot contain invalid URLs", ephemeral=self.bot.use_ephemeral)
                    return
                self.player.name = self.children[0].value
                self.player.lore = self.children[1].value
                await interaction.response.send_message("Company updated", ephemeral=self.bot.use_ephemeral)

        player = session.query(Player).filter(Player.discord_id == player.id).first()
        if not player:
            logger.debug(f"User {player.display_name} does not have a Meta Campaign company and an admin is trying to edit it")
            await interaction.response.send_message("The player doesn't have a Meta Campaign company", ephemeral=CustomClient().use_ephemeral)
            return

        modal = EditCompanyModal(player)
        await interaction.response.send_modal(modal)


bot: Bot = None
async def setup(_bot: Bot):
    """
    Registers the Admin cog with the bot.

    Args:
        _bot (Bot): The bot instance to register the cog to.
    """
    global bot
    bot = _bot
    logger.info("Setting up Admin cog")
    await bot.add_cog(Admin(bot))
    await bot.tree.sync()

async def teardown():
    """
    Unregisters the Admin cog, removing all related commands.
    """
    logger.info("Tearing down Admin cog")
    bot.remove_cog(Admin.__name__) # remove_cog takes a string, not a class
