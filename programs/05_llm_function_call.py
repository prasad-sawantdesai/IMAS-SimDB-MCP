"""Program 5: simulate an LLM function call into the SimDB search function."""

from __future__ import annotations

import json
import os

from imas_simdb_mcp.llm_function import (
    SEARCH_SIMULATIONS_FUNCTION,
    call_search_simdb_simulations,
)


def main() -> None:
    os.environ.setdefault("SIMDB_MCP_SEARCH_TABLE", "simulation_embeddings_test")

    default_arguments = {
        "query_embedding": [0.1, 0.2, 0.3],
        "limit": 5,
        "metadata_filters": {"code.name": "ITER"},
    }
    arguments = json.loads(
        os.getenv("SIMDB_MCP_LLM_ARGUMENTS", json.dumps(default_arguments))
    )

    print("LLM function definition:")
    print(json.dumps(SEARCH_SIMULATIONS_FUNCTION, indent=2))
    print("\nLLM function arguments:")
    print(json.dumps(arguments, indent=2))
    print("\nFunction result:")
    print(json.dumps(call_search_simdb_simulations(arguments), indent=2))


if __name__ == "__main__":
    main()
