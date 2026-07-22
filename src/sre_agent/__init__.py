"""sre-agent — monitor de saúde contínuo do stack (Fase 0).

Observa a saúde dos serviços (Railway, Vercel, e qualquer endpoint HTTP),
detecta falhas e produz um relatório. As fases seguintes adicionam RCA
assistido por LLM, notificação e human-in-the-loop.
"""

__version__ = "0.1.0"
