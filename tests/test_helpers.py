"""Pure functions: filters, dates, value decoding, key names, credentials, settings."""

import base64

import pytest

from simdb_mcp.auth import credentials_from_headers
from simdb_mcp.client import AuthenticationError
from simdb_mcp.config import Settings
from simdb_mcp.keys import collapse_keys, flatten_schema, key_groups, simdb_key_info, text_key_priority
from simdb_mcp.query import Filter, simdb_datetime
from simdb_mcp.records import simulation_summary

# -- filters -----------------------------------------------------------------------------


def test_filter_becomes_operator_and_value():
    assert Filter(key="pulse", op="gt", value=100).to_param() == ("pulse", "gt:100")
    assert Filter(key="machine", value="ITER").to_param() == ("machine", "eq:ITER")
    assert Filter(key="sequence", op="exist").to_param() == ("sequence", "exist:")


def test_filter_refuses_values_with_a_colon():
    with pytest.raises(ValueError, match="':'"):
        Filter(key="uri", value="imas:hdf5").to_param()


def test_dates_use_simdb_creation_date_format():
    assert simdb_datetime("2026-09-14") == "2026-09-14 00_00_00"
    assert simdb_datetime("2026-09-14T08:30") == "2026-09-14 08_30_00"
    assert Filter(key="creation_date", op="ge", value="2026-09-14").to_param() == (
        "creation_date",
        "ge:2026-09-14 00_00_00",
    )


# -- records -----------------------------------------------------------------------------


def test_summary_turns_simdb_json_into_plain_values():
    row = {
        "uuid": {"_type": "uuid.UUID", "hex": "ab" * 16},
        "alias": "100001/1",
        "metadata": [{"element": "machine", "value": "ITER"}],
    }
    summary = simulation_summary(row, dashboard_url="https://dash/{uuid}")
    assert summary["uuid"] == "ab" * 16
    assert summary["metadata"] == {"machine": "ITER"}
    assert summary["dashboard_url"] == "https://dash/" + "ab" * 16


def test_long_text_is_shortened_only_when_asked():
    row = {"uuid": "u", "metadata": [{"element": "description", "value": "x" * 1000}]}
    assert simulation_summary(row, max_chars=50)["metadata"]["description"].startswith("x" * 50 + "… [1000 chars")
    assert simulation_summary(row)["metadata"]["description"] == "x" * 1000


# -- key names ---------------------------------------------------------------------------

KEYS = [
    {"name": "code.library[0].name"},
    {"name": "code.library[1].name"},
    {"name": "code.name"},
    {"name": "boundary.elongation.source"},
    {"name": "codeid"},
]


def test_list_entries_are_shown_once_as_a_pattern():
    collapsed = {k["name"]: k for k in collapse_keys(KEYS)}
    assert collapsed["code.library[*].name"]["indexed"] == 2


def test_keys_are_grouped_by_top_level_name():
    assert key_groups(KEYS) == {"boundary": 1, "code": 3, "codeid": 1}


def test_text_search_tries_plain_keys_first_and_list_entries_last():
    ordered = sorted((k["name"] for k in KEYS), key=text_key_priority)
    assert ordered[:2] == ["codeid", "code.name"]
    assert ordered[-1].startswith("code.library[")


def test_simdb_documents_its_own_keys_but_not_free_form_ones():
    assert "deprecated" in simdb_key_info("status")["meaning"]
    assert simdb_key_info("code.version")["origin"].startswith("manifest")  # documented as part of 'code'
    assert simdb_key_info("codeid") is None


def test_validation_schema_is_flattened_to_dotted_keys():
    schema = [{"code": {"type": "dict", "schema": {"name": {"type": "string", "required": True}}}}]
    assert flatten_schema(schema) == {"code": {"type": "dict"}, "code.name": {"type": "string", "required": True}}


# -- credentials and settings ------------------------------------------------------------


def test_credentials_come_from_the_basic_authorization_header():
    header = "Basic " + base64.b64encode(b"bob:pa:ss").decode()
    credentials = credentials_from_headers({"authorization": header})
    assert (credentials.username, credentials.password) == ("bob", "pa:ss")
    assert "pa:ss" not in repr(credentials)
    assert credentials_from_headers({}) is None
    with pytest.raises(AuthenticationError):
        credentials_from_headers({"authorization": "Bearer abc"})


def test_default_columns_can_be_changed_or_turned_off(monkeypatch):
    monkeypatch.delenv("SIMDB_DEFAULT_RETURN_KEYS", raising=False)
    assert Settings.from_env().default_return_keys == ["machine", "pulse", "code.name", "status", "description"]
    monkeypatch.setenv("SIMDB_DEFAULT_RETURN_KEYS", "machine, pulse")
    assert Settings.from_env().default_return_keys == ["machine", "pulse"]
    monkeypatch.setenv("SIMDB_DEFAULT_RETURN_KEYS", "")
    assert Settings.from_env().default_return_keys == []
