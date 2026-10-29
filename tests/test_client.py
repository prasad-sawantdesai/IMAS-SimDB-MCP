"""The SimDB client: firewall login, session reuse, API version, errors."""

import asyncio

import pytest

from simdb_mcp.client import AuthenticationError, Credentials, NotFoundError, SessionPool, SimDBError
from simdb_mcp.config import Settings
from simdb_mcp.query import Filter, build_params, column_params

from .fake_simdb import BASE, PASSWORD, USERNAME, FakeSimDB

ALICE = Credentials(USERNAME, PASSWORD)


@pytest.fixture
def fake():
    return FakeSimDB()


@pytest.fixture
async def pool(fake):
    pool = SessionPool(Settings(simdb_url=BASE, auth_mode="f5"), fake.transport())
    yield pool
    await pool.aclose()


# -- login -------------------------------------------------------------------------------


async def test_logs_in_once_and_reuses_the_session(pool, fake):
    await (await pool.get(ALICE)).list_metadata_keys()
    await (await pool.get(ALICE)).list_metadata_keys()
    assert fake.login_count == 1


async def test_wrong_password_is_rejected(pool):
    with pytest.raises(AuthenticationError):
        await pool.get(Credentials(USERNAME, "wrong"))


async def test_expired_session_logs_in_again_once_for_concurrent_requests(pool, fake):
    session = await pool.get(ALICE)
    fake.expire_session()
    results = await asyncio.gather(*(session.list_metadata_keys() for _ in range(8)))
    assert all(results)
    assert fake.login_count == 2  # the first login and one re-login, not eight


# -- API version -------------------------------------------------------------------------


async def test_uses_v12_when_the_server_offers_up_to_v12(pool, fake):
    session = await pool.get(ALICE)
    await session.list_metadata_keys()
    assert fake.requests[-1].url.path == "/scenarios/api/v1.2/metadata"


async def test_prefers_v13_when_offered(pool, fake):
    fake.versions = ["v1.2", "v1.3"]
    session = await pool.get(ALICE)
    await session.list_metadata_keys()
    assert session.api_version == "v1.3"


async def test_no_supported_version_is_a_clear_error(pool, fake):
    fake.versions = ["v1", "v1.1"]
    session = await pool.get(ALICE)
    with pytest.raises(SimDBError, match="No compatible SimDB API version"):
        await session.list_metadata_keys()


# -- requests and errors -----------------------------------------------------------------


async def test_search_uses_simdb_query_syntax_and_paging_headers(pool, fake):
    session = await pool.get(ALICE)
    filters = [Filter(key="machine", value="ITER"), Filter(key="pulse", op="gt", value=100001)]
    await session.list_simulations(build_params(filters) + column_params(["status"]), limit=5, sort_by="pulse")

    request = fake.requests[-1]
    assert request.url.params.multi_items() == [("machine", "eq:ITER"), ("pulse", "gt:100001"), ("status", "")]
    assert request.headers["simdb-result-limit"] == "5"
    assert request.headers["simdb-sort-by"] == "pulse"


async def test_html_404_becomes_a_short_error_without_logging_in_again(fake):
    pool = SessionPool(Settings(simdb_url=BASE, api_version="v1.3"), fake.transport())  # not offered
    session = await pool.get(ALICE)
    with pytest.raises(NotFoundError) as error:
        await session.list_metadata_keys()
    assert "<html" not in str(error.value)
    assert fake.login_count == 1
    await pool.aclose()
