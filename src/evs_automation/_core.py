# -*- coding: utf-8 -*-
"""
EVS Automation for Python

Allows for automation of Earth Volumetric Studio instances running on the same computer,
when the EVS instance has an appropriate license.

Created by: C Tech Development Corporation - https://ctech.com
"""

from contextlib import contextmanager
import packaging.version                      # Dep: packaging: https://github.com/pypa/packaging
import win32pipe, win32file, pywintypes       # Dep: pywin32
import winreg                                 # Dep: pywin32
import psutil                                 # Dep: psutil
import time
import json
import os
import subprocess
from enum import IntFlag
from typing import Any

class CanceledByUser(Exception):
    """Raised when a script is canceled by the user"""
    pass

class InterpolationMethod(IntFlag):
    """Enumeration describing interpolation methods used by EVS"""
    Step = 1
    Linear = 2
    LinearLog = 4
    Cosine = 8
    CosineLog = 16

def _set_or_find_pid(pid):
    process = None
    if pid == -1:
        for proc in psutil.process_iter():
            if proc.name() == "EarthVolumetricStudio.exe":
                process = proc
        if process == None:
            raise ValueError('EVS Process not found. Please specify Process ID or guarantee that EVS is already running.')
    else:
        try:
            process = psutil.Process(pid)
        except:
            raise ValueError('Invalid Process ID specified. EVS Process not found.')

    return process.pid

def _find_evs_version_path(suggested = None, prefer_development = True):
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\C Tech Development Corporation") as ct_key:
        max_version = packaging.version.Version("1.0.0.0")
        max_version_key_name = ''
        for i in range(0, winreg.QueryInfoKey(ct_key)[0]):
            skey_name = winreg.EnumKey(ct_key, i)
            if skey_name.startswith('Earth Volumetric Studio '):
                version = skey_name.replace('Earth Volumetric Studio ','')
                if version == 'Development':
                    if prefer_development:
                        with winreg.OpenKey(ct_key, skey_name) as version_key:
                            return winreg.QueryValueEx(version_key, "Path")[0]
                    else:
                        continue
                else:
                    v = packaging.version.Version(version)
                    if version == suggested:
                        max_version = Version(v)
                        max_version_key_name = skey_name
                        break
                    elif v > max_version:
                        max_version = v
                        max_version_key_name = skey_name
        if max_version.major > 1:
            with winreg.OpenKey(ct_key, max_version_key_name) as version_key:
                path = winreg.QueryValueEx(version_key, "Path")[0]
                return os.path.join(path, 'bin\\system')
    raise ValueError('EVS Installation Not Found')

def _find_evs_executable_path(suggested = None, prefer_development = True):
    folder = _find_evs_version_path(suggested, prefer_development)
    exe = os.path.join(folder, 'EarthVolumetricStudio.exe')
    if os.path.exists(exe):
        return exe

    raise ValueError('EVS Installation Not Found')



class FieldData:
    """
    Represents one node or cell data component of a field.

    Attributes
    ----------
    name : str
        The name of the data
    units : str
        The data units
    is_log : bool
        Flag indicating that this data is treated using log processing
    component_count : int
        Number of components per value (1 for scalar, 3 for vector, etc.)
    values : list[float | tuple[float, ...]]
        The data values. Scalar data is a flat list, vector data is a list of tuples.
    """
    __slots__ = ('name', 'units', 'is_log', 'component_count', 'values')

    def __init__(self, raw: dict):
        self.name: str = raw['Name']
        self.units: str = raw['Units']
        self.is_log: bool = raw['IsLog']
        self.component_count: int = raw['ComponentCount']
        flat_values: list[float] = raw['Values']
        if self.component_count == 1:
            self.values: list[float | tuple[float, ...]] = flat_values
        else:
            nc = self.component_count
            self.values = [tuple(flat_values[i:i+nc]) for i in range(0, len(flat_values), nc)]


_FIELD_CHUNK_SIZE = 100_000
"""Number of items (points or values) to fetch per pipe call when reading field data.
Each chunk serializes to roughly 1.5–4.5 MB of JSON depending on component count,
keeping memory usage and pipe transfer sizes manageable for large fields."""


class FieldInfo:
    """
    Represents a field, allowing it to be read from Python via external automation.

    Note: Should be used within a with statement. Alternatively, manually call close().

    Attributes
    ----------
    number_coordinates : int
        The number of coordinates in the field
    number_cells : int
        The number of cells in the field
    number_node_data : int
        The number of node data components in the field
    number_cell_data : int
        The number of cell data components in the field
    coordinate_units : str
        The units used for the coordinates
    coordinates : list[tuple[float,float,float]]
        The list of (x,y,z) coordinate tuples for nodes, loaded lazily
    cell_centers : list[tuple[float,float,float]]
        The list of (x,y,z) coordinate tuples for cell centers, loaded lazily

    Methods
    -------
    get_node_data(index):
        Gets the node data component at the specified index
    get_cell_data(index):
        Gets the cell data component at the specified index
    close():
        Marks the FieldInfo as closed
    """
    __slots__ = ('_proc', '_module', '_port', '_summary', '_coordinates', '_cell_centers', '_closed')

    def __init__(self, proc: 'EvsProcess', module: str, port: str):
        self._proc = proc
        self._module = module
        self._port = port
        self._summary = proc._internal_request("GetFieldSummary", module, port)
        self._coordinates: list[tuple[float,float,float]] | None = None
        self._cell_centers: list[tuple[float,float,float]] | None = None
        self._closed = False

    def __enter__(self) -> 'FieldInfo':
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _check_closed(self):
        if self._closed:
            raise ValueError('FieldInfo has been closed')

    @property
    def number_coordinates(self) -> int:
        """The number of coordinates in the field"""
        return self._summary['NumberOfCoordinates']

    @property
    def number_cells(self) -> int:
        """The number of cells in the field"""
        return self._summary['NumberOfCells']

    @property
    def number_node_data(self) -> int:
        """The number of node data components in the field"""
        return self._summary['NumberOfNodeData']

    @property
    def number_cell_data(self) -> int:
        """The number of cell data components in the field"""
        return self._summary['NumberOfCellData']

    @property
    def coordinate_units(self) -> str:
        """The units used for the coordinates"""
        return self._summary['CoordinateUnits']

    def _fetch_point_data(self, method: str, total: int) -> list[tuple[float,float,float]]:
        """Fetches 3D point data (coordinates or cell centers) in chunks."""
        if total <= _FIELD_CHUNK_SIZE:
            raw = self._proc._internal_request(method, self._module, self._port)
            return [tuple(raw[i:i+3]) for i in range(0, len(raw), 3)]

        points: list[tuple[float,float,float]] = []
        offset = 0
        while offset < total:
            count = min(_FIELD_CHUNK_SIZE, total - offset)
            raw = self._proc._internal_request(method, self._module, self._port, offset, count)
            points.extend(tuple(raw[i:i+3]) for i in range(0, len(raw), 3))
            offset += count
        return points

    @property
    def coordinates(self) -> list[tuple[float,float,float]]:
        """The list of (x,y,z) coordinate tuples for nodes, loaded lazily"""
        self._check_closed()
        if self._coordinates is None:
            self._coordinates = self._fetch_point_data("GetFieldCoordinates", self.number_coordinates)
        return self._coordinates

    @property
    def cell_centers(self) -> list[tuple[float,float,float]]:
        """The list of (x,y,z) coordinate tuples for cell centers, loaded lazily"""
        self._check_closed()
        if self._cell_centers is None:
            self._cell_centers = self._fetch_point_data("GetFieldCellCenters", self.number_cells)
        return self._cell_centers

    def _fetch_data_component(self, method: str, index: int, total_values: int) -> FieldData:
        """Fetches a data component (node or cell) in chunks if needed."""
        if total_values <= _FIELD_CHUNK_SIZE:
            raw = self._proc._internal_request(method, self._module, self._port, index)
            return FieldData(raw)

        # Fetch in chunks — each response includes metadata + sliced Values
        all_values: list[float] = []
        metadata: dict | None = None
        offset = 0
        while offset < total_values:
            count = min(_FIELD_CHUNK_SIZE, total_values - offset)
            raw = self._proc._internal_request(method, self._module, self._port, index, offset, count)
            if metadata is None:
                metadata = raw
            all_values.extend(raw['Values'])
            offset += count
        metadata['Values'] = all_values
        return FieldData(metadata)

    def get_node_data(self, index: int) -> FieldData:
        """
        Gets the node data component at the specified index, including all values.

        For large fields (>100K nodes), values are fetched in chunks transparently.

        Keyword Arguments:
        index -- the zero-based index of the node data component (required)

        Raises
        ------
        ValueError
            If the index is out of range or the FieldInfo is closed
        """
        self._check_closed()
        if index < 0 or index >= self.number_node_data:
            raise ValueError('Node data index out of range')
        return self._fetch_data_component("GetFieldNodeData", index, self.number_coordinates)

    def get_cell_data(self, index: int) -> FieldData:
        """
        Gets the cell data component at the specified index, including all values.

        For large fields (>100K cells), values are fetched in chunks transparently.

        Keyword Arguments:
        index -- the zero-based index of the cell data component (required)

        Raises
        ------
        ValueError
            If the index is out of range or the FieldInfo is closed
        """
        self._check_closed()
        if index < 0 or index >= self.number_cell_data:
            raise ValueError('Cell data index out of range')
        return self._fetch_data_component("GetFieldCellData", index, self.number_cells)

    def close(self) -> None:
        """Marks the FieldInfo as closed."""
        self._closed = True


class EvsProcess:
    """A connection to a running Earth Volumetric Studio process.

    Do not instantiate this class directly. Use :func:`start_new` or
    :func:`connect_to_existing` to obtain an instance.
    """

    _bufferSize = 8192 * 8
    def __init__(self, pid, timeout):
        self.__handle = None
        self.__pid = pid
        # Give up to 5 seconds for process to start listening
        attempts_remaining = 5
        pipeName = f'\\\\.\\pipe\\EVS_{self.__pid}'
        while attempts_remaining > 0:

            try:
                self.__handle = win32file.CreateFile(
                        pipeName,
                        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                        0,
                        None,
                        win32file.OPEN_EXISTING,
                        0,
                        None
                    )
                break
            except:
                time.sleep(1)
                pass

        attempts_remaining = timeout
        success = False
        while attempts_remaining > 0:
            res = win32pipe.SetNamedPipeHandleState(self.__handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
            if res == 0:
                time.sleep(1)
                attempts_remaining = attempts_remaining - 1
            else:
                success = True
                break

        if not success:
            raise ValueError('Invalid Process ID specified. EVS Process not found or connection refused.')

    def __write(self, msg):
        win32file.WriteFile(self.__handle, (msg + "\n").encode('utf-8'))

    def __read(self):
        (success,resp) = win32file.ReadFile(self.__handle, self._bufferSize)
        return resp.decode('utf-8')

    def __send_json(self, pyobj):
        msg = json.dumps(pyobj)
        self.__write(msg)

    def __recv_json(self):
        msg = self.__read()
        return json.loads(msg)

    def __request(self, method, *args):
        self.__send_json({"method": method, "args": args})
        msg = self.__recv_json()
        return msg

    def __build_result(self, method, *args):
        res = self.__request(method, *args)
        if res['Success']:
            return res['Value']
        else:
            raise ValueError(res['Error'])

    def _internal_request(self, method, *args):
        """Internal method for use by helper classes like FieldInfo. Not part of the public API."""
        return self.__build_result(method, *args)

    def get_api_version(self) -> float:
        """
        Ask EVS for the API Version being used.
        """
        return self.__build_result("Version")

    def wait_for_ready(self) -> Any:
        """
        Wait until EVS is done processing. This is recommended after all initial
        connections and any load application or run script calls.
        """
        return self.__build_result("WaitForReady")

    def shutdown(self) -> Any:
        """
        Ask EVS to shut down.
        """
        return self.__build_result("Shutdown")

    def close(self) -> bool:
        """
        Close the connection to EVS.
        """
        if (self.__handle == None):
            return False

        self.__handle.close()
        self.__handle = None
        self.__pid = None
        return True

    def new_application(self) -> Any:
        """
        Clear the current network and reset to a blank application with default
        application properties and a viewer module.
        """
        return self.__build_result("NewApplication")

    def load_application(self, application_file: str) -> Any:
        """
        Load an application within EVS.

        Keyword Arguments:
        application_file -- the full path to the .evs application (required)
        """
        return self.__build_result("LoadApplication", application_file)

    def save_application(self, application_file: str) -> Any:
        """
        Save the current application within EVS.

        Keyword Arguments:
        application_file -- the full path to save the .evs application to (required)
        """
        return self.__build_result("SaveApplication", application_file)

    def execute_python_script(self, script_file: str) -> Any:
        """
        Execute a python script within EVS.

        Keyword Arguments:
        script_file -- the full path to the .py script (required)
        """
        return self.__build_result("ExecuteScript", script_file)

    def get_application_info(self) -> dict[str, str]:
        """
        Gets basic information about the current application.

        Returns: dict with keys Author, Organization, Filename, ExecutingScript
        """
        return self.__build_result("GetApplicationInformation")

    def get_module(self, module: str, category: str, property: str) -> Any:
        """
        Get a property value from a module within the application.

        Keyword Arguments:
        module -- the name of the module (required)
        category -- the category of the property (required)
        property -- the name of the property to read (required)
        """
        return self.__build_result("GetValue", module, '', category, property, False)

    def get_module_extended(self, module: str, category: str, property: str) -> Any:
        """
        Get an extended property value from a module within the application.

        Keyword Arguments:
        module -- the name of the module (required)
        category -- the category of the property (required)
        property -- the name of the property to read (required)
        """
        return self.__build_result("GetValue", module, '', category, property, True)

    def get_port(self, module: str, port: str, category: str, property: str) -> Any:
        """
        Get a value from a port in a module within the application.

        Keyword Arguments:
        module -- the name of the module (required)
        port -- the name of the port (required)
        category -- the category of the property (required)
        property -- the name of the property to read (required)
        """
        return self.__build_result("GetValue", module, port, category, property, False)

    def get_port_extended(self, module: str, port: str, category: str, property: str) -> Any:
        """
        Get an extended value from a port in a module within the application.

        Keyword Arguments:
        module -- the name of the module (required)
        port -- the name of the port (required)
        category -- the category of the property (required)
        property -- the name of the property to read (required)
        """
        return self.__build_result("GetValue", module, port, category, property, True)

    def set_module(self, module: str, category: str, property: str, value: Any) -> None:
        """
        Set a property value on a module within the application.

        Keyword Arguments:
        module -- the name of the module (required)
        category -- the category of the property (required)
        property -- the name of the property to set (required)
        value -- the new value for the property (required)
        """
        self.__build_result("SetValue", module, '', category, property, value)

    def set_module_interpolated(self, module: str, category: str, property: str, start_value: Any, end_value: Any, percent: float, interpolation_method: InterpolationMethod = InterpolationMethod.Linear) -> None:
        """
        Set a property value by interpolating between two values in a module within the application.

        Keyword Arguments:
        module -- the name of the module (required)
        category -- the category of the property (required)
        property -- the name of the property to set (required)
        start_value -- the start value for the interpolation (required)
        end_value -- the end value for the interpolation (required)
        percent -- the percentage along the interpolation from the start to end value (required)
        interpolation_method -- the type of interpolation to perform (optional)
            Defaults to InterpolationMethod.Linear
        """
        self.__build_result("SetValueInterpolated", module, '', category, property, start_value, end_value, percent, int(interpolation_method))

    def set_port(self, module: str, port: str, category: str, property: str, value: Any) -> None:
        """
        Set a property value on a port in a module within the application.

        Keyword Arguments:
        module -- the name of the module (required)
        port -- the name of the port (required)
        category -- the category of the property (required)
        property -- the name of the property to set (required)
        value -- the new value for the property (required)
        """
        self.__build_result("SetValue", module, port, category, property, value)

    def set_port_interpolated(self, module: str, port: str, category: str, property: str, start_value: Any, end_value: Any, percent: float, interpolation_method: InterpolationMethod = InterpolationMethod.Linear) -> None:
        """
        Set a property value by interpolating between two values in a port in a module within the application.

        Keyword Arguments:
        module -- the name of the module (required)
        port -- the name of the port (required)
        category -- the category of the property (required)
        property -- the name of the property to set (required)
        start_value -- the start value for the interpolation (required)
        end_value -- the end value for the interpolation (required)
        percent -- the percentage along the interpolation from the start to end value (required)
        interpolation_method -- the type of interpolation to perform (optional)
            Defaults to InterpolationMethod.Linear
        """
        self.__build_result("SetValueInterpolated", module, port, category, property, start_value, end_value, percent, int(interpolation_method))

    def connect(self, starting_module: str, starting_port: str, ending_module: str, ending_port: str) -> bool:
        """
        Connect two modules in the application.

        Keyword Arguments:
        starting_module -- the starting module (required)
        starting_port -- the port on the starting module (required)
        ending_module -- the ending module (required)
        ending_port -- the port on the ending module (required)
        """
        self.__build_result("Connect", starting_module, starting_port, ending_module, ending_port)
        return True

    def disconnect(self, starting_module: str, starting_port: str, ending_module: str, ending_port: str) -> bool:
        """
        Disconnect two modules in the application.

        Keyword Arguments:
        starting_module -- the starting module (required)
        starting_port -- the port on the starting module (required)
        ending_module -- the ending module (required)
        ending_port -- the port on the ending module (required)
        """
        self.__build_result("Disconnect", starting_module, starting_port, ending_module, ending_port)
        return True

    def delete_module(self, module: str) -> bool:
        """
        Delete a module from the application.

        Keyword Arguments:
        module -- the module to delete (required)
        """
        self.__build_result("DeleteModule", module)
        return True

    def instance_module(self, module: str, suggested_name: str, x: int, y: int) -> str:
        """
        Instances a module in the application.

        Keyword Arguments:
        module -- the module to instance (required)
        suggested_name -- the suggested name for the module to instance (required)
        x -- the x coordinate (required)
        y -- the y coordinate (required)

        Returns: The name of the instanced module
        """
        return self.__build_result("InstanceModule", module, suggested_name, x, y)

    def get_module_position(self, module: str) -> tuple[int, int]:
        """
        Gets the position of a module.

        Keyword Arguments:
        module -- the module (required)

        Returns: A tuple containing the (x, y) coordinate
        """
        result = self.__build_result("GetModulePosition", module)
        return (int(result['X']), int(result['Y']))

    def suspend(self) -> Any:
        """
        Suspends the execution of the application until a resume is called.
        """
        return self.__build_result("Suspend")

    def resume(self) -> Any:
        """
        Resumes the execution of the application, causing any suspended operations to run.
        """
        return self.__build_result("Resume")

    def refresh(self) -> None:
        """
        Refreshes the viewer and processes all mouse and keyboard actions in the application. Potentially unsafe operation.
        """
        self.__build_result("Refresh")

    def get_network_contents_for_mcp(self, *module_names: str) -> Any:
        """
        Get the current network contents in MCP format (non-default property values only, no path relativization).

        Keyword Arguments:
        *module_names -- optional module display names to filter to specific modules.
            Pass no arguments to get all modules and application properties.
            Pass 'Application Properties' or 'application_properties' to get only application properties.
        """
        return self.__build_result("GetNetworkContentsForMcp", *module_names)

    def patch_network_contents(self, patch_json: str | dict) -> Any:
        """
        Apply a partial JSON update to the running network. Sets only the properties present
        in the JSON without clearing or reloading the network. All changes (properties,
        connections, disconnections) are batched in a single bulk update.

        The patch JSON should use the same structure as get_network_contents_for_mcp output:
        {
            "ApplicationProperties": { "Properties": { "Category": { "Property": value } } },
            "Modules": { "module_name": { "Properties": { ... }, "Renderables": { ... } } },
            "AddConnections": [
                { "FromModule": "mod_a", "FromPort": "out", "ToModule": "mod_b", "ToPort": "in" }
            ],
            "RemoveConnections": [
                { "FromModule": "mod_a", "FromPort": "out", "ToModule": "mod_b", "ToPort": "in" }
            ]
        }

        Keyword Arguments:
        patch_json -- JSON string or dict containing the properties to update (required)
        """
        if isinstance(patch_json, dict):
            patch_json = json.dumps(patch_json)
        return self.__build_result("PatchNetworkContents", patch_json)

    def get_field_info(self, module: str, port: str) -> 'FieldInfo':
        """
        Gets a FieldInfo for a given port specified by a module and port.

        Note: Should be used within a with statement (recommended) or call close() manually.

        Keyword Arguments:
        module -- the name of the module (required)
        port -- the name of the port containing a field to read (required)

        Example:
            with evs.get_field_info('kriging_3d', 'field_out') as field:
                print(field.number_coordinates)
                for i in range(field.number_node_data):
                    data = field.get_node_data(i)
                    print(f'{data.name}: {len(data.values)} values')
        """
        return FieldInfo(self, module, port)

    def import_asset(self, name: str) -> None:
        """
        Not available in external automation. Use standard Python imports instead.
        """
        raise NotImplementedError("import_asset is not available in external automation. Use standard Python imports instead.")

    def get_export_stage(self) -> None:
        """
        Not available in external automation. Export stages are only accessible from scripts running inside EVS.
        """
        raise NotImplementedError("get_export_stage is not available in external automation. Export stages are only accessible from scripts running inside EVS.")

    def is_module_executed(self) -> bool:
        """
        Always returns False. External automation scripts are never executed by a module.
        Included for compatibility with EVS internal scripting.
        """
        return False

    def get_modules(self) -> list[str]:
        """
        Gets a list of all module names in the application.

        Returns: List of modules by name
        """
        return self.__build_result("GetModules")

    def get_module_type(self, module: str) -> str:
        """
        Gets the type of a module given its name.

        Keyword Arguments:
        module -- the name of the module (required)
        """
        return self.__build_result("GetModuleType", module)

    def rename_module(self, module: str, suggested_name: str) -> str:
        """
        Renames a module, and returns the new name.

        Keyword Arguments:
        module -- the name of the module to rename (required)
        suggested_name -- the suggested name of the module after renaming (required)

        Returns: The new name of the module
        """
        return self.__build_result("RenameModule", module, suggested_name)

    def test(self, assertion: bool, error_on_fail: str) -> bool:
        """
        Asserts that a condition is true.

        Keyword Arguments:
        assertion -- True or False
        error_on_fail -- the message to raise as an error when assertion is False
        """
        if not assertion:
            raise ValueError(error_on_fail)
        return assertion

    def check_cancel(self) -> None:
        """
        Checks to see whether a user cancelation request has occurred.
        Will stop the script at that point by raising a CanceledByUser exception if it has.
        """
        canceled = self.__build_result("CheckCancel")
        if canceled:
            raise CanceledByUser("Script canceled by user.")

    def sigfig(self, number: float, digits: int) -> float:
        """
        Converts a number to have a specified number of significant figures.

        Keyword Arguments:
        number -- the value (required)
        digits -- the number of significant digits (required)
        """
        return self.__build_result("SigFig", number, digits)

    def format_number(self, number: float, digits: int = 6, include_thousands_separators: bool = True, preserve_trailing_zeros: bool = False) -> str:
        """
        Converts a number to a string using a specified number of significant figures.

        Keyword Arguments:
        number -- the value (required)
        digits -- the number of significant digits (optional, default 6)
        include_thousands_separators -- whether to include separators for thousands (optional, defaults to True)
        preserve_trailing_zeros -- whether to preserve trailing zeros when computing significant digits (optional, defaults to False)
        """
        return self.__build_result("FormatNumber", number, digits, include_thousands_separators, preserve_trailing_zeros)

    def fn(self, number: float, digits: int = 6, include_thousands_separators: bool = True, preserve_trailing_zeros: bool = False) -> str:
        """
        Converts a number to a string using a specified number of significant figures.

        Keyword Arguments:
        number -- the value (required)
        digits -- the number of significant digits (optional, default 6)
        include_thousands_separators -- whether to include separators for thousands (optional, defaults to True)
        preserve_trailing_zeros -- whether to preserve trailing zeros when computing significant digits (optional, defaults to False)
        """
        return self.__build_result("FormatNumber", number, digits, include_thousands_separators, preserve_trailing_zeros)

    def format_number_adaptive(self, number: float, adapt_size: float, digits: int = 6, include_thousands_separators: bool = True, preserve_trailing_zeros: bool = False) -> str:
        """
        Converts a number to a string using a specified number of significant figures, adapted to the precision of a second number.

        Keyword Arguments:
        number -- the value (required)
        adapt_size -- the second value, to adapt precision to (required)
        digits -- the number of significant digits (optional, default 6)
        include_thousands_separators -- whether to include separators for thousands (optional, defaults to True)
        preserve_trailing_zeros -- whether to preserve trailing zeros when computing significant digits (optional, defaults to False)
        """
        return self.__build_result("FormatNumberAdaptive", number, adapt_size, digits, include_thousands_separators, preserve_trailing_zeros)

    def fn_a(self, number: float, adapt_size: float, digits: int = 6, include_thousands_separators: bool = True, preserve_trailing_zeros: bool = False) -> str:
        """
        Converts a number to a string using a specified number of significant figures, adapted to the precision of a second number.

        Keyword Arguments:
        number -- the value (required)
        adapt_size -- the second value, to adapt precision to (required)
        digits -- the number of significant digits (optional, default 6)
        include_thousands_separators -- whether to include separators for thousands (optional, defaults to True)
        preserve_trailing_zeros -- whether to preserve trailing zeros when computing significant digits (optional, defaults to False)
        """
        return self.__build_result("FormatNumberAdaptive", number, adapt_size, digits, include_thousands_separators, preserve_trailing_zeros)


@contextmanager
def start_new(auto_shutdown: bool = True, timeout: int = 300, auto_wait_for_ready: bool = True, start_minimized: bool = False):
    """
    Start a new instance of EVS, and connect to it.

    Note that this is intended to be used with the "with evs_automation.start_new() as evs:" syntax

    Keyword Arguments:
    auto_shutdown -- Whether to shut down after the scope used in "with" syntax ends (optional, defaults to True)
    timeout -- number of seconds to wait for EVS to startup and get licensing (optional, defaults to 300)
    auto_wait_for_ready -- whether to automatically wait until EVS is ready before continuing (optional, defaults to True)
    start_minimized -- whether to start EVS in a minimized state (optional, defaults to False)
    """
    exe = _find_evs_executable_path()
    args = [exe, '-n', '-w', '-m'] if start_minimized else [exe, '-n', '-w']
    process = subprocess.Popen(args)
    _pid = process.pid
    time.sleep(1.0)
    proc = EvsProcess(_pid, timeout)
    try:
        version = proc.get_api_version()
        if (version != 1.0):
            raise ValueError("EVS does not support proper API version for this release.")
        if auto_wait_for_ready:
            proc.wait_for_ready()
        yield proc
    except:
        proc.close()
        raise
    else:
        if auto_shutdown:
            proc.shutdown()
        proc.close()

@contextmanager
def connect_to_existing(pid: int = -1, auto_shutdown: bool = False, timeout: int = 60, auto_wait_for_ready: bool = True):
    """
    Connect to an existing, running instance of EVS.

    Note that this is intended to be used with the "with evs_automation.connect_to_existing() as evs:" syntax

    Keyword Arguments:
    pid -- The process ID of the EVS instance to connect to. If -1, try to find a running instance (optional, defaults to -1)
    auto_shutdown -- Whether to shut down after the scope used in "with" syntax ends (optional, defaults to False)
    timeout -- number of seconds to wait for EVS to startup and get licensing (optional, defaults to 60)
    auto_wait_for_ready -- whether to automatically wait until EVS is ready before continuing (optional, defaults to True)
    """
    _pid = _set_or_find_pid(pid)

    proc = EvsProcess(_pid, timeout)
    try:
        version = proc.get_api_version()
        if (version != 1.0):
            raise ValueError("EVS does not support proper API version for this release.")
        if auto_wait_for_ready:
            proc.wait_for_ready()
        yield proc
    except:
        proc.close()
        raise
    else:
        if auto_shutdown:
            proc.shutdown()
        proc.close()
