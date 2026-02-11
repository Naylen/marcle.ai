import pytest

from app.ask_services.llm_client import LLMClientError, build_chat_completion_urls


def test_build_chat_completion_urls_from_root():
    urls = build_chat_completion_urls("http://172.16.2.220:12434")
    assert urls[0] == "http://172.16.2.220:12434/v1/chat/completions"
    assert urls[1] == "http://172.16.2.220:12434/engines/v1/chat/completions"


def test_build_chat_completion_urls_from_v1_path():
    urls = build_chat_completion_urls("http://172.16.2.220:12434/v1")
    assert urls[0] == "http://172.16.2.220:12434/v1/chat/completions"
    assert urls[1] == "http://172.16.2.220:12434/engines/v1/chat/completions"


def test_build_chat_completion_urls_from_engines_path():
    urls = build_chat_completion_urls("http://172.16.2.220:12434/engines/v1")
    assert urls[0] == "http://172.16.2.220:12434/engines/v1/chat/completions"
    assert urls[1] == "http://172.16.2.220:12434/v1/chat/completions"


def test_build_chat_completion_urls_invalid():
    with pytest.raises(LLMClientError):
        build_chat_completion_urls("")

