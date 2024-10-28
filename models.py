from sqlalchemy import Column, Integer, String, Enum, ForeignKey, PickleType, event
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from enum import Enum as PyEnum
#from customclient import CustomClient

Base = declarative_base()

class UnitType(PyEnum):
    INFANTRY = "0.0"
    MEDIC = "0.1"
    ENGINEER = "0.2"
    LOGISTIC = "1.0"
    LIGHT_VEHICLE = "1.1"
    INFANTRY_VEHICLE = "1.2"
    MAIN_TANK = "1.3"
    ARTILLERY = "2.0"
    FIGHTER = "3.0"
    BOMBER = "3.1"
    VTOL = "3.2"
    HVTOL = "3.3"
    HAT = "3.4"
    LIGHT_MECH = "4.0"

class UpgradeType(PyEnum):
    UPGRADE = "0.0"
    WEAPON = "1.0"

class UnitStatus(PyEnum):
    ACTIVE = "1"
    INACTIVE = "0"
    MIA = "2"
    KIA = "3"
    PROPOSED = "4"

class Unit(Base):
    __tablename__ = "units"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), index=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    unit_type = Enum(UnitType)
    status = Enum(UnitStatus, default=UnitStatus.PROPOSED)
    
    # relationships
    player = relationship("Player", back_populates="units")
    upgrades = relationship("Upgrade", back_populates="unit")

@event.listens_for(Unit, "after_insert")
def after_insert(mapper, connection, target):
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((0, target))

@event.listens_for(Unit, "after_update")
def after_update(mapper, connection, target):
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((1, target))

@event.listens_for(Unit, "after_delete")
def after_delete(mapper, connection, target):
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((2, target))

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
    units = relationship("Unit", back_populates="player")
    dossier = relationship("Dossier", back_populates="player")
    statistic = relationship("Statistic", back_populates="player")

@event.listens_for(Player, "after_insert")
def after_insert(mapper, connection, target):
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((0, target))


@event.listens_for(Player, "after_update")
def after_update(mapper, connection, target):
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((1, target))

@event.listens_for(Player, "after_delete")
def after_delete(mapper, connection, target):
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((2, target))

class Upgrade(Base):
    __tablename__ = "upgrades"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    type = Column(Enum(UpgradeType))
    unit_id = Column(Integer, ForeignKey("units.id"))
    # relationships
    unit = relationship("Unit", back_populates="upgrades")

@event.listens_for(Upgrade, "after_insert")
def after_insert(mapper, connection, target):
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((0, target))

@event.listens_for(Upgrade, "after_update")
def after_update(mapper, connection, target):
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((1, target))

@event.listens_for(Upgrade, "after_delete")
def after_delete(mapper, connection, target):
    from customclient import CustomClient
    queue = CustomClient().queue
    queue.put_nowait((2, target))

class Dossier(Base):
    __tablename__ = "dossiers"
    # columns
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    message_id = Column(String(255), index=True)
    # relationships
    player = relationship("Player", back_populates="dossier")

class Statistic(Base):
    __tablename__ = "statistics"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    message_id = Column(String(255), index=True)
    # relationships
    player = relationship("Player", back_populates="statistic")

class Config(Base):
    __tablename__ = "configs"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(255), index=True)
    value = Column(PickleType)

create_all = Base.metadata.create_all
