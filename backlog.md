# Neon Backlog

# Configuracion
Separar el config yml con configuraciones inherentes al usuario actual como:
Timezone, language
y 
stock_maps.json, que contienen configuraciones de:
calendarios
grupos de simbolos de stock/crypto
la idea es poder poder compartir un stockmap con otros usuarios con configuraciones pre seteadas para seguir, por ejemplo, acciones de distintos paises, el stockmap cargado puede ser indicado por parametros, mientras que el config no, siempre se carga desde config.yml-

# Ai Integration.
Intrgrar la IA al sistema a traves de un API o preferentemente usando codex o claude si esta disponible, evitando el pago de un api extra.

## Integración por Simbolo.
    Al ingresar a la pantalla de detalles del simbolo con enter (donde mostramos el chart) agregar una sección al final llamada AI Analisis.
    El contenido de esa sección será un analisis realizado por la IA donde debera tener en consideración
    - Las ultimas N velas semanales
    - los valores de los indicadores cargados y como pueden afectar a la acción dada.
    - Resumen de titulares de noticias y como pueden estos afectar al simbolo y a la industria a la que pertenece.
    - Analizar como pueden afectar los proximos eventos del calendario    
    - El reporte debe ser un analisis FODA.
        Analisis General
        Riesgos
        Oportunidades
        Fortalezas 
        Debilidades

## Descripción de eventos del calendario
    Buscar por cada evento del calendario su significado, que va a informar, cuales son las espectativas 
    y como puede afectar el mercado si las espectativas se cumplen como si no se cumplen.
    Esto lo podemos hacer con IA Integrada. 


## Alertas Inteligentes
    La IA debera definir por cada simbolo limites superiores e inferiores, 

## Analisis de eventos del calendario
    cada una hora, el sistema buscara noticias relacionadas a los eventos del calendario que ya finalizaron, o que ha pasado una hora desde su inicio, y armara un informe linkeado al evento del calendario. 
    El sistema debera identificar si el resultado de ese analisis afectará o no al mercado identificando riesgos y oportunidades generales.
    El informe sera reportado en pantalla como una noticia generada por el mismo sistema, fuente: "nq news".
    el usuario podra configurar una dirección de correo para que el sistema envie estos reportes via email. (ver como hacer esto.)

## Descripcion de los indicadores
    Asi como se busca la descripción de los simbolos, buscar y registrar la descripcion los indicadores, si la ia esta presente adjuntar una descripción de como afecta el indicador si sube o baja.

## Analisis de Evolucion de indicadores
    El valor de los indicadores se analizaran cada 1 hora identificando riesgos y oportinidades no solo teniendo en cuenta el valor actual sino la tendencia y los ultimos valores para las ultimos N velas diarias.
    Estos reportes tambien seran reportados como noticias generadas por el sismte "nq news".

## Comando para activar preguntas a la IA.
:i inteligencia artificial

Se agregara como contexto a la pregunta:
1) guardas para evitar preguntas fuera de contexto o peligrosas
2) valor actual de todos los simbolos e indicadores
3) Ultimas noticias cargadas en el sistema.
4) se puede exponer al LLM una serie de tools para:
   Obtener los ultimos N velas diarias de un valor o de un indice.

