# Neon Quotes Terminal

Aplicacion de terminal multiplataforma (Windows, Linux, macOS) con interfaz estilo futurista/hacker y cotizaciones en tiempo real.

## Caracteristicas

- Interfaz TUI moderna con `Textual`
- Cotizaciones en vivo por WebSocket publico de Binance
- Tabla de crypto con precio, variacion 24h, volumen y sparkline
- Tabla separada de acciones via `yfinance` (refresh cada 10 minutos)
- Ticker tipo zocalo (derecha a izquierda) con crypto + stocks
- Panel de eventos
- Panel de noticias multi-feed Finviz (v=3, v=4, v=5, v=6 y tabla News) con refresco cada 10 minutos
- Descarga de las ultimas 21 noticias por cada feed de Finviz
- Rotacion automatica de noticias en grupos de 7 cada 10 segundos
- Precarga historica al inicio (N cotizaciones por simbolo) para graficos completos
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

## Configuracion

El archivo `config.yml` permite definir:

```yaml
timezone: "America/Argentina/Buenos_Aires"
crypto_symbols:
  - BTCUSDT
  - ETHUSDT
  - SOLUSDT
stock_symbols:
  - AAPL
  - MSFT
  - NVDA
```

Orden de prioridad (de menor a mayor):

1. `config.yml`
2. Variables de entorno (`NEON_TZ`, `NEON_CRYPTO_SYMBOLS`, `NEON_STOCK_SYMBOLS`)
3. Parametros CLI (`--tz`, `--crypto-symbols`, `--stock-symbols`)

Ejemplos de variables de entorno:

```bash
NEON_TZ=America/Argentina/Buenos_Aires ./run_neon_quotes.sh
NEON_CRYPTO_SYMBOLS="BTCUSDT,ETHUSDT,SOLUSDT,ADAUSDT" ./run_neon_quotes.sh
NEON_STOCK_SYMBOLS="AAPL,MSFT,NVDA,AMZN" ./run_neon_quotes.sh
```

## Atajos

- `q`: salir
- `r`: resetear buffers locales
- `n`: refrescar noticias manualmente
- `Enter`: abrir grafico del activo seleccionado (crypto o stock), con refresco en vivo
- `Enter` en tabla de noticias: copiar link de la noticia al portapapeles
- `t` (en modal): alternar timeframe entre 15m y 1h
- `1`: foco en BTCUSDT
- `2`: foco en ETHUSDT
- `3`: foco en SOLUSDT
- `a`: mostrar ayuda rapida en eventos


Opcional (chart XY avanzado):

```bash
.venv/bin/pip install plotext
```

## Notas

- La fuente de mercado es Binance stream publico (`@ticker`), no requiere API key.
- La tabla de acciones usa Yahoo Finance via `yfinance`, refrescada cada 10 minutos.
- Esta version es un MVP, lista para extender con alertas y multiples proveedores.
