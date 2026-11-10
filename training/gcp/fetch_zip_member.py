"""Download one member of a large remote zip using HTTP range requests.

The AI CUP release nests the 1.9 GB rally archive inside a 14 GB zip. Reading
the zip directory remotely and fetching only that member avoids the rest.

    python fetch_zip_member.py URL MEMBER OUTPUT [SHA256]
"""

import hashlib
import io
import struct
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

CHUNK = 16 * 1024 * 1024


def fetch(url, start, end):
    for attempt in range(6):
        try:
            request = Request(url, headers={"Range": f"bytes={start}-{end - 1}"})
            with urlopen(request, timeout=120) as response:
                data = response.read()
            if len(data) == end - start:
                return data
        except OSError as error:
            print(f"retry {attempt} at {start}: {error}", flush=True)
    raise RuntimeError(f"range {start}-{end} failed")


class Remote(io.RawIOBase):
    """Just enough of a seekable file for zipfile to read the directory."""

    def __init__(self, url):
        self.url, self.position = url, 0
        with urlopen(Request(url, method="HEAD"), timeout=120) as response:
            self.size = int(response.headers["Content-Length"])
            self.url = response.url

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = (0, self.position, self.size)[whence] + offset
        return self.position

    def read(self, count=-1):
        end = self.size if count < 0 else min(self.size, self.position + count)
        if end <= self.position:
            return b""
        data = fetch(self.url, self.position, end)
        self.position = end
        return data


def main():
    url, member, output = sys.argv[1:4]
    remote = Remote(url)
    info = zipfile.ZipFile(io.BufferedReader(remote, 1024 * 1024)).getinfo(member)
    if info.compress_type != zipfile.ZIP_STORED:
        raise SystemExit("member is compressed; download the whole archive instead")
    header = fetch(remote.url, info.header_offset, info.header_offset + 30)
    name_length, extra_length = struct.unpack("<HH", header[26:30])
    begin = info.header_offset + 30 + name_length + extra_length
    ranges = [
        (start, min(start + CHUNK, begin + info.file_size))
        for start in range(begin, begin + info.file_size, CHUNK)
    ]
    digest, done = hashlib.sha256(), 0
    with open(output, "wb") as sink, ThreadPoolExecutor(4) as pool:
        for data in pool.map(lambda r: fetch(remote.url, *r), ranges):
            sink.write(data)
            digest.update(data)
            done += len(data)
            print(f"{done / info.file_size:.0%}", flush=True)
    if len(sys.argv) > 4 and digest.hexdigest() != sys.argv[4]:
        raise SystemExit(f"hash mismatch: {digest.hexdigest()}")
    print("ok", digest.hexdigest())


if __name__ == "__main__":
    main()
