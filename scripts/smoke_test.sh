#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)/.."

SECRET=$(printf 'SmokeTest123\nSmokeTest123\n' | .venv/bin/python manage.py adduser smoke 2>/dev/null | sed -n 's/.*：\([A-Z2-7]\{32\}\)$/\1/p')
echo "TOTP_SECRET=$SECRET"

(.venv/bin/python run.py > /tmp/opencode/mdfedit-server.log 2>&1 &)
sleep 3
trap 'pkill -f "python run.py" || true' EXIT

echo "--- 未登入狀態 ---"
curl -s -o /dev/null -w "GET /            -> %{http_code} (redirect: %{redirect_url})\n" http://127.0.0.1:8000/

COOKIE=$(mktemp)
CSRF=$(curl -s -c "$COOKIE" http://127.0.0.1:8000/login | grep -oP '(?<=name="_csrf" value=")[0-9a-f]+')

echo "--- 第一步：帳號密碼 ---"
curl -s -b "$COOKIE" -c "$COOKIE" \
  --data-urlencode "username=smoke" \
  --data-urlencode "password=SmokeTest123" \
  --data-urlencode "_csrf=$CSRF" \
  -o /dev/null -w "POST /login      -> %{http_code} (redirect: %{redirect_url})\n" \
  http://127.0.0.1:8000/login

CSRF2=$(curl -s -b "$COOKIE" -c "$COOKIE" http://127.0.0.1:8000/login/totp | grep -oP '(?<=name="_csrf" value=")[0-9a-f]+')
CODE=$(SECRET="$SECRET" .venv/bin/python tests/gen_totp.py)

echo "--- 第二步：TOTP（$CODE）---"
curl -s -b "$COOKIE" -c "$COOKIE" \
  --data-urlencode "code=$CODE" \
  --data-urlencode "_csrf=$CSRF2" \
  -o /dev/null -w "POST /login/totp -> %{http_code} (redirect: %{redirect_url})\n" \
  http://127.0.0.1:8000/login/totp

echo "--- 搜尋姓名「王小」---"
curl -s -b "$COOKIE" "http://127.0.0.1:8000/search?name=%E7%8E%8B%E5%B0%8F" | grep -oE "(王小美|A289635741|仁愛路四段)" | sort -u || echo "(無結果)"

echo "--- 搜尋電話「0933」---"
curl -s -b "$COOKIE" --get --data-urlencode "phone=0933" http://127.0.0.1:8000/search | grep -oE "(李俊宏|0933-555-888)" | sort -u || echo "(無結果)"

echo "--- 錯誤 TOTP 應被拒絕（新 session）---"
COOKIE2=$(mktemp)
CSRF3=$(curl -s -c "$COOKIE2" http://127.0.0.1:8000/login | grep -oP '(?<=name="_csrf" value=")[0-9a-f]+')
curl -s -b "$COOKIE2" -c "$COOKIE2" \
  --data-urlencode "username=smoke" \
  --data-urlencode "password=SmokeTest123" \
  --data-urlencode "_csrf=$CSRF3" \
  -o /dev/null http://127.0.0.1:8000/login
CSRF4=$(curl -s -b "$COOKIE2" http://127.0.0.1:8000/login/totp | grep -oP '(?<=name="_csrf" value=")[0-9a-f]+')
curl -s -b "$COOKIE2" \
  --data-urlencode "code=000000" \
  --data-urlencode "_csrf=$CSRF4" \
  http://127.0.0.1:8000/login/totp | grep -oE "動態驗證碼錯誤或已被使用" | head -1 || true

rm -f "$COOKIE" "$COOKIE2"
echo "=== SMOKE TEST DONE ==="
