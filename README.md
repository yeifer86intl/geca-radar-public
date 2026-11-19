# GECA Radar — corrección del flujo Steam según el PDF

Esta versión corrige el componente Steam del proyecto entregado. La referencia
es GECA_RADAR_PRESENTACION_EJECUTIVA(4).pdf, páginas 2–4. No implementa Twitch,
una interfaz de decisiones, la cola humana ni el envío por correo. No se presenta
como implementación completa de todo el servicio descrito en la presentación.

## Regla y resultados

Un juego es elegible si Steam indica `coming_soon=true`, la consulta de ficha
fue correcta y su fecha está entre el corte menos 7 días y el corte, inclusive.
La fecha de lanzamiento puede ser un día, un año, un trimestre o desconocida.
No se exige un mínimo de reseñas ni una proporción de votos positivos.

Una propuesta requiere además una pregunta GECA explícita, registrada por appid.
Se verifican los candidatos antes de escoger hasta tres en orden de appid.
Este orden es operativo, no una valoración editorial. La persona decide qué analizar.
La caché conserva la fecha de consulta original y se refresca para los candidatos
con pregunta antes de generar el resumen.

- `maestro.csv`: todos los elegibles por lanzamiento, sin límite de tres.
- `maestro_completo.csv`: universo procesado, evidencia, reseñas y advertencias.
- `propuestas.csv`: de cero a tres propuestas con pregunta GECA.
- `resumen.md` y `resumen.json`: corte, alcance, reglas y resultados.
- Los Excel de catálogo, fichas y verificación mantienen su formato anterior.
- `estado/historial.sqlite`: observaciones con fecha, evidencia y alcance.

`candidato_recomendado` se conserva como alias de elegible por lanzamiento por
compatibilidad. No equivale a una recomendación editorial. `recepcion_favorable`
también se conserva como dato informativo heredado (30 reseñas y 80 % positivas),
pero no interviene en ningún filtro de candidatos ni propuestas.

## Instalar y ejecutar

Desde la carpeta que contiene `pyproject.toml`, con Python 3.10 o posterior:

```sh
python -m pip install -e ".[test]"
python -m pytest -q
python -m kedro run --pipeline radar
```

Para un recorrido pequeño: `python -m kedro run --pipeline radar --env prueba`.
La descarga real consulta Steam; las pruebas usan respuestas simuladas.

Antes de esperar propuestas, editar `conf/base/parameters_radar.yml`:

```yaml
radar:
  zona_horaria: America/Caracas
  max_edad_dias: 7
  max_propuestas: 3
  carpeta_estado: estado
  carpeta_salida: data/04_radar
  preguntas_geca:
    "APPID_REAL": "Pregunta editorial concreta que el analista quiere validar"
```

Sustituir APPID_REAL por el identificador numérico del juego. El archivo entregado
mantiene las preguntas vacías para no inventar interés editorial. Con preguntas
vacías habrá elegibles, pero cero propuestas finales.

## Alcance de descubrimiento

Se conserva la tienda de España (`pais: es`), se incluyen todas las plataformas
y se elimina el intervalo fijo de octubre/noviembre. Las fechas 1900–9999 son
límites técnicos amplios, no un horizonte editorial. Las fechas aproximadas se
incluyen expresamente. El estado de lanzamiento lo determina la ficha.

El buscador puede devolver fechas públicas desordenadas: eso ya no detiene el
recorrido. No se corta por encontrar una página posterior a la fecha límite.
Los errores de red, páginas repetidas y desajustes de paginación siguen controlados.

El valor inicial `max_paginas: 10` es un límite operativo diario (hasta 1.000
filas consultadas), no una regla del PDF ni una promesa de cobertura total.
Se puede aumentar o usar `null` para recorrer todo; descargar miles de fichas y
reseñas puede durar muchas horas y superar el tiempo permitido por GitHub Actions.
La presentación sitúa la ampliación del catálogo en la siguiente evolución.

Una captura parcial no invalida una ficha individual correcta y vigente.
El resumen lo advierte y `propuestas.csv` incluye `captura_completa`. No se afirma
haber analizado todo Steam. Las discrepancias entre fecha del buscador y ficha
son advertencias para el analista, no reglas nuevas de descarte.

## Cambios respecto del proyecto entregado

1. `src/steam_pipeline/radar.py`: regla de lanzamiento, reseñas informativas,
   selección tras verificar, captura parcial explícita, comparación de fechas
   normalizadas, fecha pasada basada en la ficha y evidencia en el resumen.
2. `src/steam_pipeline/descargas/steam_proximos_paginados.py`: no detener por
   desorden cronológico ni realizar corte temprano por fecha.
3. `conf/base/parameters_seleccion.yml`: incluir fechas aproximadas/desconocidas.
4. `conf/base/parameters_proximos.yml`: alcance sin intervalo fijo ni filtro Windows,
   y límite operativo explícito.
5. `conf/base/parameters_radar.yml`: eliminar horizonte no utilizado.
6. `pyproject.toml`: declarar openpyxl, requerido por las exportaciones existentes.
7. `.github/workflows/radar.yml`: 11:00 UTC corresponde a 07:00 Caracas.
8. Pruebas y esta documentación.

Los descargadores de fichas y reseñas no se reescribieron. Las respuestas brutas
siguen guardándose en estado; algunos archivos se sobrescriben al actualizar.
El historial SQLite no equivale a un archivo inmutable de todos los JSON originales.

## Validación

Ver `VALIDACION.txt` para el resultado real de las pruebas. No se hizo una descarga
en vivo ni se desplegó el workflow. Al aplicar la regla a los datos guardados del
28/10/2026 se conservan 567 elegibles de 568, con cero propuestas si no se añaden
preguntas GECA. Esto es un resultado histórico, no una evaluación actual.
