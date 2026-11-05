#!/usr/bin/env bash
# Run once as root inside Ubuntu WSL. Secrets remain under the Linux home directory.
set -euo pipefail

demo_user=pipe6
secret_dir=/home/${demo_user}/.config/hikcentral_bridge
secret_file=${secret_dir}/db.env
install -d -m 700 -o "$demo_user" -g "$demo_user" "$secret_dir"

if [[ -f "$secret_file" ]]; then
  # shellcheck disable=SC1090
  source "$secret_file"
else
  DB_ADMIN_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  printf 'DB_ADMIN_PASSWORD=%s\n' "$DB_ADMIN_PASSWORD" > "$secret_file"
  chown "$demo_user:$demo_user" "$secret_file"
  chmod 600 "$secret_file"
fi

mariadb <<SQL
CREATE USER IF NOT EXISTS 'hikcentral_bench'@'localhost' IDENTIFIED BY '${DB_ADMIN_PASSWORD}';
ALTER USER 'hikcentral_bench'@'localhost' IDENTIFIED BY '${DB_ADMIN_PASSWORD}';
GRANT ALL PRIVILEGES ON *.* TO 'hikcentral_bench'@'localhost' WITH GRANT OPTION;
FLUSH PRIVILEGES;
SQL

echo 'Local MariaDB bench administrator is ready; password is stored outside Git.'
