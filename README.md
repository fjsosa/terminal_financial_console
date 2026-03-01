# Neon Quotes Terminal

Aplicacion de terminal multiplataforma (Windows, Linux, macOS) con interfaz estilo futurista/hacker y cotizaciones en tiempo real.

## Caracteristicas

- Interfaz TUI moderna con `Textual`
- Tabla principal con rotacion automatica de grupos definidos en `config.yml` (mixto crypto/stocks)
- Pausa inteligente de rotacion (60s) cuando hay actividad del usuario en tabla principal o news
- Navegacion manual de grupos con `←/→` y `<`/`>` (con wrap ciclico)
- Tabla de alertas (`ALERTAS`) con top 15 por variacion `24h %` (orden descendente)
- Panel de indicadores globales con grupos configurables y rotacion automatica/manual
- Cotizaciones crypto en vivo por WebSocket publico de Binance
- Cotizaciones de acciones via `yfinance` (refresh periodico)
- Columna `Spark` en tabla principal con evolucion en vivo por simbolo
- Columna ticker en formato `TICKER:NAME` (nombre truncado)
- Columna tipo compacta (`CRT` para crypto, `STK` para stock)
- Volumen compacto con sufijo `M` para valores grandes (ej. `150.00M`)
- Zocalo inferior tipo TV (derecha a izquierda) con 2 modos automaticos:
  - `quotes`: solo simbolos presentes en la tabla `ALERTAS`
  - `news`: 10 noticias mas nuevas en formato `[fuente: edad] titular`
  - Intercalado de `BREAKING NEWS` con efecto titilante en color de alerta
  - Rotacion de modo: `quotes` 1 minuto y `news` 3 minutos
- Panel de eventos
- Panel de noticias multi-feed Finviz (v=3, v=4, v=5, v=6 y tabla News) con refresco cada 10 minutos
- Descarga de las ultimas 21 noticias por cada feed de Finviz
- Rotacion automatica de noticias en grupos de 7 cada 10 segundos
- Graficos por simbolo (desde tabla principal y alertas) con:
  - Velas OHLC
  - Grafico de live updates
  - Timeframes `15m`, `1h`, `1d`, `1w`, `1mo`
- Carga dinamica de historicos por timeframe para llenar el viewport del chart
- Scroll vertical en modal de chart para terminales chicas
- En modo chart, `←/→` y `<`/`>` navegan al ticker anterior/siguiente (ciclico entre grupos)
- Lazy loading por grupos visibles y carga de historicos en background
- Precarga historica optimizada al arranque (grupo visible) y completado on-demand en charts
- Cache local con TTL en `~/.cache/neon_quotes/` para historicos y nombres
- Resolucion de nombres en background (UI no bloqueante)
- Refresco de cotizaciones por ventana/grupo activo (no universo completo por ciclo)
- Modal de arranque con animacion y progreso de carga de historicos
- Reconexion automatica ante desconexiones
- Atajos de teclado

## Requisitos

- Python 3.10+
- Internet para consumir el stream en vivo

## Instalacion

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows PowerShell
pip install -r requirements.txt
```

## Uso

```bash
python main.py
```

## Uso Multi-Instancia (2 mercados en paralelo)

Puedes ejecutar la app en dos terminales distintas con configuraciones diferentes para monitorear mercados en paralelo.

Ejemplo de escenario:

- Terminal A: `config_name: "Acciones USA"` con tickers de EEUU.
- Terminal B: `config_name: "Acciones Argentina"` con tickers de Argentina.

Como la app toma configuracion desde `config.yml` del directorio actual, la forma recomendada es usar dos carpetas de trabajo:

```bash
# Terminal A
cp -r tfz tfz-usa
cd tfz-usa
# editar config.yml para mercado USA
python main.py

# Terminal B
cp -r tfz tfz-ar
cd tfz-ar
# editar config.yml para mercado Argentina
python main.py
```

En cada instancia veras en el header el `config_name`, lo que ayuda a identificar rapidamente que mercado estas mirando.

Ejemplo practico con configuraciones separadas:

```bash
# preparar dos configuraciones
cp config.yml config-usa.yml
cp config.yml config-ar.yml

# editar cada archivo:
# - config-usa.yml -> config_name: "Acciones USA"
# - config-ar.yml  -> config_name: "Acciones Argentina"
```

Ejemplo de arranque en dos terminales (misma base de codigo, directorios separados):

```bash
# Terminal A (USA)
cp -r tfz tfz-usa
cd tfz-usa
cp config-usa.yml config.yml
python main.py

# Terminal B (Argentina)
cp -r tfz tfz-ar
cd tfz-ar
cp config-ar.yml config.yml
python main.py
```

Alternativa rapida en una sola carpeta (no paralela, para cambiar de mercado antes de iniciar):

```bash
cp config-usa.yml config.yml && python main.py
# cerrar
cp config-ar.yml config.yml && python main.py
```

## Configuracion

El archivo `config.yml` permite definir grupos mixtos (formato recomendado):

```yaml
config_name: "Activos USA y Criptomonedas"
timezone: "America/Argentina/Buenos_Aires"
language: "es"
quick_actions:
  "1": "BTCUSDT"
  "2": "AAPL"
  "3": "^VIX"
indicator_groups:
  - name: "Indices USA"
    symbols:
      - symbol: "^DJI"
        type: stock
      - symbol: "^IXIC"
        type: stock
      - symbol: "^GSPC"
        type: stock
  - name: "Riesgo y Dolar"
    symbols:
      - symbol: "^VIX"
        type: stock
      - symbol: "DX-Y.NYB"
        type: stock
      - symbol: "^TNX"
        type: stock
groups:
  - name: "Crypto"
    symbols:
      - symbol: BTCUSDT
        type: crypto
      - symbol: ETHUSDT
        type: crypto
      - symbol: SOLUSDT
        type: crypto
  - name: "Tecnologia"
    symbols:
      - symbol: AAPL
        type: stock
      - symbol: MSFT
        type: stock
      - symbol: NVDA
        type: stock
```

Opcionalmente cada simbolo puede incluir `name`:

```yaml
groups:
  - name: "Crypto"
    symbols:
      - symbol: BTCUSDT
        type: crypto
        name: Bitcoin
  - name: "Tecnologia"
    symbols:
      - symbol: AAPL
        type: stock
        name: Apple Inc.
```

Fuente de configuracion:

- La app toma toda la configuracion desde `config.yml`.
- No se usan variables de entorno ni parametros CLI para sobrescribir simbolos, timezone o idioma.
- `indicator_groups` define los grupos del panel de indicadores (nombre + lista de simbolos).
- `config_name` define el nombre global de la configuracion y se muestra en el header superior.

## Resolucion de Nombres de Simbolos

Al iniciar, la app carga nombres desde cache local y luego resuelve en background el nombre legible de cada ticker:

- `stock`: ejemplo `AAPL -> Apple Inc.`
- `crypto`: ejemplo `BTCUSDT -> Bitcoin` (toma el activo base del par e ignora el quote)

Comportamiento por origen de configuracion:

- Si los simbolos vienen de `config.yml` y falta `name`, la app busca el nombre y actualiza el `config.yml` para reutilizarlo en futuros arranques.

Si una fuente externa no responde o no encuentra el nombre, la app usa fallback:

- stocks: el propio ticker
- crypto: el activo base del par

## Cache Local

Se usa cache local en:

- `~/.cache/neon_quotes/history/` para historicos por simbolo
- `~/.cache/neon_quotes/names.json` para nombres resueltos

La app usa la cache para render inicial rapido y refresca en segundo plano.

## Atajos

- `q`: salir
- `←` / `→`: grupo anterior/siguiente en tabla principal y tabla news (ciclico)
- `<` / `>`: grupo anterior/siguiente en tabla principal y tabla news (ciclico)
- `←` / `→` en tabla de indicadores: grupo anterior/siguiente (ciclico)
- `<` / `>` en tabla de indicadores: grupo anterior/siguiente (ciclico)
- `Enter`: abrir grafico del activo seleccionado (crypto o stock), con refresco en vivo
- `Enter` en tabla de noticias: copiar link de la noticia al portapapeles
- `t` (en modal): alternar timeframe entre 15m, 1h, 1d, 1w y 1mo
- `←` / `→` (en modal chart): ticker anterior/siguiente, atravesando grupos en forma ciclica
- `<` / `>` (en modal chart): ticker anterior/siguiente, atravesando grupos en forma ciclica
- `:` entrar a modo comando
- `F2`: entrar a modo comando
- `Esc` salir de modo comando
- `Tab` (en modo comando): autocompletar comando/simbolo/grupo
- `?`: abrir panel de ayuda (README) con scroll
- `Ctrl+P` / `⌃P`: abrir command palette de Textual
- `1`: foco en simbolo configurado en `quick_actions["1"]`
- `2`: foco en simbolo configurado en `quick_actions["2"]`
- `3`: foco en simbolo configurado en `quick_actions["3"]`

Las teclas `1`, `2`, `3` se pueden reasignar desde `config.yml` en `quick_actions`.

Comandos en modo comando:

- `:q` salir
- `:r` reset
- `:n` refresh news
- `:?` abrir panel de ayuda (README)
- `:add <symbol> <crypto|stock> <group> [name]` agregar ticker a un grupo existente
- `:del <symbol>` eliminar ticker de su grupo
- `:mv <symbol> <group>` mover ticker entre grupos
- `:edit <symbol> group=<name> type=<crypto|stock> name=<label>` editar metadatos y/o mover ticker

Ejemplos:

- `:add TSLA stock Tecnologia "Tesla Inc."`
- `:del ADAUSDT`
- `:mv AAPL Finanzas`
- `:edit BTCUSDT group=Crypto name="Bitcoin"`

Notas de edicion:

- Los cambios se aplican en caliente (sin reiniciar) y se persisten en `config.yml`.
- Si se elimina un simbolo asignado en `quick_actions`, la tecla se limpia automaticamente.
- `group` debe existir previamente para `add/mv/edit`.
- Si el nombre del grupo o `name` tiene espacios, usar comillas (ej: `"Consumo basico"`).

Autocompletado en modo comando (`Tab`):

- Completa comandos base: `q`, `r`, `n`, `?`, `add`, `del`, `mv`, `edit`.
- En `:del`, `:mv`, `:edit` completa símbolos configurados.
- En `:add` completa el tipo (`crypto`, `stock`) y luego el nombre de grupo.
- En `:mv` completa el grupo destino.
- En `:edit` completa claves de edicion (`group=`, `type=`, `name=`).
- En `:add` y `:mv`, al volver a presionar `Tab` sobre el argumento de grupo, cicla por los grupos disponibles (case-insensitive).
- En `:edit`, si estas editando `group=...`, el ciclo por grupos aplica igual.
- Si hay multiples coincidencias sin prefijo comun suficiente, muestra sugerencias en el panel de eventos.

## Zocalo Inferior

El zocalo rota automaticamente entre 2 modos:

- `quotes`: muestra precios y variacion de los simbolos en `ALERTAS` durante 1 minuto
- `news`: muestra titulares recientes y marcador `BREAKING NEWS` intercalado durante 3 minutos

Formato en modo `news`:

- `[source: age] headline` (mismo formato base que la tabla de noticias)


Opcional (chart XY avanzado):

```bash
.venv/bin/pip install plotext
```

## Notas

- La fuente de mercado es Binance stream publico (`@ticker`), no requiere API key.
- La tabla de acciones usa Yahoo Finance via `yfinance`, refrescada cada 10 minutos.
- Esta version es un MVP, lista para extender con alertas y multiples proveedores.
