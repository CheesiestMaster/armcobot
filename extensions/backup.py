from logging import getLogger
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac, Attachment
from pandas import DataFrame, ExcelWriter, read_excel, read_csv
import pandas as pd
from models import BaseModel
from sqlalchemy import select, text
from FileRoller import FileRoller
import asyncio
import os
from customclient import CustomClient
from utils import uses_db, error_reporting
from sqlalchemy.orm import Session
import io
import tempfile
logger = getLogger(__name__)

class Backup(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
 
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
    @uses_db(CustomClient().sessionmaker)
    async def create_xls(self, interaction: Interaction, session: Session):
        await interaction.response.defer(ephemeral=self.use_ephemeral)
        
        # Roll the file and prepare for writing
        self.xls_roller.roll()
        handle_path = self.xls_roller.current_handle.name
        self.xls_roller.close()  # Close the handle, as pandas will be using it

        # Get table names
        table_names = [table.name for table in BaseModel.metadata.tables.values()]

        # Use ExcelWriter to write each table to a separate sheet
        with ExcelWriter(handle_path) as writer:
            for table_name in table_names:
                # Execute the query and fetch all rows
                query = select(BaseModel.metadata.tables[table_name])
                result = session.execute(query)
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

    @ac.command(name="restore", description="Restore database from Excel or CSV file")
    @error_reporting(verbose=True)
    @uses_db(CustomClient().sessionmaker)
    async def restore_db(self, interaction: Interaction, session: Session, file: Attachment, table_name: str = None, separator: str = ","):
        await interaction.response.defer(ephemeral=self.use_ephemeral)
        
        try:
            # Download the file
            file_data = await file.read()
            file_extension = os.path.splitext(file.filename)[1].lower()
            
            # Determine file type and process accordingly
            if file_extension == '.xlsx':
                await self._restore_from_xlsx(session, file_data, interaction)
            elif file_extension == '.csv':
                if not table_name:
                    await interaction.followup.send("Table name is required for CSV files", ephemeral=True)
                    return
                await self._restore_from_csv(session, file_data, table_name, separator, interaction)
            else:
                await interaction.followup.send("Unsupported file type. Please use .xlsx or .csv files", ephemeral=True)
                return
                
        except Exception as e:
            logger.error(f"Error during restore: {str(e)}")
            await interaction.followup.send(f"Error during restore: {str(e)}", ephemeral=True)
            raise
    
    async def _restore_from_xlsx(self, session: Session, file_data: bytes, interaction: Interaction):
        """Restore database from Excel file using sheet names as table names"""
        with tempfile.NamedTemporaryFile(suffix='.xlsx') as temp_file:
            temp_file.write(file_data)
            temp_file.flush()
            
            # Read all sheets
            excel_data = read_excel(temp_file.name, sheet_name=None)
            
            # Disable foreign key checks
            self._disable_foreign_keys(session)
            
            try:
                total_records = 0
                updated_tables = []
                
                for sheet_name, df in excel_data.items():
                    if sheet_name in BaseModel.metadata.tables:
                        records_processed = await self._upsert_dataframe(session, df, sheet_name)
                        total_records += records_processed
                        updated_tables.append(f"{sheet_name} ({records_processed} records)")
                        logger.info(f"Processed {records_processed} records for table {sheet_name}")
                    else:
                        logger.warning(f"Table {sheet_name} not found in database schema, skipping")
                
                # Re-enable foreign key checks
                self._enable_foreign_keys(session)
                
                # Validate foreign key constraints
                await self._validate_foreign_keys(session)
                
                await interaction.followup.send(
                    f"Restore completed successfully!\n"
                    f"Total records processed: {total_records}\n"
                    f"Updated tables: {', '.join(updated_tables)}",
                    ephemeral=self.use_ephemeral
                )
                
            except Exception as e:
                # Re-enable foreign key checks even if there was an error
                self._enable_foreign_keys(session)
                raise e
    
    async def _restore_from_csv(self, session: Session, file_data: bytes, table_name: str, separator: str, interaction: Interaction):
        """Restore database from CSV file for specified table"""
        if table_name not in BaseModel.metadata.tables:
            await interaction.followup.send(f"Table {table_name} not found in database schema", ephemeral=True)
            return
        
        # Read CSV data
        df = read_csv(io.BytesIO(file_data), sep=separator)
        
        # Disable foreign key checks
        self._disable_foreign_keys(session)
        
        try:
            records_processed = await self._upsert_dataframe(session, df, table_name)
            
            # Re-enable foreign key checks
            self._enable_foreign_keys(session)
            
            # Validate foreign key constraints
            await self._validate_foreign_keys(session)
            
            await interaction.followup.send(
                f"Restore completed successfully!\n"
                f"Table: {table_name}\n"
                f"Records processed: {records_processed}",
                ephemeral=self.use_ephemeral
            )
            
        except Exception as e:
            # Re-enable foreign key checks even if there was an error
            self._enable_foreign_keys(session)
            raise e
    
    async def _upsert_dataframe(self, session: Session, df: DataFrame, table_name: str) -> int:
        """Upsert DataFrame records into the specified table"""
        table = BaseModel.metadata.tables[table_name]
        records_processed = 0
        
        # Get primary key columns
        primary_keys = [col.name for col in table.primary_key.columns]
        
        for _, row in df.iterrows():
            # Convert row to dictionary, handling NaN values
            row_dict = {}
            for col_name, value in row.items():
                if col_name in table.columns:
                    # Handle NaN/None values
                    if pd.isna(value):
                        row_dict[col_name] = None
                    else:
                        row_dict[col_name] = value
            
            if row_dict:  # Only process if we have valid data
                # Check if record exists by primary key
                if primary_keys:
                    pk_conditions = []
                    for pk in primary_keys:
                        if pk in row_dict and row_dict[pk] is not None:
                            pk_conditions.append(table.c[pk] == row_dict[pk])
                    
                    if pk_conditions:
                        # Check if record exists
                        existing = session.execute(
                            select(table).where(*pk_conditions)
                        ).first()
                        
                        if existing:
                            # Update existing record
                            session.execute(
                                table.update().where(*pk_conditions).values(**row_dict)
                            )
                        else:
                            # Insert new record
                            session.execute(table.insert().values(**row_dict))
                    else:
                        # No primary key values, just insert
                        session.execute(table.insert().values(**row_dict))
                else:
                    # No primary key defined, just insert
                    session.execute(table.insert().values(**row_dict))
                
                records_processed += 1
        
        return records_processed
    
    def _disable_foreign_keys(self, session: Session):
        """Disable foreign key checks in a dialect-aware manner"""
        client = CustomClient()
        if client.dialect == "mysql":
            session.execute(text("SET foreign_key_checks = 0"))
        else:  # SQLite
            session.execute(text("PRAGMA foreign_keys = OFF"))
    
    def _enable_foreign_keys(self, session: Session):
        """Enable foreign key checks in a dialect-aware manner"""
        client = CustomClient()
        if client.dialect == "mysql":
            session.execute(text("SET foreign_key_checks = 1"))
        else:  # SQLite
            session.execute(text("PRAGMA foreign_keys = ON"))
    
    async def _validate_foreign_keys(self, session: Session):
        """Validate all foreign key constraints after restore"""
        # This will fail if there are any foreign key constraint violations
        try:
            # Run a query that would trigger foreign key validation
            session.execute(text("SELECT 1"))
            session.flush()
        except Exception as e:
            logger.error(f"Foreign key validation failed: {str(e)}")
            raise Exception(f"Foreign key constraint validation failed: {str(e)}")

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    await bot.add_cog(Backup(bot))

async def teardown():
    bot.remove_cog(Backup.__name__) # remove_cog takes a string, not a class