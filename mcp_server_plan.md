# EVS MCP Server Plan

## Overview

Build an MCP server for Earth Volumetric Studio that allows AI assistants to read, understand, and modify EVS applications programmatically. The server will be built on top of the `evs_automation` Python library, which communicates with a running EVS instance over a named pipe (`\\.\pipe\EVS_{pid}`).

## Architecture

```
AI Assistant  <-->  MCP Server (Python)  <-->  Named Pipe  <-->  EVS Instance
                          |
                          +--> EVS install on disk (schema files, module defaults, help)
```

- **MCP Server**: Python process exposing MCP tools that map to EVS automation calls
- **evs_automation**: Python library wrapping the named pipe JSON protocol (`{method, args}` -> `{Success, Value, Error}`)
- **Static resources**: Schema files (`runtime/schema/`), module defaults (`runtime/module_defaults/`), and help files are read directly from the EVS install directory — no pipe call needed

## evs_automation Updates Needed

### API Parity with Internal evs.py

The internal `evs.py` (EvsShared/evs.py) has functions that the external `evs_automation.py` (`_EvsProcess` class) is missing or handles differently:

| Internal evs.py | evs_automation | Status | Notes |
|---|---|---|---|
| `get_module()` | `get_module()` | Present | |
| `get_module_extended()` | `get_module_extended()` | Present | |
| `set_module()` | `set_module()` | Present | |
| `set_module_interpolated()` | `set_module_interpolated()` | Present | |
| `get_port()` | `get_port()` | Present | |
| `get_port_extended()` | `get_port_extended()` | Present | |
| `set_port()` | `set_port()` | Present | |
| `set_port_interpolated()` | `set_port_interpolated()` | Present | |
| `connect()` | `connect()` | Present | |
| `disconnect()` | `disconnect()` | Present | |
| `delete_module()` | `delete_module()` | Present | |
| `instance_module()` | `instance_module()` | Present | |
| `get_module_position()` | `get_module_position()` | Present | Return type differs (internal returns tuple directly) |
| `get_modules()` | `get_modules()` | Present | |
| `get_module_type()` | `get_module_type()` | Present | |
| `rename_module()` | `rename_module()` | Present | |
| `suspend()` | `suspend()` | Present | |
| `resume()` | `resume()` | Present | |
| `refresh()` | `refresh()` | Present | |
| `check_cancel()` | `check_cancel()` | Present | |
| `test()` | `test()` | Present | |
| `sigfig()` | `sigfig()` | Present | |
| `format_number()` / `fn()` | `format_number()` / `fn()` | Present | |
| `format_number_adaptive()` / `fn_a()` | `format_number_adaptive()` / `fn_a()` | Present | |
| `get_application_info()` | `get_application_info()` | Present | |
| `is_module_executed()` | `is_module_executed()` | Present | Always returns False (stub) |
| `get_field_info()` | — | **Redesign** | See "Field Data Access" section below |
| `import_asset()` | — | N/A | Internal-only (loads Python modules from EVS application assets via .NET loader). Not applicable externally. |
| `get_export_stage()` | — | N/A | Internal-only (reads globals set by EVS export pipeline). Not applicable externally. |

### New Functions for MCP Server

These do not exist in either API yet and require new pipe operations on the EVS side (ExternalScriptOperations.cs):

| Function | Pipe Method | Purpose |
|---|---|---|
| `get_network_contents_for_mcp(*module_names)` | `GetNetworkContentsForMcp` | Returns diff-only JSON of the current network (non-default property values, no path relativization). Accepts optional module display names to filter. |
| `patch_network_contents(json)` | `PatchNetworkContents` | Applies a partial JSON update to the running network — sets only the properties present in the JSON, without clearing/reloading. This avoids the expense of a full `LoadApplication` round-trip. |
| `new_application()` | `NewApplication` | Clears the current network and resets to a blank application. Requires new pipe operation. |
| `save_application(path)` | `SaveApplication` | Pipe method exists but not exposed in evs_automation. |

### patch_network_contents Design

The MCP workflow is:
1. AI reads current state via `get_network_contents_for_mcp()`
2. AI decides what to change
3. AI sends back a partial JSON with only the changed properties via `patch_network_contents()`

The patch JSON uses the same structure as the MCP contents output:
```json
{
  "Modules": {
    "module_display_name": {
      "Properties": {
        "CategoryName": {
          "PropertyName": new_value
        }
      },
      "Renderables": {
        "port_name": {
          "Properties": {
            "CategoryName": {
              "PropertyName": new_value
            }
          }
        }
      }
    }
  },
  "ApplicationProperties": {
    "Properties": {
      "Properties": {
        "PropertyName": new_value
      }
    }
  }
}
```

This translates directly to `SetValue` calls for each property found in the patch. No module instancing or connection changes — just property updates. Module instancing, connections, and deletions should use the existing discrete API calls.

### Field Data Access

Internally, `get_field_info()` returns a `FieldInfo` object that holds a .NET field reader. Properties like `coordinates` and `values` are lazily loaded and can be very large (millions of points). This doesn't translate to a single pipe call.

External replacement — split into multiple calls:

| Function | Pipe Method | Returns |
|---|---|---|
| `get_field_summary(module, port)` | `GetFieldSummary` | `{number_coordinates, number_cells, number_node_data, number_cell_data, coordinate_units}` |
| `get_field_coordinates(module, port)` | `GetFieldCoordinates` | List of `[x, y, z]` tuples |
| `get_field_cell_centers(module, port)` | `GetFieldCellCenters` | List of `[x, y, z]` tuples |
| `get_field_node_data(module, port, index)` | `GetFieldNodeData` | `{name, units, is_log, values: [...]}` |
| `get_field_cell_data(module, port, index)` | `GetFieldCellData` | `{name, units, is_log, values: [...]}` |

This lets callers fetch only what they need (e.g. just the summary, or just one data component) without pulling the entire field over the pipe. For very large fields, chunked/paginated variants may be needed later.

## Work Items

### Phase 1: EVS-side pipe operations
- [ ] Add `GetNetworkContentsForMcp` operation to `ExternalScriptOperations.cs`
- [ ] Add `PatchNetworkContents` operation to `ExternalScriptOperations.cs`
- [ ] Add `NewApplication` operation to `ExternalScriptOperations.cs`
- [ ] Add field data operations (`GetFieldSummary`, `GetFieldCoordinates`, `GetFieldCellCenters`, `GetFieldNodeData`, `GetFieldCellData`)

### Phase 2: evs_automation library updates
- [ ] Add `get_network_contents_for_mcp(*module_names)` to `_EvsProcess`
- [ ] Add `patch_network_contents(json)` to `_EvsProcess`
- [ ] Add `new_application()` to `_EvsProcess`
- [ ] Add `save_application(path)` to `_EvsProcess`
- [ ] Add field data methods (`get_field_summary`, `get_field_coordinates`, `get_field_cell_centers`, `get_field_node_data`, `get_field_cell_data`)
- [ ] Review and fix any other gaps vs internal API

### Phase 3: MCP server implementation
- [ ] Design MCP tool surface (which tools to expose, granularity)
- [ ] Implement MCP server using evs_automation as the transport
- [ ] Static resource access: read schema/defaults/help from EVS install directory
- [ ] Error handling and connection lifecycle

## Open Questions

- Should `patch_network_contents` support adding/removing connections, or keep that to discrete `connect()`/`disconnect()` calls?
- MCP tool granularity: one big "edit application" tool vs many small tools?
- Field data: will chunked/paginated reads be needed for very large fields, or is the pipe buffer sufficient?
