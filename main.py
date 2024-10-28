from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, Unit, Player, Upgrade, UnitType, UpgradeType
from dotenv import load_dotenv
import os
from customclient import CustomClient
import asyncio

load_dotenv()

# delete the database
try:
    os.remove("armco.db")
except Exception:
    pass

# create a DB engine
engine = create_engine(os.getenv("DATABASE_URL"))

# create the tables
Base.metadata.create_all(bind=engine)

# create a session
Session = sessionmaker(bind=engine)
session = Session()

# create the bot
bot = CustomClient(session)

# start the bot
print("starting bot")
asyncio.run(bot.start())

# close the session
session.close()