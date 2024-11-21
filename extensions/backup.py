from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac
from pandas import DataFrame, ExcelWriter
from models import Base
from sqlalchemy import select
from FileRoller import FileRoller
import asyncio
import os
logger = getLogger(__name__)

class Backup(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.session = bot.session
        self.use_ephemeral = bot.use_ephemeral
        self.xls_roller = FileRoller("backup.xlsx", 6)
        self.sql_roller = FileRoller("backup.sql", 2)
        self.interaction_check = self.is_mod

    async def is_mod(self, interaction: Interaction):
        valid = any(interaction.user.get_role(role_id) for role_id in self.bot.mod_roles)
        if not valid:
            logger.warning(f"{interaction.user.global_name} tried to use backup commands")
        return valid

    @ac.command(name="create-xls", description="Create an Excel file with the current state of the database")
    async def create_xls(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=self.use_ephemeral)
        
        # Roll the file and prepare for writing
        self.xls_roller.roll()
        handle_path = self.xls_roller.current_handle.name
        self.xls_roller.close()  # Close the handle, as pandas will be using it

        # Get table names
        table_names = [table.name for table in Base.metadata.tables.values()]

        # Use ExcelWriter to write each table to a separate sheet
        with ExcelWriter(handle_path) as writer:
            for table_name in table_names:
                # Execute the query and fetch all rows
                query = select(Base.metadata.tables[table_name])
                result = self.session.execute(query)
                rows = result.fetchall()

                # Convert rows to DataFrame
                df = DataFrame(rows, columns=result.keys())
                logger.debug(f"Writing table {table_name} with {len(df)} rows")
                df.to_excel(writer, sheet_name=table_name, index=True)

        await interaction.followup.send(f"Excel file created: {handle_path}", ephemeral=self.use_ephemeral)

    @ac.command(name="create-sql", description="Create a mysqldump file with the current state of the database")
    async def create_sql(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=self.use_ephemeral)
        # we need to use subprocess to call mysqldump
        # for all other parameters, we assume localhost and armco as the user and schema
        
        # Roll the file and prepare for writing
        self.sql_roller.roll() 
        # we will use the async subprocess to redirect the output to the handle, so we need to leave it open
        command = ["mysqldump", "-h", "localhost", "-u", "armco", "armco"]
        process = await asyncio.create_subprocess_exec(*command, stdout=self.sql_roller.current_handle, stderr=asyncio.subprocess.PIPE, env={"MYSQL_PWD": os.getenv("MYSQL_PASSWORD")})

        _, stderr = await process.communicate()
        if stderr or process.returncode != 0:
            logger.error(f"Error creating SQL dump: {stderr.decode() if stderr else 'Unknown error'}")
            await interaction.followup.send(f"Error creating SQL dump: {stderr.decode() if stderr else 'Unknown error'}", ephemeral=True)
        else:
            await interaction.followup.send(f"SQL dump created: {self.sql_roller.current_handle.name}", ephemeral=self.use_ephemeral)
        self.sql_roller.close()

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    await bot.add_cog(Backup(bot))

async def teardown():
    bot.remove_cog(Backup.__name__) # remove_cog takes a string, not a class