"""One connection owner for simulation writes, outside model-call threads."""

from concurrent.futures import ThreadPoolExecutor

from backend.store import BackendStore


class RunWriter:
    def __init__(self, path):
        if str(path) == ":memory:":
            raise ValueError("Run writer requires a file-backed database")
        self.database_path = str(path)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ecosim-writer")
        try:
            self._store = self._executor.submit(BackendStore, path).result()
        except BaseException:
            self._executor.shutdown()
            raise

    def __getattr__(self, name):
        if name.startswith("_") or name in {"connection", "transaction", "close"}:
            raise AttributeError(name)
        def invoke(*args, **kwargs):
            return self._executor.submit(
                getattr(self._store, name), *args, **kwargs
            ).result()
        return invoke

    def close(self):
        try:
            self._executor.submit(self._store.close).result()
        finally:
            self._executor.shutdown()
