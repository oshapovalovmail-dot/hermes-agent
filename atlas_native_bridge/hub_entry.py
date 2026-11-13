"""Fixed isolated source dispatcher; never selects ambient modules."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from atlas_native_bridge.hub import main
if __name__=='__main__':main()
