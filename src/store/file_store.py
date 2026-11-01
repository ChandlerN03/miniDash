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
        # The data of the transaction that is open right now, or None. Only the thread
        # holding the lock can see it as not None, so nested transactions share it.
        self._open_data: dict | None = None

    def initialize(self, seed: dict) -> None:
        """Make sure the file has every collection in `seed`.

        A missing or empty file is filled with the whole seed. If the file
        already has data, only collections that are missing from it are added
        (this is how an older file gets "sessions" and "group_orders"). Existing
        collections are never changed.
        """
        with self._lock:
            if not self._path.exists() or not self._path.read_text().strip():
                self._write(copy.deepcopy(seed))
                return
            data = self._load()
            missing = {name: copy.deepcopy(value) for name, value in seed.items() if name not in data}
            if missing:
                data.update(missing)
                self._write(data)

    def read(self) -> dict:
        """A copy of the data. Inside a transaction (on the same thread) it includes
        the changes made so far; from another thread it waits for the transaction to finish.
        """
        with self._lock:
            if self._open_data is not None:
                return copy.deepcopy(self._open_data)
            return self._load()

    @contextmanager
    def transaction(self) -> Iterator[dict]:
        """Load the data, let the caller change it, then save it.

        The lock is held the whole time, so two requests cannot overwrite each
        other. If the caller raises, nothing is saved.

        Transactions can be nested (for example an order created while a group
        order is being updated). A nested transaction works on the same data as
        the outer one, and only the outermost one writes the file, so nothing is
        lost and everything is saved or nothing is. If a nested transaction
        raises, its own changes are undone.
        """
        with self._lock:
            if self._open_data is not None:
                outer_data = self._open_data
                before = copy.deepcopy(outer_data)
                try:
                    yield outer_data
                except BaseException:
                    outer_data.clear()
                    outer_data.update(before)
                    raise
                return

            data = self._load()
            self._open_data = data
            try:
                yield data
                self._write(data)
            finally:
                self._open_data = None

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
