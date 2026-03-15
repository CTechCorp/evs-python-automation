# -*- coding: utf-8 -*-
"""
EVS Automation for Python

Allows for automation of Earth Volumetric Studio instances running on the same computer,
when the EVS instance has an appropriate license.

Created by: C Tech Development Corporation - https://ctech.com
"""

__version__ = "0.1.0"

from evs_automation._core import (
    CanceledByUser,
    EvsProcess,
    InterpolationMethod,
    FieldData,
    FieldInfo,
    find_install_path,
    start_new,
    connect_to_existing,
)

from evs_automation.util import (
    evsdate_to_datetime,
    datetime_to_evsdate,
    datetime_to_excel,
    evsdate_to_excel,
    excel_to_datetime,
    excel_to_evsdate,
)

__all__ = [
    "CanceledByUser",
    "EvsProcess",
    "InterpolationMethod",
    "FieldData",
    "FieldInfo",
    "find_install_path",
    "start_new",
    "connect_to_existing",
    "evsdate_to_datetime",
    "datetime_to_evsdate",
    "datetime_to_excel",
    "evsdate_to_excel",
    "excel_to_datetime",
    "excel_to_evsdate",
]
