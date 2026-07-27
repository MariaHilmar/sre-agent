# Guia de teste manual

Como exercitar o `sre-agent` na mão, além da suíte automatizada. A maioria dos
comandos pode ser testada **sem nenhum segredo**, usando endpoints e repositórios
públicos.

## Preparação

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

## Suíte automatizada, lint e cobertura

```bash
pytest -q                                  # testes
ruff check src tests                       # lint
pytest --cov=sre_agent --cov-report=term   # cobertura (~90%)
```

## Testando cada comando

Crie um `config.demo.yaml` (não versionado) com alvos públicos:

```yaml
defaults:
  timeout_seconds: 10
targets:
  - name: exemplo-ok
    platform: web
    url: https://example.com
    health_path: ""
    expect: { status: 200 }
  - name: demo-fora-do-ar          # retorna 503 de propósito
    platform: demo
    url: https://httpbin.org
    health_path: /status/503
    expect: { status: 200 }
github:
  token: ${GITHUB_TOKEN}           # vazio = leitura pública (rate-limited)
  repos: [encode/httpx]
  lookback_hours: 720
```

### `check` — health (sem segredo)

```bash
sre-agent check --config config.demo.yaml
```
Esperado: tabela com `exemplo-ok` verde e `demo-fora-do-ar` vermelho; estado
geral **DOWN**; **exit code 1**. `--json` troca a saída para JSON.

### `changes` — deploys e merges (repo público, sem token)

```bash
sre-agent changes --config config.demo.yaml
```
Esperado: linha do tempo de deploys/merges recentes do `encode/httpx`.

### `propose` / `actions` / `approve` / `reject` — fila (sem segredo)

```bash
sre-agent propose --config config.demo.yaml \
  --service sj-scraping --kind rollback --description "reverter deploy 14h02"
sre-agent actions  --config config.demo.yaml     # mostra a ação #1 pendente
sre-agent approve  --config config.demo.yaml 1   # -> approved
sre-agent actions  --config config.demo.yaml --all
```
Esperado: a ação some das pendentes após aprovar; `--all` mostra o histórico.
Aprovar de novo retorna exit code 2 (já decidida).

### `triage` — o ciclo do agente (sem segredo, com degradação graciosa)

```bash
sre-agent triage --config config.demo.yaml --no-propose
```
Esperado: a tabela de saúde + um bloco de RCA por serviço com falha. **Sem**
`ANTHROPIC_API_KEY`, o RCA é pulado com um aviso (`⚠ Sem LLM disponível...`) e o
comando ainda sai com **exit code 1** — não quebra. Com a chave (`pip install
".[rca]"`), o bloco de RCA traz a causa raiz e uma ação `runbook` é enfileirada.
Rodar de novo com o mesmo serviço caído **não duplica** a ação (dedup). `--json`
dá a saída estruturada; `--notify` manda o resumo ao Slack se configurado.

## Comandos que exigem credenciais

| Comando | Precisa de | Como habilitar |
|---|---|---|
| `advisors` | `SUPABASE_ACCESS_TOKEN` + seção `supabase` | Personal Access Token do Supabase no `.env` |
| `diagnose` | `pip install ".[rca]"` + `ANTHROPIC_API_KEY` | instalar o extra e definir a chave |
| `check --notify` | `SLACK_WEBHOOK_URL` + `notify.enabled: true` | incoming webhook do Slack no `.env` |

Sem o pacote/chave, `diagnose` falha com uma mensagem clara (degradação graciosa),
não com stack trace.

## Apontando para serviços reais

Copie `config.example.yaml` para `config.yaml` (gitignored), troque as URLs pelos
seus serviços e os tokens por referências `${VAR}` lidas do `.env`.
