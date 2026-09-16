# GitHub Actions — conceitos aplicados no laboratório

Este documento explica **o GitHub Actions em si**: como o serviço funciona, quais recursos existem e como cada um foi usado no laboratório `actions-demo`. Ele não descreve a implementação da API ou dos manifests; para isso veja o README do projeto.

---

## 1. O que é

GitHub Actions é a plataforma de automação nativa do GitHub. Ela executa **workflows** — sequências de tarefas descritas em YAML — em resposta a eventos do repositório. Serve para CI (lint, testes, build), CD (publicar imagens, fazer deploy) e automações gerais (rotinas agendadas, comentários em PR, gestão de issues).

O que a diferencia de outras ferramentas de CI/CD:

- não há servidor para instalar ou manter: o orquestrador é o próprio GitHub;
- a definição vive no repositório, versionada junto com o código (`.github/workflows/*.yml`);
- existe um **Marketplace** com milhares de ações prontas reutilizáveis (`uses:`);
- integração nativa com PRs, checks, environments, secrets, Container Registry (GHCR) e o token automático `GITHUB_TOKEN`.

---

## 2. Anatomia de um workflow

```
Workflow  ── arquivo .yml em .github/workflows/
 ├── on:        eventos que disparam
 ├── env:       variáveis globais
 ├── permissions, concurrency, defaults
 └── jobs:      unidades de execução independentes
      └── job
           ├── runs-on:  em qual tipo de máquina roda
           ├── needs:    dependências de outros jobs
           ├── if:       condição para executar
           ├── strategy: matriz de variações
           ├── environment, outputs, timeout-minutes, continue-on-error
           └── steps:    executados em ordem, na mesma máquina
                ├── run:  comando shell
                └── uses: action pronta (owner/repo@versao)
```

Pontos essenciais:

- **Jobs rodam em paralelo** por padrão, cada um em uma máquina limpa. Só `needs` cria ordem.
- **Steps compartilham o filesystem** dentro do job, mas cada `run:` é um shell novo (variáveis de shell não sobrevivem; use `$GITHUB_ENV`).
- O código **não** é baixado automaticamente — `actions/checkout` faz isso, por isso é quase sempre o primeiro step.

No laboratório: quatro workflows (`ci.yml`, `deploy.yml`, `pr-checks.yml`, `scheduled.yml`), cada um mostrando um grupo de recursos.

---

## 3. Eventos (`on:`)

| Evento | Quando dispara | Uso no laboratório |
|---|---|---|
| `push` | commit chega em branch/tag | CI completo na `main` |
| `pull_request` | PR aberto/atualizado (`types:` refina: `opened`, `labeled`…) | validações sem publicar imagem |
| `workflow_dispatch` | botão *Run workflow*, com formulário de `inputs` | deploy manual escolhendo ambiente |
| `workflow_call` | outro workflow chama este como função | `ci.yml` chama `deploy.yml` |
| `schedule` | cron (sempre em UTC) | health check noturno |
| `workflow_run`, `release`, `issues`, `issue_comment`… | outros eventos do repositório | não usados |

Filtros: `branches`, `branches-ignore`, `tags`, `paths`, `paths-ignore`. Ex.: `paths-ignore: ["**.md"]` evita gastar minutos em commits só de documentação.

Em `pull_request`, o workflow executado é o **do branch do PR**, e o `GITHUB_TOKEN` de forks tem permissão só de leitura — proteção contra código malicioso.

---

## 4. Runners

O runner é o agente que executa um job. É escolhido pelo `runs-on`, que casa **labels**.

### GitHub-hosted (compartilhados)
- `ubuntu-latest`, `windows-latest`, `macos-latest` (ou versões fixas).
- VM **efêmera**: criada para o job, destruída ao fim. Nada persiste.
- Vêm com Docker, Python, Node, Go, Java, kubectl, helm, gh, CLIs de cloud… (lista em `actions/runner-images`).
- Têm sudo e saída livre para a internet; **não** enxergam sua rede privada.
- Limites: 6 h por job; minutos gratuitos limitados em repositórios privados.

### Self-hosted (seus)
- Você instala o agente numa VM, container ou pod. Ele **só abre conexão HTTPS de saída** para o GitHub e fica aguardando jobs (long-polling). Nenhuma porta de entrada, nenhuma regra de firewall.
- Executa com acesso a tudo que a máquina vê: cluster, banco, rede interna.
- Labels definem o roteamento: `runs-on: [self-hosted, linux, k8s]` exige um runner com **todas** essas labels.
- Pode ser persistente (mesma máquina reaproveitada) ou **efêmero** (um job e morre — mais seguro).
- Regra: **nunca** em repositório público.

No laboratório: CI (lint, testes, build) roda em `ubuntu-latest`; deploy e cron rodam em um runner self-hosted na máquina do desenvolvedor, que acessa um cluster kind local.

---

## 5. Contextos e expressões `${{ }}`

Tudo entre `${{ }}` é avaliado pelo GitHub antes de executar. Principais contextos:

| Contexto | Conteúdo | Exemplo |
|---|---|---|
| `github` | evento, sha, ref, repositório, ator | `github.ref == 'refs/heads/main'` |
| `env` | variáveis definidas em `env:` | `${{ env.IMAGE_NAME }}` |
| `secrets` | secrets do repo/org/environment | `${{ secrets.GITHUB_TOKEN }}` |
| `vars` | variáveis de configuração (não sensíveis) | `${{ vars.K8S_NAMESPACE }}` |
| `inputs` | entradas de `workflow_dispatch`/`workflow_call` | `${{ inputs.environment }}` |
| `needs` | outputs e resultado de jobs anteriores | `needs.build.outputs.image_tag` |
| `steps` | outputs/resultado de steps anteriores | `steps.meta.outputs.tags` |
| `matrix` | valores da combinação atual | `${{ matrix.python }}` |
| `runner` | SO, arquitetura, diretório temp | `runner.os` |

Funções: `contains`, `startsWith`, `endsWith`, `format`, `join`, `toJSON`, `fromJSON`, `hashFiles`, e as de status `success()`, `failure()`, `always()`, `cancelled()`.

### Passando dados entre steps e jobs
- **Step → steps seguintes:** `echo "chave=valor" >> "$GITHUB_OUTPUT"` e leia com `steps.<id>.outputs.chave`.
- **Step → variável de ambiente do job:** `echo "VAR=valor" >> "$GITHUB_ENV"` (foi assim que o nome da imagem foi normalizado para minúsculas).
- **Job → job:** declare `outputs:` no job e leia com `needs.<job>.outputs.<nome>`.
- **Arquivos:** `actions/upload-artifact` / `download-artifact`.

---

## 6. Controle de fluxo

### Dependências — `needs`
Cria o grafo. Um job com `needs` só inicia quando todos os listados terminam com sucesso. Se um deles falha ou é pulado, o dependente é **pulado** — a menos que use `if: always()` e trate `needs.<job>.result` (`success`, `failure`, `cancelled`, `skipped`).

### Condicionais — `if`
Podem estar em jobs ou steps:
```yaml
if: github.event_name != 'pull_request'
if: needs.changes.outputs.infra == 'true'
if: contains(github.event.pull_request.labels.*.name, 'hotfix') || github.actor == 'dependabot[bot]'
if: failure()          # rollback, alerta
if: always()           # upload de relatório, notificação, cleanup
```

### Tolerância a erro
| Recurso | Nível | Comportamento |
|---|---|---|
| `continue-on-error: true` | step | step falha, job continua e termina como **sucesso**; `steps.<id>.outcome` = `failure`, `conclusion` = `success` |
| `continue-on-error: true` | job | job aparece vermelho, mas o workflow continua e dependentes rodam |
| `fail-fast: false` | matriz | uma combinação falhando não cancela as outras |
| `timeout-minutes` | job/step | encerra execuções presas (padrão 360 min) |

`outcome` = resultado real; `conclusion` = resultado depois de aplicar `continue-on-error`.

### Matriz — `strategy.matrix`
Multiplica um job por combinações de valores (versões, SOs). `include`/`exclude` ajustam casos. Cada combinação é um job independente.

### Concorrência — `concurrency`
Agrupa execuções por chave. `cancel-in-progress: true` cancela a anterior (ideal para CI em PR); `false` faz a nova esperar (obrigatório para deploy: nunca dois deploys simultâneos no mesmo ambiente).

---

## 7. Reutilização

- **Reusable workflow** (`on: workflow_call`): um workflow inteiro chamado como função por outro, com `inputs`, `secrets` e `outputs`. Chamado com `uses: ./.github/workflows/deploy.yml` (ou `owner/repo/.github/workflows/x.yml@ref`). Aparece no grafo como "chamador / job".
- **Composite action**: pacote de steps reutilizáveis (`action.yml` com `runs: using: composite`).
- **Actions do Marketplace**: `actions/checkout`, `actions/setup-python`, `docker/build-push-action`, `docker/metadata-action`, `dorny/paths-filter`, `actions/github-script`… Sempre fixe a versão (`@v4`) — e por SHA em ambientes sensíveis.

---

## 8. Segurança e credenciais

### `GITHUB_TOKEN`
Token gerado automaticamente para cada execução, válido só durante ela, com escopo no repositório. Serve para clonar, publicar no GHCR, comentar em PR, criar releases. Escopo controlado por `permissions:` — defina o **mínimo** (`contents: read`, `packages: write`, etc.). Repositórios novos exigem habilitar *Read and write* em Settings → Actions → General para operações de escrita.

### Secrets e variáveis
- **Secrets**: valores sensíveis, mascarados nos logs, em três níveis: organização, repositório e **environment**.
- **Variables** (`vars`): configuração não sensível, visível nos logs.

### Environments
Um environment (`staging`, `production`) agrupa secrets/vars próprios e **regras de proteção**: revisores obrigatórios (aprovação manual), tempo de espera, branches permitidos. Um job com `environment: production` pausa até aprovação. O deploy fica registrado na aba *Deployments*.

### Boas práticas aplicadas
- `permissions` mínimas em todos os workflows.
- Self-hosted em repositório privado, com labels específicas.
- Scan de dependências (`pip-audit`) em job separado e não bloqueante.
- Imagens no GHCR autenticadas com `GITHUB_TOKEN` (sem secret externo).

---

## 9. Saídas e observabilidade

- **Logs** em tempo real por step, com grupos dobráveis (`::group::`/`::endgroup::`).
- **Annotations**: `::error::`, `::warning::`, `::notice::` aparecem destacadas no resumo e no PR.
- **Job summary**: markdown escrito em `$GITHUB_STEP_SUMMARY` aparece na página da execução (usado para listar as tags publicadas).
- **Artifacts**: arquivos retidos por N dias, baixáveis pela interface (relatórios JUnit/cobertura).
- **Cache**: `actions/cache` ou atalhos (`setup-python` com `cache: pip`, buildx com `type=gha`) para acelerar dependências e camadas Docker.
- **Checks e status**: cada job vira um check no commit; branch protection pode exigir checks verdes para merge.

---

## 10. Como o laboratório usa cada recurso

| Recurso | Onde aparece |
|---|---|
| `push`, `pull_request`, `workflow_dispatch`, `paths-ignore` | `ci.yml` |
| `concurrency` com `cancel-in-progress` | `ci.yml` (CI) / sem cancelamento em `deploy.yml` |
| `permissions` mínimas | todos |
| `needs` + grafo | lint → test/security → build → deploy → notify |
| `strategy.matrix` + `fail-fast: false` | testes em Python 3.11 e 3.12 |
| `continue-on-error` (job e step) | job *Security scan*, step *Scan experimental* |
| `if: always()`, `if: failure()`, `needs.*.result` | upload de relatório, rollback, notify |
| `outputs` entre jobs | `build.outputs.image_tag` → deploy |
| `$GITHUB_ENV` | normalização do nome da imagem |
| `$GITHUB_STEP_SUMMARY`, annotations | resumo do build/deploy, warnings |
| `actions/upload-artifact` | relatórios de teste |
| cache pip e cache de camadas Docker | `setup-python`, `build-push-action` |
| `GITHUB_TOKEN` para GHCR e PR | login no ghcr.io, `github-script` |
| Reusable workflow (`workflow_call`) | `ci.yml` → `deploy.yml` |
| `workflow_dispatch.inputs` (choice/string) | deploy manual |
| `environment` com aprovação | `staging`, `production` |
| Runner self-hosted com labels | `runs-on: [self-hosted, linux, k8s]` |
| Filtro por caminho em PR (`dorny/paths-filter`) | `pr-checks.yml` |
| Condição por label/autor | `pr-checks.yml` |
| `schedule` (cron) | `scheduled.yml` |
| `timeout-minutes` | `deploy.yml` |

---

## 11. Glossário rápido

- **Workflow run**: uma execução de um workflow.
- **Check**: status de um job exibido no commit/PR.
- **Artifact**: arquivo produzido por um job e armazenado pelo GitHub.
- **GHCR**: GitHub Container Registry (`ghcr.io`), registry de imagens integrado.
- **Ephemeral runner**: runner que executa um único job e é descartado.
- **ARC**: Actions Runner Controller, operador que cria runners como pods no Kubernetes.
- **Marketplace**: catálogo de actions públicas.
