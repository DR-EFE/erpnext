# Demo HikCentral → ERPNext/Frappe HR

Guía para ejecutar la demo local desde Windows, pasando a Ubuntu mediante WSL.

La demo reproduce cuatro marcajes simulados de HikCentral, los envía a Frappe HR y genera dos registros de `Attendance` mediante Auto Attendance.

## Nueva demo con página de marcaje

Esta opción permite crear los marcajes desde una página local, sin dispositivo físico. Los eventos se guardan en SQLite con campos similares a registros originales de HikCentral y el puente los consulta cada 10 segundos. La página **no escribe en HikCentral**.

Desde PowerShell abre Ubuntu:

```powershell
wsl -d Ubuntu
```

En Ubuntu, asegúrate de que MariaDB y Redis estén activos. Si no lo están, desde otra ventana de PowerShell:

```powershell
wsl -d Ubuntu -u root -- systemctl start mariadb redis-server
```

Abre tres terminales de Ubuntu. En la primera inicia ERPNext:

```bash
source /home/pipe6/.nvm/nvm.sh
cd /home/pipe6/frappe/hikcentral-bench
/home/pipe6/.local/bin/bench start
```

En la segunda prepara empleados y turno, y arranca la página:

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
/home/pipe6/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli seed
python3 -m hikcentral_bridge serve
```

Abre `http://localhost:8765` desde Windows. Selecciona cada empleado y registra una entrada y una salida el mismo día, por ejemplo a las 09:00 y 18:00. La página enseña el identificador de origen, el estado de envío y el nombre del `Employee Checkin`. El botón **Sincronizar ahora** permite ejecutar la consulta sin esperar 10 segundos.

En la tercera terminal de Ubuntu puedes forzar o repetir la consulta:

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
python3 -m hikcentral_bridge sync
```

Repetir `sync` muestra `skipped` para eventos ya enviados. El programa carga automáticamente `~/.config/hikcentral_bridge/erpnext.env`; no necesitas ejecutar `source` ni `set -a` en PowerShell.

Después de cerrar el turno, procesa y verifica el día usado en la página (sustituye la fecha de ejemplo):

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
/home/pipe6/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli finalize --date 2026-11-05
/home/pipe6/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli verify --date 2026-11-05
```

La verificación espera cuatro `Employee Checkin` y dos `Attendance` con estado `Present` para ese día. Conviene hacer los cuatro marcajes en un día sin otros registros de estos empleados ficticios.

### Conexión futura con HikCentral real

La configuración pública está en `hikcentral_bridge/hikcentral.env.example`. Copia sus variables, con valores reales, a `~/.config/hikcentral_bridge/hikcentral.env` dentro de Ubuntu y limita sus permisos a tu usuario (`chmod 600`). Nunca pongas la clave secreta en la página ni en `config.example.json`.

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
python3 -m hikcentral_bridge probe
```

`probe` prueba la firma y conectividad contra el endpoint de versión de OpenAPI. Mantiene TLS validado; para un certificado interno, indica un archivo CA con `HIKCENTRAL_CA_BUNDLE` y usa el nombre de host que figura en el certificado. Si HikCentral corre en Windows y WSL usa NAT, cambia `127.0.0.1` por la IP del host Windows y verifica el puerto HTTPS. El adaptador de lectura real requiere todavía validar la ruta, el body y la respuesta de registros originales con el Developer Guide correspondiente a OpenAPI 2.6.3. El endpoint `/artemis/api/attendance/v1/report` corresponde al reporte diario procesado y no crea marcajes.

## 1. Abrir Ubuntu desde Windows

Abre PowerShell en cualquier carpeta y ejecuta:

```powershell
wsl -d Ubuntu
```

Todos los comandos que siguen, hasta volver a PowerShell, se ejecutan dentro de Ubuntu.

## 2. Comprobar servicios y Bench

Dentro de Ubuntu:

```bash
test -d /home/pipe6/frappe/hikcentral-bench && echo "Bench encontrado"
test -x /home/pipe6/.local/bin/bench && echo "Bench CLI encontrado"
```

Si MariaDB o Redis no están activos, abre otra ventana de PowerShell y ejecuta:

```powershell
wsl -d Ubuntu -u root -- systemctl start mariadb redis-server
```

Vuelve a Ubuntu y arranca el Bench:

```bash
source /home/pipe6/.nvm/nvm.sh
cd /home/pipe6/frappe/hikcentral-bench
/home/pipe6/.local/bin/bench start
```

Mantén esta terminal abierta. El Bench inicia ERPNext, Redis del sitio, workers, scheduler y el servidor web.

## 3. Abrir ERPNext

Desde Windows abre:

```text
http://localhost:8000
```

Usuario:

```text
Administrator
```

La contraseña se encuentra en Ubuntu en:

```text
/home/pipe6/.config/hikcentral_bridge/admin.env
```

Para verla desde PowerShell:

```powershell
wsl -d Ubuntu -- cat /home/pipe6/.config/hikcentral_bridge/admin.env
```

## 4. Preparar los datos de la demo

Abre una segunda ventana de PowerShell y entra al repositorio dentro de Ubuntu:

```powershell
wsl -d Ubuntu
```

Dentro de Ubuntu ejecuta:

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
/home/pipe6/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli seed
```

Este comando prepara de forma idempotente:

- La compañía `HikCentral Demo`.
- El turno `HikCentral Demo 09-18`.
- Auto Attendance.
- Los empleados `HIK-DEMO-CDMX` y `HIK-DEMO-OAX`.
- El usuario técnico de integración.
- La zona horaria `America/Mexico_City`.

## 5. Reproducir los marcajes simulados

En la misma segunda ventana de Ubuntu:

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
python3 -m hikcentral_bridge hikcentral_bridge/fixtures/demo_events.json
```

La salida esperada contiene cuatro líneas con estado `sent` y nombres `EMP-CKIN-*`.

Los eventos se registran en:

```text
~/.local/share/hikcentral_bridge/events.sqlite3
```

Si ejecutas el mismo comando otra vez, los cuatro eventos deben aparecer como `skipped`. Esto confirma que no se duplican marcajes.

## 6. Procesar Auto Attendance

Después de enviar los cuatro marcajes:

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
/home/pipe6/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli finalize
```

La salida esperada contiene cuatro `Employee Checkin` y dos registros `Attendance`.

El comando actualiza `Last Sync of Checkin`, ejecuta el procesamiento del turno y comprueba que ambos empleados queden como `Present`.

## 7. Verificar la demo

```bash
/home/pipe6/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli verify
```

También puedes revisar los documentos desde ERPNext:

1. Abre `Employee Checkin`.
2. Filtra por los dispositivos `HIK-CDMX-01` y `HIK-OAX-01`.
3. Comprueba cuatro registros con tipo `IN`/`OUT`.
4. Abre `Attendance`.
5. Comprueba dos registros `Present` del turno `HikCentral Demo 09-18`.

## 8. Ejecutar pruebas técnicas

Desde Ubuntu:

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
python3 -m unittest discover -s hikcentral_bridge/tests -v
python3 -m hikcentral_bridge.tests.live_checks
```

Las pruebas negativas cubren empleado inexistente, dirección inválida, credenciales incorrectas y caída de red.

## 9. Reiniciar la demo desde cero

Este comando elimina los marcajes y asistencias ficticios del día seleccionado, incluidos los eventos de la página local. Conserva compañía, empleados y turno. Detén la página antes de ejecutarlo:

```bash
cd /mnt/c/Users/pipe6/Documents/erpnext
/home/pipe6/frappe/hikcentral-bench/env/bin/python -m hikcentral_bridge.site_cli reset-attempt
```

Después vuelve a ejecutar los pasos 5, 6 y 7.

## 10. Detener el entorno

En la terminal donde corre `bench start`, pulsa:

```text
Ctrl+C
```

Para cerrar Ubuntu y sus procesos desde PowerShell:

```powershell
wsl --shutdown
```

## Problemas frecuentes

### `bench` no se reconoce en PowerShell

Es normal. `bench` está instalado dentro de Ubuntu. Usa `wsl -d Ubuntu` o el comando completo `/home/pipe6/.local/bin/bench` dentro de Ubuntu.

### No llega el correo de verificación

El entorno local no tiene SMTP configurado. Entra con `Administrator` y la contraseña de `admin.env`; la demo no depende del correo.

### El evento aparece con hora actual

Comprueba que el usuario técnico conserve permiso de escritura de nivel 1 para el campo `time` de `Employee Checkin`. El comando `seed` configura ese permiso.

### No se genera `Attendance`

Comprueba que `bench start` siga activo y vuelve a ejecutar `finalize`. El turno debe tener Auto Attendance habilitado y `Last Sync of Checkin` debe estar después del final del turno.

### El puerto 13000 está ocupado

Ya existe otra instancia de Bench. Usa esa instancia y no ejecutes un segundo `bench start`, o detén la primera con `Ctrl+C` antes de iniciar otra.

