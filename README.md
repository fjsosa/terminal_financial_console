# Neon Quotes Terminal

Aplicacion de terminal multiplataforma (Windows, Linux, macOS) con interfaz estilo futurista/hacker y cotizaciones en tiempo real.

## Caracteristicas

- Interfaz TUI moderna con `Textual`
- Tabla principal con rotacion automatica de grupos definidos en `config.yml` (mixto crypto/stocks)
- Pausa inteligente de rotacion (60s) cuando hay actividad del usuario en tabla principal o news
- Navegacion manual de grupos con `←/→` y `<`/`>` (con wrap ciclico)
- Tabla de alertas (`ALERTAS`) con top 15 por variacion `24h %` (orden descendente)
- Cotizaciones crypto en vivo por WebSocket publico de Binance
- Cotizaciones de acciones via `yfinance` (refresh periodico)
- Columna `Spark` en tabla principal con evolucion en vivo por simbolo
- Columna ticker en formato `TICKER:NAME` (nombre truncado)
- Columna tipo compacta (`CRT` para crypto, `STK` para stock)
- Volumen compacto con sufijo `M` para valores grandes (ej. `150.00M`)
- Ticker tipo zocalo (derecha a izquierda) con crypto + stocks
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

Con simbolos personalizados:

```bash
python main.py --crypto-symbols BTCUSDT ETHUSDT SOLUSDT ADAUSDT --stock-symbols AAPL MSFT NVDA
```

Usando archivo de configuracion:

```bash
python main.py --config config.yml
```

Forzar zona horaria por parametro:

```bash
python main.py --tz America/Argentina/Buenos_Aires
```

Forzar idioma por parametro:

```bash
python main.py --lang es
```

## Configuracion

El archivo `config.yml` permite definir grupos mixtos (formato recomendado):

```yaml
timezone: "America/Argentina/Buenos_Aires"
language: "es"
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

Tambien se soporta el formato legacy con `crypto_symbols` y `stock_symbols` por compatibilidad.

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

Orden de prioridad (de menor a mayor):

1. `config.yml`
2. Variables de entorno (`NEON_TZ`, `NEON_LANG`, `NEON_CRYPTO_SYMBOLS`, `NEON_STOCK_SYMBOLS`)
3. Parametros CLI (`--tz`, `--lang`, `--crypto-symbols`, `--stock-symbols`)

Ejemplos de variables de entorno:

```bash
NEON_TZ=America/Argentina/Buenos_Aires ./run_neon_quotes.sh
NEON_LANG=es ./run_neon_quotes.sh
NEON_CRYPTO_SYMBOLS="BTCUSDT,ETHUSDT,SOLUSDT,ADAUSDT" ./run_neon_quotes.sh
NEON_STOCK_SYMBOLS="AAPL,MSFT,NVDA,AMZN" ./run_neon_quotes.sh
```

## Resolucion de Nombres de Simbolos

Al iniciar, la app carga nombres desde cache local y luego resuelve en background el nombre legible de cada ticker:

- `stock`: ejemplo `AAPL -> Apple Inc.`
- `crypto`: ejemplo `BTCUSDT -> Bitcoin` (toma el activo base del par e ignora el quote)

Comportamiento por origen de configuracion:

- Si los simbolos vienen de `config.yml` y falta `name`, la app busca el nombre y actualiza el `config.yml` para reutilizarlo en futuros arranques.
- Si los simbolos vienen por CLI/env, la app busca y asocia nombres solo en memoria (no modifica archivos).

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
- `r`: resetear buffers locales
- `n`: refrescar noticias manualmente
- `←` / `→`: grupo anterior/siguiente en tabla principal y tabla news (ciclico)
- `<` / `>`: grupo anterior/siguiente en tabla principal y tabla news (ciclico)
- `Enter`: abrir grafico del activo seleccionado (crypto o stock), con refresco en vivo
- `Enter` en tabla de noticias: copiar link de la noticia al portapapeles
- `t` (en modal): alternar timeframe entre 15m, 1h, 1d, 1w y 1mo
- `←` / `→` (en modal chart): ticker anterior/siguiente, atravesando grupos en forma ciclica
- `<` / `>` (en modal chart): ticker anterior/siguiente, atravesando grupos en forma ciclica
- `:` entrar a modo comando
- `Esc` salir de modo comando
- `1`: foco en BTCUSDT
- `2`: foco en ETHUSDT
- `3`: foco en SOLUSDT
- `a`: mostrar ayuda rapida en eventos

Comandos en modo comando:

- `:q` salir
- `:r` reset
- `:n` refresh news
- `:help` ayuda de comandos


Opcional (chart XY avanzado):

```bash
.venv/bin/pip install plotext
```

## Notas

- La fuente de mercado es Binance stream publico (`@ticker`), no requiere API key.
- La tabla de acciones usa Yahoo Finance via `yfinance`, refrescada cada 10 minutos.
- Esta version es un MVP, lista para extender con alertas y multiples proveedores.
