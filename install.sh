#!/bin/sh
# Installazione CLI DesignChecker (macOS / Linux) — da eseguire UNA volta:
#   bash install.sh
# Dopo: `designchecker ...` (o `dck ...`) funziona da qualsiasi cartella,
# senza mai attivare il venv a mano.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "1/5  Ambiente virtuale…"
if [ ! -d "$DIR/.venv" ]; then
  python3 -m venv "$DIR/.venv"
fi

echo "2/5  Dipendenze…"
"$DIR/.venv/bin/python3" -m pip install --quiet --upgrade pip
"$DIR/.venv/bin/python3" -m pip install --quiet pyyaml

echo "3/5  Comando globale in ~/.local/bin…"
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/designchecker" <<EOF
#!/bin/sh
# Wrapper DesignChecker: usa il Python del venv senza attivarlo.
PYTHONPATH="$DIR" exec "$DIR/.venv/bin/python3" -m designchecker "\$@"
EOF
chmod +x "$HOME/.local/bin/designchecker"
# Alias corto: dck (NON "dc": su Unix dc e' la calcolatrice da terminale)
ln -sf "$HOME/.local/bin/designchecker" "$HOME/.local/bin/dck"

echo "4/5  PATH…"
case ":$PATH:" in
  *":$HOME/.local/bin:"*)
    echo "     ~/.local/bin gia' nel PATH ✓" ;;
  *)
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"
    echo "     Aggiunto ~/.local/bin al PATH in ~/.zshrc"
    echo "     → apri un NUOVO terminale (o esegui: source ~/.zshrc)" ;;
esac

echo "5/5  Parser TSX (per 'dck import code')…"
if command -v node >/dev/null 2>&1; then
  if [ ! -d "$DIR/tools/node_modules/@babel/parser" ]; then
    if (cd "$DIR/tools" && npm install --no-bin-links); then
      echo "     @babel/parser installato ✓"
    else
      echo "     ⚠ npm install fallito: 'dck import code' non funzionera' finche' non risolvi."
      echo "       Riprova con: cd $DIR/tools && npm install"
    fi
  else
    echo "     @babel/parser pronto ✓"
  fi
else
  echo "     Node.js non trovato: 'dck import code' lo richiede (lo stesso Node di Expo)."
  echo "     Installa Node e poi esegui: cd $DIR/tools && npm install"
fi

echo ""
echo "✓ Installazione completata. Prova: designchecker version"
