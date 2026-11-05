#!/usr/bin/env bash
# Run as the regular Ubuntu user after Bench and its apps have been installed.
set -euo pipefail

bench_dir=/home/pipe6/frappe/hikcentral-bench
secret_dir=/home/pipe6/.config/hikcentral_bridge
site=hikcentral.localhost
source "$secret_dir/db.env"
export PATH="/home/pipe6/.local/bin:$PATH"
cd "$bench_dir"
if [[ "$(redis-cli -p 13000 ping 2>/dev/null || true)" != PONG ]]; then
  echo 'Start bench in another WSL terminal before installing Frappe HR (redis_cache port 13000).' >&2
  exit 1
fi

if [[ ! -f "sites/$site/site_config.json" ]]; then
  ADMIN_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  printf 'ADMIN_PASSWORD=%s\n' "$ADMIN_PASSWORD" > "$secret_dir/admin.env"
  chmod 600 "$secret_dir/admin.env"
  bench new-site "$site" --set-default \
    --db-root-username hikcentral_bench --db-root-password "$DB_ADMIN_PASSWORD" \
    --admin-password "$ADMIN_PASSWORD"
fi

bench --site "$site" install-app erpnext hrms
bench --site "$site" enable-scheduler
echo "Site $site is ready; Administrator password is in $secret_dir/admin.env"
