import discord
from discord import app_commands, Interaction, Member, TextChannel
from discord.ext import commands
from os import getenv
from dotenv import load_dotenv

load_dotenv("sensitive.env")

class TestClient(commands.Bot):
    def __init__(self, *args, **kwargs):
        intents = discord.Intents.default()
        #intents.members = True  # Enable member intents if needed
        super().__init__(intents=intents, *args, **kwargs)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Register a simple test command
        @self.tree.command(name="test", description="A simple test command")
        async def test_command(interaction: discord.Interaction):
            await interaction.response.send_message("Test command executed successfully!", ephemeral=True)

        self.add_cog(TestingCommands(self))
        # Sync commands with Discord
        await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user}")

class EphemeralView(discord.ui.View):
    @discord.ui.button(label="Click Me!", style=discord.ButtonStyle.primary)
    async def button_click(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.send_message("You clicked the button!", ephemeral=True)

class CustomModal(discord.ui.Modal, title="Test Modal"):
    response = discord.ui.TextInput(label="Input something", placeholder="Type here...")

    async def on_submit(self, interaction: Interaction):
        await interaction.response.send_message(f"You submitted: {self.response.value}", ephemeral=True)

class TestingCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Member Context Menu Options
    @app_commands.context_menu(name="Member: Regular Message")
    async def member_regular(self, interaction: Interaction, member: discord.Member):
        await interaction.response.send_message(f"Hello, {member.display_name}!")

    @app_commands.context_menu(name="Member: Ephemeral Message")
    async def member_ephemeral(self, interaction: Interaction, member: discord.Member):
        await interaction.response.send_message(f"This is a secret message for {member.display_name}.", ephemeral=True)

    @app_commands.context_menu(name="Member: Ephemeral View")
    async def member_ephemeral_view(self, interaction: Interaction, member: discord.Member):
        view = EphemeralView()
        await interaction.response.send_message("This message has a button!", view=view, ephemeral=True)

    @app_commands.context_menu(name="Member: Ephemeral Embed")
    async def member_ephemeral_embed(self, interaction: Interaction, member: discord.Member):
        embed = discord.Embed(title="Member Info", description=f"Name: {member.display_name}", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.context_menu(name="Member: Modal")
    async def member_modal(self, interaction: Interaction, member: discord.Member):
        await interaction.response.send_modal(CustomModal())

    # TextChannel Context Menu Options
    @app_commands.context_menu(name="Channel: Regular Message")
    async def channel_regular(self, interaction: Interaction, channel: discord.TextChannel):
        await interaction.response.send_message(f"Hello, this is {channel.name}!")

    @app_commands.context_menu(name="Channel: Ephemeral Message")
    async def channel_ephemeral(self, interaction: Interaction, channel: discord.TextChannel):
        await interaction.response.send_message(f"This is a secret message about {channel.name}.", ephemeral=True)

    @app_commands.context_menu(name="Channel: Ephemeral View")
    async def channel_ephemeral_view(self, interaction: Interaction, channel: discord.TextChannel):
        view = EphemeralView()
        await interaction.response.send_message("This message has a button!", view=view, ephemeral=True)

    @app_commands.context_menu(name="Channel: Ephemeral Embed")
    async def channel_ephemeral_embed(self, interaction: Interaction, channel: discord.TextChannel):
        embed = discord.Embed(title="Channel Info", description=f"Name: {channel.name}", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.context_menu(name="Channel: Modal")
    async def channel_modal(self, interaction: Interaction, channel: discord.TextChannel):
        await interaction.response.send_modal(CustomModal())

    # Slash Commands
    @app_commands.command(name="member_regular_message")
    async def slash_member_regular(self, interaction: Interaction, member: discord.Member):
        await interaction.response.send_message(f"Hello, {member.display_name}!")

    @app_commands.command(name="member_ephemeral_message")
    async def slash_member_ephemeral(self, interaction: Interaction, member: discord.Member):
        await interaction.response.send_message(f"This is a secret message for {member.display_name}.", ephemeral=True)

    @app_commands.command(name="member_ephemeral_view")
    async def slash_member_ephemeral_view(self, interaction: Interaction, member: discord.Member):
        view = EphemeralView()
        await interaction.response.send_message("This message has a button!", view=view, ephemeral=True)

    @app_commands.command(name="member_ephemeral_embed")
    async def slash_member_ephemeral_embed(self, interaction: Interaction, member: discord.Member):
        embed = discord.Embed(title="Member Info", description=f"Name: {member.display_name}", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="member_modal")
    async def slash_member_modal(self, interaction: Interaction):
        await interaction.response.send_modal(CustomModal())

    @app_commands.command(name="channel_regular_message")
    async def slash_channel_regular(self, interaction: Interaction, channel: discord.TextChannel):
        await interaction.response.send_message(f"Hello, this is {channel.name}!")

    @app_commands.command(name="channel_ephemeral_message")
    async def slash_channel_ephemeral(self, interaction: Interaction, channel: discord.TextChannel):
        await interaction.response.send_message(f"This is a secret message about {channel.name}.", ephemeral=True)

    @app_commands.command(name="channel_ephemeral_view")
    async def slash_channel_ephemeral_view(self, interaction: Interaction, channel: discord.TextChannel):
        view = EphemeralView()
        await interaction.response.send_message("This message has a button!", view=view, ephemeral=True)

    @app_commands.command(name="channel_ephemeral_embed")
    async def slash_channel_ephemeral_embed(self, interaction: Interaction, channel: discord.TextChannel):
        embed = discord.Embed(title="Channel Info", description=f"Name: {channel.name}", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="channel_modal")
    async def slash_channel_modal(self, interaction: Interaction):
        await interaction.response.send_modal(CustomModal())


# Example of running the test bot
if __name__ == "__main__":
    bot = TestClient()
    bot.run(getenv("BOT_TOKEN"))