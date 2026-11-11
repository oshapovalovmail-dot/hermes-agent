"""Exit a real fixture producer after its delivery attempt is durably recorded."""
from pathlib import Path
import asyncio
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from gateway import delivery_ledger
from tests.gateway.test_delivery_ledger_producer import _Adapter, _event, _run


def main():
    delivery_ledger._db_path = lambda: Path(sys.argv[1])
    adapter = _Adapter()

    async def die_after_attempting(chat_id, content, reply_to=None, metadata=None):
        os._exit(37)

    adapter.send = die_after_attempting
    asyncio.run(_run(adapter, _event()))
    raise AssertionError("The crash injection never reached the real send")


if __name__ == "__main__":
    main()
