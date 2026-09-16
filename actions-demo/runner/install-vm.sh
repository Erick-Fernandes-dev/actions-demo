#!/usr/bin/env bash
# Instala um runner self-hosted em uma VM/servidor Linux (fora do k8s).
# Uso: ./install-vm.sh <owner/repo> <TOKEN_DE_REGISTRO>
# O token vem de: repositório > Settings > Actions > Runners > New self-hosted runner
# (válido por 1 hora; serve só para registrar, não fica salvo).
set -euo pipefail

REPO="${1:?owner/repo}"
TOKEN="${2:?registration token}"
VERSION="${RUNNER_VERSION:-2.319.1}"
DIR="${RUNNER_DIR:-$HOME/actions-runner}"

mkdir -p "$DIR" && cd "$DIR"
curl -sSL -o runner.tar.gz \
  "https://github.com/actions/runner/releases/download/v${VERSION}/actions-runner-linux-x64-${VERSION}.tar.gz"
tar xzf runner.tar.gz && rm runner.tar.gz

./config.sh --unattended \
  --url "https://github.com/${REPO}" \
  --token "${TOKEN}" \
  --name "$(hostname)-runner" \
  --labels "self-hosted,linux,k8s" \
  --work _work \
  --replace

# Instala como serviço systemd (sobe no boot, reinicia se cair)
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
