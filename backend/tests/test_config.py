from repopilot.core.config import Settings


def test_qwen_api_key_uses_clear_shared_name() -> None:
    settings = Settings(
        _env_file=None,
        qwen_api_key="new-key",
    )

    assert settings.qwen_api_key == "new-key"


def test_qdrant_server_url_is_optional() -> None:
    local_settings = Settings(_env_file=None)
    docker_settings = Settings(
        _env_file=None,
        vector_database_url="http://qdrant:6333",
    )

    assert local_settings.vector_database_url is None
    assert docker_settings.vector_database_url == "http://qdrant:6333"
