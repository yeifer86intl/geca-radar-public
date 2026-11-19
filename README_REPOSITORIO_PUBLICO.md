# GECA Radar — un único repositorio público

Esta entrega usa **un solo repositorio público** para código, histórico en Excel y checkpoints.
El catálogo puede ser leído por cualquiera. Revisa permisos/licencias de los datos antes de publicarlo.

## Primer arranque
1. Crea un repositorio **público vacío**, por ejemplo `geca-radar-public`.
2. Sube todo el contenido de la carpeta `geca-radar/` a la raíz del repositorio.
   **NO subas la carpeta contenedora `geca-radar/` como carpeta extra.**
3. Ve a Settings → Actions → General → Workflow permissions y selecciona
   **Read and write permissions**. El workflow tiene `contents: write`.
4. En Actions → GECA Radar diario, pulsa **Run workflow**, marca
   `inicializar_desde_respaldo = true` **solo una vez** y ejecuta en `main`.
5. El primer arranque utiliza `bootstrap/geca_steam_historico.xlsx`, con 4.323 AppID,
   22.283 observaciones y 21 ejecuciones. Al terminar publica el release `estado-geca`
   con el Excel actualizado y el artifact `geca-steam-catalog` para Twitch.
6. En las ejecuciones siguientes deja `inicializar_desde_respaldo = false`.
   Si falta el release o es ilegible, el job **falla sin reiniciar el histórico**.

## Respaldos y actualizaciones
- Histórico de estado: release público `estado-geca`, archivo `geca_steam_historico.xlsx`.
- Copias previas inmutables: releases `respaldo-geca-<run_id>`.
- Avances de fichas: rama `geca-checkpoints`, en bloques comprimidos.
- Los checkpoints conservan la fecha real de cada consulta y se revalidan según antigüedad
  y cambios observables de nombre/fecha; `parameters_fichas.yml` utiliza `actualizar: false`.
- La ventana de prueba es 3 meses (`conf/base/parameters_proximos.yml`), configurable.
  El listado no tiene límite artificial de páginas (`max_paginas: null`).
- `geca-steam-catalog` sigue publicándose para compatibilidad con `geca_twitch`.
  **Cambia su parámetro --repo al nombre del nuevo repositorio**, por ejemplo
  `yeifer86intl/geca-radar-public`, y verifica que use la hoja `seguimiento_activo`.
- Los datos `2027`/`Próximamente` permanecen en el histórico como fechas imprecisas;
  no se consideran estrenos con fecha exacta dentro de la ventana.

## Importante
- Es un flujo reanudable **para fichas**, no hace reanudación de páginas de búsqueda.
- Si un job supera 330 minutos todavía puede cancelarse; las fichas publicadas
  en la rama técnica se podrán recuperar en el siguiente intento.
- Los logs de Python/pytest deben quedar verdes antes de publicar.
- **No borres el histórico anterior** antes de verificar las cinco hojas, cifras y copias.
- Exponer un repositorio como público también expone su Excel y checkpoints.
- No guardes claves ni credenciales en el repositorio; utiliza GitHub Secrets.
