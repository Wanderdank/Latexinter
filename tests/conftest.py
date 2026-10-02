import sys
from pathlib import Path

# Los tests importan los paquetes del proyecto igual que app.py y cli.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
