"""
Embed the two Blobby sprite sheets into dashboard/blob.js as base64 data URIs,
replacing the __BLOB_BODY_DATAURI__ / __BLOB_EYES_DATAURI__ markers.

Keeps blob.js a single self-contained text file (no binary side-car to serve
from inside the Streamlit component iframe). Re-run after regenerating the sheets
with gen_blobby_ref.py.

    python scripts/embed_blob_sheets.py
"""

import base64
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / 'dashboard'
JS = DASH / 'blob.js'


def datauri(png):
    return 'data:image/png;base64,' + base64.b64encode(png.read_bytes()).decode()


def main():
    src = JS.read_text(encoding='utf-8')
    body = datauri(DASH / 'blob_body.png')
    eyes = datauri(DASH / 'blob_eyes.png')

    # Replace only the marker (or an already-embedded data URI) between quotes,
    # so re-running is idempotent.
    src = re.sub(r"var SHEET_BODY_SRC = '[^']*';",
                 "var SHEET_BODY_SRC = '" + body + "';", src)
    src = re.sub(r"var SHEET_EYES_SRC = '[^']*';",
                 "var SHEET_EYES_SRC = '" + eyes + "';", src)

    JS.write_text(src, encoding='utf-8')
    print(f'embedded body {len(body)//1024}KB, eyes {len(eyes)//1024}KB into blob.js')


if __name__ == '__main__':
    main()
