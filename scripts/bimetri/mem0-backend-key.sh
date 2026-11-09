#!/usr/bin/env bash
# mem0-backend-key.sh — bimetri yamasi: AgenticKode backend'i icin mem0 API anahtari (yama 72).
#
# Repo kokunde root olarak: scripts/bimetri/mem0-backend-key.sh
#   1. mem0'da yonetici hesabi yoksa olusturur (e-posta ve parola sorulur, parola gizli).
#      Hesap olusana kadar /auth/register herkese aciktir; bu adim onu kapatir.
#   2. .env.mem0'daki ADMIN_API_KEY ile "agentickode-backend" etiketli anahtar uretir.
#   3. Anahtari ekrana yazmadan .env'e MEM0_API_KEY olarak ekler.
# .env'de MEM0_API_KEY zaten doluysa hicbir sey yapmaz.
# Sonra backend yeniden olusturulmali (restart .env'i yeniden okumaz):
#   docker compose -p agentickode -f ... -f docker-compose.bimetri.yml up -d backend
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."

bind=$(grep -oP '^MEM0_BIND=\K.*' .env 2>/dev/null || true)
MEM0=${MEM0:-http://${bind:-127.0.0.1}:8890}

alan() { python3 -c "import json, sys; print(json.load(sys.stdin).get('$1', ''))"; }

if grep -q '^MEM0_API_KEY=.' .env 2>/dev/null; then
  echo "MEM0_API_KEY zaten .env'de; degisiklik yapilmadi."
  exit 0
fi

if [[ $(curl -fsS "$MEM0/auth/setup-status" | alan needsSetup) == True ]]; then
  read -rp "mem0 yonetici e-postasi: " email
  read -rsp "mem0 yonetici parolasi (en az 8 karakter): " parola
  echo
  kod=$(EMAIL=$email PAROLA=$parola python3 -c \
    'import json, os; print(json.dumps({"name": "admin", "email": os.environ["EMAIL"], "password": os.environ["PAROLA"]}))' |
    curl -sS -o /dev/null -w '%{http_code}' -X POST "$MEM0/auth/register" \
      -H 'Content-Type: application/json' --data-binary @-)
  unset parola
  [[ $kod == 200 ]] || { echo "HATA: yonetici hesabi olusturulamadi (HTTP $kod)"; exit 1; }
  echo "mem0 yonetici hesabi olusturuldu; acik kayit kapandi."
fi

# Anahtarlar komut satirina (ps) dusmesin: basliklar stdin'den.
admin=$(grep -oP '^ADMIN_API_KEY=\K.*' .env.mem0)
anahtar=$(printf 'X-API-Key: %s\n' "$admin" |
  curl -fsS -X POST "$MEM0/api-keys" -H @- -H 'Content-Type: application/json' \
    -d '{"label": "agentickode-backend"}' | alan key)
unset admin
[[ -n $anahtar ]] || { echo "HATA: mem0 anahtari uretilemedi"; exit 1; }

[[ -z $(tail -c1 .env 2>/dev/null) ]] || echo >>.env
printf 'MEM0_API_KEY=%s\n' "$anahtar" >>.env
unset anahtar
echo "MEM0_API_KEY .env'e eklendi (etiket: agentickode-backend)."
