import asyncio
from collections.abc import Mapping, Sequence
from functools import lru_cache, wraps
import inspect
from inspect import Parameter, Signature
import logging
from logging import Logger, getLogger
import os
import re
import traceback
from types import FunctionType
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Generator, Iterable, Iterator, ParamSpec, TypeVar, cast

import discord
from discord import Interaction, abc, app_commands as ac
import pandas as pd
from prometheus_client import Counter, Gauge
from sqlalchemy import ColumnElement, true
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import scoped_session

if TYPE_CHECKING:
    from customclient import CustomClient
else:
    CustomClient = None

P = TypeVar("P")
T = TypeVar("T", bound=Sequence[Any])
Ps = ParamSpec("Ps")
R = TypeVar("R")
F = Callable[Ps, R]

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
    allowed_domains = EnvironHelpers.get_str("ALLOWED_DOMAINS", "")
    allowed_domains_list = [domain.strip() for domain in allowed_domains.split(",") if domain.strip()]
    allowed_domains_regex = "|".join(re.escape(domain) for domain in allowed_domains_list)

    if not allowed_domains:
        return re.compile("(?=a)b") # dummy pattern that matches nothing, just to prevent any errors

    # Compile and return the regex pattern
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
    """
    Exception raised to signal that the current database transaction should be
    rolled back without re-raising. Used with uses_db-decorated functions;
    when raised, the session is rolled back and the function returns None.
    """

    pass

async def _notify_owner_mysql_error_4031():
    """
    Notify the bot owner when MySQL error 4031 (client disconnected by server)
    is detected. Sends a Discord message asking them to restart the bot.
    """

    try:
        global CustomClient
        if CustomClient is None:
            from customclient import CustomClient
        bot = CustomClient()
        owner_id = EnvironHelpers.required_int("BOT_OWNER_ID")
        owner = await bot.fetch_user(owner_id)
        if owner:
            await owner.send("⚠️ **MySQL Error 4031 Detected**\n\nThe bot encountered MySQL error 4031 (client disconnected by server). Please restart the bot.")
            logger.info(f"Notified owner {owner_id} about MySQL error 4031")
    except Exception as notify_error:
        logger.error(f"Failed to notify owner about MySQL error 4031: {notify_error}")

created_sessions = Counter("armcobot_created_sessions_total", "Total number of sessions created", labelnames=["scope"])
inflight_sessions = Gauge("armcobot_inflight_sessions", "Number of sessions currently in use", labelnames=["scope"])

def fqn(func: Callable) -> str:
    """
    Return the fully qualified name of a callable (module path and name).

    Args:
        func: Any callable (function, method, etc.).

    Returns:
        A string like "module.submodule.function_name", with local and
        lambda placeholders normalized.
    """

    return f"{func.__module__}.{func.__qualname__}".replace(".<locals>.", ".").replace("<lambda>", "lambda")

def uses_db(sessionmaker):
    """
    Decorator that injects a SQLAlchemy scoped session as the `session` keyword
    argument to the wrapped function. Commits on success, rolls back on
    RollbackException or other exceptions. Handles MySQL error 4031 by
    notifying the bot owner.

    Args:
        sessionmaker: A callable that returns a Session (e.g. sessionmaker()
            from SQLAlchemy).

    Returns:
        A decorator that wraps sync or async functions and provides a
        session. The wrapped function must accept a `session` keyword argument.
    """

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
                        logger.debug(f"calling {fqn(func)}")
                        created_sessions.labels(scope=fqn(func)).inc()
                        inflight_sessions.labels(scope=fqn(func)).inc()
                        result = await func(*args, session=session, **kwargs)
                        logger.debug(f"commiting session for {fqn(func)}")
                        session.commit()
                        logger.debug(f"committed session for {fqn(func)}")
                        return result
                    except RollbackException:
                        logger.debug(f"rolling back session for {fqn(func)}")
                        session.rollback()
                        logger.debug(f"rolled back session for {fqn(func)}")
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
                            logger.error(f"MySQL OperationalError 4031 detected in {fqn(func)}, notifying owner")
                            try:
                                await _notify_owner_mysql_error_4031()
                            except Exception as notify_error:
                                logger.error(f"Failed to notify owner about MySQL error 4031: {notify_error}")
                        logger.debug(f"rolling back session for {fqn(func)} due to OperationalError")
                        session.rollback()
                        logger.debug(f"rolled back session for {fqn(func)} due to OperationalError")
                        raise e
                    except Exception as e:
                        logger.debug(f"rolling back session for {fqn(func)} due to unhandled exception")
                        session.rollback()
                        logger.debug(f"rolled back session for {fqn(func)} due to unhandled exception")
                        raise e
                    finally:
                        inflight_sessions.labels(scope=fqn(func)).dec()
        else:
            @wraps(func)
            def wrapper(*args, **kwargs):
                with session_scope() as session:
                    try:
                        logger.debug(f"calling {fqn(func)}")
                        created_sessions.labels(scope=fqn(func)).inc()
                        inflight_sessions.labels(scope=fqn(func)).inc()
                        result = func(*args, session=session, **kwargs)
                        logger.debug(f"commiting session for {fqn(func)}")
                        session.commit()
                        logger.debug(f"committed session for {fqn(func)}")
                        return result
                    except RollbackException:
                        logger.debug(f"rolling back session for {fqn(func)}")
                        session.rollback()
                        logger.debug(f"rolled back session for {fqn(func)}")
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
                            logger.error(f"MySQL OperationalError 4031 detected in {fqn(func)}, notifying owner")
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
                        logger.debug(f"rolling back session for {fqn(func)} due to OperationalError")
                        session.rollback()
                        logger.debug(f"rolled back session for {fqn(func)} due to OperationalError")
                        raise e
                    except Exception as e:
                        logger.debug(f"rolling back session for {fqn(func)} due to unhandled exception")
                        session.rollback()
                        logger.debug(f"rolled back session for {fqn(func)} due to unhandled exception")
                        raise e
                    finally:
                        inflight_sessions.labels(scope=fqn(func)).dec()
        wrapper.__signature__ = new_signature # type: ignore[attr-defined]
        return wrapper
    return decorator


def string_to_list(string: str) -> list[str]:
    """
    Parse a comma- or newline-separated string into a list of stripped
    non-empty items. Used for parsing user input (e.g. unit names).

    Args:
        string: Input string (comma- or newline-separated).

    Returns:
        List of stripped strings (duplicates removed via set).
    """

    if "\n" in string[:40]:
        string = set(string.split("\n")) # type: ignore
    else:
        string = set(string.split(",")) # type: ignore
    string = [name.strip() for name in string] # type: ignore
    return string # type: ignore

class RollingCounter:
    def __init__(self, duration: int):
        """
        Initializes the RollingCounter with a specified duration.

        :param duration: Duration in seconds to keep each increment active. Must be > 0.
        """

        if duration <= 0:
            raise ValueError("Duration must be greater than 0.")
        self.duration = duration
        self.counter = 0

    def _decrement(self):
        """
        Decrement the counter after the scheduled delay. Used internally
        by the event loop after set() is called.
        """

        self.counter -= 1

    def set(self):
        """
        Increments the counter and schedules a callback to decrement it after the duration.
        """

        self.counter += 1

        try:
            loop = asyncio.get_running_loop()
            loop.call_later(self.duration, self._decrement)
        except RuntimeError:
            self.counter -= 1
            print("no loop")
            return # break early if we're not in an event loop, since we can't schedule the decrement

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
    """
    A dict of RollingCounters keyed by string. Each key has its own
    auto-decrementing counter with the same duration. Used for per-key
    rate limiting or counts.
    """

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

def chunk_list(lst: T, chunk_size: int) -> list[T]:
    """
    Split a sequence into contiguous chunks of a given size.

    Args:
        lst: The sequence to chunk (e.g. list or str).
        chunk_size: Maximum size of each chunk. Must be positive.

    Returns:
        A list of subsequences; the last may be shorter if len(lst)
        is not divisible by chunk_size.

    Raises:
        ValueError: If chunk_size is less than or equal to zero.
    """

    if chunk_size <= 0:
        raise ValueError("Chunk size must be greater than 0")

    # Create chunks for all but the last chunk
    chunks = [lst[i:i + chunk_size] for i in range(0, len(lst) - len(lst) % chunk_size, chunk_size)]

    # Handle the last chunk if there are remaining elements
    if len(lst) % chunk_size != 0:
        chunks.append(lst[-(len(lst) % chunk_size):])

    return chunks


class Paginator:
    """
    Bidirectional paginator over a list, exposing fixed-size "pages" (slices).
    Used for Discord embeds or UIs that show a limited number of items per view.
    """

    def __init__(self, items: list[P], view_size: int):
        """
        Build a paginator over `items`, with each page having up to `view_size` items.

        Args:
            items: The full list to paginate.
            view_size: Maximum number of items per page.
        """

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

async def callback_listener(callback: Coroutine, bind: str):
    """
    Run an HTTP server on `bind` (e.g. "127.0.0.1:12345") that invokes
    `callback` on each request and responds with 200 OK. Used for shutdown
    or health-check endpoints. Runs until the server is closed.

    Args:
        callback: A coroutine to run on each request (e.g. bot shutdown).
        bind: "address:port" string for the server.
    """

    address, port = bind.split(":")

    async def listener(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            await callback()
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n"
                "Content-Length: 0\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("utf-8")
            writer.write(response)
            await writer.drain()
        except Exception as e:
            logger.error(f"Error in callback_listener: {e}")
            response = (
                "HTTP/1.1 500 Internal Server Error\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n"
                "Content-Length: 0\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("utf-8")
            writer.write(response)
            await writer.drain()
        finally:
            writer.close()


    try:
        server = await asyncio.start_server(listener, address, int(port))
        await server.serve_forever()
    except Exception as e:
        logger.error(f"Error in callback_listener: {e}") # we don't want to crash the bot if the callback happens twice, which would OSE 98
        return

def check_notify(message: str = "You are not allowed to run this command"):
    """
    Decorator that sends an ephemeral message when the wrapped async check
    returns False. Used for permission checks on slash commands.

    Args:
        message: Message to send when the check fails. Defaults to a generic
            permission-denied message.

    Returns:
        A decorator that wraps an async function (Interaction, ...) -> bool.
    """

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
    """
    Check whether the interaction user has a management role. If not silent,
    sends a permission-denied message on failure.

    Args:
        interaction: The Discord interaction (used for user and guild).
        silent: If True, do not send a message when the check fails.

    Returns:
        True if the user has a management role, False otherwise.
    """

    global CustomClient
    if CustomClient is None:
        from customclient import CustomClient
    valid = any(role in interaction.user.roles for role in [interaction.guild.get_role(role_id) for role_id in CustomClient().mod_roles])
    if not silent:
        logger.info(f"{interaction.user.name} is management: {valid}")
    return valid

async def is_management_no_notify(interaction: Interaction, silent: bool = False) -> bool:
    """
    Check whether the interaction user has a management role, without sending
    any message on failure. Used when the caller will handle the response.

    Args:
        interaction: The Discord interaction (used for user and guild).
        silent: If True, avoid logging the result.

    Returns:
        True if the user has a management role, False otherwise.
    """

    global CustomClient
    if CustomClient is None:
        from customclient import CustomClient
    valid = any(role in interaction.user.roles for role in [interaction.guild.get_role(role_id) for role_id in CustomClient().mod_roles])
    if not silent:
        logger.info(f"{interaction.user.name} is management: {valid}")
    return valid

async def is_gm(interaction: Interaction, silent: bool = False) -> bool:
    """
    Check whether the interaction user is a GM (game master) or has management
    permissions. Sends a permission-denied message on failure unless silent.

    Args:
        interaction: The Discord interaction (used for user and guild).
        silent: If True, do not send a message when the check fails.

    Returns:
        True if the user has the GM role or a management role, False otherwise.
    """

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
    """
    Enable or disable the global command ban (maintenance mode). When enabled,
    only management can run commands. Updates interaction_check and
    maintenance.flag; optionally notifies the comm channel.

    Args:
        desired_state: True to enable command ban, False to disable.
        initiator: String identifying who triggered the change (for logging).

    Returns:
        The previous command-ban state (bool).
    """

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
        comm_net_id = EnvironHelpers.required_int("COMM_NET_CHANNEL_ID")
        if comm_net_id:
            comm_net = CustomClient().get_channel(comm_net_id)
            if comm_net:
                await comm_net.send(f"# Command ban has been enabled by {initiator}")
        logger.info(f"Command ban enabled by {initiator}")
    else:
        comm_net_id = EnvironHelpers.required_int("COMM_NET_CHANNEL_ID")
        if comm_net_id:
            comm_net = CustomClient().get_channel(comm_net_id)
            if comm_net:
                await comm_net.send(f"# Command ban has been disabled by {initiator}")
        logger.info(f"Command ban disabled by {initiator}")
    return desired_state

async def is_server(interaction: Interaction) -> bool:
    """
    Check whether the interaction occurred in a guild (server) channel.

    Args:
        interaction: The Discord interaction.

    Returns:
        True if the interaction has a guild, False for DMs.
    """

    return interaction.guild is not None

async def is_dm(interaction: Interaction) -> bool:
    """
    Check whether the interaction occurred in a direct message (no guild).

    Args:
        interaction: The Discord interaction.

    Returns:
        True if the interaction is in a DM, False if in a guild.
    """

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
    """
    Decorator that increments a Prometheus counter by guild and error type
    before calling the wrapped error handler.

    Args:
        counter: A Prometheus Counter with labelnames including "guild_name"
            and "error".

    Returns:
        A decorator for async (interaction, error) handlers.
    """

    def decorator(func: Callable[[Interaction, Exception], Coroutine]):
        @wraps(func)
        async def wrapper(interaction: Interaction, error: Exception):
            counter.labels(guild_name=interaction.guild.name if interaction.guild else "DMs", error=type(error).__name__).inc()
            return await func(interaction, error)
        return wrapper
    return decorator

def inject(**_kwargs):
    """
    Decorator that injects fixed keyword arguments into every call to the
    wrapped function. Caller-provided kwargs override injected ones.

    Args:
        **kwargs: Keyword arguments to inject (e.g. session=None for tests).

    Returns:
        A decorator that adds the given kwargs to the function's call.
    """

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
    """
    Raised when a rate limit is exceeded (e.g. too many requests per user).
    Used by rate-limiting logic to abort the current operation.
    """

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
                    .filter(column.ilike(f"%{current}%") if current else true())
                    .union_all(*(session.query(union_column.label("value"))
                     .filter((union_column.isnot(None)) if not_null else true())
                     .filter(union_column.ilike(f"%{current}%") if current else true())
                     for union_column in union_columns))
                    .distinct()
                    .limit(25)
                    .all()
                )
            )
        )
    )

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
    def _bool(value: str) -> bool:
        return value.lower() in ["true", "1", "yes", "y"]

    @staticmethod
    def _parse_size_bytes(size_str: str) -> int:
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
        >>> EnvironHelpers._parse_size_bytes('10 MB')
        10000000
        >>> EnvironHelpers._parse_size_bytes('5.5 GiB')
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

    @staticmethod
    def get_bool(key: str, default: bool = False) -> bool:
        v = os.getenv(key)
        return EnvironHelpers._bool(v) if v else default

    @staticmethod
    def get_int(key: str, default: int = 0) -> int:
        try:
            v = os.getenv(key)
            return int(v) if v else default
        except ValueError:
            return default

    @staticmethod
    def get_float(key: str, default: float = 0.0) -> float:
        try:
            v = os.getenv(key)
            return float(v) if v else default
        except ValueError:
            return default

    @staticmethod
    def get_str(key: str, default: str = "") -> str:
        return os.getenv(key, default) # getenv is already str, so we just return it directly

    @staticmethod
    def get_log_level(key: str, default: str = "INFO") -> int:
        v = os.getenv(key, default).upper()
        return logging._nameToLevel.get(v, logging.INFO) # default to INFO if the value is not a valid log level

    @staticmethod
    def get_size(key: str, default: str = "0") -> int:
        """
        Get a file size from an environment variable and convert it to bytes.

        This method retrieves a human-readable file size string from an environment variable
        (e.g., '10 MB', '5.5 GiB') and converts it into an integer representing the size in bytes.
        It supports both decimal (e.g., 'KB') and binary (e.g., 'KiB') prefixes.

        Parameters:
        key (str): The environment variable key to retrieve.
        default (str): Default value if the environment variable is not set. Defaults to "0".

        Returns:
        int: The size in bytes.

        Raises:
        ValueError: If the input string is not a valid size format.

        Example:
        >>> EnvironHelpers.get_size('LOG_FILE_SIZE', '10 MB')
        10000000
        """
        size_str = os.getenv(key, default)
        return EnvironHelpers._parse_size_bytes(size_str)

    @staticmethod
    def required_str(key: str) -> str:
        v = os.getenv(key)
        if v is None:
            raise EnvironmentError(f"{key} is not set")
        return v

    @staticmethod
    def required_int(key: str) -> int:
        v = os.getenv(key)
        if v is None:
            raise EnvironmentError(f"{key} is not set")
        return int(v)

    @staticmethod
    def required_float(key: str) -> float:
        v = os.getenv(key)
        if v is None:
            raise EnvironmentError(f"{key} is not set")
        return float(v)

    @staticmethod
    def required_bool(key: str) -> bool:
        v = os.getenv(key)
        if v is None:
            raise EnvironmentError(f"{key} is not set")
        return EnvironHelpers._bool(v)

    @staticmethod
    def required_size(key: str) -> int:
        v = os.getenv(key)
        if v is None:
            raise EnvironmentError(f"{key} is not set")
        return EnvironHelpers._parse_size_bytes(v)

    @staticmethod
    def get_str_list(key: str, default: list[str] = None, separator: str = ";") -> list[str]:
        v = os.getenv(key, default)
        if v is None:
            raise EnvironmentError(f"{key} is not set")
        return [item.strip() for item in v.split(separator)]

    @staticmethod
    def get_int_list(key: str, default: list[int] = None, separator: str = ";") -> list[int]:
        v = os.getenv(key, default)
        if v is None:
            raise EnvironmentError(f"{key} is not set")
        return [int(item) for item in v.split(separator)]

    @staticmethod
    def get_float_list(key: str, default: list[float] = None, separator: str = ";") -> list[float]:
        v = os.getenv(key, default)
        if v is None:
            raise EnvironmentError(f"{key} is not set")
        return [float(item) for item in v.split(separator)]

    @staticmethod
    def get_bool_list(key: str, default: list[bool] = None, separator: str = ";") -> list[bool]:
        v = os.getenv(key, default)
        if v is None:
            raise EnvironmentError(f"{key} is not set")
        return [EnvironHelpers._bool(item) for item in v.split(separator)]

    @staticmethod
    def get_size_list(key: str, default: list[int] = [], separator: str = ";") -> list[int]:
        v = os.getenv(key, default)
        if v is None:
            raise EnvironmentError(f"{key} is not set")
        return [EnvironHelpers._parse_size_bytes(item) for item in v.split(separator)]


def maybe_decorate(condition: bool, decorator: Callable[[F], F]) -> Callable[[F], F]:
    def _apply(func: F) -> F:
        if not condition:
            if inspect.iscoroutinefunction(func):
                @wraps(func)
                async def wrapper(*args: Ps.args, **kwargs: Ps.kwargs) -> R:
                    return await func(*args, **kwargs)
                return cast(F, wrapper) if isinstance(func, FunctionType) else func
            else:
                @wraps(func)
                def wrapper(*args: Ps.args, **kwargs: Ps.kwargs) -> R:
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
                async def wrapper(*args: Ps.args, **kwargs: Ps.kwargs) -> R:
                    return await decorated(*args, **kwargs)
                return cast(F, wrapper)
            else:
                @wraps(decorated)
                async def wrapper(*args: Ps.args, **kwargs: Ps.kwargs) -> R:
                    return await decorated(*args, **kwargs)
                return cast(F, wrapper)
        else:
            if getattr(decorated, "__wrapped__", None) is None:
                @wraps(func)
                def wrapper(*args: Ps.args, **kwargs: Ps.kwargs) -> R:
                    return decorated(*args, **kwargs)
                return cast(F, wrapper)
            else:
                @wraps(decorated)
                def wrapper(*args: Ps.args, **kwargs: Ps.kwargs) -> R:
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
    """
    Join strings into chunks that do not exceed chunk_size (e.g. Discord
    message limit). Yields one chunk per iteration. Useful for splitting
    long messages into multiple sends.

    Args:
        items: Strings to join (e.g. list of lines).
        chunk_size: Maximum length of each chunk. Must be positive.
        separator: String to insert between items (default space).

    Yields:
        Chunks of joined strings, each at most chunk_size characters.

    Raises:
        ValueError: If chunk_size is less than or equal to zero.
    """

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


async def chunked_send(
    interaction: Interaction,
    text: str,
    ephemeral: bool,
    chunk_size: int = 2000,
) -> None:
    """
    Send text to a Discord interaction in chunks that do not exceed chunk_size,
    using chunk_list (strings are iterables, so text is chunked by character).

    Args:
        interaction: The Discord interaction (response or followup used as needed).
        text: The full text to send.
        ephemeral: Whether messages are ephemeral.
        chunk_size: Maximum characters per chunk (default 2000).
    """
    if not text:
        if interaction.response.is_done():
            await interaction.followup.send("", ephemeral=ephemeral)
        else:
            await interaction.response.send_message("", ephemeral=ephemeral)
        return
    if len(text) <= chunk_size:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(text, ephemeral=ephemeral)
        return
    chunks = chunk_list(text, chunk_size)
    send_first = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send_first(chunks[0], ephemeral=ephemeral)
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk, ephemeral=ephemeral)