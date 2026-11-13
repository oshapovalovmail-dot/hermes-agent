"""Generation/reopen proof only; not a sandbox-containment or delivery test."""
from pathlib import Path
import tempfile,unittest

class DocumentRoundtripTests(unittest.TestCase):
    def test_all_four_document_formats(self):
        from docx import Document
        from pptx import Presentation
        from openpyxl import Workbook,load_workbook
        from reportlab.pdfgen.canvas import Canvas
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'receipts') as folder:
            root=Path(folder)
            doc=Document();doc.add_paragraph('Atlas document fixture');doc.save(root/'report.docx')
            self.assertEqual(Document(root/'report.docx').paragraphs[0].text,'Atlas document fixture')
            ppt=Presentation();slide=ppt.slides.add_slide(ppt.slide_layouts[1]);slide.shapes.title.text='Atlas fixture';ppt.save(root/'report.pptx')
            self.assertEqual(Presentation(root/'report.pptx').slides[0].shapes.title.text,'Atlas fixture')
            book=Workbook();book.active['A1']='Atlas';book.active['B1']=42;book.save(root/'report.xlsx')
            reopened=load_workbook(root/'report.xlsx',data_only=True);self.assertEqual(reopened.active['B1'].value,42);reopened.close()
            canvas=Canvas(str(root/'report.pdf'));canvas.drawString(72,720,'Atlas PDF fixture');canvas.save()
            pdf=PdfReader(root/'report.pdf');self.assertIn('Atlas PDF fixture',pdf.pages[0].extract_text())
            for path in root.iterdir():self.assertGreater(path.stat().st_size,100)

if __name__=='__main__':unittest.main()
