# Tools

These are the tools the server offers. Claude picks them itself; you do not call them by
name. All of them only read from SimDB.

| Tool | What it does |
|---|---|
| `simdb_server_info` | Which SimDB server is used, its API versions, and whether your login works. |
| `simdb_list_metadata_keys` | The metadata keys that exist. On a large catalogue it first returns groups (`boundary`, `code`, …); ask again with `prefix` to see a group. |
| `simdb_list_metadata_values` | The distinct values of one key, e.g. every `code.name`, to get the exact spelling. |
| `simdb_describe_keys` | What a key means and where it comes from: the IMAS Data Dictionary entry (units, meaning, COCOS label) for keys from the `summary` IDS, SimDB's own description for keys the server sets, the server's validation rule, or "free-form" for uploader-chosen keys. |
| `simdb_search_simulations` | Search with filters combined with AND, e.g. `code.name eq JINTRAC` and `machine eq ITER`. Paged. |
| `simdb_list_recent_simulations` | Simulations uploaded in a date window, newest first. |
| `simdb_search_text` | Find a word in any text key when you do not know which key holds it. |
| `simdb_get_simulation` | The record of one simulation, by alias or UUID. Can be limited to some key groups. |
| `simdb_get_simulation_trace` | Status history and the chain of simulations it replaces or is replaced by. |

The server also publishes a short reference of the filter operators as the resource
`simdb://query-operators`.

## Filter operators

| Operator | Meaning |
|---|---|
| `eq`, `ne` | equal, not equal (text comparisons ignore case) |
| `in`, `ni` | contains, does not contain (substring, ignores case) |
| `gt`, `ge`, `lt`, `le` | greater / less than (or equal) |
| `agt`, `age`, `alt`, `ale` | for arrays such as time traces: *some* value is greater / less than |
| `exist` | the key is present |

The special key `creation_date` filters on the upload date, e.g. `creation_date ge 2026-07-01`.

## What the answers contain

- **Units.** Results include a `units` map for keys that have units in the Data Dictionary.
- **Arrays.** Time traces are shown as `n`, `min`, `max`, `first` and `last` of the stored
  values, not the full array. Values are as stored; no unit or sign convention is applied.
- **Long text.** Descriptions are cut to 300 characters in result lists; the full text is in
  `simdb_get_simulation`.
- **Default columns.** Search results show `machine`, `pulse`, `code.name`, `status` and
  `description` unless other keys are asked for.

## Limits

- Values that contain `:` cannot be searched. SimDB splits query values on `:`.
- SimDB cannot sort by upload date; `simdb_list_recent_simulations` sorts the results itself.
- Keys that hold numbers in some simulations cannot be searched with `in` on SimDB 0.15;
  the text search reports them as failed.
- The server searches metadata only. It does not open the simulation data files.
