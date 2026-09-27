import json
import sys
import uuid
from pathlib import Path

cbz = Path(sys.argv[-1])
if "fail" in cbz.name:
    print("boom", file=sys.stderr)
    sys.exit(1)
(cbz.parent / "_ocr").mkdir(exist_ok=True)
data = {
    "title": cbz.parent.name,
    "title_uuid": str(uuid.uuid4()),
    "volume": cbz.stem,
    "volume_uuid": str(uuid.uuid4()),
    "pages": [{"blocks": [{"lines": ["日本語"]}]}],
}
cbz.with_suffix(".mokuro").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
