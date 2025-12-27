from collections.abc import Mapping
import inspect
import logging
import re
import os
from functools import lru_cache, wraps
from inspect import Parameter, Signature
import traceback
from types import FunctionType
import discord
from sqlalchemy.orm import scoped_session
from sqlalchemy import ColumnElement, true
from sqlalchemy.exc import OperationalError
from logging import Logger, getLogger
import asyncio
from collections import deque
from typing import Any, Coroutine, Callable, Generator, Iterable, ParamSpec, TypeVar, Iterator, cast
from discord import Interaction, abc, app_commands as ac
import pandas as pd
from prometheus_client import Counter

CustomClient = None

logger = getLogger(__name__)

@lru_cache(maxsize=1)
def get_url_pattern() -> re.Pattern:
    """
    Lazily initializes and caches the regex pattern for matching invalid URLs
    based on a comma-separated list of allowed domains in an environment variable.

    Returns:
        re.Pattern: Compiled regex pattern for detecting invalid URLs.
    """
    # Get the allowed domains from the environment variable
    allowed_domains = os.getenv("ALLOWED_DOMAINS", "")
    allowed_domains_list = [domain.strip() for domain in allowed_domains.split(",") if domain.strip()]
    allowed_domains_regex = "|".join(re.escape(domain) for domain in allowed_domains_list)

    if not allowed_domains:
        return re.compile("(?=a)b") # dummy pattern that matches nothing, just to prevent any errors

    # Compile and returwn the regex pattern
    logger.info(rf"domains: https?:\/\/(?!{allowed_domains_regex})(?:[\w.-]+\.\w+)(?:\/\S*)?")
    return re.compile(
        rf"https?:\/\/(?!{allowed_domains_regex})(?:[\w.-]+\.\w+)(?:\/\S*)?"
    )

def has_invalid_url(text: str) -> bool:
    """
    Checks if a string contains any URL that does not belong to the allowed domains.

    Args:
        text (str): The string to check.

    Returns:
        bool: True if an invalid URL exists, False otherwise.
    """
    pattern = get_url_pattern()
    result = pattern.search(text)
    logger.info(f"has_invalid_url result: {result}")
    return bool(result)

class RollbackException(Exception):
    pass

async def _notify_owner_mysql_error_4031():
    """Helper function to notify the bot owner about MySQL error 4031"""
    try:
        global CustomClient
        if CustomClient is None:
            from customclient import CustomClient
        bot = CustomClient()
        owner_id = int(os.getenv("BOT_OWNER_ID"))
        owner = await bot.fetch_user(owner_id)
        if owner:
            await owner.send("⚠️ **MySQL Error 4031 Detected**\n\nThe bot encountered MySQL error 4031 (client disconnected by server). Please restart the bot.")
            logger.info(f"Notified owner {owner_id} about MySQL error 4031")
    except Exception as notify_error:
        logger.error(f"Failed to notify owner about MySQL error 4031: {notify_error}")

def uses_db(sessionmaker):
    session_scope = scoped_session(sessionmaker)
    def decorator(func):
        logger.debug(f"decorating {func.__name__}")
        original_signature = Signature.from_callable(func)
        new_params = [param for name, param in original_signature.parameters.items() if name != "session"]
        new_signature = original_signature.replace(parameters=new_params)
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def wrapper(*args, **kwargs): 
                with session_scope() as session:
                    try:
                        logger.debug(f"calling {func.__name__}")
                        result = await func(*args, session=session, **kwargs)
                        logger.debug(f"commiting session for {func.__name__}")
                        session.commit()
                        logger.debug(f"committed session for {func.__name__}")
                        return result
                    except RollbackException:
                        logger.debug(f"rolling back session for {func.__name__}")
                        session.rollback()
                        logger.debug(f"rolled back session for {func.__name__}")
                        return None
                    except OperationalError as e:
                        # Check for MySQL error 4031 (client disconnected by server)
                        error_code = None
                        if hasattr(e, 'orig'):
                            # Try errno first (PyMySQL)
                            if hasattr(e.orig, 'errno'):
                                error_code = e.orig.errno
                            # Fall back to args[0] if errno not available
                            elif hasattr(e.orig, 'args') and len(e.orig.args) > 0:
                                error_code = e.orig.args[0]
                        
                        if error_code == 4031:
                            logger.error(f"MySQL OperationalError 4031 detected in {func.__name__}, notifying owner")
                            try:
                                await _notify_owner_mysql_error_4031()
                            except Exception as notify_error:
                                logger.error(f"Failed to notify owner about MySQL error 4031: {notify_error}")
                        logger.debug(f"rolling back session for {func.__name__} due to OperationalError")
                        session.rollback()
                        logger.debug(f"rolled back session for {func.__name__} due to OperationalError")
                        raise e
                    except Exception as e:
                        logger.debug(f"rolling back session for {func.__name__} due to unhandled exception")
                        session.rollback()
                        logger.debug(f"rolled back session for {func.__name__} due to unhandled exception")
                        raise e
        else:
            @wraps(func)
            def wrapper(*args, **kwargs):
                with session_scope() as session:
                    try:
                        logger.debug(f"calling {func.__name__}")
                        result = func(*args, session=session, **kwargs)
                        logger.debug(f"commiting session for {func.__name__}")
                        session.commit()
                        logger.debug(f"committed session for {func.__name__}")
                        return result
                    except RollbackException:
                        logger.debug(f"rolling back session for {func.__name__}")
                        session.rollback()
                        logger.debug(f"rolled back session for {func.__name__}")
                        return None
                    except OperationalError as e:
                        # Check for MySQL error 4031 (client disconnected by server)
                        error_code = None
                        if hasattr(e, 'orig'):
                            # Try errno first (PyMySQL)
                            if hasattr(e.orig, 'errno'):
                                error_code = e.orig.errno
                            # Fall back to args[0] if errno not available
                            elif hasattr(e.orig, 'args') and len(e.orig.args) > 0:
                                error_code = e.orig.args[0]
                        
                        if error_code == 4031:
                            logger.error(f"MySQL OperationalError 4031 detected in {func.__name__}, notifying owner")
                            try:
                                # For sync functions, create a task to notify asynchronously
                                try:
                                    loop = asyncio.get_running_loop()
                                    asyncio.create_task(_notify_owner_mysql_error_4031())
                                except RuntimeError:
                                    # No running loop, create a new one
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    loop.run_until_complete(_notify_owner_mysql_error_4031())
                                    loop.close()
                            except Exception as notify_error:
                                logger.error(f"Failed to notify owner about MySQL error 4031: {notify_error}")
                        logger.debug(f"rolling back session for {func.__name__} due to OperationalError")
                        session.rollback()
                        logger.debug(f"rolled back session for {func.__name__} due to OperationalError")
                        raise e
                    except Exception as e:
                        logger.debug(f"rolling back session for {func.__name__} due to unhandled exception")
                        session.rollback()
                        logger.debug(f"rolled back session for {func.__name__} due to unhandled exception")
                        raise e
        wrapper.__signature__ = new_signature # type: ignore[attr-defined]
        return wrapper
    return decorator


def string_to_list(string: str) -> list[str]:
    if "\n" in string[:40]:
        string = set(string.split("\n")) # type: ignore
    else:
        string = set(string.split(",")) # type: ignore
    string = [name.strip() for name in string] # type: ignore
    return string # type: ignore

class RollingCounter:
    def __init__(self, duration: int):
        """
        Initializes the RollingCounter with a specified duration and event loop.

        :param duration: Duration in seconds to keep each increment active. Must be > 0.
        :param loop: Optional asyncio event loop to use. Defaults to asyncio.get_event_loop().
        """
        if duration <= 0:
            raise ValueError("Duration must be greater than 0.")
        self.duration = duration
        self.counter = 0
        self.tasks = deque()

    async def _decrement_after_delay(self):
        """Waits for the specified duration, then decrements the counter."""
        await asyncio.sleep(self.duration)
        self.counter -= 1
         
        self.tasks.popleft()  # Remove the completed task from the queue

    def set(self):
        """
        Increments the counter and schedules a task to decrement it after the duration.
        """
        self.counter += 1

        try:
            asyncio.get_running_loop()
            task = asyncio.create_task(self._decrement_after_delay())
        except RuntimeError:
            self.counter -= 1
            print("no loop")
            return # break early if we're not in an event loop, since we can't make the decrement task
         
        self.tasks.append(task)

    def get(self) -> int:
        """
        Returns the current value of the counter.
        """
        return self.counter

    def average(self) -> float:
        """
        Returns the average number of increments per second over the duration.

        :return: Average value (counter / duration)
        """
        return self.counter / self.duration

    def __str__(self):
        return str(self.counter) # make it easy to use in templates
    
    def __repr__(self):
        return f"RollingCounter(duration={self.duration}, counter={self.counter})"
    
    def __iadd__(self, _):
        """
        Increment the counter by 1, regardless of the value of the argument, and return the counter
        """
        self.set()
        return self

class RollingCounterDict:
    def __init__(self, duration: int):
        """
        Initializes a RollingCounterDict with a specified duration for each counter.

        :param duration: Duration in seconds for each RollingCounter. Must be > 0.
        :param loop: Optional asyncio event loop to use. Defaults to asyncio.get_event_loop().
        """
        if duration <= 0:
            raise ValueError("Duration must be greater than 0.")
        self.duration = duration
        self.counters: dict[str, RollingCounter] = {}

    def set(self, key: str):
        """
        Increments the counter for the given key, initializing it if it doesn't exist.

        :param key: The key for the counter to increment.
        """
        if key not in self.counters:
            self.counters[key] = RollingCounter(self.duration)
        self.counters[key].set()

    def get(self, key: str) -> int|float:
        """
        Returns the current value of the counter for the given key, or 0.0 as a sentinel if the key doesn't exist.

        :param key: The key for the counter.
        :return: The current value of the counter or 0.0.
        """
        if key in self.counters:
            return self.counters[key].get()
        return float(0)

    def __setitem__(self, key: str, _: None):
        """
        Increments the counter for the given key, initializing it if it doesn't exist.

        :param key: The key for the counter to increment.
        """
        self.set(key)

    def __getitem__(self, key: str) -> int|float:
        """
        Returns the current value of the counter for the given key, or 0.0 as a sentinel if the key doesn't exist.

        :param key: The key for the counter.
        :return: The current value of the counter or 0.0.
        """
        return self.get(key)

    def __str__(self):
        """
        Returns a newline-separated string of the keys and their counts
        """
        return "\n".join([f"{key}: {self.get(key)}" for key in self.counters])
    
    def values(self) -> list[int|float]:
        """
        Returns a list of the values of the counters
        """
        return [self.get(key) for key in self.counters]
    
def chunk_list(lst: list, chunk_size: int) -> list[list]:
    """Splits a list into chunks of specified size."""
    if chunk_size <= 0:
        raise ValueError("Chunk size must be greater than 0")
    
    # Create chunks for all but the last chunk
    chunks = [lst[i:i + chunk_size] for i in range(0, len(lst) - len(lst) % chunk_size, chunk_size)]
    
    # Handle the last chunk if there are remaining elements
    if len(lst) % chunk_size != 0:
        chunks.append(lst[-(len(lst) % chunk_size):])
    
    return chunks

P = TypeVar("P")

class Paginator:
    # a bidirectional iterator over a list of items, with a constrained view size
    def __init__(self, items: list[P], view_size: int):
        self.items = chunk_list(items, view_size)
        self.index = 0

    def __iter__(self) -> Iterator[list[P]]:
        return self
    
    def next(self, is_iter: bool = False) -> list[P]:
        logger.debug(f"Paginator.next() called: current_index={self.index}, total_items={len(self.items)}, is_iter={is_iter}")
        
        old_index = self.index
        self.index += 1
        if self.index >= len(self.items):
            logger.debug(f"Index {self.index} >= len({len(self.items)}), at end of items")
            if is_iter:
                logger.debug("Raising StopIteration for iterator mode")
                raise StopIteration
            else:
                logger.debug(f"Non-iterator mode: setting index to {len(self.items) - 1} and returning last item")
                self.index = len(self.items) - 1
                return self.items[self.index] # bump off the end and return the same item
        
        logger.debug(f"Index incremented: {old_index} -> {self.index}, returning item at new index")
        return self.items[self.index]
    
    def previous(self) -> list[P]:
        if self.index == 0:
            return self.items[self.index]
        self.index -= 1
        return self.items[self.index]
    
    def __next__(self) -> list[P]:
        return self.next(True)
    
    def current(self) -> list[P]:
        return self.items[self.index]
    
    def has_next(self) -> bool:
        return self.index < len(self.items) - 1 if len(self.items) > 1 else False
    
    def has_previous(self) -> bool:
        return self.index > 0 if len(self.items) > 1 else False
    
    def __len__(self) -> int:
        return len(self.items)
    
async def callback_listener(callback: Coroutine, bind:str):
    address, port = bind.split(":")

    async def listener(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            await callback()
            writer.write(b"200 OK") # just send a 200 ok response, not with any proper headers, since nc doesn't care about them
            await writer.drain()
        except Exception as e:
            logger.error(f"Error in callback_listener: {e}")
            writer.write(b"500 Internal Server Error")
            await writer.drain()
        finally:
            writer.close()


    try:
        server = await asyncio.start_server(listener, address, port)
        await server.serve_forever()
    except Exception as e:
        logger.error(f"Error in callback_listener: {e}") # we don't want to crash the bot if the callback happens twice, which would OSE 98
        return

def check_notify(message: str = "You are not allowed to run this command"):
    message = message.strip() 
    def decorator(func: Callable[[Interaction], bool]):
        @wraps(func)
        async def wrapper(interaction: Interaction, *args, **kwargs):
            result = await func(interaction, *args, **kwargs)
            if not result:
                if not interaction.response.is_done():
                    await interaction.response.send_message(message, ephemeral=True)
            return result
        return wrapper
    return decorator


@check_notify(message="You don't have permission to run this command")
async def is_management(interaction: Interaction, silent: bool = False) -> bool:
    """Check if a user has management permissions"""
    global CustomClient
    if CustomClient is None:
        from customclient import CustomClient
    valid = any(role in interaction.user.roles for role in [interaction.guild.get_role(role_id) for role_id in CustomClient().mod_roles])
    if not silent:
        logger.info(f"{interaction.user.name} is management: {valid}")
    return valid

async def is_management_no_notify(interaction: Interaction, silent: bool = False) -> bool:
    """Check if a user has management permissions"""
    global CustomClient
    if CustomClient is None:
        from customclient import CustomClient
    valid = any(role in interaction.user.roles for role in [interaction.guild.get_role(role_id) for role_id in CustomClient().mod_roles])
    if not silent:
        logger.info(f"{interaction.user.name} is management: {valid}")
    return valid

async def is_gm(interaction: Interaction, silent: bool = False) -> bool:
    """Check if a user has GM permissions"""
    is_management_result = await is_management(interaction, silent)
    is_gm_role = interaction.guild.get_role(CustomClient().gm_role) in interaction.user.roles
    if not silent:
        logger.info(f"{interaction.user.name} is management: {is_management_result}, is gm: {is_gm_role}")
    valid = is_gm_role or is_management_result
    if not valid:
        await interaction.response.send_message("You don't have permission to run this command", ephemeral=True)
    return valid

def filter_df(df: pd.DataFrame, col_name: str, filter: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    mask = df[col_name].astype(str).isin(filter)
    logger.debug(mask.any())
    return df[mask], df[~mask]

async def toggle_command_ban(desired_state: bool, initiator: str):
    global CustomClient
    if CustomClient is None:
        from customclient import CustomClient
    current_state = CustomClient().tree.interaction_check == CustomClient().check_banned_interaction
    if current_state == desired_state:
        return current_state
    CustomClient().tree.interaction_check = CustomClient().check_banned_interaction if desired_state else CustomClient().no_commands
    
    # Create/remove maintenance.flag file based on command ban state
    if not desired_state:
        # Command ban is active - create maintenance flag
        try:
            open("maintenance.flag", "w").close()
        except Exception:
            pass  # Ignore file creation failures
    else:
        # Command ban is not active - remove maintenance flag
        try:
            os.unlink("maintenance.flag")
        except FileNotFoundError:
            pass  # Ignore if file doesn't exist
        except Exception:
            pass  # Ignore other failures
    
    if not desired_state:
        comm_net_id = os.getenv("COMM_NET_CHANNEL_ID")
        if comm_net_id:
            comm_net = CustomClient().get_channel(int(comm_net_id))
            if comm_net:
                await comm_net.send(f"# Command ban has been enabled by {initiator}")
        logger.info(f"Command ban enabled by {initiator}")
    else:
        comm_net_id = os.getenv("COMM_NET_CHANNEL_ID")
        if comm_net_id:
            comm_net = CustomClient().get_channel(int(comm_net_id))
            if comm_net:
                await comm_net.send(f"# Command ban has been disabled by {initiator}")
        logger.info(f"Command ban disabled by {initiator}")
    return desired_state

async def is_server(interaction: Interaction) -> bool:
    """Check if a command is being run in a server"""
    return interaction.guild is not None

async def is_dm(interaction: Interaction) -> bool:
    """Check if a command is being run in a DM"""
    return interaction.guild is None

def error_reporting(verbose: None | bool = None):
    
    logger.debug(f"Applying @error_reporting with verbose={verbose}")

    format_error = (
        (lambda e: f"```\n{''.join(traceback.format_exception(e)).strip()[:1990]}\n```") if verbose is True
        else (lambda e: f"Something went wrong: `{type(e).__name__}`") if verbose is False
        else (lambda _: "Something went wrong.")
    )

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_msg = format_error(e)
                
                # Find the Interaction object in the arguments
                interaction = None
                for arg in args:
                    if isinstance(arg, discord.Interaction):
                        interaction = arg
                        break
                
                if interaction:
                    if interaction.response.is_done():
                        await interaction.followup.send(error_msg, ephemeral=True)
                    else:
                        await interaction.response.send_message(error_msg, ephemeral=True)

                raise

        return wrapper

    return decorator

def on_error_decorator(counter: Counter):
    def decorator(func: Callable[[Interaction, Exception], Coroutine]):
        @wraps(func)
        async def wrapper(interaction: Interaction, error: Exception):
            counter.labels(guild_name="total", error=type(error).__name__).inc()
            counter.labels(guild_name=interaction.guild.name if interaction.guild else "DMs", error=type(error).__name__).inc()
            return await func(interaction, error)
        return wrapper
    return decorator

def inject(**_kwargs):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            kwargs_ = {**_kwargs, **kwargs}
            return func(*args, **kwargs_)
        return wrapper
    return decorator

def with_log_level(logger: Logger|str, level: int = logging.DEBUG):
    if isinstance(logger, str):
        logger = getLogger(logger)
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            old_level = logger.level
            logger.setLevel(level)
            try:
                return func(*args, **kwargs)
            finally:
                logger.setLevel(old_level)
        return wrapper
    return decorator

class RatelimitError(Exception):
    def __init__(self, message: str = "Ratelimit exceeded"):
        super().__init__(message)

class DelayedReleaseSemaphore(asyncio.Semaphore):
    def __init__(self, max_concurrent: int, delay: float):
        if delay <= 0: raise ValueError("Delay must be greater than 0")
        if max_concurrent <= 0: raise ValueError("Max concurrent must be greater than 0")
        self.delay = delay
        super().__init__(max_concurrent)

    def acquire_nowait(self) -> bool:
        if self._value == 0: raise RatelimitError()
        self._value -= 1
        return True

    def release(self):
        loop = asyncio.get_running_loop()
        loop.call_later(self.delay, super().release)

class UserSemaphore(Mapping[abc.User, DelayedReleaseSemaphore]):
    def __init__(self, max_concurrent: int, delay: float):
        if delay <= 0: raise ValueError("Delay must be greater than 0")
        if max_concurrent <= 0: raise ValueError("Max concurrent must be greater than 0")
        self.max_concurrent = max_concurrent
        self.delay = delay
        self._store = dict[int, DelayedReleaseSemaphore]()

    def __setitem__(self, user: abc.User, semaphore: DelayedReleaseSemaphore):
        raise NotImplementedError("UserSemaphore is read-only")

    def __getitem__(self, user: abc.User) -> DelayedReleaseSemaphore:
        if not isinstance(user, abc.User): raise TypeError("User must be a discord.User or discord.Member")
        if user.id not in self._store:
            self._store[user.id] = DelayedReleaseSemaphore(self.max_concurrent, self.delay)
        return self._store[user.id]

    def __len__(self) -> int:
        return len(self._store)

    def __iter__(self) -> Iterator[abc.User]:
        return iter(self._store)

    def __contains__(self, user: abc.User) -> bool:
        return user.id in self._store

# Global cache registry for fuzzy autocomplete caches
fuzzy_autocomplete_caches: list = []  # list of all the caches for the autocompletes. which we only ever add to, never remove from

def fuzzy_autocomplete(column: ColumnElement[str], *union_columns: ColumnElement[str], not_null: bool = False):
    """
    Creates a fuzzy autocomplete function for Discord slash commands.
    
    Args:
        column: The primary SQLAlchemy column to search
        *union_columns: Additional columns to search and union with the primary column
        not_null: Whether to filter out null values from the results
    
    Returns:
        An async autocomplete function that can be used with Discord's @app_commands.autocomplete decorator
    """
    global CustomClient
    if CustomClient is None:
        from customclient import CustomClient
    
    lookup = lru_cache(maxsize=100)(
        uses_db(CustomClient().sessionmaker)(
            lambda current, session: tuple(
                row[0] for row in (
                    session.query(column.label("value"))
                    .filter((column.isnot(None)) if not_null else true())
                    .union_all(*(session.query(union_column.label("value")) for union_column in union_columns))
                    .distinct()
                    .limit(25)
                    .all()
                 if not current else
                    session.query(column.label("value"))
                    .filter(column.ilike(f"%{current}%"), (column.isnot(None)) if not_null else true())
                    .union_all(*(session.query(union_column.label("value")).filter(union_column.ilike(f"%{current}%"), (union_column.isnot(None)) if not_null else true()) for union_column in union_columns))
                    .distinct()
                    .limit(25)
                    .all()))))
    
    async def autocomplete(interaction: Interaction, current: str):
        return [ac.Choice(name=item, value=item) for item in lookup(current.strip().lower())]
    
    # Register the cache in the global registry
    fuzzy_autocomplete_caches.append(lookup)
    return autocomplete

class EnvironHelpers:
    """
    A class for getting environment variables with defaults and type coercion.

    This class is not instantiable, and is used as a namespace for the static methods.
    """
    def __new__(cls):
        raise TypeError(f"{cls.__name__} is static and cannot be instantiated")

    @staticmethod
    def get_bool(key: str, default: bool = False) -> bool:
        return os.getenv(key).lower() in ["true", "1", "yes", "y"] if os.getenv(key) else default

    @staticmethod
    def get_int(key: str, default: int = 0) -> int:
        return int(os.getenv(key)) if os.getenv(key) else default

    @staticmethod
    def get_float(key: str, default: float = 0.0) -> float:
        return float(os.getenv(key)) if os.getenv(key) else default

    @staticmethod
    def get_str(key: str, default: str = "") -> str:
        return os.getenv(key, default) # getenv is already str, so we just return it directly

    @staticmethod
    def get_log_level(key: str, default: str = "INFO") -> int:
        value = os.getenv(key, default).upper()
        return logging.getLevelNamesMapping().get(value, logging.INFO) # default to INFO if the value is not a valid log level

P = ParamSpec("P")
R = TypeVar("R")
F = Callable[P, R]

def maybe_decorate(condition: bool, decorator: Callable[[F], F]) -> Callable[[F], F]:
    def _apply(func: F) -> F:
        if not condition:
            if inspect.iscoroutinefunction(func):
                @wraps(func)
                async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    return await func(*args, **kwargs)
                return cast(F, wrapper) if isinstance(func, FunctionType) else func
            else:
                @wraps(func)
                def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    return func(*args, **kwargs)
                return cast(F, wrapper) if isinstance(func, FunctionType) else func

        decorated = decorator(func)

        # If decorator returns a non-FunctionType (e.g., Command from ac.command()),
        # return it directly so GroupCog can scan for it
        if not isinstance(decorated, FunctionType):
            return decorated

        if inspect.iscoroutinefunction(decorated):
            if getattr(decorated, "__wrapped__", None) is None:
                @wraps(func)
                async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    return await decorated(*args, **kwargs)
                return cast(F, wrapper)
            else:
                @wraps(decorated)
                async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    return await decorated(*args, **kwargs)
                return cast(F, wrapper)
        else:
            if getattr(decorated, "__wrapped__", None) is None:
                @wraps(func)
                def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    return decorated(*args, **kwargs)
                return cast(F, wrapper)
            else:
                @wraps(decorated)
                def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    return decorated(*args, **kwargs)
                return cast(F, wrapper)

    return _apply

def hide_arg(arg_name: str, default: Any) -> Callable[[F], F]:
    """
    Remove `arg_name` from the function's *visible* signature (via __signature__)
    so frameworks like discord.app_commands do not see it. At call time, inject
    `arg_name=default`. We do not accept callers passing this arg explicitly.
    """
    def _decorator(func: F) -> F:
        sig = Signature.from_callable(func)
        if arg_name not in sig.parameters:
            raise ValueError(f"{func.__name__} has no parameter named {arg_name!r}")

        param = sig.parameters[arg_name]
        if param.kind is Parameter.POSITIONAL_ONLY:
            raise ValueError(
                f"Cannot hide positional-only parameter {arg_name!r}; "
                "make it keyword-capable (pos-or-kw or kw-only)."
            )
        if param.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
            raise ValueError(
                f"Cannot hide variadic parameter {arg_name!r} (*args/**kwargs)."
            )

        # Build the visible signature without the hidden parameter
        new_params = [p for n, p in sig.parameters.items() if n != arg_name]
        new_sig = sig.replace(parameters=new_params)

        # Optional: trim annotations for nicer help()
        new_annotations = dict(getattr(func, "__annotations__", {}))
        new_annotations.pop(arg_name, None)

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Validate/normalize incoming args against the visible signature
                bound_visible = new_sig.bind_partial(*args, **kwargs)
                bound_visible.apply_defaults()

                # Reconstruct full call mapping for the original function
                call_map = dict(bound_visible.arguments)
                call_map[arg_name] = default

                # Bind to the real signature to respect kinds/order/defaults
                bound_full = sig.bind_partial(**call_map)
                bound_full.apply_defaults()

                return await func(*bound_full.args, **bound_full.kwargs)
        else:
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Validate/normalize incoming args against the visible signature
                bound_visible = new_sig.bind_partial(*args, **kwargs)
                bound_visible.apply_defaults()

                # Reconstruct full call mapping for the original function
                call_map = dict(bound_visible.arguments)
                call_map[arg_name] = default

                # Bind to the real signature to respect kinds/order/defaults
                bound_full = sig.bind_partial(**call_map)
                bound_full.apply_defaults()

                return func(*bound_full.args, **bound_full.kwargs)

        # Make introspection show the hidden-arg-free signature
        wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
        wrapper.__annotations__ = new_annotations  # type: ignore[attr-defined]
        return cast(F, wrapper)
    return _decorator

def chunked_join(items: Iterable[str], chunk_size: int = 2000, separator: str = " ") -> Generator[str, None, None]:
    if chunk_size <= 0:
        raise ValueError("Chunk size must be greater than 0")
    current_chunk = ""
    current_length = 0
    for item in items:
        if len(item) + len(separator) > chunk_size:
            raise ValueError(f"Item {item} is too long to fit in a chunk of size {chunk_size}")
        if current_length + len(item) + len(separator) > chunk_size:
            yield current_chunk
            current_chunk = ""
            current_length = 0
        current_chunk += item + separator
        current_length += len(item) + len(separator)
    if current_chunk:
        yield current_chunk