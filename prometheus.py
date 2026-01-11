from prometheus_client import Gauge
from discord.ext.tasks import loop
from customclient import CustomClient # just needed so we can get a bunch of the stats, and a sessionmaker for the db stats
from datetime import datetime
from sqlalchemy import func
from models import Player, Unit, PlayerUpgrade
from utils import EnvironHelpers
import psutil
import subprocess
import asyncio
from logging import getLogger
logger = getLogger(__name__)

start_time = Gauge("armcobot_start_time", "The start time of the bot")
player_count = Gauge("armcobot_player_count", "The number of users registered with the bot")
rec_points = Gauge("armcobot_rec_points", "The total number of unspent requisition points")
bonus_pay = Gauge("armcobot_bonus_pay", "The total number of unspent bonus pay")
units = Gauge("armcobot_units", "The number of units created")
purchased_units = Gauge("armcobot_purchased_units", "The number of units purchased")
active_units = Gauge("armcobot_active_units", "The number of active units")
dead_units = Gauge("armcobot_dead_units", "The number of dead units")
upgrades = Gauge("armcobot_upgrades", "The number of upgrades purchased")
as_of = Gauge("armcobot_as_of", "The time the metrics were last updated", labelnames=['loop'])
units_by_type = Gauge("armcobot_units_by_type", "The number of units by type", labelnames=['unit_type'])
purchased_by_type = Gauge("armcobot_purchased_by_type", "The number of units purchased by type", labelnames=['unit_type'])
live_by_type = Gauge("armcobot_live_by_type", "The number of units live by type", labelnames=['unit_type'])
units_by_type_and_campaign = Gauge("armcobot_units_by_type_and_campaign", "The number of units by type and campaign", labelnames=['unit_type', 'campaign_id'])
root_disk_usage = Gauge("armcobot_root_disk_usage_percent", "Percent of / disk used")
info = Gauge("armcobot_info", "Information about the bot", labelnames=['commit', 'ahead', 'behind'])

# Disk alert variables
DISK_ALERT_THRESHOLD = 90.0
DISK_ALERT_USER_ID = EnvironHelpers.required_int("BOT_OWNER_ID")
last_disk_alert_time = None
bot: CustomClient = CustomClient()
start_time.set(int(bot.start_time.timestamp()))

# get the commit hash, and current ahead and behind counts
commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], stdout=subprocess.PIPE, text=True).stdout.strip()
behind = int(subprocess.run(["git", "rev-list", "--count", "HEAD..origin/main"], stdout=subprocess.PIPE, text=True).stdout.strip())
ahead = int(subprocess.run(["git", "rev-list", "--count", "origin/main..HEAD"], stdout=subprocess.PIPE, text=True).stdout.strip())
info.labels(commit=commit, ahead=ahead, behind=behind).set(1)

last_alerted_version = None
@loop(seconds=60)
async def poll_metrics_slow():
    global last_disk_alert_time
    bot: CustomClient = CustomClient() # type: ignore
    as_of.labels(loop="slow").set(int(datetime.now().timestamp()))
    # Add disk usage metric for /
    usage = psutil.disk_usage(r'C:\\' if os.name == 'nt' else '/')
    root_disk_usage.set(usage.percent)
    
    # Check disk usage alert
    current_time = datetime.now()
    if usage.percent > DISK_ALERT_THRESHOLD:
        # Only send alert if we haven't sent one in the last hour
        if last_disk_alert_time is None or (current_time - last_disk_alert_time).total_seconds() > 3600:
            try:
                user = await bot.fetch_user(DISK_ALERT_USER_ID)
                await user.send(f"🚨 **Disk Usage Alert** 🚨\n\nRoot disk usage is at **{usage.percent:.1f}%**\n\n"
                              f"Free space: {usage.free / (1024**3):.1f} GB\n"
                              f"Total space: {usage.total / (1024**3):.1f} GB\n\n"
                              f"Consider:\n• Log compression\n• Log rotation/discard\n• Adding more disk space")
                last_disk_alert_time = current_time
                print(f"Disk alert sent to user {DISK_ALERT_USER_ID} at {current_time}")
            except Exception as e:
                print(f"Failed to send disk alert: {e}")
    
    with bot.sessionmaker() as session:
        db_stats_dict = {
                    "players": session.query(Player).count(),
                    "rec_points": session.query(func.sum(Player.rec_points)).scalar() or 0,
                    "bonus_pay": session.query(func.sum(Player.bonus_pay)).scalar() or 0,
                    "units": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").count(),
                    "purchased": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").filter(Unit.status != "PROPOSED").count(),
                    "active": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").filter(Unit.status == "ACTIVE").count(),
                    "dead": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").filter(Unit.status.in_(["KIA", "MIA"])).count(),
                    "upgrades": session.query(PlayerUpgrade).filter(PlayerUpgrade.original_price > 0).count(),
                    "units_by_type": session.query(Unit.unit_type, func.count()).filter(Unit.unit_type != "STOCKPILE").group_by(Unit.unit_type).all(),
                    "purchased_by_type": session.query(Unit.unit_type, func.count()).filter(Unit.unit_type != "STOCKPILE", Unit.status != "PROPOSED").group_by(Unit.unit_type).all(),
                    "live_by_type": session.query(Unit.unit_type, func.count()).filter(Unit.unit_type != "STOCKPILE", ~Unit.status.in_(["PROPOSED", "KIA", "MIA"])).group_by(Unit.unit_type).all(),
                    "units_by_type_and_campaign": session.query(Unit.unit_type, Unit.campaign_id, func.count()).filter(Unit.unit_type != "STOCKPILE").group_by(Unit.unit_type, Unit.campaign_id).all()
                }
    player_count.set(db_stats_dict["players"])
    rec_points.set(db_stats_dict["rec_points"])
    bonus_pay.set(db_stats_dict["bonus_pay"])
    units.set(db_stats_dict["units"])
    purchased_units.set(db_stats_dict["purchased"])
    active_units.set(db_stats_dict["active"])
    dead_units.set(db_stats_dict["dead"])
    upgrades.set(db_stats_dict["upgrades"])
    for unit_type, count in db_stats_dict["units_by_type"]:
        units_by_type.labels(unit_type=unit_type).set(count)
    for unit_type, count in db_stats_dict["purchased_by_type"]:
        purchased_by_type.labels(unit_type=unit_type).set(count)
    for unit_type, count in db_stats_dict["live_by_type"]:
        live_by_type.labels(unit_type=unit_type).set(count)
    for unit_type, campaign_id, count in db_stats_dict["units_by_type_and_campaign"]:
        units_by_type_and_campaign.labels(unit_type=unit_type, campaign_id=campaign_id).set(count)
    
    global last_alerted_version, behind, ahead
    if EnvironHelpers.get_bool("GIT_AUTOFETCH"):
        fetch_proc = await asyncio.create_subprocess_exec("git", "fetch", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        await fetch_proc.communicate()
        # we don't need to get the commit hash again, because we already have it and it represents what is running
        behind_proc = await asyncio.create_subprocess_exec("git", "rev-list", "--count", "HEAD..origin/main", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await behind_proc.communicate()
        if stderr:
            logger.error(f"Error fetching behind: {stderr.decode().strip()}")
        behind = int(stdout.decode().strip())
        ahead_proc = await asyncio.create_subprocess_exec("git", "rev-list", "--count", "origin/main..HEAD", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await ahead_proc.communicate()
        if stderr:
            logger.error(f"Error fetching ahead: {stderr.decode().strip()}")
        ahead = int(stdout.decode().strip())
        info.labels(commit=commit, ahead=ahead, behind=behind).set(1)
    if behind > 0 and EnvironHelpers.get_bool("NOTIFY_ON_NEW_VERSION"):
        latest_proc = await asyncio.create_subprocess_exec("git", "rev-parse", "--short", "origin/main", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await latest_proc.communicate()
        if stderr:
            logger.error(f"Error fetching latest: {stderr.decode().strip()}")
        latest = stdout.decode().strip()
        if latest != last_alerted_version:
            user = await bot.fetch_user(DISK_ALERT_USER_ID)
            await user.send(f"🚨 **New Version Available** 🚨\n\nA new version of the bot is available, please update to the latest version.\n\n"
                            f"You are {behind} commits behind the latest version.\n"
                            f"Your commit is {commit}, the latest commit is {latest}.\n"
                            "Please run /debug update_and_restart to update the bot.")
            last_alerted_version = latest

poll_metrics_slow.start()