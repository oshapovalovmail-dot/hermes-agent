"""Owned, consent-seeded fixture; no operator home or network access."""
import os
import sys
from pathlib import Path
CORE = Path(os.environ['ATLAS_TEST_CORE']).resolve()
DELTA = Path(os.environ.get('ATLAS_TEST_DELTA', str(Path(__file__).resolve().parents[1] / 'source'))).resolve()
sys.path.insert(0, str(CORE))
import gateway
gateway.__path__.insert(0, str(DELTA / 'gateway'))
AUTHORITY = DELTA / 'gateway/session_authority.py'
