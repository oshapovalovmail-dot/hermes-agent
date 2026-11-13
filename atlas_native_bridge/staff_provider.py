"""Concrete qyp_guard Staff factory; no home bootstrap or arbitrary module path.

Install alongside provider.py in the trusted qyp_guard package. Only a
provisioner-owned admin_home and reviewed_service_files pin select the existing
Atlas read sidecar. Execute admitted bytes, never reopen by import path.
"""
import hashlib
import os
from pathlib import Path
import re
import stat
import types

if __package__:
    from .provider import StaffPersonHTTP, StaffUsernameProvider
else:
    from provider import StaffPersonHTTP, StaffUsernameProvider


def _admitted_sidecar(ctx):
    try:
        home_value = ctx.get_config('admin_home')
        pins = ctx.get_config('reviewed_service_files', {})
        if type(home_value) is not str or type(pins) is not dict:
            raise ValueError
        home = Path(home_value)
        pin = pins.get('sidecar.py')
        if (not home.is_absolute() or home.name != 'home' or '..' in home.parts
                or type(pin) is not str or re.fullmatch(r'[0-9a-f]{64}', pin) is None):
            raise ValueError
        path = home.parent / 'services' / 'atlas-read' / 'sidecar.py'
        # Walk by directory descriptors. O_NOFOLLOW covers every path component,
        # including admin roots; a check-then-read race cannot swap in a symlink.
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in path.parts[1:-1]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = child
            source_fd = os.open('sidecar.py', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                info = os.fstat(source_fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 2_000_000:
                    raise ValueError
                with os.fdopen(source_fd, 'rb', closefd=False) as stream:
                    data = stream.read(2_000_001)
                if len(data) > 2_000_000 or hashlib.sha256(data).hexdigest() != pin:
                    raise ValueError
            finally:
                os.close(source_fd)
        finally:
            os.close(fd)
        return path, data, pin
    except Exception:
        raise PermissionError('staff_reviewed_sidecar_required') from None


def build_staff_provider(ctx):
    path, data, pin = _admitted_sidecar(ctx)
    try:
        module = types.ModuleType('_atlas_staff_sidecar_' + pin)
        module.__file__ = str(path)
        module.__package__ = ''
        # compile exactly the already admitted in-memory buffer (no TOCTOU).
        exec(compile(data, str(path), 'exec', dont_inherit=True), module.__dict__)
        client = module.TrackerAPI()
        if not callable(client._auth_reader) or not callable(getattr(client._opener, 'open', None)):
            raise ValueError
        return StaffUsernameProvider(StaffPersonHTTP(client._auth_reader, client._opener))
    except Exception:
        raise PermissionError('staff_native_transport_unavailable') from None
