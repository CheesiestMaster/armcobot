import discord
from discord import app_commands
from os import getenv
from dotenv import load_dotenv

load_dotenv()

class TestClient(discord.Client):
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

        # Sync commands with Discord
        await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user}")

# Example of running the test bot
if __name__ == "__main__":
    bot = TestClient()
    bot.run(getenv("BOT_TOKEN"))