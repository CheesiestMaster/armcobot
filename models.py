from __future__ import annotations

import logging
from enum import Enum as PyEnum
from typing import Any, Callable, Iterable, Iterator, MutableMapping, Optional

import discord
from sqlalchemy import ColumnElement, Integer, String, Enum, ForeignKey, PickleType, Boolean, BigInteger, func, literal, select, Index, UniqueConstraint, CheckConstraint, text, DDL, event, MetaData
from sqlalchemy.ext.hybrid import Comparator, hybrid_property
from sqlalchemy.orm import Session, relationship, DeclarativeBase, Mapped, mapped_column, column_property, validates
from sqlalchemy.sql.operators import OperatorType
from sqlalchemy.types import TypeDecorator

import utils

logger = logging.getLogger(__name__)

engine_logger = logging.getLogger("sqlalchemy.engine")
#engine_logger.setLevel(logging.DEBUG)

class UnitStatus(PyEnum):
    ACTIVE = "1"
    INACTIVE = "0"
    MIA = "2"
    KIA = "3"
    PROPOSED = "4"
    LEGACY = "5"


class UnitStatusCoercingEnum(TypeDecorator):
    """Coerces various status inputs to a valid UnitStatus before binding.
    Accepts values like 'UnitStatus.ACTIVE', 'ACTIVE', UnitStatus.ACTIVE, or the enum value strings.
    """

    impl = Enum(UnitStatus)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        # Normalize string inputs
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("UnitStatus."):
                stripped = stripped.split(".", 1)[1]
            # Try by name first
            if stripped in UnitStatus.__members__:
                value = UnitStatus[stripped]
            else:
                # Try by value
                try:
                    value = UnitStatus(stripped)
                except Exception:
                    # Leave as-is; DB will error if invalid
                    value = stripped
        return value

    def process_result_value(self, value, dialect):
        return value

class DiscordUserComparator(Comparator):
    """
    SQLAlchemy hybrid comparator for comparing Discord user IDs (stored as
    BigInteger) with discord.User or discord.Member instances in queries.
    """

    @staticmethod
    def _to_int(other):
        if isinstance(other, discord.abc.User):
            return other.id
        if isinstance(other, int):
            return other
        raise TypeError(f"Cannot compare {type(other).__name__}")

    @classmethod
    def _coerce_other(cls, other):
        if isinstance(other, Iterable) and not isinstance(other, (str, bytes)):

            return [cls._to_int(item) for item in other]
        return cls._to_int(other)

    def operate(self, op: OperatorType, other: Any, **kwargs: Any) -> ColumnElement[Any]:
        other = self._coerce_other(other)
        return op(self.__clause_element__(), other, **kwargs)

    def reverse_operate(self, op: OperatorType, other: Any, **kwargs: Any) -> ColumnElement[Any]:
        other = self._coerce_other(other)
        return op(other, self.__clause_element__(), **kwargs)

class BaseModel(DeclarativeBase):
    """
    Abstract base for all SQLAlchemy models. Provides naming conventions for
    indexes and constraints, and default __repr__, __hash__, and __eq__.
    """

    __abstract__ = True

    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_label)s",
        "ck": "ck_%(table_name)s_%(column_0_label)s",
        "fk": "fk_%(table_name)s_%(column_0_label)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s"
    })

    def __repr__(self):
        class_name = self.__class__.__name__
        # Correctly access primary key columns
        primary_keys = ", ".join(
            [f"{key}={getattr(self, key)!r}" for key in self.__table__.primary_key.columns.keys()] # type: ignore
        )
        return f"<{class_name}({primary_keys})>"

    __str__ = __repr__

    def __hash__(self):
        return hash(repr(self))

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return repr(self) == repr(other)


# Models


class UpgradeType(BaseModel):
    """
    Upgrade type definition (e.g. weapon, armor). Referenced by ShopUpgrade
    and PlayerUpgrade. Defines name, emoji, and purchase rules.
    """

    __tablename__ = "upgrade_types"

    # Table options
    __table_args__ = (
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'sqlite_with_rowid': False},
    )

    # columns
    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    emoji: Mapped[str] = mapped_column(String(4), nullable=False, server_default="")
    is_refit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", index=True)
    non_purchaseable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", index=True)
    can_use_unit_req: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", index=True)

    # relationships
    shop_upgrades: Mapped[list[ShopUpgrade]] = relationship("ShopUpgrade", foreign_keys="ShopUpgrade.type", back_populates="upgrade_type", lazy="select", passive_deletes=True)
    player_upgrades: Mapped[list[PlayerUpgrade]] = relationship("PlayerUpgrade", foreign_keys="PlayerUpgrade.type", back_populates="upgrade_type", lazy="select", passive_deletes=True)

class Extension(BaseModel):
    """
    Tracks which bot extensions (cogs) are loaded. One row per extension name;
    used to persist loaded extensions across restarts.
    """

    __tablename__ = "extensions"

    # Table options
    __table_args__ = (
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'sqlite_with_rowid': False},
    )

    # column
    name: Mapped[str] = mapped_column(String(264), primary_key=True, nullable=False) # this table is just a list of loaded extensions, hence only one column and no relationships

class Campaign(BaseModel):
    """
    A campaign (game instance) that players can join. Has optional player limit,
    required role, and GM. Units belong to campaigns; players join via invites.
    """

    __tablename__ = "campaigns"

    # Table-level constraints and indexes
    __table_args__ = (
        Index('ix_campaigns_active_open', 'active', 'open'),
        CheckConstraint('player_limit IS NULL OR player_limit > 0', name='ck_campaigns_player_limit_positive'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1", index=True)
    open: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", index=True)
    gm: Mapped[str] = mapped_column(String(255), nullable=False, server_default="", index=True)
    player_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) # null for no limit
    required_role: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True) # null for no role required
    # relationships
    units: Mapped[list[Unit]] = relationship("Unit", back_populates="campaign", lazy="select", passive_deletes=True)
    invites: Mapped[list[CampaignInvite]] = relationship("CampaignInvite", back_populates="campaign", cascade="all, delete-orphan", lazy="select", passive_deletes=True)
    players: Mapped[set[Player]] = relationship(
        "Player",
        secondary="units",
        primaryjoin="Campaign.id == Unit.campaign_id",
        secondaryjoin="Unit.player_id == Player.id",
        collection_class=set,
        overlaps="units",
        lazy="select",
        passive_deletes=True
    )
    live_players: Mapped[set[Player]] = relationship(
        "Player",
        secondary="units",
        primaryjoin="and_(Campaign.id == Unit.campaign_id, Unit.status == 'ACTIVE')",
        secondaryjoin="Unit.player_id == Player.id",
        collection_class=set,
        overlaps="players,units",
        lazy="select",
        passive_deletes=True
    )

class CampaignInvite(BaseModel):
    __tablename__ = "campaign_invites"

    # Table options (PKs are implicitly indexed)
    __table_args__ = (
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'sqlite_with_rowid': False},
    )

    # just an association table for the many-to-many relationship between campaigns and invited players
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True, nullable=False)

    # relationships
    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="invites", lazy="joined", passive_deletes=True)
    player: Mapped[Player] = relationship("Player", back_populates="campaign_invites", lazy="joined", passive_deletes=True)

class Player(BaseModel):
    """
    A player (Discord user) in the system. Holds requisition points, bonus pay,
    lore, and links to units, medals, dossiers, and statistics messages.
    """

    __tablename__ = "players"

    # Table-level constraints and options
    __table_args__ = (
        CheckConstraint('bonus_pay >= 0', name='ck_players_bonus_pay_positive'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    @validates("lore")
    def _coherse_lore(self, _, value):
        return "" if value is None else value

    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    lore: Mapped[str] = mapped_column(String(1000), nullable=True, server_default="")
    rec_points: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", index=True)
    bonus_pay: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", index=True)
    # relationships
    units: Mapped[list[Unit]] = relationship("Unit", back_populates="player", cascade="none", overlaps="live_players,players", lazy="select", passive_deletes=True)
    dossier: Mapped[Dossier] = relationship("Dossier", back_populates="player", passive_deletes=True)
    statistic: Mapped[Statistic] = relationship("Statistic", back_populates="player", passive_deletes=True)
    medals: Mapped[list[Medals]] = relationship("Medals", back_populates="player", cascade="none", lazy="select", passive_deletes=True)
    campaign_invites: Mapped[list[CampaignInvite]] = relationship("CampaignInvite", back_populates="player", cascade="none", lazy="select", passive_deletes=True)

    stockpile: Mapped[Optional[Unit]] = relationship(
        "Unit",
        primaryjoin="and_(Player.id == Unit.player_id, Unit.unit_type == 'STOCKPILE')",
        uselist=False,
        viewonly=True
    )
    active_units: Mapped[list[Unit]] = relationship(
        "Unit",
        primaryjoin="and_(Player.id == Unit.player_id, Unit.active == True)",
        uselist=True,
        viewonly=True
    )

    @hybrid_property
    def user(self) -> discord.User:
        """Returns a concrete discord.User object.

        Note: The property always returns discord.User (concrete type), while the
        comparator accepts discord.abc.User (which includes User, ClientUser, and Member).
        This allows queries to work with any user-like object while the property
        always returns a consistent concrete type.
        """
        from customclient import CustomClient
        client = CustomClient()
        return client.get_user(int(self.discord_id))

    @user.comparator
    def user(cls) -> DiscordUserComparator:
        return DiscordUserComparator(cls.discord_id)

    @hybrid_property
    def mention(self) -> str:
        return f"<@{self.discord_id}>"

    @mention.expression
    def mention(cls) -> ColumnElement[str]:
        return literal("<@") + cls.discord_id + literal(">")

class PlayerUpgrade(BaseModel):
    """
    An upgrade owned by a player's unit (e.g. weapon, armor). Links to
    UpgradeType, Unit, and optionally ShopUpgrade. Tracks original price
    and whether it is non-transferable.
    """

    __tablename__ = "player_upgrades"

    # Table-level constraints and options
    __table_args__ = (
        CheckConstraint('original_price >= 0', name='original_price_positive'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(ForeignKey("upgrade_types.name", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    original_price: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True)
    shop_upgrade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shop_upgrades.id", ondelete="SET NULL"), nullable=True, index=True)
    non_transferable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", index=True)
    # relationships
    unit: Mapped[Unit] = relationship("Unit", back_populates="upgrades", lazy="joined", passive_deletes=True)
    shop_upgrade: Mapped[Optional[ShopUpgrade]] = relationship("ShopUpgrade", back_populates="player_upgrades", lazy="joined", passive_deletes=True)
    upgrade_type: Mapped[UpgradeType] = relationship("UpgradeType", foreign_keys=[type], back_populates="player_upgrades", lazy="joined", passive_deletes=True)

class Dossier(BaseModel):
    __tablename__ = "dossiers"

    # Table options
    __table_args__ = (
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), unique=True, nullable=False)
    message_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # relationships
    player: Mapped[Player] = relationship("Player", back_populates="dossier", lazy="joined", passive_deletes=True)

class Statistic(BaseModel):
    """
    Links a player to their statistics message ID in the statistics channel.
    One row per player; used to update or recreate the stats embed.
    """

    __tablename__ = "statistics"

    # Table options
    __table_args__ = (
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), unique=True, nullable=False)
    message_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # relationships
    player: Mapped[Player] = relationship("Player", back_populates="statistic", lazy="joined", passive_deletes=True)

class Config(BaseModel):
    __tablename__ = "configs"

    # Table options
    __table_args__ = (
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'sqlite_with_rowid': False},
    )

    # columns
    key: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)
    value: Mapped[PickleType] = mapped_column(PickleType, nullable=False)

class Medals(BaseModel):
    """
    A medal awarded to a player. Name identifies the medal type; player_id
    links to the player. Display uses medal emotes from config.
    """

    __tablename__ = "medals"

    # Table-level constraints and indexes
    __table_args__ = (
        Index('ix_medals_player_id_name', 'player_id', 'name'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    # relationships
    player: Mapped[Player] = relationship("Player", back_populates="medals", lazy="joined", passive_deletes=True)

class Faq(BaseModel):
    __tablename__ = "faq"

    # Table options
    __table_args__ = (
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    answer: Mapped[str] = mapped_column(String(1873), nullable=False)

class ShopUpgrade(BaseModel):
    """
    An upgrade available in the shop. Has type, cost, optional refit target,
    and compatibility with unit types. Links to ShopUpgradeUnitTypes.
    """

    __tablename__ = "shop_upgrades"

    # Table-level constraints and indexes
    __table_args__ = (
        Index('ix_shop_upgrades_type_cost', 'type', 'cost'),
        CheckConstraint('cost >= 0', name='cost_positive'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    type: Mapped[str] = mapped_column(ForeignKey("upgrade_types.name", ondelete="RESTRICT"), nullable=False, index=True)
    cost: Mapped[int] = mapped_column(Integer, nullable=True, server_default="0", index=True)
    refit_target: Mapped[str | None] = mapped_column(ForeignKey("unit_types.unit_type", ondelete="SET NULL"), nullable=True, index=True)
    required_upgrade_id: Mapped[int | None] = mapped_column(ForeignKey("shop_upgrades.id", ondelete="SET NULL"), nullable=True, index=True)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", index=True)
    repeatable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", index=True)

    sort_key = column_property(select(UpgradeType.sort_order).where(UpgradeType.name == type).scalar_subquery())

    # relationships
    player_upgrades: Mapped[list[PlayerUpgrade]] = relationship("PlayerUpgrade", back_populates="shop_upgrade", cascade="all", lazy="select", passive_deletes=True)
    unit_types: Mapped[list[ShopUpgradeUnitTypes]] = relationship("ShopUpgradeUnitTypes", back_populates="shop_upgrade", cascade="all, delete-orphan", lazy="select", passive_deletes=True)
    required_upgrade: Mapped[Optional[ShopUpgrade]] = relationship("ShopUpgrade", remote_side=[id], lazy="joined", passive_deletes=True)
    target_type_info: Mapped[UnitType] = relationship("UnitType", foreign_keys=[refit_target], lazy="joined", back_populates="refit_targets", passive_deletes=True)
    compatible_units: Mapped[list[Unit]] = relationship(
        "Unit",
        secondary="shop_upgrade_unit_types",
        primaryjoin="ShopUpgrade.id==ShopUpgradeUnitTypes.shop_upgrade_id",
        secondaryjoin="Unit.unit_type==ShopUpgradeUnitTypes.unit_type",
        back_populates="available_upgrades",
        overlaps="unit_types,type_info",
        lazy="select",
        passive_deletes=True)
    compatible_unit_types: Mapped[list[UnitType]] = relationship(
        "UnitType",
        secondary="shop_upgrade_unit_types",
        primaryjoin="ShopUpgrade.id==ShopUpgradeUnitTypes.shop_upgrade_id",
        secondaryjoin="UnitType.unit_type==ShopUpgradeUnitTypes.unit_type",
        back_populates="compatible_upgrades",
        overlaps="compatible_units,unit_types,type_info",
        lazy="select",
        passive_deletes=True)
    upgrade_type: Mapped[UpgradeType] = relationship("UpgradeType", foreign_keys=[type], back_populates="shop_upgrades", lazy="joined", passive_deletes=True)

class Unit(BaseModel):
    __tablename__ = "units"

    # Table-level constraints and indexes
    __table_args__ = (
        Index('ix_units_player_id_active', 'player_id', 'active'),
        Index('ix_units_campaign_id_status', 'campaign_id', 'status'),
        Index('ix_units_unit_type_status', 'unit_type', 'status'),
        CheckConstraint('unit_req >= 0', name='ck_units_unit_req_positive'),
        UniqueConstraint('name', 'player_id', name='uq_units_name_player_id'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    # columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_type: Mapped[str] = mapped_column(ForeignKey("unit_types.unit_type", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[UnitStatus] = mapped_column(UnitStatusCoercingEnum(), nullable=False, server_default=text("'PROPOSED'"), index=True)
    legacy: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", index=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    callsign: Mapped[str] = mapped_column(String(15), unique=True, nullable=True, index=True)
    battle_group: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    original_type: Mapped[Optional[str]] = mapped_column(ForeignKey("unit_types.unit_type", ondelete="SET NULL"), nullable=True, index=True)
    unit_req: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", index=True)

    # relationships
    player: Mapped[Player] = relationship("Player", back_populates="units", overlaps="live_players,players", passive_deletes=True, lazy="joined")
    upgrades: Mapped[list[PlayerUpgrade]] = relationship("PlayerUpgrade", back_populates="unit", cascade="delete, delete-orphan", lazy="select", passive_deletes=True)
    campaign: Mapped[Optional[Campaign]] = relationship("Campaign", back_populates="units", overlaps="live_players,players", passive_deletes=True, lazy="joined")
    type_info: Mapped[UnitType] = relationship("UnitType", foreign_keys=[unit_type], lazy="joined", back_populates="units", cascade="save-update", passive_deletes=True)
    original_type_info: Mapped[Optional[UnitType]] = relationship("UnitType", foreign_keys=[original_type], lazy="joined", back_populates="original_units", passive_deletes=True)
    available_upgrades: Mapped[list[ShopUpgrade]] = relationship(
        "ShopUpgrade",
        order_by=(ShopUpgrade.sort_key, ShopUpgrade.type, ShopUpgrade.id),
        secondary="shop_upgrade_unit_types",
        primaryjoin="Unit.unit_type==ShopUpgradeUnitTypes.unit_type",
        secondaryjoin="ShopUpgrade.id==ShopUpgradeUnitTypes.shop_upgrade_id",
        overlaps="unit_types,type_info",
        lazy="select",
        viewonly=True)
    unit_history: Mapped[list[UnitHistory]] = relationship("UnitHistory", back_populates="unit", lazy="select", passive_deletes=True)

class ShopUpgradeUnitTypes(BaseModel):
    """
    Association between a shop upgrade and a unit type (which unit types
    can purchase this upgrade). Many-to-many link between ShopUpgrade
    and UnitType.
    """

    __tablename__ = "shop_upgrade_unit_types"

    # Table-level constraints and indexes
    __table_args__ = (
        Index('ix_shop_upgrade_unit_types_unit_type_shop_upgrade_id', 'unit_type', 'shop_upgrade_id'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'sqlite_with_rowid': False},
    )

    # columns - composite primary key with unit_type first
    unit_type: Mapped[str] = mapped_column(ForeignKey("unit_types.unit_type", ondelete="CASCADE"), primary_key=True, nullable=False)
    shop_upgrade_id: Mapped[int] = mapped_column(ForeignKey("shop_upgrades.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    shop_upgrade: Mapped[ShopUpgrade] = relationship(back_populates="unit_types", overlaps="compatible_unit_types,available_upgrades,compatible_units", lazy="joined", passive_deletes=True)
    type_info: Mapped[UnitType] = relationship(lazy="joined", back_populates="upgrade_types", overlaps="available_upgrades,compatible_units", passive_deletes=True)

class UnitType(BaseModel):
    __tablename__ = "unit_types"

    # Table-level constraints and indexes
    __table_args__ = (
        CheckConstraint('unit_req >= 0', name='ck_unit_types_unit_req_positive'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    # columns
    unit_type: Mapped[str] = mapped_column(String(15), primary_key=True, nullable=False)
    is_base: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", index=True)
    free_upgrade_1: Mapped[Optional[int]] = mapped_column(ForeignKey("shop_upgrades.id", ondelete="SET NULL"), nullable=True, index=True)
    free_upgrade_2: Mapped[Optional[int]] = mapped_column(ForeignKey("shop_upgrades.id", ondelete="SET NULL"), nullable=True, index=True)
    unit_req: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", index=True)

    # relationships
    units: Mapped[list[Unit]] = relationship("Unit", foreign_keys="Unit.unit_type", back_populates="type_info", lazy="select", passive_deletes=True)
    original_units: Mapped[list[Unit]] = relationship("Unit", foreign_keys="Unit.original_type", back_populates="original_type_info", overlaps="original_type_info", lazy="select", passive_deletes=True)
    refit_targets: Mapped[list[ShopUpgrade]] = relationship("ShopUpgrade", foreign_keys="ShopUpgrade.refit_target", back_populates="target_type_info", overlaps="target_type_info", lazy="select", passive_deletes=True)
    upgrade_types: Mapped[list[ShopUpgradeUnitTypes]] = relationship("ShopUpgradeUnitTypes", back_populates="type_info", overlaps="compatible_unit_types,available_upgrades,compatible_units,type_info", lazy="select", passive_deletes=True)
    free_upgrade_1_info: Mapped[Optional[ShopUpgrade]] = relationship(
        "ShopUpgrade",
        foreign_keys=[free_upgrade_1],
        overlaps="target_type_info",
        passive_deletes=True)
    free_upgrade_2_info: Mapped[Optional[ShopUpgrade]] = relationship(
        "ShopUpgrade",
        foreign_keys=[free_upgrade_2],
        overlaps="target_type_info",
        passive_deletes=True)
    compatible_upgrades: Mapped[list[ShopUpgrade]] = relationship(
        "ShopUpgrade",
        secondary="shop_upgrade_unit_types",
        primaryjoin="UnitType.unit_type==ShopUpgradeUnitTypes.unit_type",
        secondaryjoin="ShopUpgrade.id==ShopUpgradeUnitTypes.shop_upgrade_id",
        back_populates="compatible_unit_types",
        overlaps="compatible_units,upgrade_types,compatible_units,shop_upgrade,unit_types,type_info",
        order_by=(ShopUpgrade.sort_key, ShopUpgrade.id),
        lazy="select",
        passive_deletes=True)
    tags: Mapped[list[Tags]] = relationship("Tags", secondary="unit_type_tags", back_populates="unit_types", lazy="select", passive_deletes=True)
    unit_type_tags: Mapped[list[UnitTypeTags]] = relationship("UnitTypeTags", back_populates="unit_type_info", overlaps="tags", lazy="select", passive_deletes=True)

class Tags(BaseModel):
    """
    A tag name used to categorize unit types. Many-to-many with UnitType
    via UnitTypeTags.
    """

    __tablename__ = "tags"

    # Table options
    __table_args__ = (
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'sqlite_with_rowid': False},
    )

    name: Mapped[str] = mapped_column(String(30), primary_key=True, nullable=False)
    unit_types: Mapped[list[UnitType]] = relationship("UnitType", secondary="unit_type_tags", back_populates="tags", overlaps="unit_type_tags", lazy="select", passive_deletes=True)
    unit_type_tags: Mapped[list[UnitTypeTags]] = relationship("UnitTypeTags", back_populates="tag_info", overlaps="tags,unit_types", lazy="select", passive_deletes=True)

class UnitTypeTags(BaseModel):
    __tablename__ = "unit_type_tags"

    # Table options (PKs are implicitly indexed)
    __table_args__ = (
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'sqlite_with_rowid': False},
    )

    unit_type: Mapped[str] = mapped_column(ForeignKey("unit_types.unit_type", ondelete="CASCADE"), primary_key=True, nullable=False)
    tag: Mapped[str] = mapped_column(ForeignKey("tags.name", ondelete="CASCADE"), primary_key=True, nullable=False)
    unit_type_info: Mapped[UnitType] = relationship("UnitType", back_populates="unit_type_tags", overlaps="tags,unit_types", lazy="joined", passive_deletes=True)
    tag_info: Mapped[Tags] = relationship("Tags", back_populates="unit_type_tags", overlaps="tags,unit_types", lazy="joined", passive_deletes=True)

class UnitHistory(BaseModel):
    """
    Historical record of a unit's presence in a campaign (unit_id +
    campaign_name). Used for audit or history views.
    """

    __tablename__ = "unit_history"

    __table_args__ = (
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci', 'sqlite_with_rowid': False},
    )

    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    campaign_name: Mapped[str] = mapped_column(String(30), nullable=False, primary_key=True)

    unit: Mapped[Unit] = relationship("Unit", back_populates="unit_history", lazy="joined", passive_deletes=True)
    # we don't have a relationship to the campaign, because campaigns get deleted when they end
    # but we populate this table before that happens

create_all = BaseModel.metadata.create_all
Base = BaseModel # alias just for external tooling convenience

def ConfigDict(sessionmaker: Callable):
    class _ConfigDict(MutableMapping[str, Any]):
        def __init__(self):
            old = self.get("BOT_CONFIG")
            if old:
                self["dossier_channel_id"] = old.value["dossier_channel_id"]
                self["statistics_channel_id"] = old.value["statistics_channel_id"]
                del self["BOT_CONFIG"]

        @utils.uses_db(sessionmaker)
        def __getitem__(self, key: str, session: Session, /) -> Any:
            try:
                return session.get(Config, key).value
            except AttributeError:
                raise KeyError(key)

        @utils.uses_db(sessionmaker)
        def __setitem__(self, key: str, value: Any, session: Session, /) -> None:
            config = session.get(Config, key)
            if config:
                config.value = value
            else:
                config = Config(key=key, value=value)
                session.add(config)

        @utils.uses_db(sessionmaker)
        def __delitem__(self, key: str, session: Session, /) -> None:
            s = session.query(Config).filter(Config.key == key).delete()
            if s == 0:
                raise KeyError(key)

        @utils.uses_db(sessionmaker)
        def __iter__(self, session: Session, /) -> Iterator[str]:
            for k in session.execute(select(Config.key)).scalars().all():
                yield k

        @utils.uses_db(sessionmaker)
        def __len__(self, session: Session, /) -> int:
            return session.query(Config).count()

        @utils.uses_db(sessionmaker)
        def __contains__(self, key: str, session: Session, /) -> bool:
            return session.get(Config, key) is not None

        def get(self, key: str, default: Any = None, /) -> Any:
            try:
                return self[key]
            except KeyError:
                return default

        @utils.uses_db(sessionmaker)
        def items(self, session: Session, /) -> Iterator[tuple[str, Any]]:
            for k, v in session.execute(select(Config.key, Config.value)).tuples().all():
                yield k, v

        @utils.uses_db(sessionmaker)
        def keys(self, session: Session, /) -> Iterator[str]:
            for k in session.execute(select(Config.key)).scalars().all():
                yield k

        @utils.uses_db(sessionmaker)
        def values(self, session: Session, /) -> Iterator[Any]:
            for v in session.execute(select(Config.value)).scalars().all():
                yield v

        def clear(self, /) -> None:
            raise NotImplementedError("clear is not implemented for ConfigDict for safety reasons")
    return _ConfigDict()


# MySQL-only triggers to coerce NULLs to defaults at the DB layer
# Drop triggers before creating (idempotent), then create them after tables exist
event.listen(
    BaseModel.metadata,
    "before_create",
    DDL("DROP TRIGGER IF EXISTS bi_players_lore_default").execute_if(dialect="mysql")
)
event.listen(
    BaseModel.metadata,
    "before_create",
    DDL("DROP TRIGGER IF EXISTS bi_shop_upgrades_cost_default").execute_if(dialect="mysql")
)

@event.listens_for(BaseModel.metadata, "after_create")
def _conditionally_create_triggers(metadata, connection, **kw):
    if connection.dialect.name == "mysql":
        try:
            ok = connection.execute(text("SELECT @@GLOBAL.log_bin_trust_function_creators")).scalar()
        except Exception:
            ok = None
        if ok != 1:
            return  # don't attempt to create triggers under binary logging restrictions
        # Create triggers for MySQL
        connection.execute(text(
            "CREATE TRIGGER bi_players_lore_default "
            "BEFORE INSERT ON players FOR EACH ROW "
            "BEGIN IF NEW.lore IS NULL THEN SET NEW.lore = ''; END IF; END"
        ))
        connection.execute(text(
            "CREATE TRIGGER bi_shop_upgrades_cost_default "
            "BEFORE INSERT ON shop_upgrades FOR EACH ROW "
            "BEGIN IF NEW.cost IS NULL THEN SET NEW.cost = 0; END IF; END"
        ))
    elif connection.dialect.name == "sqlite":
        # SQLite cannot assign to NEW.* in BEFORE triggers; use AFTER INSERT and update the just-inserted row
        connection.execute(text(
            "CREATE TRIGGER IF NOT EXISTS ai_players_lore_default "
            "AFTER INSERT ON players FOR EACH ROW "
            "WHEN NEW.lore IS NULL "
            "BEGIN "
            "  UPDATE players SET lore = '' WHERE rowid = NEW.rowid; "
            "END;"
        ))
        connection.execute(text(
            "CREATE TRIGGER IF NOT EXISTS ai_shop_upgrades_cost_default "
            "AFTER INSERT ON shop_upgrades FOR EACH ROW "
            "WHEN NEW.cost IS NULL "
            "BEGIN "
            "  UPDATE shop_upgrades SET cost = 0 WHERE rowid = NEW.rowid; "
            "END;"
        ))

    # After creating tables, enforce NOT NULL at MySQL only where needed
    if connection.dialect.name == "mysql":
        # players.lore should be NOT NULL with default ''
        connection.execute(text(
            "ALTER TABLE players MODIFY lore VARCHAR(1000) NOT NULL DEFAULT ''"
        ))
        # shop_upgrades.cost should be NOT NULL with default 0
        connection.execute(text(
            "ALTER TABLE shop_upgrades MODIFY cost INTEGER NOT NULL DEFAULT 0"
        ))