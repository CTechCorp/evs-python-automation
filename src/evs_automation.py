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
from enum import IntEnum

class CanceledByUser(Exception):
    pass

class InterpolationMethod(IntEnum):
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
    


class _EvsProcess:
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

    def get_api_version(self):
        """
        Ask EVS for the API Version being used.
        
        Keyword Arguments: None
        """
        return self.__build_result("Version")
        
    def wait_for_ready(self):
        """
        Wait until EVS is done processing. This is recommend after all initial connections and any load application or run script calls.
        
        Keyword Arguments: None
        """
        return self.__build_result("WaitForReady")
    
    def shutdown(self):
        """
        Ask EVS to shut down.
        
        Keyword Arguments: None
        """
        return self.__build_result("Shutdown")        
    
    def close(self):
        """
        Close the connection to EVS.
        
        Keyword Arguments: None
        """
        if (self.__handle == None):
            return False

        self.__handle.close()
        self.__handle = None
        self.__pid = None
        return True

    def load_application(self, application_file):
        """
        Load an application within EVS.

        Keyword Arguments:
        application_file -- the full path to the .evs application (required)
        """
        return self.__build_result("LoadApplication", application_file)

    def save_application(self, application_file):
        """
        Save the current application within EVS.

        Keyword Arguments:
        application_file -- the full path to save the .evs application to (required)
        """
        return self.__build_result("SaveApplication", application_file)

    def execute_python_script(self, script_file):
        """
        Execute a python script within EVS.
        
        Keyword Arguments: 
        script_file -- the full path to the .py script (required)
        """
        return self.__build_result("ExecuteScript", script_file)
        
    def get_application_info(self):
        """
        Gets basic information about the current application.
        
        Keyword Arguments: None
        """
        return self.__build_result("GetApplicationInformation")
        
    def get_module(self, module, category, property):
        """
        Get a property value from a module within the application.
        
        Keyword Arguments:
        module -- the name of the module (required)
        category -- the category of the property(required)
        property -- the name of the property to read(required)
        """
        return self.__build_result("GetValue", module, '', category, property, False)

    def get_module_extended(self, module, category, property):
        """
        Get an extended property value from a module within the application.
        
        Keyword Arguments:
        module -- the name of the module (required)
        category -- the category of the property(required)
        property -- the name of the property to read(required)
        """
        return self.__build_result("GetValue", module, '', category, property, True)

    def get_port(self, module, port, category, property):
        """
        Get a value from a port in a module within the application.
        
        Keyword Arguments:
        module -- the name of the module (required)
        port -- the name of the port(required)
        category -- the category of the property(required)
        property -- the name of the property to read(required)
        """
        return self.__build_result("GetValue", module, port, category, property, False)
            
    def get_port_extended(self, module, port, category, property):
        """
        Get an extended value from a port in a module within the application.
        
        Keyword Arguments:
        module -- the name of the module (required)
        port -- the name of the port(required)
        category -- the category of the property(required)
        property -- the name of the property to read(required)
        """
        return self.__build_result("GetValue", module, port, category, property, True)
            
    def set_module(self, module, category, property, value):
        """
        Set a property value to a module within the application.
        
        Keyword Arguments:
        module -- the name of the module (required)
        category -- the category of the property(required)
        property -- the name of the property to read(required)
        value -- the new value for the property(required)
        """
        return self.__build_result("SetValue", module, '', category, property, value)

    def set_module_interpolated(self, module, category, property, start_value, end_value, percent, interpolation_method = InterpolationMethod.Linear):
        """
        Set a property value by interpolating between two values in a module within the application.
        
        Keyword Arguments:
        module -- the name of the module (required)
        category -- the category of the property(required)
        property -- the name of the property to read(required)
        start_value -- the start value for the interpolation(required)
        end_value -- the end value for the interpolation(required)
        percent -- the percentage along the interpolation from the start to end value(required)
        interpolation_type -- the type of interpolation to perform(optional) 
            Defaults to evs.InterpolationMethod.Linear
        """
        return self.__build_result("SetValueInterpolated", module, '', category, property, start_value, end_value, percent, interpolation_method.value)

    def set_port(self, module, port, category, property, value):
        """
        Set a property value to a port in a module within the application.
        
        Keyword Arguments:
        module -- the name of the module (required)
        port -- the name of the port(required)
        category -- the category of the property(required)
        property -- the name of the property to read(required)
        value -- the new value for the property(required)
        """
        return self.__build_result("SetValue", module, port, category, property, value)
                    
    def set_port_interpolated(self, module, port, category, property, start_value, end_value, percent, interpolation_method = InterpolationMethod.Linear):
        """
        Set a property value by interpolating between two values in a port in a module within the application.
        
        Keyword Arguments:
        module -- the name of the module (required)
        port -- the name of the port(required)
        category -- the category of the property(required)
        property -- the name of the property to read(required)
        start_value -- the start value for the interpolation(required)
        end_value -- the end value for the interpolation(required)
        percent -- the percentage along the interpolation from the start to end value(required)
        interpolation_type -- the type of interpolation to perform(optional) 
            Defaults to evs.InterpolationMethod.Linear
        """
        return self.__build_result("SetValueInterpolated", module, port, category, property, start_value, end_value, percent, interpolation_method.value)

    def connect(self, starting_module, starting_port, ending_module, ending_port):
        """
        Connect two modules in the application.
    
        Keyword Arguments:
        starting_module -- the starting module (required)
        starting_port -- the port on the starting module (required)
        ending_module -- the ending module (required)
        ending_port -- the port on the ending module (required)
        """
        return self.__build_result("Connect", starting_module, starting_port, ending_module, ending_port)
    
    def disconnect(self, starting_module, starting_port, ending_module, ending_port):
        """
        Disconnect two modules in the application.
    
        Keyword Arguments:
        starting_module -- the starting module (required)
        starting_port -- the port on the starting module (required)
        ending_module -- the ending module (required)
        ending_port -- the port on the ending module (required)
        """
        return self.__build_result("Disconnect", starting_module, starting_port, ending_module, ending_port)
  
    def delete_module(self, module):
        """
        Delete a module from the application.
    
        Keyword Arguments:
        module -- the module to delete (required)
        """
        return self.__build_result("DeleteModule", module)

    def instance_module(self, module, suggested_name, x, y):
        """
        Instances a module in the application.
    
        Keyword Arguments:
        module -- the module to instance (required)
        suggested_name -- the suggested name for the module to instance (required)
        x -- the x coordinate (required)
        y -- the y coordinate (required)
    
        Result: The name of the instanced module
        """
        return self.__build_result("InstanceModule", module, suggested_name, x, y)
    
    def get_module_position(self, module):
        """
        Gets the position of a module.
    
        Keyword Arguments:
        module -- the module (required)
    
        Result: A tuple containing the (x,y) coordinate
        """
        result = self.__build_result("GetModulePosition", module)
        return (int(result.X), int(result.Y))

    def suspend(self):
        """
        Suspends the execution of the application until a resume is called.
        """
        return self.__build_result("Suspend")
    
    def resume(self):
        """
        Resumes the execution of the application, causing any suspended operations to run.
        """
        return self.__build_result("Resume")
    
    def refresh(self):
        """
        Refreshes the viewer and processes all mouse and keyboard actions in the application. Potentially unsafe operation.
        """
        return self.__build_result("Refresh")

    def get_network_contents_for_mcp(self, *module_names):
        """
        Get the current network contents in MCP format (non-default property values only, no path relativization).

        Keyword Arguments:
        *module_names -- optional module display names to filter to specific modules.
            Pass no arguments to get all modules and application properties.
            Pass 'Application Properties' or 'application_properties' to get only application properties.
        """
        return self.__build_result("GetNetworkContentsForMcp", *module_names)

    def patch_network_contents(self, patch_json):
        """
        Apply a partial JSON update to the running network. Sets only the properties present
        in the JSON without clearing or reloading the network.

        The patch JSON should use the same structure as get_network_contents_for_mcp output:
        {
            "ApplicationProperties": { "Properties": { "Category": { "Property": value } } },
            "Modules": { "module_name": { "Properties": { ... }, "Renderables": { ... } } }
        }

        Keyword Arguments:
        patch_json -- JSON string or dict containing the properties to update (required)
        """
        if isinstance(patch_json, dict):
            patch_json = json.dumps(patch_json)
        return self.__build_result("PatchNetworkContents", patch_json)

    def is_module_executed(self):
        """
        Always returns False. Included for compatibility with EVS internal scripting.
        External automation scripts are never executed by a module.
        """
        return False

    def get_modules(self):
        """
        Gets a list of all module names in the application.
    
        Returns: List of modules by name
        """
        return self.__build_result("GetModules")
    
    def get_module_type(self, module):
        """
        Gets the type of a module given its name.
    
        Keyword Arguments:
        module -- the name of the module (required)
        """
        return self.__build_result("GetModuleType", module)
    
    def rename_module(self, module, suggested_name):
        """
        Renames a module, and returns the new name.
        
        Keyword Arguments:
        module -- the name of the module to rename(required)
        suggested_name -- the suggested name of the module after renaming (required)
    
        Returns: The new name of the module
        """
        return self.__build_result("RenameModule", module, suggested_name)
    
    def test(self, assertion, error_on_fail):
        """
        Asserts that a condition is true. Note that this raises an exception here, unlike in EVS.
    
        Keyword Arguments:
        assertion -- True or False
        error_on_assertion -- the message to print as an error when assertion is False
        """
        if not assertion:
            raise ValueError(error_on_fail)
        return assertion
    
    def check_cancel(self):
        """
        Checks to see whether a user cancelation request has occurred. Will stop the script at that point by raising an CanceledByUser exception if it has.
        """
        canceled = self.__build_result("CheckCancel")
        if canceled:
            raise CanceledByUser("Script canceled by user.")
    
    def sigfig(self, number, digits):
        """
        Converts a number to have a specified number of significant figures.
    
        Keyword Arguments:
        number -- the value (required)
        digits -- the number of significant digits (required)
        """
        return self.__build_result("SigFig", number, digits)
    
    def format_number(self, number, digits=6, include_thousands_separators=True, preserve_trailing_zeros=False):
        """
        Converts a number to a string using a specified number of significant figures.
    
        Keyword Arguments:
        number -- the value (required)
        digits -- the number of significant digits (optional - default of 6)
        include_thousands_separators -- whether to include separators for thousands (optional, defaults to True)
        preserve_trailing_zeros -- whether to preserve trailing zeros when computing significant digits(optional, defaults to False)
        """
        return self.__build_result("FormatNumber", number, digits, include_thousands_separators, preserve_trailing_zeros)
    
    def fn(self, number, digits=6, include_thousands_separators=True, preserve_trailing_zeros=False):
        """
        Converts a number to a string using a specified number of significant figures.
    
        Keyword Arguments:
        number -- the value (required)
        digits -- the number of significant digits (optional - default of 6)
        include_thousands_separators -- whether to include separators for thousands (optional, defaults to True)
        preserve_trailing_zeros -- whether to preserve trailing zeros when computing significant digits(optional, defaults to False)
        """
        return self.__build_result("FormatNumber", number, digits, include_thousands_separators, preserve_trailing_zeros)
    
    def format_number_adaptive(self, number, adapt_size, digits=6, include_thousands_separators=True, preserve_trailing_zeros=False):
        """
        Converts a number to a string using a specified number of significant figures, adapted to the precision of a second number.
    
        Keyword Arguments:
        number -- the value (required)
        adapt_size -- the second value, to adapt precision to (required)
        digits -- the number of significant digits (optional - default of 6)
        include_thousands_separators -- whether to include separators for thousands (optional, defaults to True)
        preserve_trailing_zeros -- whether to preserve trailing zeros when computing significant digits(optional, defaults to False)
        """
        return self.__build_result("FormatNumberAdaptive", number, adapt_size, digits, include_thousands_separators, preserve_trailing_zeros)
    
    def fn_a(self, number, adapt_size, digits=6, include_thousands_separators=True, preserve_trailing_zeros=False):
        """
        Converts a number to a string using a specified number of significant figures, adapted to the precision of a second number.
    
        Keyword Arguments:
        number -- the value (required)
        adapt_size -- the second value, to adapt precision to (required)
        digits -- the number of significant digits (optional - default of 6)
        include_thousands_separators -- whether to include separators for thousands (optional, defaults to True)
        preserve_trailing_zeros -- whether to preserve trailing zeros when computing significant digits(optional, defaults to False)
        """
        return self.__build_result("FormatNumberAdaptive", number, adapt_size, digits, include_thousands_separators, preserve_trailing_zeros)
    

@contextmanager
def start_new(auto_shutdown = True, timeout = 300, auto_wait_for_ready = True, start_minimized = False):
    """
    Start a new instance of EVS, and connect to it.
    
    Note that this is intended to be used with the "with evs_automation.start_new() as evs:" syntax

    Keyword Arguments:
    auto_shutdown -- Whether to shut down after the scope used in "with" syntax ends (optional, defaults to True)
    timeout -- number of seconds to wait for EVS to startup and get licensing (optional, defaults to 300)
    auto_wait_for_ready -- whether to automatically wait until EVS is ready before continuing (optional - default to True)
    start_minimized -- whether to start EVS in a minimized state (optional, defaults to False)
    """
    exe = _find_evs_executable_path()
    args = [exe, '-n', '-w', '-m'] if start_minimized else [exe, '-n', '-w']
    process = subprocess.Popen(args)
    _pid = process.pid
    time.sleep(1.0)
    proc = _EvsProcess(_pid, timeout)
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
def connect_to_existing(pid = -1, auto_shutdown = False, timeout = 60, auto_wait_for_ready = True):
    """
    Connect to an existing, running instance of EVS.
    
    Note that this is intended to be used with the "with evs_automation.connect_to_existing() as evs:" syntax

    Keyword Arguments:
    pid -- The process ID of the EVS instance to connect to. If -1, try to find a running instance (options, defaults to -1)
    auto_shutdown -- Whether to shut down after the scope used in "with" syntax ends (optional, defaults to True)
    timeout -- number of seconds to wait for EVS to startup and get licensing (optional, defaults to 60)
    auto_wait_for_ready -- whether to automatically wait until EVS is ready before continuing (optional - default to True)
    """
    _pid = _set_or_find_pid(pid)
        
    proc = _EvsProcess(_pid, timeout)
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