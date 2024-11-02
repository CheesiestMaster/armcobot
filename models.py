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
    WEAPON = "1.0"
    SPECIAL = "2.0"

class UnitStatus(PyEnum):
    ACTIVE = "1"
    INACTIVE = "0"
    MIA = "2"
    KIA = "3"
    PROPOSED = "4"

class LegacyUnitStatus(PyEnum):
    MIA = "2"
    KIA = "3"
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
    
    # relationships
    player = relationship("Player", back_populates="units")
    upgrades = relationship("Upgrade", back_populates="unit", cascade="all, delete-orphan")
    active_unit = relationship("ActiveUnit", back_populates="unit", cascade="all, delete-orphan")

class ActiveUnit(Base):
    __tablename__ = "active_units"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), unique=True, index=True)
    callsign = Column(String(8), index=True, unique=True)
    unit_id = Column(Integer, ForeignKey("units.id"), unique=True, index=True)
    force_strength = Column(Integer, default=0)
    range = Column(Integer, default=0)
    speed = Column(Integer, default=0)
    defense = Column(Integer, default=0)
    armor = Column(Integer, default=0)
    north_south = Column(Integer, default=0)
    east_west = Column(Integer, default=0)
    facing = Column(Integer, default=0)
    area_operation = Column(String(30), default="ARMCO")
    supply = Column(Integer, default=0)
    immobilized = Column(Boolean, default=False)
    disarmed = Column(Boolean, default=False)
    transport_id = Column(Integer, ForeignKey("active_units.id"))
    campaign_id = Column(Integer, ForeignKey("campaigns.id"))
    # relationships
    player = relationship("Player", back_populates="active_units")
    unit = relationship("Unit", back_populates="active_unit")
    transport = relationship("ActiveUnit", remote_side=[id], backref=backref("passengers", lazy="dynamic"))
    campaign = relationship("Campaign", back_populates="active_units")

class Campaign(Base):
    __tablename__ = "campaigns"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    active = Column(Boolean, default=True)
    open = Column(Boolean, default=False)
    # relationships
    active_units = relationship("ActiveUnit", back_populates="campaign")

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
    active_units = relationship("ActiveUnit", back_populates="player", cascade="all, delete-orphan")
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

class LegacyUnit(Base):
    __tablename__ = "legacy_units"
    # almost identical to Unit, but uses a different pair of Enums for status and type
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    player_id = Column(Integer, ForeignKey("players.id"), index=True)
    unit_type = Column(String(30), index=True)
    status = Column(String(30), index=True)

class Medals(Base):
    __tablename__ = "medals"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(30), index=True)
    player_id = Column(Integer, ForeignKey("players.id"), index=True)
    # relationships
    player = relationship("Player", back_populates="medals")
# Unit, ActiveUnit, Upgrade need all 3 listeners
# Dossier and Statistic need only after_delete

[event.listen(model, "after_insert", after_insert) for model in [Player, Unit, ActiveUnit, Upgrade]]
[event.listen(model, "after_update", after_update) for model in [Player, Unit, ActiveUnit, Upgrade]]
[event.listen(model, "after_delete", after_delete) for model in [Unit, ActiveUnit, Upgrade, Dossier, Statistic]]

create_all = Base.metadata.create_all
