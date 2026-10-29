"""Log in through the F5 firewall and save the SimDB OpenAPI spec (the data behind /<ver>/docs).

python scripts/fetch_api_spec.py                    # -> simdb-v1.2-swagger.json
python scripts/fetch_api_spec.py --version v1.2 --url https://simdb.iter.org/scenarios/api
"""

import argparse
import asyncio
import getpass
import json
import os

from simdb_mcp.client import Credentials, SimDBSession
from simdb_mcp.config import Settings


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://simdb.iter.org/scenarios/api")
    parser.add_argument("--version", default="v1.2")
    parser.add_argument("--username", default=os.environ.get("SIMDB_USERNAME") or getpass.getuser())
    parser.add_argument("--auth-mode", default="f5", choices=["f5", "basic", "none"])
    args = parser.parse_args()
    password = os.environ.get("SIMDB_PASSWORD") or getpass.getpass(f"SimDB password for {args.username}: ")

    settings = Settings(simdb_url=args.url.rstrip("/"), api_version=args.version, auth_mode=args.auth_mode)
    session = SimDBSession(settings, Credentials(args.username, password))
    try:
        spec = await session.get_json("swagger.json")
    finally:
        await session.aclose()
    out = f"simdb-{args.version}-swagger.json"
    with open(out, "w") as f:
        json.dump(spec, f, indent=2)
    print(f"Saved {out}: {len(spec.get('paths', {}))} paths")
    for path, ops in sorted(spec.get("paths", {}).items()):
        print(f"  {','.join(m.upper() for m in ops if m != 'parameters'):<18} {path}")


if __name__ == "__main__":
    asyncio.run(main())
