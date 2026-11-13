"""Minimal interpreter launcher, not an agent or a policy/security mechanism.

Keep -I/-S semantics: no cwd, user site, .pth, startup hooks or PYTHONPATH.
Only the immutable, image-owned package directory is added explicitly.
"""
import sys

sys.path.insert(0, '/opt/atlas/python')
sys.dont_write_bytecode = True
args = sys.argv[1:]
while args and args[0] in ('-I', '-S', '-B', '-E', '-s', '-P', '-u'):
    args.pop(0)
if args[:1] == ['-c'] and len(args) >= 2:
    code = args[1]
    sys.argv = ['-c'] + args[2:]
    exec(compile(code, '<auxiliary>', 'exec'), {'__name__': '__main__', '__package__': None})
elif args and not args[0].startswith('-'):
    script = args[0]
    sys.argv = args
    with open(script, 'rb') as stream:
        code = stream.read()
    exec(compile(code, script, 'exec'), {'__name__': '__main__', '__file__': script, '__package__': None})
elif args[:1] in (['--version'], ['-V']):
    print(sys.version)
else:
    raise SystemExit('atlas-python: use [-I] [-S] -c CODE or SCRIPT [ARGS]')
