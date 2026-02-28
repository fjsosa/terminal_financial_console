#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV_DIR="$ROOT_DIR/.venv"

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s' "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s' "python"
    return 0
  fi
  return 1
}

ensure_venv() {
  PYTHON_BIN=$(find_python) || {
    echo "Error: no se encontro python ni python3 en PATH." >&2
    exit 1
  }

  if [ ! -d "$VENV_DIR" ]; then
    echo "Creando entorno virtual en $VENV_DIR..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi
}

resolve_venv_python() {
  if [ -x "$VENV_DIR/bin/python" ]; then
    printf '%s' "$VENV_DIR/bin/python"
    return 0
  fi
  if [ -x "$VENV_DIR/Scripts/python.exe" ]; then
    printf '%s' "$VENV_DIR/Scripts/python.exe"
    return 0
  fi
  return 1
}

ensure_venv
VENV_PYTHON=$(resolve_venv_python) || {
  echo "Error: no se encontro el ejecutable de Python del entorno virtual." >&2
  exit 1
}

ensure_pip() {
  if "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
    return 0
  fi
  echo "pip no esta disponible en el entorno virtual. Intentando repararlo..."
  if ! "$VENV_PYTHON" -m ensurepip --upgrade >/dev/null 2>&1; then
    echo "Error: no se pudo instalar pip con ensurepip." >&2
    echo "Recomendacion: instala python3-venv/python3-pip y vuelve a ejecutar el script." >&2
    exit 1
  fi
}

ensure_pip

has_runtime_deps() {
  "$VENV_PYTHON" -c "import textual, websockets, yfinance" >/dev/null 2>&1
}

echo "Instalando/actualizando dependencias..."
if ! "$VENV_PYTHON" -m pip install -r "$ROOT_DIR/requirements.txt"; then
  if has_runtime_deps; then
    echo "Advertencia: no se pudieron actualizar dependencias por red, usando las ya instaladas."
  else
    echo "Error: no se pudieron instalar dependencias y no hay paquetes previos disponibles." >&2
    echo "Verifica conectividad DNS/Internet e intenta de nuevo." >&2
    exit 1
  fi
fi

echo "Iniciando Neon Quotes Terminal..."
exec "$VENV_PYTHON" "$ROOT_DIR/main.py" "$@"
