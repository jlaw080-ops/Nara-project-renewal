#!/usr/bin/env bash
# 서버에서 새 코드를 받아 다시 띄운다. sudo를 쓸 수 있는 관리 계정(ubuntu)으로 실행한다.
set -euo pipefail
sudo -u nara git -C /srv/nara pull --ff-only
sudo -u nara bash -c "cd /srv/nara && /home/nara/.local/bin/uv sync --frozen"
sudo systemctl restart nara-web
echo "갱신 완료: $(sudo -u nara git -C /srv/nara log --oneline -1)"
