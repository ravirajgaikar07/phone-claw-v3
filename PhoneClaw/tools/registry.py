"""Tool registry — maps tool names to functions with metadata."""

from utils.logger import get_logger

log = get_logger("tools.registry")


class ToolRegistry:
    """Central registry for all agent tools."""

    def __init__(self):
        self._tools = {}

    def register(self, name, description, args_schema=None):
        """Decorator to register a tool function.

        Usage:
            @registry.register("my_tool", "Does something", {"arg1": "string"})
            def my_tool(arg1):
                ...
        """
        if args_schema is None:
            args_schema = {}

        def decorator(func):
            self._tools[name] = {
                "name": name,
                "description": description,
                "args": args_schema,
                "func": func,
            }
            log.debug("Registered tool: %s", name)
            return func

        return decorator

    def register_func(self, name, func, description, args_schema=None):
        """Register a tool function directly (non-decorator)."""
        if args_schema is None:
            args_schema = {}
        self._tools[name] = {
            "name": name,
            "description": description,
            "args": args_schema,
            "func": func,
        }
        log.debug("Registered tool: %s", name)

    def get(self, name):
        """Get a tool entry by name, or None."""
        return self._tools.get(name)

    def execute(self, name, args=None):
        """Execute a tool by name with the given args dict.

        Returns the result string, or an error string prefixed with 'ERROR:'.
        """
        if args is None:
            args = {}

        tool = self._tools.get(name)
        if tool is None:
            return f"ERROR: Unknown tool '{name}'"

        try:
            result = tool["func"](**args)
            return str(result) if result is not None else "OK (no output)"
        except TypeError as exc:
            log.error("Tool '%s' argument error: %s", name, exc)
            return f"ERROR: Bad arguments for '{name}': {exc}"
        except Exception as exc:
            log.error("Tool '%s' failed: %s", name, exc, exc_info=True)
            return f"ERROR: Tool '{name}' failed: {exc}"

    def get_all_metadata(self):
        """Return list of tool metadata dicts (name, description, args)."""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "args": t["args"],
            }
            for t in self._tools.values()
        ]

    def list_names(self):
        """Return sorted list of registered tool names."""
        return sorted(self._tools.keys())

    def __contains__(self, name):
        return name in self._tools

    def __len__(self):
        return len(self._tools)


# Global singleton
registry = ToolRegistry()
