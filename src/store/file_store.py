import copy
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class FileStore:
    """Keeps all data in one text file that holds JSON.

    Only the repository layer should use this class.
    """

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._lock = threading.RLock()

    def initialize(self, seed: dict) -> None:
        """Write the seed data if the file is missing or empty."""
        with self._lock:
            if not self._path.exists() or not self._path.read_text().strip():
                self._write(copy.deepcopy(seed))

    def read(self) -> dict:
        with self._lock:
            return self._load()

    @contextmanager
    def transaction(self) -> Iterator[dict]:
        """Load the data, let the caller change it, then save it.

        The lock is held the whole time, so two requests cannot overwrite each
        other. If the caller raises, nothing is saved.
        """
        with self._lock:
            data = self._load()
            yield data
            self._write(data)

    def _load(self) -> dict:
        return json.loads(self._path.read_text())

    def _write(self, data: dict) -> None:
        # Write a temporary file first, then replace the real one, so a crash
        # cannot leave a half-written data file.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=self._path.parent, prefix=".minidash-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as temp_file:
                json.dump(data, temp_file, indent=2)
            os.replace(temp_name, self._path)
        except BaseException:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
            raise
