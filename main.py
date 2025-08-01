#!/usr/bin/env python3
import logging
from dotenv import load_dotenv
import sys
import os

from coloredformatter import ColoredFormatter
if not os.path.exists("global.env"):
    raise FileNotFoundError("global.env not found")
load_dotenv("global.env")
LOCAL_ENV_FILE = os.getenv("LOCAL_ENV_FILE")
if not os.path.exists(LOCAL_ENV_FILE):
    # touch the file
    open(LOCAL_ENV_FILE, "w").close()
load_dotenv(LOCAL_ENV_FILE, override=True)
SENSITIVE_ENV_FILE = os.getenv("SENSITIVE_ENV_FILE")
if not os.path.exists(SENSITIVE_ENV_FILE):
    # create the file with the required variables
    with open(SENSITIVE_ENV_FILE, "w") as f:
        f.write("BOT_TOKEN='TOKEN'\n")
        f.write("DATABASE_URL='URL'\n")
        f.write("MYSQL_PASSWORD='PASSWORD'\n")
    raise FileNotFoundError("SENSITIVE_ENV_FILE wasn't found so a new one was created, please fill it in")

load_dotenv(SENSITIVE_ENV_FILE, override=True)

# add a file handler to the root logger
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(ColoredFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("armco.log"),
                        stream_handler
                    ],
                    force=True) # needed to delete the default stderr handler
# rest of the imports   
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import BaseModel
from customclient import CustomClient
import asyncio
loop = asyncio.get_event_loop()
asyncio.set_event_loop(loop)

logging.addLevelName(9, "TRIAGE")

def triage(self, message, *args, **kwargs):
    if self.isEnabledFor(9):
        self._log(9, message, args, **kwargs)
logging.Logger.triage = triage

logger = logging.getLogger(__name__)



# create a DB engine
engine = create_engine(
    url = os.getenv("DATABASE_URL"),
    pool_pre_ping= True,
    pool_size=10,
    max_overflow=20)

logger.debug("Database engine created with URL: %s", os.getenv("DATABASE_URL"))

# logging.getLogger("sqlalchemy.engine").setLevel(logging.DEBUG)
# logging.getLogger("sqlalchemy.pool").setLevel(logging.DEBUG)
# logging.getLogger("sqlalchemy.orm").setLevel(logging.DEBUG)
# logging.getLogger("sqlalchemy.dialects.mysql").setLevel(logging.DEBUG)

# create the tables
BaseModel.metadata.create_all(bind=engine)
logger.info("Database tables created successfully.")

# create a session
Session = sessionmaker(bind=engine)
session = Session()

session.commit()
logger.info("Upgrade types populated successfully.")
if engine.dialect.name == "mysql":
    session.execute(text("SET SESSION innodb_lock_wait_timeout = 10")) # set the lock timeout to 10 seconds only for the global session

logger.debug("Session created successfully.")

# create the bot
bot = CustomClient(session, sessionmaker=Session, dialect=engine.dialect.name)
logger.info("Bot created successfully.")

# start the bot
logger.info("starting bot")
loop.run_until_complete(bot.start())
logger.info("Bot terminated")

# close the session
session.commit()
session.close()
logger.info("Session closed successfully.")