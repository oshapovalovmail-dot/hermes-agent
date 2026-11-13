"""Fixed private Mac business worker entrypoint; no arbitrary modules/commands."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from atlas_work_read.cli import main
if __name__=='__main__':main('worker')
