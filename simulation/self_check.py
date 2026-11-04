"""Compatibility entry point for the rebuilt backend runtime check."""

from simulation.execution.self_check import ScriptedGateway, main

__all__ = ["ScriptedGateway", "main"]

if __name__ == "__main__":
    main()
