# sre-agent

> Monitor de saúde contínuo e agente de AIOps para stacks modernos (Railway · Vercel · Supabase · GitHub).

[![CI](https://github.com/MariaHilmar/sre-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/MariaHilmar/sre-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

`sre-agent` observa a saúde dos seus serviços, detecta falhas e — nas próximas
fases — diagnostica a causa raiz correlacionando deploys, merges e logs. Um
plantonista de SRE que cabe num comando.

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
```

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
- [ ] **Fase 2 — Notificação + human-in-the-loop**
  - [x] 2.1 — notificação Slack (via webhook), só dispara em falha (`sre-agent check --notify`).
  - [ ] 2.2 — agendamento (cron/Actions) · 2.3 — fila de aprovação human-in-the-loop.
- [ ] **Fase 3 — Multiagente + painel**: agentes especialistas, orquestrador, painel de controle (timeline, MTTR).

---

## Princípios de design

- **Motor público, config privada** — segredos nunca no repositório.
- **Config-driven** — o que monitorar é dado (YAML), não código.
- **Sem estado até precisar** — a Fase 0 é uma função pura; banco só a partir da Fase 1.
- **LLM só onde agrega** — health check é `httpx`; raciocínio LLM entra no diagnóstico.

## Desenvolvimento

```bash
pip install -e ".[dev]"
pytest -q
```

## Licença

MIT — veja [LICENSE](LICENSE).
