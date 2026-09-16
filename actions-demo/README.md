# GitHub Actions — guia prático + laboratório

Este repositório é um laboratório completo para entender e demonstrar GitHub Actions:

| Pasta / arquivo | O que é |
|---|---|
| `app/` | API FastAPI (`/health`, `/items`) com testes pytest |
| `Dockerfile` | build multi-stage, usuário não-root, HEALTHCHECK |
| `.github/workflows/ci.yml` | pipeline principal: lint → test (matriz) → security → build/push → deploy staging → notify |
| `.github/workflows/deploy.yml` | deploy em k8s via runner **self-hosted** (reutilizável + manual) |
| `.github/workflows/pr-checks.yml` | condicionais avançadas, filtro por caminho, comentário no PR |
| `.github/workflows/scheduled.yml` | job agendado (cron) |
| `k8s/` | Deployment + Service com placeholders `${IMAGE}` / `${NAMESPACE}` |
| `runner/` | 3 formas de subir runner self-hosted: VM (systemd), Docker, dentro do k8s (ARC) |

---

## 1. Como o GitHub Actions funciona

**Hierarquia**

```
Workflow (arquivo .yml em .github/workflows/)
 └── Jobs (rodam em paralelo por padrão; cada um em uma máquina limpa)
      └── Steps (rodam em sequência, na mesma máquina, compartilhando o filesystem)
           ├── run:  comando shell
           └── uses: action pronta (do Marketplace, do próprio repo ou de outro repo)
```

**Fluxo de uma execução**

1. Um **evento** acontece (`push`, `pull_request`, `schedule`, `workflow_dispatch`, `release`, `workflow_call`…).
2. GitHub lê os workflows do commit em questão e verifica os filtros (`branches`, `paths`, `types`).
3. Para cada job, resolve `needs` e `if` para montar o grafo de dependências.
4. Cada job é enfileirado com base no `runs-on`. Um **runner** com aquelas labels pega o job.
5. O runner baixa o código (só se você usar `actions/checkout`), executa os steps, envia logs em tempo real.
6. Steps podem gerar **outputs** (`$GITHUB_OUTPUT`), **artifacts** (arquivos entre jobs), **cache**, e escrever um **summary** (`$GITHUB_STEP_SUMMARY`).
7. Ao fim, o status volta para o commit/PR (checks) e pode bloquear merge via branch protection.

**Contextos** (variáveis que você usa em `${{ }}`): `github.*` (evento, sha, ref, actor), `env.*`, `secrets.*`, `vars.*`, `needs.<job>.outputs/result`, `steps.<id>.outputs/outcome/conclusion`, `matrix.*`, `inputs.*`, `runner.*`.

---

## 2. Opções mais usadas (todas exemplificadas nos workflows)

### Condicionais (`if`)
```yaml
if: github.event_name != 'pull_request'                      # tipo de evento
if: github.ref == 'refs/heads/main'                          # branch
if: needs.changes.outputs.infra == 'true'                    # output de outro job
if: contains(github.event.pull_request.labels.*.name, 'hotfix')
if: startsWith(github.ref, 'refs/tags/v')                    # só em tag de versão
if: always()          # roda mesmo se algo anterior falhou/foi pulado
if: failure()         # roda só se algo anterior falhou (bom para rollback/alerta)
if: success()         # padrão implícito
if: cancelled()
```
Funções: `contains`, `startsWith`, `endsWith`, `format`, `join`, `toJSON`, `fromJSON`, `hashFiles`. Operadores `&&`, `||`, `!`, `==`, `!=`.

> **Atenção:** se um job com `needs` depende de um job **pulado** (`if` falso), ele também é pulado, a menos que use `if: always()` ou verifique `needs.X.result`.

### Não deixar um erro quebrar a pipeline
| Mecanismo | Onde | Efeito |
|---|---|---|
| `continue-on-error: true` | step | step falha, mas job continua e é marcado como sucesso; `steps.<id>.outcome == 'failure'` fica disponível |
| `continue-on-error: true` | job | job falha, mas o workflow continua e jobs com `needs` nele rodam normalmente |
| `strategy.fail-fast: false` | matrix | uma combinação falhando não cancela as outras |
| `if: always()` | step/job | executa independente do resultado anterior (upload de relatório, cleanup, notificação) |
| `timeout-minutes` | job/step | evita job preso consumindo minutos (padrão: 360 min) |
| `|| true` / `set +e` | shell | controle fino dentro do script |

Diferença importante: **`outcome`** é o resultado real do step; **`conclusion`** é o resultado após aplicar `continue-on-error`.

### Outros recursos
- **`needs`** — dependência entre jobs; `needs.build.outputs.image_tag` passa dados.
- **`strategy.matrix`** — mesma job para várias versões/SOs; `include`/`exclude` para casos especiais.
- **`concurrency`** — impede execuções paralelas do mesmo grupo (cancelar CI antigo; **nunca** cancelar deploy em andamento).
- **`environment`** — secrets/vars por ambiente + *required reviewers* (aprovação manual antes de production) + *wait timer* + regra de branch.
- **`permissions`** — escopo do `GITHUB_TOKEN`; defina o mínimo.
- **Reusable workflows** (`workflow_call`) — DRY entre repos; **composite actions** para reutilizar steps.
- **Cache** (`actions/cache`, `cache: pip`, `cache-from: type=gha`) — acelera install/build.
- **Artifacts** — arquivos entre jobs e para download (relatórios, binários).
- **`$GITHUB_STEP_SUMMARY`** — markdown na página da execução.
- **Annotations** — `::error::`, `::warning::`, `::notice::` aparecem no PR.
- **`workflow_dispatch.inputs`** — formulário para execução manual (`choice`, `boolean`, `string`, `environment`).

---

## 3. Runners compartilhados (GitHub-hosted)

- `runs-on: ubuntu-latest | windows-latest | macos-latest` (e versões fixas: `ubuntu-24.04`).
- VM **efêmera e limpa** para cada job: nada persiste entre jobs (por isso existem cache e artifacts).
- Ubuntu padrão: 4 vCPU, 16 GB RAM, 14 GB SSD; runners maiores disponíveis para pagos.
- Já vem com Docker, docker compose, Python/Node/Go/Java em várias versões, kubectl, helm, gh CLI, AWS/Azure/GCP CLI, etc. Lista completa: `github.com/actions/runner-images`.
- Você tem **sudo**, rede de saída livre para a internet, e pode rodar `services:` (containers auxiliares como Postgres/Redis) ou o job inteiro em `container:`.
- Limites: 6 h por job, 35 dias por workflow, 20 jobs simultâneos no free (varia por plano). Repos públicos: ilimitado/grátis; privados: 2.000 min/mês no free, depois cobrado por minuto (Windows 2x, macOS 10x).
- **Segurança:** ele está na internet, na infra do GitHub. Ele **não** enxerga sua rede interna. Para acessar seu cluster você teria que expor a API do k8s ou usar VPN/túnel — exatamente o que você não quer.

---

## 4. Runner self-hosted (rodar dentro da sua rede)

### Por que resolve seu problema de rede/firewall
O runner **não recebe conexões**. Ele abre uma conexão HTTPS (443) de **saída** para `github.com`/`api.github.com`/`*.actions.githubusercontent.com` e fica em *long-polling* esperando job. Quando pega um job, executa **localmente**, com acesso a tudo que aquela máquina/pod acessa (API do k8s, banco, serviços internos). Zero portas abertas, zero regra de entrada no firewall.

### Três formas (arquivos em `runner/`)

**A) VM / servidor Linux** — `runner/install-vm.sh`
1. Repo → *Settings → Actions → Runners → New self-hosted runner* → copie o token.
2. `./runner/install-vm.sh SEU_USUARIO/actions-demo TOKEN`
3. Instale `kubectl` + kubeconfig e Docker nessa máquina. Pronto: `runs-on: [self-hosted, linux, k8s]`.

**B) Container Docker** — `runner/docker-compose.yml` (rápido para testar em qualquer máquina).

**C) Dentro do cluster (recomendado para produção)** — *Actions Runner Controller (ARC)*, `runner/arc-values.yaml` + `runner/arc-rbac.yaml`.
Um controller no cluster escuta a fila do GitHub e cria **pods efêmeros** sob demanda (`minRunners: 0` → custo zero ocioso; `maxRunners` limita). O pod usa uma ServiceAccount com RBAC restrito e faz `kubectl apply` pela rede interna. Suporta `docker build` via *dind* ou modo *kubernetes*.

### Boas práticas
- **Nunca** use self-hosted em repositório **público** (fork pode executar código arbitrário na sua rede).
- Prefira runners **efêmeros** (`--ephemeral` / ARC): job termina, ambiente é destruído.
- Restrinja com `permissions:` mínimo, `environment` com aprovação para production, e RBAC específico no k8s.
- Use **labels** para rotear (`k8s`, `gpu`, `prod`) e grupos de runners (org) para controlar quais repos podem usar.
- Pin de actions por SHA em ambientes sensíveis (`uses: actions/checkout@<sha>`).

---

## 5. Cenário simulado: ciclo de vida da aplicação

```
 PR aberto ────► pr-checks.yml (detecta mudanças, valida k8s, comenta)
             └─► ci.yml: lint → test(3.11, 3.12) + security ─► (build pulado em PR)
 merge na main ─► ci.yml: lint → test → security → build & push ghcr.io ─┐
                                                                         ▼
                                                   deploy.yml (staging) em runner self-hosted
                                                   kubectl apply → rollout → smoke test → rollback se falhar
 manual ───────► deploy.yml via "Run workflow" (choice: production) → aguarda aprovação do environment
 cron ─────────► scheduled.yml: checagem noturna em staging
```

### Passo a passo para testar
1. Crie um repo **privado** `actions-demo` e envie estes arquivos.
2. *Settings → Environments*: crie `staging` e `production`. Em `production`, adicione você como *required reviewer*. Opcional: variáveis `K8S_NAMESPACE` e `APP_URL`.
3. *Settings → Actions → General*: em *Workflow permissions* marque **Read and write** (para publicar no GHCR e comentar em PR).
4. Suba um runner self-hosted (seção 4) com labels `self-hosted,linux,k8s`, com `kubectl` apontando para um cluster (kind/minikube/k3d serve para o teste).
5. Faça um push na `main` e acompanhe a aba **Actions**. Depois abra um PR alterando `app/main.py` e outro alterando `k8s/` para ver as condicionais.
6. Rode *Deploy → Run workflow* escolhendo `production` para ver o gate de aprovação.
7. Para demonstrar tolerância a falhas, veja o job **Security scan** (`continue-on-error`) e o step "Scan experimental" que falha de propósito sem quebrar nada.

### Rodar localmente
```bash
make install && make lint && make test
make run                      # http://localhost:8000/docs
make docker-build && make docker-run
```

### Rodar os workflows localmente (opcional)
[`act`](https://github.com/nektos/act) executa workflows em Docker: `act push -j lint`. Útil para iterar sem gastar minutos, mas não cobre 100% (environments, GHCR, self-hosted).
