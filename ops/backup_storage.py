"""Downloads every file in Supabase Storage (reward and event images) into a folder.

Used by the nightly backup workflow. Needs SUPABASE_URL and SUPABASE_SERVICE_KEY.
    python ops/backup_storage.py out/storage
Standard library only, so it runs without installing anything.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def call(method: str, path: str, body: dict = None) -> bytes:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{URL}/storage/v1/{path}", data=data, method=method,
                                 headers={**HEADERS, **({"Content-Type": "application/json"} if data else {})})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def files_in(bucket: str, prefix: str = ""):
    offset = 0
    while True:
        items = json.loads(call("POST", f"object/list/{bucket}",
                                {"prefix": prefix, "limit": 1000, "offset": offset, "sortBy": {"column": "name", "order": "asc"}}))
        for item in items:
            path = f"{prefix}{item['name']}"
            if item.get("id") is None:          # a folder
                yield from files_in(bucket, path + "/")
            else:
                yield path
        if len(items) < 1000:
            return
        offset += 1000


def main(out_dir: str) -> None:
    total = 0
    for bucket in json.loads(call("GET", "bucket")):
        name = bucket["id"]
        for path in files_in(name):
            target = os.path.join(out_dir, name, *path.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(call("GET", f"object/{name}/{urllib.parse.quote(path)}"))
            total += 1
    print(f"Storage backup: {total} files")


if __name__ == "__main__":
    main(sys.argv[1])
