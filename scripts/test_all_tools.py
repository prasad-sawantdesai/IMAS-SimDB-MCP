"""Call every tool of a running SimDB MCP server and report PASS/FAIL.

Arguments for later calls are taken from earlier results (a real key, a real value,
a real simulation alias), so it works on any SimDB catalogue.

    python scripts/test_all_tools.py http://127.0.0.1:8000/mcp
    python scripts/test_all_tools.py http://127.0.0.1:8000/mcp --text JINTRAC --show search_text
    python scripts/test_all_tools.py http://127.0.0.1:8000/mcp --verbose     # print every response

"chars" is the size of the JSON the model receives for that call.
"""

import argparse
import asyncio
import base64
import datetime
import getpass
import json
import os
import time

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

rows: list[tuple[str, str, int, float, str]] = []


async def run(client, label, tool, args, args_ns, expect_error=False):
    start = time.monotonic()
    try:
        result = await client.call_tool(tool, args)
    except Exception as exc:  # transport-level failure
        rows.append((label, "FAIL", 0, time.monotonic() - start, f"{type(exc).__name__}: {exc}"))
        return None
    elapsed = time.monotonic() - start
    text = result.content[0].text if result.content else ""
    ok = result.is_error == expect_error
    note = text[:120].replace("\n", " ") if result.is_error else ""
    rows.append((label, "PASS" if ok else "FAIL", len(text), elapsed, note))
    if args_ns.verbose or label in args_ns.show:
        print(f"\n=== {label}: {tool}({json.dumps(args)}) ===")
        try:
            print(json.dumps(json.loads(text), indent=2))
        except ValueError:
            print(text)
    if result.is_error:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--username", default=os.environ.get("SIMDB_USERNAME") or getpass.getuser())
    parser.add_argument("--text", default="JINTRAC", help="Text for simdb_search_text.")
    parser.add_argument("--simulation", help="Alias or UUID for get_simulation (default: first search hit).")
    parser.add_argument("--show", nargs="*", default=[], help="Labels whose full response to print.")
    parser.add_argument("--verbose", action="store_true", help="Print every response in full.")
    parser.add_argument("--insecure", action="store_true", help="Skip TLS verification of the MCP URL.")
    a = parser.parse_args()
    password = os.environ.get("SIMDB_PASSWORD") or getpass.getpass(f"SimDB password for {a.username}: ")
    token = base64.b64encode(f"{a.username}:{password}".encode()).decode()

    async with httpx2.AsyncClient(
        headers={"Authorization": f"Basic {token}"}, verify=not a.insecure, timeout=300
    ) as http:
        async with Client(streamable_http_client(a.url, http_client=http)) as client:
            tools = [t.name for t in (await client.list_tools()).tools]
            print("Tools:", ", ".join(tools))

            await run(client, "server_info", "simdb_server_info", {}, a)

            overview = await run(client, "keys_overview", "simdb_list_metadata_keys", {}, a) or {}
            top = overview.get("top_level_keys") or overview.get("keys") or []
            groups = list((overview.get("groups") or {}).keys())
            if groups:
                group = "code" if "code" in groups else groups[0]
                await run(client, f"keys_prefix_{group}", "simdb_list_metadata_keys", {"prefix": group}, a)
            await run(client, "keys_contains", "simdb_list_metadata_keys", {"name_contains": "name"}, a)

            text_keys = [k["name"] for k in top if k.get("type") in ("str", "string") and "[" not in k["name"]]
            text_keys.sort(key=lambda n: ("." in n, n))  # top-level keys first
            value_key, value = "alias", None
            for candidate in text_keys[:3] or ["alias"]:
                values = (
                    await run(
                        client,
                        f"values_{candidate}",
                        "simdb_list_metadata_values",
                        {"key": candidate, "max_values": 20},
                        a,
                    )
                    or {}
                )
                value = next((v for v in values.get("values", []) if isinstance(v, str) and v and ":" not in v), None)
                if value is not None:
                    value_key = candidate
                    break

            columns = text_keys[:4]
            page = (
                await run(client, "search_all", "simdb_search_simulations", {"limit": 3, "return_keys": columns}, a)
                or {}
            )
            await run(client, "search_page2", "simdb_search_simulations", {"limit": 3, "page": 2}, a)
            if value is not None:
                await run(
                    client,
                    "search_eq",
                    "simdb_search_simulations",
                    {"filters": [{"key": value_key, "op": "eq", "value": value}], "limit": 3},
                    a,
                )
                await run(
                    client,
                    "search_in",
                    "simdb_search_simulations",
                    {"filters": [{"key": value_key, "op": "in", "value": value[:4]}], "limit": 3},
                    a,
                )
            await run(
                client,
                "search_exist",
                "simdb_search_simulations",
                {"filters": [{"key": value_key, "op": "exist"}], "limit": 3},
                a,
            )
            await run(client, "search_text", "simdb_search_text", {"text": a.text, "limit": 5}, a)
            since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
            await run(client, "recent_30d", "simdb_list_recent_simulations", {"since": since, "limit": 5}, a)

            sim = a.simulation or next((r["alias"] or r["uuid"] for r in page.get("results", [])), None)
            if sim:
                await run(client, "get_simulation", "simdb_get_simulation", {"simulation": sim}, a)
                await run(
                    client, "get_sim_prefix", "simdb_get_simulation", {"simulation": sim, "prefixes": ["code"]}, a
                )
                await run(
                    client, "get_sim_files", "simdb_get_simulation", {"simulation": sim, "include_files": True}, a
                )
                await run(client, "trace", "simdb_get_simulation_trace", {"simulation": sim}, a)

            # Errors the tools must report clearly (PASS = an error came back)
            await run(
                client,
                "err_colon",
                "simdb_search_simulations",
                {"filters": [{"key": "alias", "value": "a:b"}]},
                a,
                expect_error=True,
            )
            await run(
                client,
                "err_missing",
                "simdb_get_simulation",
                {"simulation": "no-such-simulation-xyz"},
                a,
                expect_error=True,
            )

            start = time.monotonic()
            try:
                res = await client.read_resource("simdb://query-operators")
                body = res.contents[0].text
                rows.append(("resource", "PASS", len(body), time.monotonic() - start, ""))
            except Exception as exc:
                rows.append(("resource", "FAIL", 0, time.monotonic() - start, str(exc)[:120]))

    print(f"\n{'check':<22} {'result':<6} {'chars':>8} {'secs':>6}  note")
    for label, status, size, secs, note in rows:
        print(f"{label:<22} {status:<6} {size:>8} {secs:>6.1f}  {note}")
    failed = sum(1 for r in rows if r[1] == "FAIL")
    print(f"\n{len(rows) - failed}/{len(rows)} passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
