from max.llm.models import LLMResponse, ModelType, ToolCall


def test_tool_call_creation():
    tc = ToolCall(id="toolu_01", name="file.write", input={"path": "/tmp/a.txt", "content": "hi"})
    assert tc.id == "toolu_01"
    assert tc.name == "file.write"
    assert tc.input == {"path": "/tmp/a.txt", "content": "hi"}


def test_llm_response_with_typed_tool_calls():
    resp = LLMResponse(
        text="",
        input_tokens=10,
        output_tokens=5,
        model="claude-opus-4-6",
        stop_reason="tool_use",
        tool_calls=[
            ToolCall(id="toolu_01", name="file.write", input={"path": "/tmp/a.txt"}),
            ToolCall(id="toolu_02", name="shell.exec", input={"cmd": "ls"}),
        ],
    )
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0].name == "file.write"
    assert resp.tool_calls[1].id == "toolu_02"


def test_llm_response_no_tool_calls():
    resp = LLMResponse(
        text="Hello",
        input_tokens=10,
        output_tokens=5,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )
    assert resp.tool_calls is None
