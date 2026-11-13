"""Render every PPTX slide via installed LibreOffice, then make a numbered contact sheet.

Requires soffice plus hash-locked pypdfium2 and Pillow; no installation or fake rendering.
"""
import argparse
import math
from pathlib import Path
import sys
import tempfile
from office.soffice import run_soffice


def thumbnail(source,output,cols=3):
    if cols<1 or cols>10:raise ValueError('cols must be 1..10')
    from PIL import Image,ImageDraw
    import pypdfium2 as pdfium
    source=Path(source).resolve();output=Path(output)
    with tempfile.TemporaryDirectory(prefix='atlas-thumbnails-') as tmp:
        conversion=run_soffice(['--headless','--convert-to','pdf','--outdir',tmp,str(source)],capture_output=True,text=True,timeout=120)
        pdf=Path(tmp)/(source.stem+'.pdf')
        if conversion.returncode or not pdf.is_file():raise RuntimeError('LibreOffice PDF conversion failed: '+conversion.stderr)
        doc=pdfium.PdfDocument(pdf)
        try:
            if not len(doc):raise ValueError('empty presentation')
            width,height=480,300
            grid=Image.new('RGB',(cols*width,math.ceil(len(doc)/cols)*height),'#dddddd')
            draw=ImageDraw.Draw(grid)
            for i in range(len(doc)):
                page=doc[i]
                try:
                    bitmap=page.render(scale=1)
                    try:image=bitmap.to_pil().copy()
                    finally:bitmap.close()
                finally:page.close()
                image.thumbnail((width-16,height-32))
                x=(i%cols)*width+8;y=(i//cols)*height+24
                grid.paste(image,(x,y));draw.text((x,y-20),str(i+1),fill='black')
            output.parent.mkdir(parents=True,exist_ok=True);grid.save(output)
        finally:doc.close()
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('output',nargs='?',type=Path)
    parser.add_argument('--cols',type=int,default=3)
    args=parser.parse_args()
    try:print(thumbnail(args.source,args.output or args.source.with_suffix('.thumbnails.png'),args.cols));return 0
    except RuntimeError as error:print(str(error),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
