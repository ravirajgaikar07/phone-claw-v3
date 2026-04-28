"""Tools package — importing this registers all tools with the registry."""

from tools.registry import registry  # noqa: F401

# Import all tool modules so their @registry.register decorators run
from tools import file_tools      # noqa: F401
from tools import system_tools    # noqa: F401
from tools import web_tools       # noqa: F401
from tools import device_tools    # noqa: F401
from tools import session_tools   # noqa: F401
from tools import memory_tools    # noqa: F401
from tools import schedule_tools  # noqa: F401
from tools import code_tools     # noqa: F401
