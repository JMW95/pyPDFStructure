# pyPDFStructure

Python library to parse Tagged PDFs and extract document structure and text.

Extracts the usually-hidden structural information which is stored in recent PDF versions for accessibility.

This information makes automatically reading tables etc. from the PDF document really easy.


See top of the file for more usage information and details.


## Example Usage:

```
from pyPDFStructure import *

fin = open("somedoc.pdf", "rb")
doc = PDFDocument(fin.read())
fin.close()

tree = doc.get_structure_tree()
```
