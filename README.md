# Neon Quotes Terminal

Aplicacion de terminal multiplataforma (Windows, Linux, macOS) con interfaz estilo futurista/hacker y cotizaciones en tiempo real.

## Caracteristicas

- Interfaz TUI moderna con `Textual`
- Cotizaciones en vivo por WebSocket publico de Binance
- Tabla de watchlist con precio, variacion 24h, volumen y sparkline
- Ticker animado y panel de eventos
- Panel de noticias crypto (Finviz) con refresco cada 10 minutos
- Precarga historica al inicio (N cotizaciones por simbolo) para graficos completos
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
python main.py --symbols BTCUSDT ETHUSDT SOLUSDT ADAUSDT
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
symbols:
  - BTCUSDT
  - ETHUSDT
  - SOLUSDT
```

Orden de prioridad (de menor a mayor):

1. `config.yml`
2. Variables de entorno (`NEON_TZ`, `NEON_SYMBOLS`)
3. Parametros CLI (`--tz`, `--symbols`)

Ejemplos de variables de entorno:

```bash
NEON_TZ=America/Argentina/Buenos_Aires ./run_neon_quotes.sh
NEON_SYMBOLS="BTCUSDT,ETHUSDT,SOLUSDT,ADAUSDT" ./run_neon_quotes.sh
```

## Atajos

- `q`: salir
- `r`: resetear buffers locales
- `n`: refrescar noticias manualmente
- `Enter`: abrir grafico del par seleccionado (incluye velas 15m y refresco en vivo)
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
- Esta version es un MVP, lista para extender con alertas y multiples proveedores.
