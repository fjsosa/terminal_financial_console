# Specifications Update UI

## 1. Objetivo

Definir una actualización de UX/UI que agregue capacidades de comando e integración futura con IA sin degradar la experiencia actual para usuarios avanzados de Linux.

## 2. Principios de Diseño

1. No romper flujo actual de teclado.
2. Priorizar acciones de una tecla para operaciones frecuentes.
3. Agregar capacidades de comando en modo progresivo, no disruptivo.
4. Mantener comportamiento predecible por foco (tabla crypto, tabla stocks, tabla news, modal chart).
5. Configuración clara, validable y editable por humanos.

## 3. Requisitos Funcionales

### 3.1 Interacción por teclado

1. Mantener atajos existentes:
   - `q` salir
   - `r` reset
   - `n` refrescar noticias
   - `Enter` abrir chart/copiar link según tabla enfocada
   - `t` cambiar timeframe dentro del modal de chart
2. Agregar modo comando iniciado con `:`, sin reemplazar atajos directos.
3. El modo comando debe:
   - Mostrar prompt visible en status line.
   - Permitir cancelar con `Esc`.
   - Ejecutar comando solo con `Enter`.
4. Comandos iniciales a soportar (v1):
   - `:q`
   - `:r`
   - `:n`
   - `:help`
5. Comandos de gestión de tickers (`add`, `edit`, `remove`) quedan definidos pero **no obligatorios en v1**.

### 3.2 Status line

1. Mantener footer funcional para hints de bindings.
2. Agregar status line superior o inferior (sin bloquear footer actual) con:
   - Estado global (`normal` / `command`)
   - Mensaje corto contextual
3. En modo comando, mostrar entrada actual (`:...`) y estado de validación básica.

### 3.3 Tabla principal de mercado

1. Mantener dos tablas visibles:
   - `crypto_quotes`
   - `stock_quotes`
2. No renombrar `stock_quotes` a `alerts` hasta existir funcionalidad real de alertas.
3. No forzar rotación automática de grupos de tickers en tablas de mercado en v1.

### 3.4 Noticias

1. Mantener panel/tabla de noticias con rotación por grupos.
2. Mantener soporte de copiar link con `Enter` en `news_table`.
3. Mantener encabezado por categoría (`CRYPTO NEWS`, `STOCKS NEWS`, etc.).

### 3.5 Charts

1. Mantener modal de chart unificado para crypto y stocks.
2. Mantener refresh en vivo mientras el modal esté abierto.
3. Mantener toggle de timeframe (`15m` / `1h`) con tecla `t`.

## 4. Integración IA (Fase posterior)

### 4.1 Alcance

1. Definir integración opcional con CLI local (`codex`, `claude`) sin dependencia obligatoria de API paga.
2. Si no hay CLI disponible, ofrecer fallback manual (copiar snapshot/prompt).

### 4.2 No incluir en esta entrega

1. No implementar todavía panel IA en UI.
2. No ejecutar comandos externos automáticamente sin confirmación explícita de diseño.

## 5. Configuración

### 5.1 Formato

1. Mantener `config.yml` como fuente principal.
2. Mantener precedencia:
   - `config.yml`
   - variables de entorno
   - argumentos CLI
3. Estructura mínima:
   - `timezone`
   - `crypto_symbols`
   - `stock_symbols`

### 5.2 Validación

1. Validar campos al iniciar y reportar errores en `events`.
2. Evitar typos en claves (p. ej. `tickers`, no `tikers`).

## 6. Requisitos de Usabilidad (Linux avanzado)

1. Acciones frecuentes en una tecla.
2. Comandos tipados disponibles, pero opcionales.
3. No ocultar datos críticos por carruseles automáticos en tablas de mercado.
4. Comportamiento consistente de foco y `Enter`.
5. `:help` siempre disponible para discoverability.

## 7. Criterios de Aceptación

1. La app conserva todos los atajos actuales sin regresión.
2. El modo comando se activa con `:` y sale con `Esc`.
3. `:q`, `:r`, `:n`, `:help` funcionan correctamente.
4. El footer/status line deja claro el modo actual.
5. Charts y noticias mantienen funcionalidad actual.
6. No se introducen bloqueos de UI ni pérdida de rendimiento perceptible.

## 8. Fuera de Alcance (por ahora)

1. CRUD completo de tickers con formularios TUI.
2. Sistema de alertas real.
3. Integración IA productiva con ejecución de análisis automática.
4. Cambios de proveedor de datos no estabilizados.

