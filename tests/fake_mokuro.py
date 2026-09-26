import sys
from pathlib import Path

cbz = Path(sys.argv[-1])
if "fail" in cbz.name:
    print("boom", file=sys.stderr)
    sys.exit(1)
(cbz.parent / "_ocr").mkdir(exist_ok=True)
cbz.with_suffix(".mokuro").write_text('{"pages": []}')
