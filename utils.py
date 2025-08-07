import re
import os
from functools import lru_cache, wraps
from inspect import Signature
import traceback
import discord
from sqlalchemy.orm import scoped_session
from logging import getLogger
import asyncio
from collections import deque
from typing import Coroutine, Callable, TypeVar, Iterator
from discord import Interaction
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

def uses_db(sessionmaker):
    session_scope = scoped_session(sessionmaker)
    def decorator(func):
        logger.debug(f"decorating {func.__name__}")
        original_signature = Signature.from_callable(func)
        new_params = [param for name, param in original_signature.parameters.items() if name != "session"]
        new_signature = original_signature.replace(parameters=new_params)
        @wraps(func)
        async def wrapper(*args, **kwargs): 
            with session_scope() as session: # we are not currently using async with, because the sessionmaker is not async yet
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
                except Exception as e:
                    logger.debug(f"rolling back session for {func.__name__} due to unhandled exception")
                    session.rollback()
                    logger.debug(f"rolled back session for {func.__name__} due to unhandled exception")
                    raise e
        wrapper.__signature__ = new_signature
        return wrapper
    return decorator


def string_to_list(string: str) -> list[str]:
    if "\n" in string[:40]:
        string = set(string.split("\n"))
    else:
        string = set(string.split(","))
    string = [name.strip() for name in string]
    return string

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

    def get(self, key: str) -> int:
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

    def __getitem__(self, key: str) -> int:
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
    
    def values(self) -> list[int]:
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
        logger.error(f"Error in callback_listener: {e}") # we don't want to crash the bot if the callback happens twice, whichh would OSE 98
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