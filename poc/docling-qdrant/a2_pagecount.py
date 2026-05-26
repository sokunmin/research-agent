"""A2: Verify PARTIAL_SUCCESS page-count method using JSON cache from A1."""
import sys
from pathlib import Path

import pypdf

sys.path.insert(0, str(Path(__file__).parent))
from poc_base import DoclingPoc, PocReporter


def run() -> bool:
    r = PocReporter("A2")
    doc = DoclingPoc.load_doc()

    with open(DoclingPoc.PDF_PATH, "rb") as f:
        total_pages = len(pypdf.PdfReader(f).pages)

    parsed_pages = len(doc.pages)   # dict — len() works correctly
    success_rate = parsed_pages / total_pages if total_pages > 0 else 0.0

    r.check("pypdf total_pages > 0", total_pages > 0, str(total_pages))
    r.check("parsed_pages > 0", parsed_pages > 0, str(parsed_pages))
    r.check("parsed_pages ≤ total_pages", parsed_pages <= total_pages,
            f"{parsed_pages}/{total_pages} ({success_rate:.0%})")
    r.check("no AttributeError (pages is dict)", True)  # reaching here means dict access worked

    return r.summary()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
