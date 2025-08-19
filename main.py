#!/usr/bin/env python3
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
import sys
import os
from coloredformatter import ColoredFormatter
import stat

# Environ setup
if not os.path.exists("global.env"):
    raise FileNotFoundError("global.env not found")
load_dotenv("global.env")
LOCAL_ENV_FILE = os.getenv("LOCAL_ENV_FILE")
if not os.path.exists(str(LOCAL_ENV_FILE)):
    # touch the file
    open(str(LOCAL_ENV_FILE), "w").close()
load_dotenv(LOCAL_ENV_FILE, override=True)

# check that secrets aren't set prematurely
if os.getenv("BOT_TOKEN"):
    raise EnvironmentError("BOT_TOKEN set in global or local environment file, please move it to the sensitive environment file")
if os.getenv("DATABASE_URL"):
    raise EnvironmentError("DATABASE_URL set in global or local environment file, please move it to the sensitive environment file")
if os.getenv("MYSQL_PASSWORD"):
    raise EnvironmentError("MYSQL_PASSWORD set in global or local environment file, please move it to the sensitive environment file")

SENSITIVE_ENV_FILE = os.getenv("SENSITIVE_ENV_FILE")
if not os.path.exists(str(SENSITIVE_ENV_FILE)):
    # create the file with the required variables
    with os.fdopen(os.open(str(SENSITIVE_ENV_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_EXCL, 0o600), "w") as f:
        f.write("BOT_TOKEN='TOKEN'\n")
        f.write("DATABASE_URL='URL'\n")
        f.write("MYSQL_PASSWORD='PASSWORD'\n")
    raise FileNotFoundError("SENSITIVE_ENV_FILE wasn't found so a new one was created, please fill it in")

# Check file permissions - should be 0o600 (owner read/write only)
if os.name != 'nt':  # Skip on Windows
    file_stat = os.stat(str(SENSITIVE_ENV_FILE))
    if file_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO) != 0:
        raise EnvironmentError(f"SENSITIVE_ENV_FILE has insecure permissions: {oct(file_stat.st_mode & 0o777)}. File should not have group or world permissions")
    if os.path.islink(str(SENSITIVE_ENV_FILE)):
        raise EnvironmentError(f"SENSITIVE_ENV_FILE is a symlink, please remove it")
    if os.path.isdir(str(SENSITIVE_ENV_FILE)):
        raise EnvironmentError(f"SENSITIVE_ENV_FILE is a directory, please remove it")

load_dotenv(SENSITIVE_ENV_FILE, override=True)
if not os.getenv("BOT_TOKEN") or os.getenv("BOT_TOKEN") == "TOKEN":
    raise EnvironmentError("BOT_TOKEN is not set")
if not os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL") == "URL":
    raise EnvironmentError("DATABASE_URL is not set")

import re
def human_size_to_bytes(size_str):
    """
    Convert a human-readable file size string into bytes.

    This function takes a string representing a file size with units such as 
    'KB', 'MB', 'GB', etc., and converts it into an integer representing the 
    size in bytes. It supports both decimal (e.g., 'KB') and binary (e.g., 'KiB') 
    prefixes.

    Parameters:
    size_str (str): A string representing the file size, e.g., '10 MB', '5.5 GiB'.

    Returns:
    int: The size in bytes.

    Raises:
    ValueError: If the input string is not a valid size format.

    Example:
    >>> human_size_to_bytes('10 MB')
    10000000
    >>> human_size_to_bytes('5.5 GiB')
    5905580032
    """
    sizes = {
        "b": 1,
        "kb": 1000, "kib": 1024,
        "mb": 1000**2, "mib": 1024**2,
        "gb": 1000**3, "gib": 1024**3,
        "tb": 1000**4, "tib": 1024**4,
        "pb": 1000**5, "pib": 1024**5,
        "eb": 1000**6, "eib": 1024**6,
        "zb": 1000**7, "zib": 1024**7,
        "yb": 1000**8, "yib": 1024**8,
    }
    pattern = r"^(\d+(\.\d+)?)\s*([kmgtpezy]?i?b)?$"
    size_str = size_str.strip().replace(" ", "").replace("_", "").replace(",", "").lower()
    match = re.match(pattern, size_str)
    if not match:
        raise ValueError(f"Invalid size string: {size_str}")
    value, _, unit = match.groups()
    unit = unit or "b" # default to bytes if no unit is provided
    value = float(value)
    return int(value * sizes[unit])

# add a file handler to the root logger
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(ColoredFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
file_handler = RotatingFileHandler(str(os.getenv("LOG_FILE")), 
                                   maxBytes=human_size_to_bytes(os.getenv("LOG_FILE_SIZE")), 
                                   backupCount=int(os.getenv("LOG_FILE_BACKUP_COUNT", 5)))
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.basicConfig(level=logging.getLevelName(os.getenv("LOG_LEVEL", "INFO")),
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        file_handler,
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
logging.Logger.triage = triage  # type: ignore

logger = logging.getLogger(__name__)



# create a DB engine
engine = create_engine(
    url = str(os.getenv("DATABASE_URL")),
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