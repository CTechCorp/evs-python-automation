# EVS Automation for Python

Python automation API for [Earth Volumetric Studio](https://www.ctech.com/products/earth-volumetric-studio/),
a commercial product of [C Tech Development Corporation](https://ctech.com).

This library provides a workflow for controlling EVS from any Python 3 environment.
Care has been taken to enable the same functionality as the internal Python API, as well
as additional features specifically intended to function from automated workflows.

## Features

- **Process Management**: Start new, or connect to existing EVS processes, and automate actions
- **Full EVS Python API**: The evs.* Python functions have all been ported, so scripts written inside EVS can be migrated to work via automation with few, minor changes.
- **New API Additions**: Additional API functions are available, including loading .evs applications, running existing Python scripts, and shutting down EVS

## Requirements

- **Windows** (uses Win32 APIs for communication with EVS)
- **Python 3.12+**
- **Earth Volumetric Studio 2026.3+**

## Installation

```bash
pip install evs-automation
```

Dependencies (`pywin32`, `psutil`, `packaging`) are installed automatically.

## Quick Start

```python
import evs_automation

try:
    # Launch a new EVS process
    with evs_automation.start_new() as evs:
        # Load an application
        evs.load_application('C:\\Projects\\my application.evs')

        # Note that the syntax below is identical to the internal EVS Python script syntax

        # Instance a titles module and set the title
        newmodule = evs.instance_module('titles', 'titles', 363, 679)
        evs.connect(newmodule, 'Output Object', 'viewer', 'Objects')
        evs.set_module(newmodule, 'Properties', 'Title', 'Title added from script')
        evs.set_module(newmodule, 'Positioning', 'Anchor Side', 0)

        # Execute a Python script
        evs.execute_python_script('C:\\Projects\\export_data.py')

        # EVS (by default) will shut down at this point automatically
except Exception as e:
    print(f"Received exception: {e}")
```

## Contributing

Thank you for considering contributing to this project! We welcome all contributions, from minor fixes to major features. To ensure effective and smooth collaboration, please follow these guidelines:

### Contributing Code

1. Check and Open Issues: Before contributing, please check if there are existing issues on GitHub related to your problem or suggestion. If not, open a new one and share the details.

2. Pull Requests: If you want to make changes, first fork the repository, create a branch for your topic, and then submit a pull request. In your pull request, clearly explain what changes you made and why.

3. Code Review: The project maintainers will review your pull request. If there are any comments, please respond to them actively.

### Code of Conduct

We aim to provide all contributors and maintainers with a safe and positive experience. Therefore, we ask you to follow this code of conduct, which is based on the Contributor Covenant:

- Respect Each Other: Treat everyone working on the project respectfully, regardless of background.

- Promote Inclusivity: Actively promote inclusivity and welcome diverse perspectives.

- Maintain a Harassment-Free Environment: Avoid any behavior seen as harassment and maintain a harassment-free environment.

## License

evs-automation is licensed under the MIT License. See [LICENSE](https://github.com/C-Tech-Development-Corp/python_evs_automation?tab=MIT-1-ov-file#readme) for more details.
