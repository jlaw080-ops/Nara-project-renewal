# 서버 설치 (Oracle Cloud 서울, 상시 무료)

사람이 해야 하는 일(계정·카드 인증)과 서버에서 칠 명령을 순서대로 적는다. 비밀값은
어디에도 적지 않는다 — `/srv/nara/.env`에만 둔다.

## 1. 계정과 서버 (사람)

1. Oracle Cloud 가입. 홈 리전은 **South Korea Central (Seoul)**. 춘천은 ARM 무료 대상이 아니다
2. Compute → Instance 만들기: 이미지 Ubuntu 24.04, 모양 `VM.Standard.A1.Flex` 1 OCPU·6GB(무료 한도 2 OCPU·12GB 안)
   - "Out of capacity"가 나오면 시간을 두고 다시 만든다
3. 공개 SSH 키를 넣고 만든다. 공인 IP를 적어 둔다
4. VCN 보안 목록에 들어오는 TCP 80·443을 연다
5. DuckDNS(duckdns.org)에 로그인해 주소 하나를 만들고 위 공인 IP를 넣는다

## 2. 서버 준비

```bash
sudo timedatectl set-timezone Asia/Seoul
sudo apt update && sudo apt -y upgrade
sudo apt -y install git sqlite3 rclone iptables-persistent debian-keyring debian-archive-keyring apt-transport-https curl
# Ubuntu 방화벽(iptables)에도 80·443을 연다 — Oracle 이미지는 기본으로 막아 둔다
sudo iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
sudo useradd --create-home --shell /bin/bash nara
sudo mkdir -p /srv/nara && sudo chown nara:nara /srv/nara
```

Caddy 설치: https://caddyserver.com/docs/install#debian-ubuntu-raspbian 의 명령을 그대로 친다.

## 3. 앱

```bash
sudo -iu nara
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/jlaw080-ops/Nara-project-renewal.git /srv/nara
cd /srv/nara && ~/.local/bin/uv sync --frozen
mkdir -p data backup
```

`.env`를 만든다(값은 직접 넣는다):

```bash
python3 -c "import secrets; print('NARA_SECRET_KEY=' + secrets.token_urlsafe(32))" > /srv/nara/.env
echo "NARA_HOST=<DuckDNS 주소>" >> /srv/nara/.env
echo "NARA_BACKUP_REMOTE=gdrive:nara-backup" >> /srv/nara/.env
nano /srv/nara/.env   # G2B_API_KEY, ANTHROPIC_API_KEY 줄을 더한다
chmod 600 /srv/nara/.env
```

## 4. DB 옮기기

사용자 PC에서(수집을 끈 뒤):

```bash
sqlite3 data/nara.db ".backup data/nara-upload.db"
scp data/nara-upload.db ubuntu@<공인 IP>:/tmp/nara.db
```

서버에서:

```bash
sudo mv /tmp/nara.db /srv/nara/data/nara.db && sudo chown nara:nara /srv/nara/data/nara.db
sudo -iu nara bash -c "cd /srv/nara && ~/.local/bin/uv run nara user add <이메일> --name <이름> --db data/nara.db"
```

사용자 PC의 작업 스케줄러에서 nara 수집 작업을 끈다. 두 곳에서 수집하면 결과가 엇갈린다.

## 5. 서비스·예약·Caddy

```bash
sudo cp /srv/nara/deploy/*.service /srv/nara/deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nara-web nara-slot-09.timer nara-slot-12.timer nara-slot-15.timer nara-backup.timer
sudo cp /srv/nara/deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile   # 첫 줄 주소를 DuckDNS 주소로
sudo systemctl reload caddy
```

## 6. 백업 보낼 곳 (rclone ↔ 구글 드라이브)

```bash
sudo -iu nara rclone config   # n → 이름 gdrive → drive → 안내대로(브라우저 인증은 PC에서 rclone authorize "drive")
sudo -iu nara bash -c "cd /srv/nara && ~/.local/bin/uv run nara backup --db data/nara.db --out backup --env .env"
```

## 7. 점검 목록

- [ ] `https://<DuckDNS 주소>`가 자물쇠와 함께 로그인 화면을 연다
- [ ] 로그인 → 임시 비밀번호 바꾸기 → 목록 249건 전후가 보인다
- [ ] 상세에서 비고를 고치면 수정 이력에 내 이름이 보인다
- [ ] `systemctl list-timers | grep nara`에 슬롯 셋과 백업이 다음 실행 시각과 함께 보인다
- [ ] 다음 날 목록 머리에서 수집·낙찰·진행현황·백업이 모두 정상이다
- [ ] 구글 드라이브 `nara-backup/`에 `nara-YYYYMMDD.db.gz`가 쌓인다
- [ ] `timedatectl`의 Time zone이 Asia/Seoul이다(12시 슬롯의 요일이 여기서 정해진다)

## 갱신

```bash
bash /srv/nara/deploy/update.sh   # ubuntu 계정으로
```

## 복구

1. 구글 드라이브에서 원하는 날짜의 `nara-YYYYMMDD.db.gz`를 받는다
2. `gunzip`으로 풀어 `/srv/nara/data/nara.db`로 둔다(지금 파일은 옆에 옮겨 둔다)
3. `sudo systemctl restart nara-web`
