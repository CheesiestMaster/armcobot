from sqlalchemy import Column, Integer, String, Enum, ForeignKey, PickleType, Boolean, event
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.declarative import declarative_base
from enum import Enum as PyEnum
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

Base = declarative_base()

class UpgradeType(PyEnum):
    UPGRADE = "0.0"
    REFIT = "1.0"
    SPECIAL = "2.0"

class UnitStatus(PyEnum):
    ACTIVE = "1"
    INACTIVE = "0"
    MIA = "2"
    KIA = "3"
    PROPOSED = "4"
    LEGACY = "5"

# Listeners

def after_insert(mapper, connection, target):
    logger.debug("Inserting target into queue")
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((0, target))

def after_update(mapper, connection, target):
    logger.debug("Updating target in queue")
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((1, target))

def after_delete(mapper, connection, target):
    logger.debug("Deleting target from queue")
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((2, target))
# Models

class Unit(Base):
    __tablename__ = "units"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    player_id = Column(Integer, ForeignKey("players.id"), index=True)
    unit_type = Column(String(15))
    status = Column(Enum(UnitStatus), default=UnitStatus.PROPOSED) # status is still an enum, but type is a string now
    legacy = Column(Boolean, default=False)
    active = Column(Boolean, default=False)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), default=1)
    callsign = Column(String(15), index=True, unique=True)
    area_operation = Column(String(30), default="ARMCO")
    
    # relationships
    player = relationship("Player", back_populates="units")
    upgrades = relationship("Upgrade", back_populates="unit", cascade="all, delete-orphan")
    campaign = relationship("Campaign", back_populates="units")

class Campaign(Base):
    __tablename__ = "campaigns"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    active = Column(Boolean, default=True)
    open = Column(Boolean, default=False)
    gm = Column(String(255), default="")
    # relationships
    units = relationship("Unit", back_populates="campaign")

class Player(Base):
    __tablename__ = "players"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    discord_id = Column(String(255), index=True)
    name = Column(String(255), index=True)
    lore = Column(String(1000), default="")
    rec_points = Column(Integer, default=0)
    bonus_pay = Column(Integer, default=0)
    # relationships
    units = relationship("Unit", back_populates="player", cascade="all, delete-orphan")
    dossier = relationship("Dossier", back_populates="player", cascade="all, delete-orphan")
    statistic = relationship("Statistic", back_populates="player", cascade="all, delete-orphan")
    medals = relationship("Medals", back_populates="player", cascade="all, delete-orphan")

class Upgrade(Base):
    __tablename__ = "upgrades"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    type = Column(Enum(UpgradeType))
    name = Column(String(30), index=True)
    unit_id = Column(Integer, ForeignKey("units.id"))
    # relationships
    unit = relationship("Unit", back_populates="upgrades")

class Dossier(Base):
    __tablename__ = "dossiers"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), unique=True, index=True)
    message_id = Column(String(255), index=True)
    # relationships
    player = relationship("Player", back_populates="dossier")

class Statistic(Base):
    __tablename__ = "statistics"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), unique=True, index=True)
    message_id = Column(String(255), index=True)
    # relationships
    player = relationship("Player", back_populates="statistic")

class Config(Base):
    __tablename__ = "configs"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(255), index=True, unique=True)
    value = Column(PickleType)

class Medals(Base):
    __tablename__ = "medals"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    player_id = Column(Integer, ForeignKey("players.id"), index=True)
    # relationships
    player = relationship("Player", back_populates="medals")
# Unit, Upgrade need all 3 listeners
# Dossier and Statistic need only after_delete

[event.listen(model, "after_insert", after_insert) for model in [Player, Unit, Upgrade]]
[event.listen(model, "after_update", after_update) for model in [Player, Unit, Upgrade]]
[event.listen(model, "after_delete", after_delete) for model in [Unit, Upgrade, Dossier, Statistic]]

create_all = Base.metadata.create_all
