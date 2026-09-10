#!/bin/sh
# Installazione CLI DesignChecker (macOS / Linux) — da eseguire UNA volta:
#   bash install.sh
# Dopo: `designchecker ...` (o `dc ...`) funziona da qualsiasi cartella,
# senza mai attivare il venv a mano.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "1/4  Ambiente virtuale…"
if [ ! -d "$DIR/.venv" ]; then
  python3 -m venv "$DIR/.venv"
fi

echo "2/4  Dipendenze…"
"$DIR/.venv/bin/python3" -m pip install --quiet --upgrade pip
"$DIR/.venv/bin/python3" -m pip install --quiet pyyaml

echo "3/4  Comando globale in ~/.local/bin…"
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/designchecker" <<EOF
#!/bin/sh
# Wrapper DesignChecker: usa il Python del venv senza attivarlo.
PYTHONPATH="$DIR" exec "$DIR/.venv/bin/python3" -m designchecker "\$@"
EOF
chmod +x "$HOME/.local/bin/designchecker"
ln -sf "$HOME/.local/bin/designchecker" "$HOME/.local/bin/dc"

echo "4/4  PATH…"
case ":$PATH:" in
  *":$HOME/.local/bin:"*)
    echo "     ~/.local/bin gia' nel PATH ✓" ;;
  *)
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"
    echo "     Aggiunto ~/.local/bin al PATH in ~/.zshrc"
    echo "     → apri un NUOVO terminale (o esegui: source ~/.zshrc)" ;;
esac

echo ""
echo "✓ Installazione completata. Prova: designchecker version"
