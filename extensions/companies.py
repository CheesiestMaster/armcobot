import asyncio
from logging import getLogger

from discord import ButtonStyle, Interaction, app_commands as ac, ui, TextStyle, Member, User
from discord.ext.commands import GroupCog
from sqlalchemy.orm import Session
import templates as tmpl

from customclient import CustomClient
from models import Player, Unit, UnitStatus
from utils import RecordingLayoutView, RecordingModal, has_invalid_url, uses_db, EnvironHelpers, error_reporting

logger = getLogger(__name__)

class Company(GroupCog, description="Meta Campaign company: create, edit, show, refresh."):
    """
    Cog for the company slash command: create a new Meta Campaign company
    (player record). Used when a user first joins the system.
    """

    def __init__(self, bot: CustomClient):
        """Store a reference to the bot instance."""

        self.bot = bot

    @ac.command(name="create", description="Create a new Meta Campaign company")
    @error_reporting()
    @uses_db(CustomClient().sessionmaker)
    async def create(self, interaction: Interaction, session: Session):
        logger = getLogger(f"{__name__}.create")
        # check if the user already has a company
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if player:
            logger.debug(f"User {interaction.user.display_name} already has a Meta Campaign company")
            await interaction.response.send_message(tmpl.already_have_company, ephemeral=self.bot.use_ephemeral)
            return

        # create a new Player in the database
        player = Player(discord_id=interaction.user.id, name=interaction.user.name, rec_points=EnvironHelpers.required_int("INITIAL_REQ"))
        session.add(player)
        session.commit() # flush to get the player id
        await asyncio.sleep(0.1) # we need an awaitable here so the consumer can act on the new player
        stockpile = Unit(name="Stockpile", player_id=player.id, status=UnitStatus.INACTIVE, unit_type="STOCKPILE")
        session.add(stockpile)
        logger.debug(f"User {interaction.user.display_name} created a new Meta Campaign company")
        await interaction.response.send_message(tmpl.joined_meta_campaign, ephemeral=self.bot.use_ephemeral)
        self.bot.queue.put_nowait((0, player, 0)) # this is the only one that gets a 0, all others are 1

    @ac.command(name="edit", description="Edit your Meta Campaign company")
    @uses_db(CustomClient().sessionmaker)
    async def edit(self, interaction: Interaction, session: Session):
        await self._send_menu(interaction, session)

    @ac.command(name="show", description="Displays a Players Meta Campaign company")
    @ac.describe(member="The players Meta Campaign company to show")
    @uses_db(CustomClient().sessionmaker)
    async def show(self, interaction: Interaction, session: Session, member: Member|User|None=None):
        if member is None:
            await self._send_menu(interaction, session)
            return

        player = session.query(Player).filter(Player.discord_id == member.id).first()
        if not player:
            await interaction.response.send_message(tmpl.member_no_company.format(member=member), ephemeral=CustomClient().use_ephemeral)
            return

        unit_display = await self.bot.generate_unit_message(player=player)
        await interaction.response.send_message(
            view=CompanyPublicLayoutView(player, unit_display),
            ephemeral=self.bot.use_ephemeral,
        )

    @ac.command(name="menu", description="Show the menu")
    @uses_db(CustomClient().sessionmaker)
    async def menu(self, interaction: Interaction, session: Session):
        await self._send_menu(interaction, session)

    async def _send_menu(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.discord_id == interaction.user.id).first()
        if not player:
            await interaction.response.send_message(
                view=CompanyMissingLayoutView(interaction.user.id),
                ephemeral=True,
            )
            return
        unit_display = await self.bot.generate_unit_message(player=player)
        await interaction.response.send_message(
            view=CompanyInfoLayoutView(
                bot=self.bot,
                player=player,
                owner_id=interaction.user.id,
                unit_display=unit_display,
            ),
            ephemeral=True,
        )


class AuthorizedCompanyLayoutView(RecordingLayoutView):
    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id

    @error_reporting(True)
    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("You are not the owner of this menu", ephemeral=True)
            return False
        return True


class CompanyMissingLayoutView(AuthorizedCompanyLayoutView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(ui.Container(
            ui.TextDisplay(content=f"## Company\n{tmpl.no_meta_campaign_company}"),
            ui.TextDisplay(content="Use `/company create` to create one."),
        ))


class CompanyPublicLayoutView(RecordingLayoutView):
    def __init__(self, player: Player, unit_display: ui.Container):
        super().__init__(timeout=None)
        self.add_item(ui.Container(
            ui.TextDisplay(content=f"# {player.name}"),
            ui.TextDisplay(content=player.lore or "*No company lore has been set.*"),
            ui.TextDisplay(content=(
                f"**{tmpl.MAIN_CURRENCY}:** {player.rec_points}\n"
                f"**{tmpl.SECONDARY_CURRENCY}:** {player.bonus_pay}"
            )),
        ))
        self.add_item(unit_display)


class CompanyInfoLayoutView(AuthorizedCompanyLayoutView):
    def __init__(
        self,
        bot: CustomClient,
        player: Player,
        owner_id: int,
        unit_display: ui.Container,
    ):
        super().__init__(owner_id)
        self.bot = bot
        self.player_id = player.id
        company_display = ui.Container(
            ui.TextDisplay(content=f"# {player.name}"),
            ui.TextDisplay(content=player.lore or "*No company lore has been set.*"),
            ui.TextDisplay(
                content=(
                    f"**{tmpl.MAIN_CURRENCY}:** {player.rec_points}\n"
                    f"**{tmpl.SECONDARY_CURRENCY}:** {player.bonus_pay}"
                )
            ),
        )
        edit_button = ui.Button(label="Edit Company", style=ButtonStyle.primary)
        edit_button.callback = self.edit_button_callback
        refresh_button = ui.Button(label="Refresh", style=ButtonStyle.secondary)
        refresh_button.callback = self.refresh_button_callback
        self.add_item(company_display)
        self.add_item(unit_display)
        self.add_item(ui.ActionRow(edit_button, refresh_button))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def edit_button_callback(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.id == self.player_id).first()
        if not player:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=True)
            return
        await interaction.response.send_modal(CompanyEditModal(self.bot, player))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def refresh_button_callback(self, interaction: Interaction, session: Session):
        player = session.query(Player).filter(Player.id == self.player_id).first()
        if not player:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=True)
            return
        unit_display = await self.bot.generate_unit_message(player=player)
        await interaction.response.edit_message(
            view=CompanyInfoLayoutView(
                bot=self.bot,
                player=player,
                owner_id=self.owner_id,
                unit_display=unit_display,
            )
        )


class CompanyEditModal(RecordingModal):
    def __init__(self, bot: CustomClient, player: Player):
        super().__init__(title="Edit your Meta Campaign company")
        self.bot = bot
        self.player_id = player.id
        self.add_item(ui.TextInput(
            label="Name",
            placeholder="Enter the company name",
            required=True,
            max_length=32,
            default=player.name,
        ))
        self.add_item(ui.TextInput(
            label="Lore",
            placeholder="Enter the company lore",
            max_length=1000,
            style=TextStyle.paragraph,
            default=player.lore or "",
            required=False,
        ))

    @error_reporting(True)
    @uses_db(CustomClient().sessionmaker)
    async def on_submit(self, interaction: Interaction, session: Session):
        name = self.children[0].value
        lore = self.children[1].value
        if any(char in child.value for child in self.children for char in EnvironHelpers.get_str("BANNED_CHARS", "")):
            await interaction.response.send_message(tmpl.invalid_input, ephemeral=True)
            return
        if not 0 < len(name) <= 32:
            await interaction.response.send_message(tmpl.company_name_length, ephemeral=True)
            return
        if len(lore) > 1000:
            await interaction.response.send_message(tmpl.company_lore_length, ephemeral=True)
            return
        if has_invalid_url(lore):
            await interaction.response.send_message(tmpl.company_lore_urls, ephemeral=True)
            return

        player = session.query(Player).filter(Player.id == self.player_id).first()
        if not player:
            await interaction.response.send_message(tmpl.no_meta_campaign_company, ephemeral=True)
            return
        player.name = name
        player.lore = lore
        session.flush()
        unit_display = await self.bot.generate_unit_message(player=player)
        await interaction.response.edit_message(
            view=CompanyInfoLayoutView(
                bot=self.bot,
                player=player,
                owner_id=interaction.user.id,
                unit_display=unit_display,
            )
        )
        self.bot.queue.put_nowait((1, player, 0))
async def setup(_bot: CustomClient):
    logger.info("Setting up Company cog")
    await _bot.add_cog(Company(_bot))


async def teardown(_bot: CustomClient):
    logger.info("Tearing down Company cog")
    await _bot.remove_cog(Company.__name__)  # remove_cog takes a string, not a class