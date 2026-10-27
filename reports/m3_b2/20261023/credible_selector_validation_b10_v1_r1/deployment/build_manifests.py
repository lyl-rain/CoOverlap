"""Use the single root freeze_package.py builder; never start a model."""
from pathlib import Path
import runpy
if __name__=='__main__':runpy.run_path(str(Path(__file__).resolve().parents[1]/'freeze_package.py'),run_name='__main__')
