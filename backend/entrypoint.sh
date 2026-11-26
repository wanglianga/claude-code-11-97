#!/bin/sh
set -e

echo "等待 PostgreSQL 就绪..."
python - <<'PY'
import os, time
import psycopg2

url = os.environ["CLM_DATABASE_URL"]
# 转成 psycopg2 可识别的关键字参数
import re
m = re.match(r"postgresql\+psycopg2://([^:]+):([^@]+)@([^:/]+):(\d+)/(.+)", url)
user, pwd, host, port, dbname = m.groups()
for i in range(60):
    try:
        psycopg2.connect(user=user, password=pwd, host=host, port=port, dbname=dbname).close()
        print("PostgreSQL 已就绪")
        break
    except Exception as exc:
        print(f"  尚未就绪({i+1}/60): {exc}")
        time.sleep(2)
else:
    raise SystemExit("数据库连接超时")
PY

echo "初始化表结构与种子数据（幂等）..."
python -m app.seed_idempotent

echo "启动 FastAPI 服务..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
