from prometheus_client import start_http_server, Gauge
from discord.ext.tasks import loop
from customclient import CustomClient # just needed so we can get a bunch of the stats, and a sessionmaker for the db stats
from extensions.faq import counters
from extensions.debug import process
from coloredformatter import stats
from datetime import datetime
from sqlalchemy import func
from models import Player, Unit, PlayerUpgrade
from threading import Thread
from os import getenv

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
resident_memory = Gauge("resident_memory", "The resident memory of the bot")
cpu_time = Gauge("cpu_time", "The duration of CPU used by the bot")
log_counts = Gauge("log_counts", "The number of logs", labelnames=["count_type", "log_level"])
up = Gauge("up", "Is the bot up?")

@loop(seconds=15)
async def poll_metrics():
    bot = CustomClient()
    up.set(True)
    uptime.set((datetime.now() - bot.start_time).total_seconds())
    start_time.set(int(bot.start_time.timestamp()))
    queue_size.set(bot.queue.qsize())
    faq_queries.set(sum(counters.values()))
    if process is not None:
        resident_memory.set(process.memory_info().rss)
        cpu_time.set(process.cpu_times().user + process.cpu_times().system)
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
    with bot.sessionmaker() as session:
        db_stats_dict = {
                    "players": session.query(Player).count(),
                    "rec_points": session.query(func.sum(Player.rec_points)).scalar() or 0,
                    "bonus_pay": session.query(func.sum(Player.bonus_pay)).scalar() or 0,
                    "units": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").count(),
                    "purchased": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").filter(Unit.status != "PROPOSED").count(),
                    "active": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").filter(Unit.status == "ACTIVE").count(),
                    "dead": session.query(Unit).filter(Unit.unit_type != "STOCKPILE").filter(Unit.status.in_(["KIA", "MIA"])).count(),
                    "upgrades": session.query(PlayerUpgrade).filter(PlayerUpgrade.original_price > 0).count()
                }
    player_count.set(db_stats_dict["players"])
    rec_points.set(db_stats_dict["rec_points"])
    bonus_pay.set(db_stats_dict["bonus_pay"])
    units.set(db_stats_dict["units"])
    purchased_units.set(db_stats_dict["purchased"])
    active_units.set(db_stats_dict["active"])
    dead_units.set(db_stats_dict["dead"])
    upgrades.set(db_stats_dict["upgrades"])


start_wrapper = lambda: start_http_server(9108 if getenv("PROD", "false").lower() == "true" else 9107)
_thread = Thread(target=start_wrapper)
_thread.start()
poll_metrics.start()
