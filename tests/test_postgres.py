from imas_simdb_mcp.config import Settings
from imas_simdb_mcp.postgres import PostgresVectorSearch, _vector_literal


def test_vector_literal():
    assert _vector_literal([1, 2.5, -3]) == "[1.0,2.5,-3.0]"


def test_rejects_invalid_table_name():
    settings = Settings(
        database_url="postgresql://example",
        search_table="simulation_embeddings; drop table simulations",
    )

    try:
        PostgresVectorSearch(settings)
    except ValueError as err:
        assert "simple SQL identifier" in str(err)
    else:
        raise AssertionError("invalid table name was accepted")
