# sre-agent

> Monitor de saúde contínuo e agente de AIOps para stacks modernos (Railway · Vercel · Supabase · GitHub).

[![CI](https://github.com/MariaHilmar/sre-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/MariaHilmar/sre-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen)
![Ruff](https://img.shields.io/badge/lint-ruff-black)
![License](https://img.shields.io/badge/license-MIT-green)

`sre-agent` observa a saúde dos seus serviços, detecta falhas, correlaciona
deploys e merges, e diagnostica a causa raiz com um LLM — propondo a próxima
ação para você aprovar. Um plantonista de SRE que cabe num comando.

O motor é **público e genérico**; a sua configuração (URLs, tokens) é **privada
e fica fora do versionamento**. O mesmo código serve qualquer stack.

---

## O problema

Hoje, saber se tudo está no ar significa abrir o dashboard do Railway, o do
Vercel, o do Supabase e o do GitHub — cada um numa aba. `sre-agent` consolida
esses sinais numa visão só e responde: **o que está no ar, o que caiu, e (em
breve) por quê.**

---

## O que faz hoje (Fases 0 e 1)

Monitora a saúde dos serviços, monta a linha do tempo de mudanças (deploys +
merges via GitHub/Vercel/Railway), lê os advisors do banco (Supabase) e, quando
algo cai, diagnostica a causa raiz com Claude — usando o histórico de incidentes
como contexto.

O exemplo abaixo é o health check (Fase 0), que verifica em paralelo o endpoint
de cada serviço, valida o status HTTP e (opcionalmente) o corpo JSON, mede a
latência e emite um relatório com código de saída pronto para CI/cron.

```
$ sre-agent check

                     sre-agent · saúde dos serviços
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Estado     ┃ Serviço     ┃ Plataforma ┃ Latência ┃ Detalhe               ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━┩
│ 🔴 down    │ meu-worker  │ railway    │   —      │ HTTP 503 (esperado 200)│
│ 🟢 healthy │ minha-api   │ railway    │  142 ms  │ status=healthy, db=ok │
│ 🟢 healthy │ meu-front   │ vercel     │   88 ms  │ HTTP 200              │
└────────────┴─────────────┴────────────┴──────────┴───────────────────────┘

🔴 Estado geral: DOWN
2/3 serviços saudáveis (verificados em 151 ms).
FORA DO AR: meu-worker (HTTP 503 (esperado 200))
```

---

## Instalação e uso

```bash
# 1. instalar
pip install -e .

# 2. configurar para os SEUS serviços (o config.yaml é gitignored)
cp config.example.yaml config.yaml
#    edite config.yaml com suas URLs

# 3. rodar
sre-agent check                 # saúde dos serviços (Fase 0)
sre-agent check --json          # saída JSON para automação
sre-agent changes               # linha do tempo de deploys e merges (Fase 1)
sre-agent advisors              # advisors de saúde do banco (Fase 1)
sre-agent diagnose              # RCA por LLM dos serviços com falha (Fase 1)
sre-agent triage                # ciclo completo: coleta → RCA → proposta (Fase 3)
sre-agent actions               # fila de aprovação (Fase 2)
sre-agent approve <id>          # aprova uma ação pendente (não executa)
```

### Human-in-the-loop

O agente **nunca executa ação sozinho**. Ele *propõe* (ex.: `diagnose --propose rollback`),
a ação fica **pendente** em `sre-agent actions`, e só um `approve`/`reject` humano
decide. Aprovar apenas libera — a execução em si é decisão explícita (Fase 3).

> `diagnose` precisa do extra de RCA e de uma chave: `pip install "sre-agent[rca]"`
> e `ANTHROPIC_API_KEY` no ambiente.

Configura-se **editando dados** (`config.yaml`), nunca o código:

```yaml
targets:
  - name: minha-api
    platform: railway
    url: https://minha-api.up.railway.app
    expect:
      status: 200
      json: { status: healthy, database: ok }
```

Segredos (para as próximas fases) ficam em `.env` (gitignored) e são
referenciados no YAML como `${VAR}`.

### Na sua pipeline

`sre-agent check` sai com código `1` se algo estiver DOWN/DEGRADED — use-o como
portão de qualidade pós-deploy:

```yaml
- run: pip install sre-agent
- run: sre-agent check --config config.yaml
```

### Monitoramento agendado

O workflow [`Monitor`](.github/workflows/monitor.yml) roda o health check de hora
em hora (cron) e notifica no Slack se algo cair. Para ativar:

1. Versione um `config.ci.yaml` com os serviços (URLs públicas; sem segredos).
2. Adicione o secret `SLACK_WEBHOOK_URL` no repositório.

Sem `config.ci.yaml`, o passo é pulado e o job fica verde — nada quebra.

---

## Comandos

| Comando | O que faz | Fase |
|---|---|---|
| `check` | Health check paralelo dos serviços (`--json`, `--notify`) | 0 |
| `changes` | Linha do tempo de deploys + merges (GitHub/Vercel/Railway) | 1 |
| `advisors` | Advisors de segurança/performance do banco (Supabase) | 1 |
| `diagnose` | RCA por LLM dos serviços com falha (`--propose <tipo>`) | 1 |
| `triage` | Ciclo do agente: coleta → RCA → proposta, num comando (`--json`, `--notify`, `--no-propose`) | 3 |
| `actions` | Lista a fila de aprovação (`--all`) | 2 |
| `propose` | Enfileira uma ação para aprovação | 2 |
| `approve` / `reject` | Decide uma ação pendente | 2 |

Todos os comandos que detectam falha saem com **código 1** — prontos para CI/cron.

---

## Arquitetura

Núcleo agnóstico + adapters por plataforma (ports & adapters). O núcleo não
conhece Railway/Vercel; cada fonte de sinal é um adapter atrás de uma interface
uniforme. Adicionar uma plataforma = escrever um adapter, sem tocar no núcleo.

```
                        ┌─────────────────────────┐
        agendamento ───►│  núcleo: loop + models  │───► relatório / exit code
        (cron/CI)       └────────────┬────────────┘
                                     │  interface uniforme
              ┌──────────────┬───────┴───────┬──────────────┐
              ▼              ▼               ▼              ▼
          HTTP health    GitHub          Supabase       Railway/Vercel
          (Fase 0)       (Fase 1)        (Fase 1)       (Fase 1)
```

---

## Roadmap

- [x] **Fase 0 — Monitor de saúde**: health check HTTP paralelo, relatório, exit code para CI.
- [x] **Fase 1 — RCA assistido por LLM**
  - [x] 1.1 — adapter GitHub: linha do tempo de mudanças (deploys + merges), deploy com falha é alertável (`sre-agent changes`).
  - [x] 1.2 — adapter Supabase: advisors de saúde do banco, nível ERROR é alertável (`sre-agent advisors`).
  - [x] 1.3 — adapters Railway (GraphQL) + Vercel (REST): status de deploy unificado na linha do tempo.
  - [x] 1.4 — loop de RCA: reúne evidência (mudanças + advisors + histórico) e diagnostica com Claude (`sre-agent diagnose`).
  - [x] 1.5 — memória de incidentes: histórico em SQLite, recuperado como contexto no RCA.
- [x] **Fase 2 — Notificação + human-in-the-loop**
  - [x] 2.1 — notificação Slack (via webhook), só dispara em falha (`sre-agent check --notify`).
  - [x] 2.2 — agendamento: workflow `Monitor` (cron/Actions) roda o check e notifica sozinho.
  - [x] 2.3 — fila de aprovação: o agente propõe, o humano aprova/rejeita (`actions`/`approve`/`reject`).
- [ ] **Fase 3 — Orquestração + monitoramento profundo** (foco: aprofundar Supabase/Vercel/Railway, ver [ADR-004](docs/DECISIONS.md))
  - [x] 3.1 — orquestrador: um comando encadeia coleta → RCA → proposta (dedup de ações), com saída estruturada (`sre-agent triage`).
  - [ ] 3.2 — logs como evidência: adapters de log (Supabase/Vercel/Railway) numa janela limitada, injetados no RCA determinístico.
  - [ ] 3.3 — checks de ciclo de vida e quotas: estado do projeto/serviço (pausado, crash-loop), limites de quota e validade de SSL declarados no YAML — viram DEGRADED preventivo antes de virar DOWN.
  - [ ] 3.4 — runbooks no YAML: contexto estruturado por serviço/tipo de falha injetado no prompt de RCA.
- [ ] **Fase 4 — Multiagente + painel**
  - [ ] 4.1 — toolsets declarativos: fontes de sinal registradas via config (não código), base dos agentes especialistas.
  - [ ] 4.2 — agentes especialistas por domínio (infra, banco) atrás da interface uniforme.
  - [ ] 4.3 — métricas de incidente (MTTR) a partir da memória.
  - [ ] 4.4 — painel de controle (timeline, MTTR).

---

## Princípios de design

- **Motor público, config privada** — segredos nunca no repositório.
- **Config-driven** — o que monitorar é dado (YAML), não código.
- **Sem estado até precisar** — a Fase 0 é uma função pura; banco só a partir da Fase 1.
- **LLM só onde agrega** — health check é `httpx`; raciocínio LLM entra no diagnóstico.

## Desenvolvimento

```bash
pip install -e ".[dev]"
pytest -q                                  # testes (cobertura ~90%)
ruff check src tests                       # lint
```

Para experimentar cada comando na mão (sem segredos, com endpoints públicos),
veja o [guia de teste manual](docs/TESTING.md).

## Licença

MIT — veja [LICENSE](LICENSE).
