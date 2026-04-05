"""Native tool implementations for Max.

Call ``register_all_native_tools(provider)`` to register every built-in tool.
"""

from __future__ import annotations

from max.tools.native.file_tools import (
    TOOL_DEFINITIONS as FILE_TOOLS,
)
from max.tools.native.file_tools import (
    handle_directory_list,
    handle_file_delete,
    handle_file_edit,
    handle_file_glob,
    handle_file_read,
    handle_file_write,
)
from max.tools.native.git_tools import (
    TOOL_DEFINITIONS as GIT_TOOLS,
)
from max.tools.native.git_tools import (
    handle_git_commit,
    handle_git_diff,
    handle_git_log,
    handle_git_status,
)
from max.tools.native.process_tools import (
    TOOL_DEFINITIONS as PROCESS_TOOLS,
)
from max.tools.native.process_tools import (
    handle_process_list,
)
from max.tools.native.search_tools import (
    TOOL_DEFINITIONS as SEARCH_TOOLS,
)
from max.tools.native.search_tools import (
    handle_grep_search,
)
from max.tools.native.shell_tools import (
    TOOL_DEFINITIONS as SHELL_TOOLS,
)
from max.tools.native.shell_tools import (
    handle_shell_execute,
)
from max.tools.native.web_tools import (
    TOOL_DEFINITIONS as WEB_TOOLS,
)
from max.tools.native.web_tools import (
    handle_http_fetch,
    handle_http_request,
)
from max.tools.providers.native import NativeToolProvider

_HANDLER_MAP = {
    "file.read": handle_file_read,
    "file.write": handle_file_write,
    "file.edit": handle_file_edit,
    "directory.list": handle_directory_list,
    "file.glob": handle_file_glob,
    "file.delete": handle_file_delete,
    "shell.execute": handle_shell_execute,
    "git.status": handle_git_status,
    "git.diff": handle_git_diff,
    "git.log": handle_git_log,
    "git.commit": handle_git_commit,
    "http.fetch": handle_http_fetch,
    "http.request": handle_http_request,
    "process.list": handle_process_list,
    "grep.search": handle_grep_search,
}

ALL_TOOL_DEFINITIONS = (
    FILE_TOOLS + SHELL_TOOLS + GIT_TOOLS + WEB_TOOLS + PROCESS_TOOLS + SEARCH_TOOLS
)


def register_all_native_tools(provider: NativeToolProvider) -> None:
    """Register all built-in native tools on the given provider."""
    for tool_def in ALL_TOOL_DEFINITIONS:
        handler = _HANDLER_MAP.get(tool_def.tool_id)
        if handler:
            provider.register_tool(tool_def, handler)
