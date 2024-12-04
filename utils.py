import re
import os
from functools import lru_cache, wraps
from inspect import Signature
from sqlalchemy.orm import scoped_session
from logging import getLogger

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
                    logger.debug(f"calling {func.__name__} with args: {args} and kwargs: {kwargs}")
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