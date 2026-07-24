import importlib.util

import pytest

from sre_agent.config import LLMConfig
from sre_agent.llm import build_llm


def test_unknown_provider_raises():
    with pytest.raises(RuntimeError):
        build_llm(LLMConfig(provider="foo"))


def test_anthropic_without_package_raises():
    if importlib.util.find_spec("anthropic") is not None:
        pytest.skip("pacote anthropic instalado — caminho de erro não se aplica")
    with pytest.raises(RuntimeError):
        build_llm(LLMConfig(provider="anthropic"))
