from website_audit_agent.config import DEFAULT_MODEL, load_config


def test_missing_key_is_none_not_an_error():
    assert load_config({}).gemini_api_key is None
    assert load_config({"GEMINI_API_KEY": "   "}).gemini_api_key is None


def test_default_model():
    assert load_config({"GEMINI_API_KEY": "k"}).model == DEFAULT_MODEL == "gemini-3.8-flash"


def test_model_from_env():
    config = load_config({"GEMINI_API_KEY": "k", "AUDIT_AGENT_MODEL": " gemini-other "})
    assert config.gemini_api_key == "k" and config.model == "gemini-other"
