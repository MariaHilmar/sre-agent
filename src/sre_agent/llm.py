"""Clientes LLM para o RCA.

`AnthropicClient` usa Claude via SDK oficial. O import de `anthropic` é
preguiçoso: o pacote só é exigido quando o RCA roda de fato — a Fase 0 e os
adapters nunca dependem dele.
"""

from __future__ import annotations

from .config import LLMConfig


class AnthropicClient:
    def __init__(self, config: LLMConfig) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - caminho de dependência
            raise RuntimeError(
                "O pacote 'anthropic' é necessário para o RCA. "
                "Instale com: pip install anthropic"
            ) from exc

        kwargs = {"api_key": config.api_key} if config.api_key else {}
        self._client = anthropic.Anthropic(**kwargs)
        self._model = config.model

    def complete(self, system: str, prompt: str) -> str:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )


def build_llm(config: LLMConfig):
    if config.provider == "anthropic":
        return AnthropicClient(config)
    raise RuntimeError(f"Provedor de LLM não suportado: {config.provider}")
