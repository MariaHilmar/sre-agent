# Registro de decisões (ADR)

Log das decisões de arquitetura e escopo do `sre-agent`. Cada entrada registra o
**contexto**, a **decisão** tomada, as **alternativas** consideradas e as
**consequências** (vantagens e desvantagens que aceitamos conscientemente).

Formato leve, ordem cronológica. O roadmap "o que" vive no [README](../README.md);
aqui fica o "por quê".

---

## ADR-001 — Orquestrador `triage` (Fase 3.1)

- **Data:** 2026-07-27
- **Status:** ✅ implementado (comando `sre-agent triage`)
- **Fase:** 3.1 (pré-requisito de 3.2 agentes especialistas e 3.4 painel)

### Contexto

Hoje o operador roda os comandos na mão: `check` → (vê falha) → `diagnose
--propose`. As peças já existem e são testadas (`run_checks`, `gather_evidence`,
`diagnose`, `IncidentStore`, `ActionStore`, `build_llm`, `build_notifier`), mas
não há um fluxo único que as encadeie. Isso é o que falta para o projeto ser um
"agente" de fato, e não um conjunto de scripts.

### Decisão

Adicionar um **orquestrador** que compõe (não reescreve) as peças existentes num
ciclo único: **coleta → correlaciona → diagnostica → propõe → notifica**,
preservando o human-in-the-loop (propõe, nunca executa).

Entregas:

1. **Núcleo** — função `triage()` em `agent.py`, retornando um `TriageResult`
   estruturado (report + lista de `(Evidence, root_cause, Action|None)`).
2. **CLI** — comando `sre-agent triage` com flags `--notify`, `--propose <tipo>`
   / `--no-propose` (default: propõe `runbook`), `--json`; exit code 1 em falha.
3. **Relatório** — `render_triage()` / `summarize_triage()`: visão consolidada
   (saúde + RCA + ações) em vez de três saídas separadas.
4. **Deduplicação de ações abertas** por serviço (ver ADR-002).
5. **Testes** (`tests/test_triage.py`) mantendo cobertura ~90%.
6. **Docs** — README (tabela de comandos + roadmap) e `docs/TESTING.md`.

### Alternativas consideradas

- **Estender `diagnose` em vez de criar `triage`.** Rejeitado: sobrecarregaria um
  comando de "debug de um serviço" com responsabilidade de "ciclo do agente".
  Posicionamento escolhido: `diagnose` = investigar um serviço; `triage` = o ciclo.

### Consequências

**A favor**
- Autonomia real: um comando executa o ciclo inteiro.
- Baixo risco: compõe funções já testadas; superfície nova é fina.
- Preserva o princípio central (propõe, nunca executa).
- O `TriageResult` estruturado vira a fonte de dados do painel (3.4) e o ponto de
  plugagem dos agentes especialistas (3.2).

**Contra (aceitos)**
- Sobreposição com `diagnose --propose` — mitigado pelo posicionamento acima.
- Custo de LLM embutido no caminho principal — mitigado pela degradação graciosa
  (roda sem `ANTHROPIC_API_KEY` / sem fontes, entregando evidência determinística
  e **avisando** claramente quando uma fonte está ausente, para não mascarar
  configuração incompleta).

---

## ADR-002 — Deduplicação de ações abertas

- **Data:** 2026-07-27
- **Status:** ✅ implementado (`ActionStore.propose_unique`)

### Contexto

Com o `triage` enfileirando ações automaticamente, um serviço que segue caído
gera uma proposta idêntica a cada execução. Sob cron (de hora em hora), isso vira
uma fila poluída e spam de Slack.

### Decisão

Ao propor uma ação, **não duplicar** se já existe uma ação pendente para o mesmo
`(service, kind)`. Incluído já na Fase 3.1 por ser barato e evitar o pior efeito
colateral da automação.

### Consequências

- **A favor:** fila limpa; a automação por cron fica segura para ativar depois.
- **Contra:** uma nova ocorrência do mesmo tipo não gera item novo enquanto a
  anterior estiver pendente — aceitável (o incidente ainda é registrado na
  memória; a fila é de *decisão*, não de *histórico*).

---

## ADR-003 — Cron continua em `check` (não em `triage`) por ora

- **Data:** 2026-07-27
- **Status:** aceito

### Contexto

O workflow `monitor.yml` (cron/Actions) hoje roda `check`. Poderíamos apontá-lo
para `triage`, tornando o monitor autônomo (diagnostica e propõe sozinho 24/7).

### Decisão

**Manter o cron em `check` nesta etapa.** A troca para `triage` será uma etapa
consciente e separada, feita **depois** da dedup (ADR-002) estar no lugar.

### Alternativas consideradas

- **Apontar o cron para `triage` já agora.** Rejeitado nesta etapa: acoplaria a
  feature a uma mudança de infra de produção no mesmo PR, e — o ponto decisivo —
  colocaria o LLM num loop de cron **sem supervisão**, com custo imprevisível e
  risco de spam antes da dedup existir.

### Consequências

- **A favor:** PR focado (feature isolada de infra); custo de LLM permanece sob
  controle (zero até rodar `triage` na mão); sem ruído.
- **Contra:** o monitor automático ainda não faz RCA sozinho — autonomia total
  fica para a etapa seguinte. Aceito conscientemente.

---

## ADR-004 — Foco nas 3 plataformas, aprofundar em vez de alargar

- **Data:** 2026-07-27
- **Status:** aceito
- **Fase:** direciona a Fase 3 (3.2 a 3.4) e a Fase 4

### Contexto

O sre-agent monitora hoje o essencial de Supabase, Vercel e Railway: saúde HTTP,
status de deploy, advisors do banco, linha do tempo de mudanças. Surgiu a questão
de para onde crescer. A referência analisada foi o [HolmesGPT](https://github.com/HolmesGPT/holmesgpt)
(CNCF Sandbox): um agente de RCA **agêntico** (o LLM decide o que investigar, em
loop), com 50+ toolsets cloud-native (K8s, Prometheus, Datadog…), escala petabyte
e operador in-cluster.

### Decisão

**Manter o foco nas três plataformas (Supabase, Vercel, Railway) e crescer em
PROFUNDIDADE, não em largura.** Ou seja: extrair mais sinal das APIs que já
usamos, em vez de adicionar novas plataformas.

Ordem de valor decidida:

1. **Logs como evidência** (3.2) — puxar logs de erro recentes (janela limitada)
   para o `gather_evidence`. Maior retorno: hoje o LLM diagnostica sem ver o log
   que explica a falha. Continua **determinístico** (nós definimos a janela e a
   busca) — não vira RCA agêntico.
2. **Ciclo de vida + quotas** (3.3) — estado do projeto/serviço (pausado,
   crash-loop), quota (egress/storage) e validade de SSL, com thresholds no YAML.
   Torna o agente **preventivo** (DEGRADED antes de DOWN), não só reativo.
3. **Runbooks no YAML** (3.4) — contexto estruturado por serviço/falha injetado
   no prompt de RCA.

### O que adotamos do HolmesGPT (como ideia)

- **Toolsets declarativos** (Fase 4.1): fontes de sinal registradas via config,
  não fixas no código — evolução natural do nosso ports-and-adapters.
- **Runbooks estruturados** (3.4): telemetria + LLM + runbook.
- **LLM-agnóstico**: expor OpenAI/Gemini/Ollama atrás do `build_llm` já existente
  (Ollama local atende o público indie sem custo de API). Candidato a quick win.

### O que NÃO adotamos (não-objetivos)

- **RCA totalmente agêntico** — mantemos a evidência determinística: previsível,
  barata, testável. O LLM raciocina; ele não dirige a coleta.
- **Novas plataformas / K8s / Prometheus** — fora do nicho PaaS.
- **Escala petabyte, operador in-cluster, PRs automáticos de fix** — violam o
  "cabe num comando" e o human-in-the-loop (propõe, nunca executa).
- **Métricas de série temporal (estilo Datadog)** — puxaria o projeto para
  coletor de métricas com storage; adiado indefinidamente.

### Consequências

- **A favor:** cada incremento reforça o diferencial (config-driven, determinístico,
  human-in-the-loop) e melhora o RCA que já existe; escopo permanece enxuto e
  demonstrável num portfólio.
- **Contra:** o agente não serve stacks fora de Supabase/Vercel/Railway — decisão
  consciente de nicho, não de limitação.
