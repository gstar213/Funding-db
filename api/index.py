import pathlib
import json
from datasette.app import Datasette

ROOT = pathlib.Path(__file__).parent.parent
db_path = ROOT / "funding.db"
metadata_path = ROOT / "datasette_metadata.json"

metadata = {}
if metadata_path.exists():
    with open(metadata_path, encoding="utf-8") as f:
        metadata = json.load(f)

ds = Datasette(
    [str(db_path)],
    metadata=metadata,
    settings={
        "sql_time_limit_ms": 10000,
        "max_returned_rows": 2000,
    },
)

app = ds.app()
