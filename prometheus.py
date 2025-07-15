from prometheus_client import start_http_server, Gauge
from discord.ext.tasks import loop
from customclient import CustomClient # just needed so we can get a bunch of the stats, and a sessionmaker for the db stats
from extensions.faq import total_views
from coloredformatter import stats
from datetime import datetime
from sqlalchemy import func
from models import Player, Unit, PlayerUpgrade
from threading import Thread
from os import getenv
import psutil  # Add this import

uptime = Gauge("uptime", "The uptime of the bot")
start_time = Gauge("start_time", "The start time of the bot")
queue_size = Gauge("queue_size", "The size of the queue")
faq_queries = Gauge("faq_queries", "The number of FAQ queries")
player_count = Gauge("player_count", "The number of users registered with the bot")
rec_points = Gauge("rec_points", "The total number of unspent requisition points")
bonus_pay = Gauge("bonus_pay", "The total number of unspent bonus pay")
units = Gauge("units", "The number of units created")
purchased_units = Gauge("purchased_units", "The number of units purchased")
active_units = Gauge("active_units", "The number of active units")
dead_units = Gauge("dead_units", "The number of dead units")
upgrades = Gauge("upgrades", "The number of upgrades purchased")
log_counts = Gauge("log_counts", "The number of logs", labelnames=["count_type", "log_level"])
up = Gauge("up", "Is the bot up?")
as_of = Gauge("as_of", "The time the metrics were last updated", labelnames=['loop'])
units_by_type = Gauge("units_by_type", "The number of units by type", labelnames=['unit_type'])
purchased_by_type = Gauge("purchased_by_type", "The number of units purchased by type", labelnames=['unit_type'])
live_by_type = Gauge("live_by_type", "The number of units live by type", labelnames=['unit_type'])
units_by_type_and_campaign = Gauge("units_by_type_and_campaign", "The number of units by type and campaign", labelnames=['unit_type', 'campaign_id'])

# Add a Gauge for root disk usage
root_disk_usage = Gauge("root_disk_usage_percent", "Percent of / disk used")

# Disk alert variables
DISK_ALERT_THRESHOLD = 90.0
DISK_ALERT_USER_ID = int(getenv("BOT_OWNER_ID", "533009808501112881"))
last_disk_alert_time = None

@loop(seconds=15)
async def poll_metrics_fast():
    bot: CustomClient = CustomClient()
    up.set(True)
    as_of.labels(loop="fast").set(int(datetime.now().timestamp()))
    uptime.set((datetime.now() - bot.start_time).total_seconds())
    start_time.set(int(bot.start_time.timestamp()))
    queue_size.set(bot.queue.qsize())
    faq_queries.set(total_views)
    log_counts.labels(count_type="today", log_level="DEBUG").set(stats["today_DEBUG"].get())
    log_counts.labels(count_type="today", log_level="INFO").set(stats["today_INFO"].get())
    log_counts.labels(count_type="today", log_level="WARNING").set(stats["today_WARNING"].get())
    log_counts.labels(count_type="today", log_level="ERROR").set(stats["today_ERROR"].get())
    log_counts.labels(count_type="today", log_level="CRITICAL").set(stats["today_CRITICAL"].get())
    log_counts.labels(count_type="today", log_level="total").set(stats["today_total"].get())
    log_counts.labels(count_type="total", log_level="DEBUG").set(stats["total_DEBUG"])
    log_counts.labels(count_type="total", log_level="INFO").set(stats["total_INFO"])
    log_counts.labels(count_type="total", log_level="WARNING").set(stats["total_WARNING"])
    log_counts.labels(count_type="total", log_level="ERROR").set(stats["total_ERROR"])
    log_counts.labels(count_type="total", log_level="CRITICAL").set(stats["total_CRITICAL"])
    log_counts.labels(count_type="total", log_level="total").set(stats["total_total"])

@loop(seconds=60)
async def poll_metrics_slow():
    global last_disk_alert_time
    bot: CustomClient = CustomClient()
    as_of.labels(loop="slow").set(int(datetime.now().timestamp()))
    # Add disk usage metric for /
    usage = psutil.disk_usage('/')
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

start_wrapper = lambda: start_http_server(9108 if getenv("PROD", "false").lower() == "true" else 9107)
_thread = Thread(target=start_wrapper)
_thread.start()
poll_metrics_fast.start()
poll_metrics_slow.start()