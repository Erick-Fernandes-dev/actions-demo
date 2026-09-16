# Runbook — runner self-hosted, execução do laboratório e resolução de problemas

Registro prático do que foi feito para colocar o laboratório `actions-demo` para rodar: configuração do repositório, instalação do runner self-hosted apontando para um cluster **kind** local, problemas encontrados e como foram resolvidos, e a explicação da simulação de segurança.

---

## 1. Configuração inicial do repositório

Nenhum token de Docker é necessário: a imagem é publicada no **GHCR (ghcr.io)**, autenticado com o `GITHUB_TOKEN` automático.

| Passo | Onde | O que fazer |
|---|---|---|
| 1 | Settings → Actions → General → *Workflow permissions* | marcar **Read and write permissions** e **Allow GitHub Actions to create and approve pull requests** |
| 2 | Settings → Environments | criar `staging` e `production`; em `production`, adicionar *Required reviewers* |
| 3 | Settings → Actions → Runners | registrar o runner self-hosted (seção 3) |
| 4 | perfil → Packages (após o 1º build) | opcional: tornar o pacote `actions-demo` público para simplificar o pull no kind |
| 5 | arquivos `runner/*` | trocar `SEU_USUARIO/actions-demo` pelo repositório real |

Sem o passo 1 o push no GHCR e o comentário em PR falham com `403`. Sem o passo 3 os jobs de deploy ficam em *Queued* indefinidamente.

---

## 2. Verificação do cluster local (kind)

```bash
kind get clusters
kubectl cluster-info
kubectl get nodes
kubectl config current-context        # esperado: kind-<nome>
kubectl config use-context kind-k9s   # ajustar se necessário
kubectl get ns                        # namespace da app ainda não existe; o deploy cria
```

Saída obtida no laboratório:

```
Kubernetes control plane is running at https://127.0.0.1:40779
NAME                STATUS   ROLES           AGE   VERSION
k9s-control-plane   Ready    control-plane   82d   v1.33.1
```

Por que o runner precisa rodar **na máquina host**, e não em container: o kind publica a API em `127.0.0.1:<porta>`; de dentro de um container, `localhost` seria o próprio container. Rodando no host, o runner usa o `~/.kube/config` já existente.

---

## 3. Tutorial — instalar e registrar o runner self-hosted (Linux)

### 3.1 Obter o token de registro
Repositório → **Settings → Actions → Runners → New self-hosted runner** → escolher *Linux / x64*. A página mostra os comandos e um token que **expira em 1 hora** e serve apenas para registrar (não fica salvo, não dá acesso ao repositório). Mesmo assim, não o compartilhe em chats, prints ou commits.

### 3.2 Baixar, validar e extrair
```bash
mkdir -p ~/actions-runner && cd ~/actions-runner

curl -o actions-runner-linux-x64-2.337.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.337.0/actions-runner-linux-x64-2.337.0.tar.gz

# opcional: validar integridade (hash exibido na página do GitHub)
echo "70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613  actions-runner-linux-x64-2.337.0.tar.gz" | shasum -a 256 -c

tar xzf ./actions-runner-linux-x64-2.337.0.tar.gz
```

### 3.3 Registrar com as labels esperadas pelos workflows
```bash
./config.sh \
  --url https://github.com/<usuario>/actions-demo \
  --token <TOKEN_DE_REGISTRO> \
  --name kind-k9s \
  --labels self-hosted,linux,k8s \
  --unattended
```

- `--labels`: os workflows usam `runs-on: [self-hosted, linux, k8s]`; **todas** precisam existir no runner. Sem `k8s` o job nunca é atribuído.
- `--unattended`: pula o modo interativo. Sem a flag, responder `k8s` em *"Enter any additional labels"*.
- `--replace`: útil ao re-registrar com o mesmo nome.

Saída esperada:
```
√ Connected to GitHub
√ Runner successfully added
√ Settings Saved.
```

### 3.4 Executar
```bash
./run.sh
```
```
√ Connected to GitHub
Current runner version: '2.337.0'
Listening for Jobs
```
Em Settings → Runners o runner aparece como **Idle**. O terminal deve permanecer aberto; para rodar como serviço systemd:
```bash
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

### 3.5 Pré-requisitos no host
- `kubectl` no `PATH` de shell **não interativo** (aliases do `.bashrc`/`.zshrc` não valem). Se necessário: `sudo ln -s $(which kubectl) /usr/local/bin/kubectl` e reiniciar o `run.sh`.
- Contexto ativo do kubeconfig apontando para o cluster desejado.
- Docker só é necessário se algum job self-hosted fizer build (não é o caso do deploy).

### 3.6 Remover o runner
Settings → Runners → runner → *Remove* fornece um token de remoção:
```bash
./config.sh remove --token <TOKEN_DE_REMOCAO>
```

### 3.7 Alternativas incluídas no projeto
- `runner/install-vm.sh` — automatiza 3.2–3.4 com systemd.
- `runner/docker-compose.yml` — runner em container (não indicado com kind por causa do `localhost`).
- `runner/arc-values.yaml` + `runner/arc-rbac.yaml` — Actions Runner Controller: runners como pods efêmeros dentro do cluster, recomendado para produção.

---

## 4. Execução do pipeline e acompanhamento

Disparo manual do CI: Actions → **CI** → Run workflow. Disparo do deploy: Actions → **Deploy** → Run workflow → `staging` + tag (`main`, `latest` ou o sha curto exibido no resumo do build).

Acompanhar no cluster:
```bash
kubectl -n actions-demo-staging get pods -w
kubectl -n actions-demo-staging describe pod <pod>
kubectl -n actions-demo-staging logs deploy/actions-demo
```

Testar a API após o deploy:
```bash
kubectl -n actions-demo-staging port-forward svc/actions-demo 8080:80
curl localhost:8080/health
# http://localhost:8080/docs
```

---

## 5. Problemas encontrados e resolução

### 5.1 Build falhou: `repository name must be lowercase`

**Sintoma**
```
ERROR: failed to build: invalid tag "ghcr.io/Erick-Fernandes-dev/actions-demo:smoke":
repository name must be lowercase
```
O job *Build & push image* ficou vermelho; *Deploy staging* foi pulado (dependência falhou); *Notify* rodou por causa do `if: always()`.

**Causa**
O Docker exige nomes de repositório em minúsculas. O contexto `github.repository` devolve o nome exatamente como cadastrado (`Erick-Fernandes-dev/actions-demo`). A action `docker/metadata-action` normaliza sozinha, mas a tag `:smoke` e o `deploy.yml` montavam o nome diretamente.

**Correção** — normalizar via expansão do bash `${VAR,,}` e persistir com `$GITHUB_ENV`.

`ci.yml`, job `build`, logo após o checkout:
```yaml
- name: Normalizar nome da imagem (Docker exige minúsculas)
  run: echo "IMAGE_NAME=${IMAGE_NAME,,}" >> "$GITHUB_ENV"
```

`deploy.yml`: `IMAGE` deixou de ser fixa na `env` e passou a ser montada em um step:
```yaml
env:
  IMAGE_TAG: ${{ inputs.image_tag }}
...
- name: Definir imagem (Docker exige nome em minúsculas)
  run: |
    REPO="${{ github.repository }}"
    echo "IMAGE=ghcr.io/${REPO,,}:${IMAGE_TAG}" >> "$GITHUB_ENV"
```

**Lição**: variáveis derivadas de contexto do GitHub podem precisar de tratamento antes de ir para ferramentas externas; `$GITHUB_ENV` é o mecanismo para propagar o valor tratado para os steps seguintes.

### 5.2 Aviso: `Node 20 is being deprecated`

Mensagem informativa do runner sobre a versão do Node usada pelas actions JavaScript. Não afeta a execução. Desaparece conforme as actions são atualizadas.

### 5.3 Possíveis problemas no deploy (referência)

| Sintoma | Causa | Correção |
|---|---|---|
| Job em *Queued* sem iniciar | labels não casam ou runner offline | conferir labels em Settings → Runners; `./run.sh` ativo |
| `kubectl não encontrado no runner` | kubectl fora do PATH não interativo | link em `/usr/local/bin` |
| `ImagePullBackOff` / `denied` | pacote GHCR privado e pull secret inválido | tornar pacote público ou revisar o secret `ghcr-pull` |
| `manifest unknown` | tag inexistente | usar `latest`/`main` ou o sha do resumo do build |
| `rollout status` timeout | pod não fica *Ready* | `describe pod` / `logs`; o step de rollback reverte automaticamente |
| Deploy `production` parado em *Waiting* | aguardando aprovação do environment | aprovar na tela da execução (*Review deployments*) |

---

## 6. A simulação de segurança

O job **Security scan (não bloqueante)** demonstra dois comportamentos ao mesmo tempo.

### 6.1 Um achado real: `pip-audit`
```
Found 14 known vulnerabilities in 1 package
Name      Version ID              Fix Versions
starlette 0.38.6  PYSEC-2026-1943 0.40.0
starlette 0.38.6  PYSEC-2026-1941 0.47.2
...
Error: Process completed with exit code 1.
```
O `pip-audit` compara as dependências do `requirements.txt` com a base de vulnerabilidades (PyPI Advisory / OSV). O `starlette` (dependência transitiva do FastAPI, na versão fixada) tinha CVEs conhecidas. A ferramenta retorna exit code 1, o step falha e o job fica vermelho.

### 6.2 Por que o pipeline não parou
O job tem `continue-on-error: true`. Isso faz o GitHub tratar a falha como **não fatal**: o job é exibido como falho, mas para efeito de `needs` conta como concluído, e *Build & push image* (que depende de `[test, security]`) iniciou normalmente. O grafo da execução mostra exatamente isso: Security vermelho, Build executado em seguida.

Dentro do mesmo job há um segundo exemplo, no nível de **step**:
```yaml
- name: Scan experimental (pode falhar)
  id: experimental
  continue-on-error: true
  run: exit 1
- name: Reportar resultado do step anterior
  run: |
    echo "outcome=${{ steps.experimental.outcome }}"        # failure
    echo "conclusion=${{ steps.experimental.conclusion }}"  # success
    echo "::warning title=Scan experimental::step falhou mas foi tolerado"
```
O step falha propositalmente; `outcome` registra a falha real, `conclusion` mostra o resultado após a tolerância, e a annotation `::warning::` deixa o aviso visível na interface.

### 6.3 Quando usar cada abordagem
- **Não bloqueante** (como aqui): ao introduzir uma ferramenta nova, para medir ruído antes de travar merges; para scanners instáveis; para relatórios informativos.
- **Bloqueante** (remover o `continue-on-error`): quando a política é "nenhuma CVE alta/crítica entra em produção". Geralmente combinado com filtro de severidade (`pip-audit --ignore-vuln` para exceções documentadas) e com branch protection exigindo o check.

### 6.4 Correção do achado
```bash
pip install -U fastapi uvicorn pydantic
pip freeze | grep -iE '^(fastapi|uvicorn|pydantic|starlette)='
```
Atualizar os pins em `requirements.txt` com as versões resultantes (incluindo `starlette` explicitamente), rodar `make test`, commitar. Na próxima execução o job *Security scan* passa a ficar verde — e aí é possível decidir torná-lo bloqueante.

---

## 7. Resumo do estado final

- Repositório privado com permissões de escrita habilitadas para o `GITHUB_TOKEN`.
- Environments `staging` e `production` (este com aprovação obrigatória).
- Runner `kind-k9s` registrado com labels `self-hosted, linux, k8s`, rodando no host e usando o `kubectl` local contra o cluster kind.
- Workflows corrigidos para nomes de imagem em minúsculas.
- Scan de dependências ativo, em modo não bloqueante, com um achado real pendente de atualização de dependências.
