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

## Available evs_automation API

The MCP server has access to these automation functions via `_EvsProcess`:

### Network / Application Management
| Function | Purpose |
|---|---|
| `get_network_contents_for_mcp(*module_names)` | Returns diff-only JSON of the current network (non-default property values). Accepts optional module display names to filter. |
| `patch_network_contents(json)` | Applies a partial JSON update — sets only the properties present, with batched `AddConnections`/`RemoveConnections` support. |
| `new_application()` | Clears the current network and resets to a blank application. |
| `save_application(path)` | Saves the current application to disk. |
| `get_application_info()` | Returns application metadata. |

### Module Operations
| Function | Purpose |
|---|---|
| `instance_module(type)` | Creates a new module of the given type. |
| `delete_module(name)` | Deletes a module by display name. |
| `rename_module(old, new)` | Renames a module. |
| `get_modules()` | Lists all modules in the network. |
| `get_module_type(name)` | Returns the type of a module. |
| `get_module(name, prop)` | Gets a module property value. |
| `set_module(name, prop, value)` | Sets a module property value. |
| `get_module_position(name)` | Returns the (x, y) position of a module in the network editor. |
| `connect(from_mod, from_port, to_mod, to_port)` | Connects two ports. |
| `disconnect(from_mod, from_port, to_mod, to_port)` | Disconnects two ports. |

### Field Data Access
| Function | Purpose |
|---|---|
| `get_field_info(module, port)` | Returns a `FieldInfo` context manager with lazy chunked access to coordinates, cell centers, node/cell data. |

Field data is fetched in chunks of 100K items transparently. `FieldInfo` properties: `number_coordinates`, `number_cells`, `number_node_data`, `number_cell_data`, `coordinate_units`, `coordinates`, `cell_centers`, `get_node_data(i)`, `get_cell_data(i)`.

### patch_network_contents Format

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
  },
  "AddConnections": [
    { "FromModule": "mod_a", "FromPort": "field_out", "ToModule": "mod_b", "ToPort": "field_in" }
  ],
  "RemoveConnections": [
    { "FromModule": "mod_c", "FromPort": "field_out", "ToModule": "mod_d", "ToPort": "field_in" }
  ]
}
```

All property changes, connection adds, and connection removes are batched within a single `BulkChanges` state push. Module instancing and deletions should still use the existing discrete API calls.

## Work Items

### MCP Server Implementation
- [ ] Design MCP tool surface (which tools to expose, granularity)
- [ ] Implement MCP server using evs_automation as the transport
- [ ] Static resource access: read schema/defaults/help from EVS install directory
- [ ] Error handling and connection lifecycle

## Open Questions

- MCP tool granularity: one big "edit application" tool vs many small tools?
