# tests/test_tool_registry.py
import pytest

from max.tools.registry import ToolRegistry, ToolDefinition


@pytest.fixture
def registry():
    return ToolRegistry()


def test_register_tool(registry):
    tool = ToolDefinition(
        tool_id="shell.execute",
        category="code",
        description="Execute a shell command",
        permissions=["system.shell"],
    )
    registry.register(tool)
    assert registry.get("shell.execute") is not None


def test_get_missing_tool(registry):
    assert registry.get("nonexistent") is None


def test_list_by_category(registry):
    registry.register(ToolDefinition(
        tool_id="file.read", category="code", description="Read a file", permissions=["fs.read"],
    ))
    registry.register(ToolDefinition(
        tool_id="file.write", category="code", description="Write a file", permissions=["fs.write"],
    ))
    registry.register(ToolDefinition(
        tool_id="browser.navigate", category="web", description="Navigate to URL", permissions=["network"],
    ))
    code_tools = registry.list_by_category("code")
    assert len(code_tools) == 2
    web_tools = registry.list_by_category("web")
    assert len(web_tools) == 1


def test_check_permissions(registry):
    registry.register(ToolDefinition(
        tool_id="shell.execute",
        category="code",
        description="Execute a shell command",
        permissions=["system.shell"],
    ))
    assert registry.check_permission("shell.execute", allowed=["system.shell"])
    assert not registry.check_permission("shell.execute", allowed=["fs.read"])


def test_list_all(registry):
    registry.register(ToolDefinition(
        tool_id="a", category="x", description="A", permissions=[],
    ))
    registry.register(ToolDefinition(
        tool_id="b", category="y", description="B", permissions=[],
    ))
    assert len(registry.list_all()) == 2


def test_to_anthropic_tools(registry):
    registry.register(ToolDefinition(
        tool_id="file.read",
        category="code",
        description="Read a file from the filesystem",
        permissions=["fs.read"],
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
    ))
    tools = registry.to_anthropic_tools(["file.read"])
    assert len(tools) == 1
    assert tools[0]["name"] == "file.read"
    assert tools[0]["description"] == "Read a file from the filesystem"
    assert tools[0]["input_schema"]["properties"]["path"]["type"] == "string"
