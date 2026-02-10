import logging
import os
import tarfile
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

class TarRotatingFileHandler(TimedRotatingFileHandler):
    def __init__(self, filename, when="midnight", interval=1, backupCount=7, encoding=None, delay=False, utc=False):
        super().__init__(filename, when, interval, backupCount, encoding, delay, utc)
        self.log_dir = os.path.dirname(filename) or "."

    def doRollover(self):
        """
        Override doRollover to create a tar.gz archive of all rotated logs when backupCount is reached.
        """
        self.stream.close()

        # Get list of rotated log files
        log_prefix = os.path.basename(self.baseFilename) + "."
        old_logs = sorted(
            [f for f in os.listdir(self.log_dir) if f.startswith(log_prefix)],
            key=lambda x: os.path.getmtime(os.path.join(self.log_dir, x))  # Sort by modified time
        )

        # Add the current log file to the list for tarring
        old_logs.append(os.path.basename(self.baseFilename))

        if len(old_logs) >= self.backupCount:
            # Create tarball name based on current date
            date_str = datetime.now().strftime("%Y-%m-%d")
            tar_filename = os.path.join(self.log_dir, f"logs-{date_str}.tar.gz")

            # Archive all logs
            with tarfile.open(tar_filename, "w:gz") as tar:
                for log in old_logs:
                    log_path = os.path.join(self.log_dir, log)
                    if os.path.exists(log_path):  # Ensure the file still exists before adding
                        tar.add(log_path, arcname=log)
                        os.remove(log_path)  # Delete log after archiving

        # Perform normal rotation (creates a new empty log file)
        super().doRollover()

        # Reopen log file for new entries
        self.mode = 'a'
        self.stream = self._open()
