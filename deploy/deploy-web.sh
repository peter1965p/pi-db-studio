#!/bin/sh
# Spielt die Web-Oberfläche von Pi DB Studio in Container 104 (dbstudio-web, 192.168.178.215) ein.
# Erstes Mal: legt Benutzer, venv, Zertifikat, Geheimnis-Datei und Admin-Benutzer an.
# Das Admin-Passwort wird nur im Schlüsselbund des PCs abgelegt (Dienst „db-studio“, Eintrag „web:admin@192.168.178.215“).
set -eu
cd "$(dirname "$0")/.."
ZIEL=${ZIEL:-dbstudio-web}
IP=${IP:-192.168.178.215}

venv/bin/python -m py_compile dbstudio/web/app.py dbstudio/web/speicher.py
tar czf - --exclude=__pycache__ --exclude='dbstudio/ui' --exclude='dbstudio/__main__.py' \
    dbstudio requirements-web.txt deploy/dbstudio-web.service | ssh -o BatchMode=yes "$ZIEL" "cat > /tmp/dbstudio-web.tgz"

ssh -o BatchMode=yes "$ZIEL" IP="$IP" sh -s <<'EOF'
set -eu
export DEBIAN_FRONTEND=noninteractive
if ! command -v openssl >/dev/null || ! python3 -c 'import venv, ensurepip' 2>/dev/null || ! command -v nft >/dev/null; then
  apt-get -qq update && apt-get -qq install -y python3-venv openssl nftables >/dev/null
fi
id dbstudio >/dev/null 2>&1 || useradd --system --home /var/lib/dbstudio-web --shell /usr/sbin/nologin dbstudio
install -d -o dbstudio -g dbstudio -m 700 /var/lib/dbstudio-web
install -d -m 755 /opt/dbstudio-web /etc/dbstudio-web
rm -rf /opt/dbstudio-web/app.neu && mkdir -p /opt/dbstudio-web/app.neu
tar xzf /tmp/dbstudio-web.tgz -C /opt/dbstudio-web/app.neu && rm /tmp/dbstudio-web.tgz
[ -d /opt/dbstudio-web/venv ] || python3 -m venv /opt/dbstudio-web/venv
/opt/dbstudio-web/venv/bin/pip install -q --upgrade pip >/dev/null
/opt/dbstudio-web/venv/bin/pip install -q -r /opt/dbstudio-web/app.neu/requirements-web.txt
rm -rf /opt/dbstudio-web/app.alt; [ -d /opt/dbstudio-web/app ] && mv /opt/dbstudio-web/app /opt/dbstudio-web/app.alt
mv /opt/dbstudio-web/app.neu /opt/dbstudio-web/app
chmod -R a+rX /opt/dbstudio-web/app

# Zertifikat (selbstsigniert, EC, 10 Jahre)
if [ ! -f /etc/dbstudio-web/zert.pem ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3650 \
    -subj "/CN=Pi DB Studio" -addext "subjectAltName=IP:$IP,DNS:dbstudio-web" \
    -keyout /etc/dbstudio-web/schluessel.pem -out /etc/dbstudio-web/zert.pem 2>/dev/null
fi
chown root:dbstudio /etc/dbstudio-web/schluessel.pem /etc/dbstudio-web/zert.pem
chmod 640 /etc/dbstudio-web/schluessel.pem; chmod 644 /etc/dbstudio-web/zert.pem

# Geheimnis-Datei: Fernet-Schlüssel für Verbindungs-Passwörter und KI-Schlüssel
if [ ! -f /etc/dbstudio-web.env ]; then
  umask 077
  echo "DBSTUDIO_SCHLUESSEL=$(/opt/dbstudio-web/venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" > /etc/dbstudio-web.env
fi
chmod 600 /etc/dbstudio-web.env

# Firewall im Container: 443 und 22 nur aus dem Heimnetz (Tailscale kommt über den Subnet-Router als .86 an)
cat > /etc/nftables.conf <<'NFT'
#!/usr/sbin/nft -f
flush ruleset
table inet filter {
  chain input {
    type filter hook input priority 0; policy drop;
    iif lo accept
    ct state established,related accept
    ip protocol icmp accept
    ip6 nexthdr ipv6-icmp accept
    ip saddr 192.168.178.0/24 tcp dport { 22, 443 } accept
  }
}
NFT
systemctl enable -q nftables && systemctl restart nftables

install -m 644 /opt/dbstudio-web/app/deploy/dbstudio-web.service /etc/systemd/system/dbstudio-web.service
systemctl daemon-reload && systemctl enable -q dbstudio-web && systemctl restart dbstudio-web
sleep 3; systemctl is-active dbstudio-web
EOF

# Admin-Benutzer einmalig: Passwort erzeugen, nur im Schlüsselbund des PCs ablegen, per stdin übergeben
if ! ssh -o BatchMode=yes "$ZIEL" test -s /var/lib/dbstudio-web/benutzer.json; then
  venv/bin/python - "$ZIEL" "$IP" <<'PY'
import secrets, subprocess, sys, keyring
ziel, ip = sys.argv[1], sys.argv[2]
eintrag = f"web:admin@{ip}"
pw = keyring.get_password("db-studio", eintrag) or secrets.token_urlsafe(18)
keyring.set_password("db-studio", eintrag, pw)
befehl = ("set -a; . /etc/dbstudio-web.env; set +a; cd /opt/dbstudio-web/app && "
          "runuser -u dbstudio -- env DBSTUDIO_SCHLUESSEL=$DBSTUDIO_SCHLUESSEL DBSTUDIO_WEB_DATEN=/var/lib/dbstudio-web "
          "/opt/dbstudio-web/venv/bin/python -m dbstudio.web benutzer admin")
r = subprocess.run(["ssh", "-o", "BatchMode=yes", ziel, befehl], input=pw + "\n", text=True, capture_output=True)
print(r.stdout.strip() or r.stderr.strip()[:300])
PY
fi
curl -sk -o /dev/null -w "https://$IP/api/gesundheit -> %{http_code}\n" "https://$IP/api/gesundheit"
