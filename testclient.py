import discord
from discord import Interaction
from discord.ext import commands
from dotenv import load_dotenv
from utils import EnvironHelpers

load_dotenv("sensitive.env")

class TestClient(commands.Bot):
    def __init__(self, *args, **kwargs):
        intents = discord.Intents.default()
        #intents.members = True  # Enable member intents if needed
        super().__init__(intents=intents, command_prefix="!", *args, **kwargs)

    async def setup_hook(self):
        # Register a simple test command
        @self.tree.command(name="test", description="A simple test command")
        async def test_command(interaction: discord.Interaction):
            await interaction.response.send_message("Test command executed successfully!", ephemeral=True)

        # Member Context Menu Options
        @self.tree.context_menu(name="Member: Regular Message")
        async def member_regular(interaction: Interaction, member: discord.Member):
            await interaction.response.send_message(f"Hello, {member.display_name}!")

        @self.tree.context_menu(name="Member: Ephemeral Message")
        async def member_ephemeral(interaction: Interaction, member: discord.Member):
            await interaction.response.send_message(f"This is a secret message for {member.display_name}.", ephemeral=True)

        @self.tree.context_menu(name="Member: Ephemeral View")
        async def member_ephemeral_view(interaction: Interaction, member: discord.Member):
            view = EphemeralView()
            await interaction.response.send_message("This message has a button!", view=view, ephemeral=True)

        @self.tree.context_menu(name="Member: Ephemeral Embed")
        async def member_ephemeral_embed(interaction: Interaction, member: discord.Member):
            embed = discord.Embed(title="Member Info", description=f"Name: {member.display_name}", color=discord.Color.blue())
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @self.tree.context_menu(name="Member: Modal")
        async def member_modal(interaction: Interaction, member: discord.Member):
            await interaction.response.send_modal(CustomModal())

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

# Example of running the test bot
if __name__ == "__main__":
    bot = TestClient()
    bot.run(EnvironHelpers.required_str("BOT_TOKEN"))