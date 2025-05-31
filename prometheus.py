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
    bot: CustomClient = CustomClient()
    as_of.labels(loop="slow").set(int(datetime.now().timestamp()))
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