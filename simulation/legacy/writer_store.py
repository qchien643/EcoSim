"""Archived v0 single-writer adapter; not used by the backend-v1 runtime."""

from concurrent.futures import ThreadPoolExecutor

from .store_sqlite import SqliteSimulationStore


class WriterStore:
    def __init__(self, path):
        if str(path) == ":memory:":
            raise ValueError("Parallel mode requires a file-backed database")
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite-writer")
        try:
            self._store = self._executor.submit(SqliteSimulationStore, path).result()
        except BaseException:
            self._executor.shutdown()
            raise

    def __getattr__(self, name):
        if name.startswith("_") or name == "connection":
            raise AttributeError(name)

        def call(*args, **kwargs):
            return self._executor.submit(self._invoke, name, args, kwargs).result()

        return call

    def _invoke(self, name, args, kwargs):
        try:
            return getattr(self._store, name)(*args, **kwargs)
        except BaseException:
            self._store.connection.rollback()
            raise

    def close(self):
        try:
            self._executor.submit(self._store.close).result()
        finally:
            self._executor.shutdown(wait=True)

    # ponytail: reads also use this queue in v1; add read-only connections only
    # when profiling shows that context reads materially delay writer commits.
