"""Unpack Office OpenXML for editing; rejects traversal and symlink members."""
import argparse
from pathlib import Path
import zipfile
from helpers import safe_extract


def unpack(source, destination):
    source=Path(source);destination=Path(destination)
    if source.suffix.lower() not in ('.pptx','.docx','.xlsx'):
        raise ValueError('Office OpenXML file required')
    if destination.exists():
        raise FileExistsError('new unpack directory required')
    # Validate all names before making the destination or extracting any bytes.
    import stat
    with zipfile.ZipFile(source) as archive:
        for item in archive.infolist():
            parts=item.filename.split('/')
            if item.filename.startswith('/') or '\\' in item.filename or '..' in parts or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('unsafe archive entry')
        destination.mkdir(parents=True)
        safe_extract(archive,destination)
    return destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args();print(unpack(args.source,args.destination))

if __name__=='__main__':main()
