#!/usr/bin/env bash
set -euo pipefail

CONTAINER=${CONTAINER:-mdfedit-mssql}
SA_PASSWORD=${SA_PASSWORD:-YourStrong!Passw0rd}

if [[ $# -lt 3 ]]; then
  echo "用法：$0 <資料庫名稱> <檔名.mdf> [檔名.ldf]"
  echo "說明：mdf/ldf 檔請先放入 ./data/（容器內對應 /var/opt/mssql/data/）"
  exit 1
fi

DBNAME=$1
MDF=$2
LDF=${3:-}

SQL="CREATE DATABASE [$DBNAME] ON (FILENAME = '/var/opt/mssql/data/$MDF')"
if [[ -n "$LDF" ]]; then
  SQL="$SQL , (FILENAME = '/var/opt/mssql/data/$LDF')"
fi
SQL="$SQL FOR ATTACH"

exec docker exec -i "$CONTAINER" /opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "$SA_PASSWORD" -C -d master \
  -Q "$SQL"
