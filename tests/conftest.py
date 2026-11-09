"""Configuración común de los tests: el código vive en la raíz del repositorio."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
