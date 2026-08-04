from app.coach.web_search import WEB_SEARCH_TOOL, tools_for_coach


def test_web_search_tool_shape():
    assert WEB_SEARCH_TOOL["type"] == "web_search_20250305"
    assert WEB_SEARCH_TOOL["name"] == "web_search"


def test_tools_for_coach_returns_list_with_web_search():
    tools = tools_for_coach()
    assert isinstance(tools, list)
    assert len(tools) == 1
    assert tools[0]["name"] == "web_search"
