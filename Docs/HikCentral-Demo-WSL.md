# Demo HikCentral → ERPNext/Frappe HR

Guía para ejecutar la demo local desde Windows, pasando a Ubuntu mediante WSL.

La demo reproduce cuatro marcajes simulados de HikCentral, los envía a Frappe HR y genera dos registros de `Attendance` mediante Auto Attendance.

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
source /home/pipe6/.config/hikcentral_bridge/erpnext.env
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

Este comando elimina únicamente los cuatro marcajes y las dos asistencias ficticias de la demo. Conserva compañía, empleados y turno:

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

