"""Compatibility command for the rebuilt backend parallel mode."""

from simulation.execution.self_check import _prepare, ScriptedGateway
from backend.runtime import BackendRunExecutor
from backend.store import BackendStore
from pathlib import Path
from tempfile import TemporaryDirectory
import json


def main() -> None:
    with TemporaryDirectory(prefix="ecosim-parallel-") as directory:
        store = BackendStore(Path(directory) / "backend.sqlite")
        try:
            _prepare(store)
            store.connection.execute(
                "UPDATE runs SET execution_json=? WHERE run_id=?",
                (json.dumps({"mode": "parallel", "batch_size": 2}),
                 "run_runtime"),
            )
            store.connection.commit()
            BackendRunExecutor(store).execute(
                "run_runtime", primary=ScriptedGateway()
            )
            assert store.run_status("run_runtime") == "completed"
            print("PASS: backend batched-parallel execution")
        finally:
            store.close()


if __name__ == "__main__":
    main()
