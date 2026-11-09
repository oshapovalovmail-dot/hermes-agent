"""Suggested dedicated-image launcher; the parent installer owns final wiring."""
import json
import os
from pathlib import Path
import sys


def main():
    # Do this before importing OpenViking, whose loggers can initialize config.
    args = sys.argv[1:]
    config = None
    for i, arg in enumerate(args):
        if arg == '--config' and i + 1 < len(args):
            if config is not None:
                raise ValueError('Exactly one --config is required')
            config = args[i + 1]
        elif arg.startswith('--config='):
            if config is not None:
                raise ValueError('Exactly one --config is required')
            config = arg.split('=', 1)[1]
        if arg.startswith('--workers=') and arg != '--workers=1':
            raise ValueError('Exact adapter launcher requires one worker')
        if arg == '--workers' and (i + 1 == len(args) or args[i + 1] != '1'):
            raise ValueError('Exact adapter launcher requires one worker')
    if not config or not Path(config).is_absolute() or not Path(config).is_file():
        raise ValueError('Explicit absolute existing --config is required')
    os.environ['OPENVIKING_CONFIG_FILE'] = config
    os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
    # Reject a config that would silently discard bytes before exact chunking.
    from ov_exact import EXACT_INPUT_SENTINEL, install
    embedding = json.loads(Path(config).read_text())['embedding']
    if embedding.get('max_input_tokens') != EXACT_INPUT_SENTINEL:
        raise ValueError('embedding.max_input_tokens must be exact adapter sentinel')
    if embedding.get('sparse') or embedding.get('hybrid'):
        raise ValueError('Dedicated FRIDA image requires dense-only embeddings')
    dense = embedding['dense']
    expected = {'provider': 'openai', 'model': 'frida', 'dimension': 1536,
                'encoding_format': 'float'}
    if any(dense.get(k) != v for k, v in expected.items()):
        raise ValueError('Embedding contract does not match dedicated FRIDA image')
    install(os.environ['OV_FRIDA_TOKENIZER_FILE'], os.environ['OV_FRIDA_TOKENIZER_SHA256'])
    from openviking_cli.server_bootstrap import main as native_main
    if not any(a == '--workers' or a.startswith('--workers=') for a in args):
        sys.argv.extend(['--workers', '1'])
    return native_main()


if __name__ == '__main__':
    main()
