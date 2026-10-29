"""The MCP tools, called the way Claude calls them.

Most tests use an in-process MCP client. It sends no HTTP headers, so those run against a
SimDB without login; the login path is tested at the end over real HTTP.
"""

import base64
import json
import socket
import threading
import time

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from simdb_mcp.config import Settings
from simdb_mcp.server import create_server

from .fake_simdb import BASE, PASSWORD, USERNAME, FakeSimDB


class ToolFailed(Exception):
    """A tool answered with an error; the message is what the model would see."""


@pytest.fixture
def fake():
    return FakeSimDB()


@pytest.fixture
def make_call(fake):
    """make_call(**settings) -> call(tool, **arguments), which returns the tool's JSON answer."""

    def make_call(**settings):
        fake.require_login = False
        server = create_server(Settings(simdb_url=BASE, auth_mode="none", **settings), fake.transport())

        async def call(tool: str, **arguments):
            async with Client(server) as client:
                result = await client.call_tool(tool, arguments)
            text = result.content[0].text
            if result.is_error:
                raise ToolFailed(text)
            return json.loads(text)

        return call

    return make_call


@pytest.fixture
def call(make_call):
    return make_call(dashboard_url="https://dash.example.org/uuid/{uuid}")


def aliases(answer: dict) -> list[str]:
    return [r["alias"] for r in answer["results"]]


# -- discovery ------------------------------------------------------------------------------


async def test_every_tool_is_marked_read_only(fake):
    server = create_server(Settings(simdb_url=BASE, auth_mode="none"), fake.transport())
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    assert len(tools) == 9
    assert all(t.annotations.read_only_hint for t in tools)


async def test_key_list_includes_sub_keys_of_object_keys(call):
    answer = await call("simdb_list_metadata_keys")
    assert {"code", "code.name", "code.version", "global_quantities.ip.value"} <= {k["name"] for k in answer["keys"]}


async def test_large_key_list_returns_groups_first(call, monkeypatch):
    monkeypatch.setattr("simdb_mcp.server.FULL_KEY_LIST_MAX", 3)
    overview = await call("simdb_list_metadata_keys")
    assert "keys" not in overview and overview["groups"]["code"] == 3
    group = await call("simdb_list_metadata_keys", prefix="code")
    assert {k["name"] for k in group["keys"]} == {"code", "code.name", "code.version"}


async def test_values_of_a_key(call):
    answer = await call("simdb_list_metadata_values", key="machine")
    assert answer["values"] == ["ITER", "WEST"]


# -- describing keys ------------------------------------------------------------------------


async def test_summary_key_is_described_from_the_data_dictionary(call):
    ip = (await call("simdb_describe_keys", keys=["global_quantities.ip.value"]))["keys"]["global_quantities.ip.value"]
    assert ip["origin"].startswith("summary IDS")
    assert ip["dd"]["dd_path"] == "summary/global_quantities/ip/value"
    assert ip["dd"]["units"] == "A" and ip["dd"]["cocos_label"] == "ip_like"
    assert ip["server_rule"] == {"type": "numpy", "ge": -17000000, "le": 0}


async def test_server_key_is_described_from_simdb_documentation(call):
    status = (await call("simdb_describe_keys", keys=["status"]))["keys"]["status"]
    assert "dd" not in status and "deprecated" in status["simdb"]["meaning"]


async def test_unknown_key_is_labelled_free_form(call):
    codeid = (await call("simdb_describe_keys", keys=["codeid"]))["keys"]["codeid"]
    assert codeid["origin"] == "manifest metadata (free-form)"


# -- structured search ----------------------------------------------------------------------


async def test_filters_are_combined_with_and(call):
    answer = await call(
        "simdb_search_simulations",
        filters=[{"key": "code.name", "value": "jintrac"}, {"key": "machine", "value": "ITER"}],
    )
    assert aliases(answer) == ["100001/1"]
    assert answer["results"][0]["dashboard_url"].endswith("a" * 32)


async def test_range_operator_matches_any_point_of_the_range(call):
    answer = await call("simdb_search_simulations", filters=[{"key": "time", "op": "agt", "value": 100}])
    assert aliases(answer) == ["100001/1"]


async def test_count_and_page_size_stay_right_with_extra_columns(call):
    # SimDB 0.15 would give count 1.2 here (rows / keys) if the columns were requested with the search.
    answer = await call("simdb_search_simulations", filters=[{"key": "code.name", "value": "jintrac"}], limit=1)
    assert answer["count"] == 2 and answer["has_more"]
    assert len(answer["results"]) == 1
    assert {"machine", "pulse", "status"} <= set(answer["results"][0]["metadata"])  # default columns


async def test_exist_filter_is_applied_although_simdb_ignores_it(call):
    answer = await call(
        "simdb_search_simulations",
        filters=[{"key": "machine", "value": "ITER"}, {"key": "global_quantities.ip.value", "op": "exist"}],
    )
    assert aliases(answer) == ["100001/1"] and answer["count"] == 1


async def test_results_carry_units_from_the_data_dictionary(call):
    answer = await call(
        "simdb_search_simulations",
        filters=[{"key": "pulse", "value": 100001}],
        return_keys=["global_quantities.ip.value"],
    )
    assert answer["units"] == {"global_quantities.ip.value": "A"}


async def test_small_filtered_search_needs_a_single_request(call, fake):
    await call("simdb_search_simulations", filters=[{"key": "machine", "value": "ITER"}])
    searches = [r for r in fake.requests if r.url.path.endswith("/simulations")]
    assert len(searches) == 1  # matches and their columns together, no request per simulation


async def test_sorting_by_upload_date_points_to_the_recent_tool(call):
    with pytest.raises(ToolFailed, match="simdb_list_recent_simulations"):
        await call("simdb_search_simulations", sort_by="datetime")


# -- upload date ----------------------------------------------------------------------------


async def test_recent_lists_the_window_newest_first(call):
    assert aliases(await call("simdb_list_recent_simulations", since="2025-02-01")) == ["west-55000", "100002/1"]
    window = await call("simdb_list_recent_simulations", since="2025-02-01", until="2025-03-01")
    assert aliases(window) == ["100002/1"]


async def test_recent_finds_the_newest_even_beyond_max_limit(make_call):
    # This used to fetch max_limit simulations in server order (oldest first) and sort only those.
    call = make_call(max_limit=1)
    answer = await call("simdb_list_recent_simulations", since="2024-01-01", limit=1)
    assert answer["count"] == 3 and aliases(answer) == ["west-55000"]


async def test_upload_date_can_be_a_search_filter(call, fake):
    answer = await call(
        "simdb_search_simulations", filters=[{"key": "creation_date", "op": "ge", "value": "2025-03-01"}]
    )
    assert aliases(answer) == ["west-55000"]
    sent = [r.url.params.multi_items() for r in fake.requests]
    assert any(("creation_date", "ge:2025-03-01 00_00_00") in params for params in sent)


# -- free text ------------------------------------------------------------------------------


async def test_text_search_finds_the_text_in_any_key(call):
    answer = await call("simdb_search_text", text="jintrac")
    assert set(aliases(answer)) == {"100001/1", "west-55000"}
    assert answer["keys_with_matches"] == ["code.name"]


async def test_text_search_queries_only_keys_that_contain_the_text(call, fake):
    await call("simdb_search_text", text="jintrac")
    value_lists_read = fake.values_requests
    before = len(fake.requests)

    answer = await call("simdb_search_text", text="boron")

    assert answer["count"] == 0
    assert not [r for r in fake.requests[before:] if r.url.path.endswith("/simulations")]
    assert fake.values_requests == value_lists_read  # the value lists came from the cache


# -- one simulation -------------------------------------------------------------------------


async def test_simulation_record_has_metadata_arrays_and_file_counts(call):
    sim = await call("simdb_get_simulation", simulation="100001/1")
    assert sim["metadata"]["code"] == {"name": "JINTRAC", "version": "2.1"}
    ip = sim["metadata"]["global_quantities.ip.value"]
    assert (ip["n"], ip["min"], ip["max"]) == (4, -1.5e7, -1.0e6)  # NaN ignored
    assert sim["outputs_count"] == 1 and "outputs" not in sim
    assert sim["units"]["global_quantities.ip.value"] == "A"


async def test_simulation_record_can_be_limited_to_key_groups(call):
    sim = await call("simdb_get_simulation", simulation="100001/1", prefixes=["code"])
    assert set(sim["metadata"]) == {"code"}
    assert sim["metadata_groups"]["machine"] == 1


async def test_trace(call):
    assert (await call("simdb_get_simulation_trace", simulation="a" * 32))["status"] == "passed"


async def test_unknown_simulation_is_a_clear_error(call):
    with pytest.raises(ToolFailed, match="not found"):
        await call("simdb_get_simulation", simulation="nope")


# -- credentials, over real HTTP -------------------------------------------------------------


async def test_without_credentials_the_tool_explains_how_to_connect(fake):
    server = create_server(Settings(simdb_url=BASE), fake.transport())
    async with Client(server) as client:
        result = await client.call_tool("simdb_list_metadata_keys", {})
    assert result.is_error and "Authorization: Basic" in result.content[0].text


@pytest.fixture
def http_url(fake):
    """The real streamable-HTTP app on a free local port, logging in to the fake F5."""
    app = create_server(Settings(simdb_url=BASE), fake.transport()).streamable_http_app(
        stateless_http=True, json_response=True
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


async def call_over_http(url: str, password: str, tool: str, arguments: dict):
    header = "Basic " + base64.b64encode(f"{USERNAME}:{password}".encode()).decode()
    async with httpx2.AsyncClient(headers={"Authorization": header}) as http:
        async with Client(streamable_http_client(f"{url}/mcp", http_client=http)) as client:
            return await client.call_tool(tool, arguments)


async def test_user_credentials_are_used_to_log_in_to_simdb(http_url, fake):
    result = await call_over_http(http_url, PASSWORD, "simdb_search_simulations", {})
    assert not result.is_error
    assert fake.login_count == 1


async def test_wrong_password_is_reported(http_url):
    result = await call_over_http(http_url, "wrong", "simdb_server_info", {})
    assert result.is_error and "login failed" in result.content[0].text


async def test_health_endpoint(http_url):
    async with httpx2.AsyncClient() as http:
        assert (await http.get(f"{http_url}/healthz")).json()["status"] == "ok"
