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


def test_model_type_opus():
    assert ModelType.OPUS.model_id == "claude-opus-4-6"
    assert ModelType.OPUS.max_tokens == 32768


def test_model_type_sonnet():
    assert ModelType.SONNET.model_id == "claude-sonnet-4-6"
    assert ModelType.SONNET.max_tokens == 16384


def test_model_type_value():
    assert ModelType.OPUS.value == ("opus", "claude-opus-4-6", 32768)
    assert ModelType.SONNET.value == ("sonnet", "claude-sonnet-4-6", 16384)


def test_llm_response_no_tool_calls():
    resp = LLMResponse(
        text="Hello",
        input_tokens=10,
        output_tokens=5,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )
    assert resp.tool_calls is None
