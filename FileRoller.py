import logging
from os import remove
from pathlib import Path
from typing import BinaryIO, Optional, Union

logger = logging.getLogger(__name__)

class FileRoller:
    """
    A class to manage rolling files with optional backup limits.

    Attributes:
        path (Path): The base file path to roll.
        max_count (int): The maximum number of backup files to keep. If None, no limit is applied.
        current_handle (BinaryIO): The current file handle for the base file.
    """

    def __init__(self, path: Union[str, Path], max_count: Optional[int] = None):
        """
        Initializes the FileRoller with a path and an optional maximum count of backup files.

        Args:
            path (Union[str, Path]): The base file path to roll.
            max_count (Optional[int]): The maximum number of backup files to keep. Defaults to None.
        """
        self.path = Path(path) if isinstance(path, str) else path
        self.max_count = max_count
        self.current_handle: Optional[BinaryIO] = None

    def roll(self):
        """
        Rolls the current file, managing backup files according to the max_count.

        If max_count is specified, the oldest file is deleted and others are renamed.
        If max_count is None, files are rolled without deletion, preserving the original suffix.
        """
        if self.current_handle and not self.current_handle.closed:
            self.current_handle.close()

        original_suffix = self.path.suffix

        if self.max_count is not None:
            last_file = self.path.with_name(f"{self.path.stem}.{self.max_count - 1}{original_suffix}")
            if last_file.exists():
                remove(last_file)

            for i in range(self.max_count - 1, -1, -1):
                current_file = self.path.with_name(f"{self.path.stem}.{i}{original_suffix}")
                next_file = self.path.with_name(f"{self.path.stem}.{i + 1}{original_suffix}")
                if current_file.exists():
                    logger.debug(f"Rolling {current_file} to {next_file}")
                    current_file.rename(next_file)
        else:
            suffixes = [int(p.stem.split('.')[-1]) for p in self.path.parent.glob(f"{self.path.stem}.*{original_suffix}") if p.stem.split('.')[-1].isdigit()]
            max_suffix = max(suffixes, default=0)

            for i in range(max_suffix, 0, -1):
                current_file = self.path.with_name(f"{self.path.stem}.{i}{original_suffix}")
                next_file = self.path.with_name(f"{self.path.stem}.{i + 1}{original_suffix}")
                if current_file.exists():
                    logger.debug(f"Rolling {current_file} to {next_file}")
                    current_file.rename(next_file)

        self.current_handle = open(self.path.with_name(f"{self.path.stem}.0{original_suffix}"), "ab")

    def close(self):
        """
        Closes the current file handle if it is open.
        """
        if self.current_handle and not self.current_handle.closed:
            self.current_handle.close()

    __next__ = roll
    __iter__ = lambda self: self
