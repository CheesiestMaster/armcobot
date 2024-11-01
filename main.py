import logging
import sys
# add a file handler to the root logger
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("armco.log"),
                        logging.StreamHandler(sys.stdout)
                    ],
                    force=True) # needed to delete the default stderr handler
# rest of the imports
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base
from dotenv import load_dotenv
import os
from customclient import CustomClient
import asyncio

logger = logging.getLogger(__name__)

load_dotenv()

# delete the database
""" try:
    os.remove("armco.db")
    logger.debug("Database file 'armco.db' removed successfully.")
except Exception as e:
    logger.error("Failed to remove 'armco.db': %s", e) """

# create a DB engine
engine = create_engine(os.getenv("DATABASE_URL"))
logger.debug("Database engine created with URL: %s", os.getenv("DATABASE_URL"))

# create the tables
Base.metadata.create_all(bind=engine)
logger.info("Database tables created successfully.")

# create a session
Session = sessionmaker(bind=engine)
session = Session()
logger.debug("Session created successfully.")

# create the bot
bot = CustomClient(session)
logger.info("Bot created successfully.")

# start the bot
logger.info("starting bot")
asyncio.run(bot.start())
logger.info("Bot terminated")

# close the session
session.commit()
session.close()
logger.info("Session closed successfully.")