# How it works

This page is for maintainers. It explains the decisions that are not obvious from the code.
References to SimDB code are to release 0.15.2. `simdb.iter.org` does not report its SimDB
version, but its behaviour (listed API versions, fractional counts, ignored `exist`
filters) matches that release.

## Request flow

```text
MCP client ── Authorization: Basic ──▶ server.py (tool)
                                          │ credentials from the header (auth.py)
                                          ▼
                                   SessionPool (client.py) ── one logged-in session per user
                                          │
                                          ▼
                                   Catalogue (catalogue.py) ── search strategy, caches
                                          │
                                          ▼
                                   SimDB REST API (read endpoints only)
```

## Login

`simdb.iter.org` sits behind an F5 firewall and does not accept SimDB tokens. The server
logs in the way the `simdb` CLI does (`simdb/cli/remote_api.py`, `_load_cookies`): it posts
the user's credentials to `https://simdb.iter.org/my.policy`, keeps the firewall cookies,
and sends API requests with them. The F5 answers a refused login with an HTML page and
status 200, so a login only counts as successful once the API root returns JSON.

Sessions are cached per user (keyed on username and a hash of the password) for
`SIMDB_SESSION_TTL`. When the firewall session expires, the next request logs in again;
concurrent requests share that single login.

## API version

The server reads the API versions listed at the SimDB root and uses the highest one it
supports, v1.3 or v1.2, like the CLI's `select_api_version`. `simdb.iter.org` offers v1,
v1.1 and v1.2. Both supported versions have the same read endpoints.

## Where metadata keys come from

SimDB keeps metadata from three sources in one namespace:

1. **The `summary` IDS.** At upload, SimDB reads the `summary` IDS of each IMAS output,
   converts it to the Data Dictionary version installed on the SimDB server, and stores
   every node under its path with `/` replaced by `.` (`simdb/imas/metadata.py`,
   `load_metadata`). So `global_quantities.ip.value` is
   `summary/global_quantities/ip/value`, and the full time trace is stored.
2. **The SimDB server.** `status`, `uploaded_by`, `ids`, `input_ids`, `seqid`,
   `replaced_by`, plus the record's `alias` and `uuid`.
3. **The manifest.** Whatever the uploader wrote: the conventional `machine`, `code` and
   `description`, and any free-form key such as `codeid` or `runfolder`.

`simdb_describe_keys` combines the Data Dictionary entry (`dd.py`, from the DD bundled with
IMAS-Python), SimDB's own documentation of its keys (`keys.py`, with the source of each
statement) and the server's validation rules (`GET /validation_schema`). Some names, such as
`machine`, `pulse` and `code.name`, exist both in the DD and as manifest keys, so a value may
come from either; the tool says so.

## Working around SimDB 0.15 search behaviour

`GET /simulations` on SimDB 0.15 (`simdb/database/database.py`) has quirks that
`catalogue.py` works around:

Paging is done over rows, not simulations
: The server pages and counts over *(simulation × requested key)* rows and divides the count
  by the number of keys, which gives pages of the wrong size and fractional counts when extra
  columns are requested. So a search first asks for the filtered keys only. If fewer than
  `SIMDB_MAX_LIMIT` simulations match, one request returns them all with their columns and
  the page is cut locally. Otherwise the server pages and the columns are fetched per
  simulation.

Upload date cannot be sorted
: The special filter `creation_date` (value format `YYYY-MM-DD HH_MM_SS`) selects a date
  window. The whole window is fetched with limit 0 (no limit) and sorted newest first
  locally. A wide window can time out; the MCP then retries with an always-true constraint
  on `status`, which makes SimDB load far fewer rows, and says so in `notes`.

`exist` filters are ignored
: Constraints with an empty value are dropped by the server, so `exist` is checked on the
  results.

No free-text search
: The text search first reads each key's distinct values (`/metadata/<key>`, cheap and
  cached for 10 minutes, shared by all users), and only sends an `in` query for the keys whose
  values contain the text.

Arrays arrive as raw bytes
: Numpy arrays are sent as base64-encoded bytes (`simdb/json.py`). `records.py` decodes them
  and returns `n`, `min`, `max`, `first` and `last`.

If SimDB fixes one of these, the matching workaround can be removed; each one is a separate,
documented method in `catalogue.py`.

## Caches

| What | Lifetime | Shared |
|---|---|---|
| User's SimDB login | `SIMDB_SESSION_TTL` (30 min) | per user |
| List of metadata keys | 5 min | per user |
| Distinct values of a key | 10 min | all users |
| Server validation rules | 1 hour | all users |

Caches live in memory, in each worker process.
