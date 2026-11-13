"""Fixed isolated Mac source dispatcher; no polling without config."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'native'),str(root)] if (root/'native').is_dir() else [str(root)]
from atlas_native_bridge.edge_cli import main
if __name__=='__main__':main()
