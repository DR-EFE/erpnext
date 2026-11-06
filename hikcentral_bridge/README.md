# Demo HikCentral → Frappe HR

Este puente reproduce **marcajes originales simulados** en `Employee Checkin`. Frappe HR genera `Attendance` al cerrar el turno. No procesa nómina ni consulta aún HikCentral: el endpoint, autenticación y esquema reales se conectarán cuando estén disponibles.

## Página local de marcaje

La nueva página permite demostrar el flujo sin terminal. Desde Ubuntu/WSL, con el Bench activo y después de ejecutar `site_cli seed`:

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
python3 -m hikcentral_bridge serve
```

Abrir `http://localhost:8765` en Windows. Registrar entrada y salida de los dos empleados ficticios el mismo día. La página guarda cada evento con un `eventId` en el SQLite del puente y consulta la fuente local cada 10 segundos para enviarlo a Frappe. `python3 -m hikcentral_bridge sync` fuerza una consulta; las siguientes lecturas quedan como `skipped` en el ledger. La página es solo local y no registra datos dentro de HikCentral.

Después de las cuatro marcas, para la fecha elegida:

```bash
~/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli finalize --date 2026-11-05
~/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli verify --date 2026-11-05
```

El módulo carga automáticamente `~/.config/hikcentral_bridge/erpnext.env`. Para probar la autenticación OpenAPI, copiar la plantilla `hikcentral.env.example` a `~/.config/hikcentral_bridge/hikcentral.env`, completar los valores fuera de Git y ejecutar `python3 -m hikcentral_bridge probe`. Mantener `HIKCENTRAL_VERIFY_TLS=true`; si hay CA interna, configurar `HIKCENTRAL_CA_BUNDLE`. El cliente firmado y la interfaz paginada existen, pero activar la fuente real requiere contrastar el contrato de búsqueda de eventos originales con el Developer Guide 2.6.3.

## Instalación local (Ubuntu en WSL)

El Bench y la base de datos están fuera del repositorio, en `~/frappe/hikcentral-bench`. Este checkout de ERPNext está en `/mnt/c/Users/pipe6/Documents/erpnext`. El Bench usa una copia superficial de la misma revisión (`911a478`) en el disco Linux; el puente permanece en este checkout. Frappe, ERPNext y HRMS usan `develop` de la serie 17.

Desde PowerShell, instalar los servicios y preparar un administrador local de MariaDB:

```powershell
wsl -d Ubuntu -u root -- apt-get install -y git redis-server libmariadb-dev mariadb-server mariadb-client pkg-config curl build-essential python3-dev python3-venv
wsl -d Ubuntu -u root -- systemctl start mariadb redis-server
wsl -d Ubuntu -u root -- bash /mnt/c/Users/pipe6/Documents/erpnext/hikcentral_bridge/bootstrap_db.sh
```

Desde Ubuntu WSL, instalar las herramientas y crear el Bench:

```bash
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
source ~/.nvm/nvm.sh
nvm install 24
npm install -g yarn
curl -LsSf https://astral.sh/uv/install.sh | sh
~/.local/bin/uv tool install frappe-bench
mkdir -p ~/frappe && cd ~/frappe
~/.local/bin/bench init --frappe-branch develop --python /usr/bin/python3.14 hikcentral-bench
cd hikcentral-bench
~/.local/bin/bench get-app --soft-link --skip-assets /mnt/c/Users/pipe6/Documents/erpnext
~/.local/bin/bench get-app --branch develop --skip-assets https://github.com/frappe/hrms.git
git clone --depth 1 --branch develop file:///mnt/c/Users/pipe6/Documents/erpnext apps/erpnext-native
test -L apps/erpnext && unlink apps/erpnext
mv apps/erpnext-native apps/erpnext
~/.local/bin/uv pip install -e apps/erpnext --python env/bin/python
cd apps/erpnext && yarn install --check-files
cd banking && yarn install --check-files
cd ../../.. && ~/.local/bin/bench build --app erpnext && ~/.local/bin/bench build --app hrms
```

En una terminal WSL, iniciar el Bench. En otra, crear el sitio y cargar los datos ficticios:

```bash
source ~/.nvm/nvm.sh
cd ~/frappe/hikcentral-bench && ~/.local/bin/bench start
```

```bash
bash /mnt/c/Users/pipe6/Documents/erpnext/hikcentral_bridge/bootstrap_site.sh
cd /mnt/c/Users/pipe6/Documents/erpnext
~/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli seed
```

El usuario de API tiene permisos de crear y leer `Employee Checkin` y de leer/escribir el campo `time` en el nivel de permiso 1. Sin este último permiso, Frappe sustituye el timestamp del marcaje por la hora actual.

## Arranque diario

```bash
source ~/.nvm/nvm.sh
cd ~/frappe/hikcentral-bench
bench start
```

Abrir `http://localhost:8000` (el sitio `hikcentral.localhost` es el predeterminado del Bench). Iniciar sesión como `Administrator`; la contraseña está en `~/.config/hikcentral_bridge/admin.env`. El sitio, sus credenciales y la base de datos viven solo en WSL. Si los servicios de sistema no están activos tras reiniciar WSL, iniciarlos como root con `systemctl start mariadb redis-server`.

## Reproducir los marcajes

En otra terminal WSL, cargar las credenciales locales generadas durante la preparación del sitio y ejecutar:

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
python3 -m hikcentral_bridge hikcentral_bridge/fixtures/demo_events.json
```

La salida muestra `source_event_id`, estado y nombre del `Employee Checkin`. Al repetir el comando, los eventos ya enviados salen como `skipped`. El registro SQLite se guarda en `~/.local/share/hikcentral_bridge/events.sqlite3` y relaciona el identificador de origen con el Checkin creado. Si se elimina el sitio o se crean otros datos de prueba, conservar o restablecer ese registro de forma coherente.

El archivo `config.example.json` contiene la URL del sitio, zona horaria de ERPNext, mapa de zonas por sede, mapa opcional de `personId` a `attendance_device_id` y mapa de dispositivos a sede. Para cambiarlo, copiarlo a `config.local.json` (ignorado por Git) y pasar `--config hikcentral_bridge/config.local.json` antes del archivo de eventos. Las credenciales de Frappe se leen de `ERPNEXT_API_KEY` y `ERPNEXT_API_SECRET` o de su archivo local.

## Verificar

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
~/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli finalize
~/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli verify
```

La verificación espera cuatro `Employee Checkin` y dos `Attendance` para el 2 de noviembre de 2026. Si los Checkin están pero no la asistencia, comprobar `Last Sync of Checkin`, la ventana del turno y el programador; también se puede usar **Mark Attendance** en el turno. Para repetir la demo desde cero, detén la página y ejecuta `~/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli reset-attempt --date 2026-11-02`. El comando elimina los marcajes, asistencias y eventos locales de ese día de los empleados de prueba; conserva los datos maestros.

Pruebas del puente:

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
python3 -m unittest discover -s hikcentral_bridge/tests -v
python3 -m hikcentral_bridge.tests.live_checks
```

En Windows fuera de WSL, instalar `tzdata` para que `zoneinfo` encuentre `America/Mexico_City`.

## Datos pendientes de HikCentral

- Versión exacta de HikCentral Professional, licencia y OpenAPI habilitada.
- URL, certificado TLS, método de autenticación y credenciales de demo.
- Endpoint de búsqueda de marcajes originales, filtros, paginación y límites.
- Ejemplos reales con identificador estable de evento, `employeeNo`, fecha con zona, dirección y dispositivo.
- Ventana máxima de retraso y política de retención de eventos para definir el avance de sincronización.

El registro de eventos en HikCentral debe verificarse con el proveedor antes de describirlo como evidencia legal inmutable.
