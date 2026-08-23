from repopilot.core.config import Settings


def test_qwen_api_key_uses_clear_shared_name() -> None:
    settings = Settings(
        _env_file=None,
        qwen_api_key="new-key",
    )

    assert settings.qwen_api_key == "new-key"
