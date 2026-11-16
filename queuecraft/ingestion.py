"""One-pass bounded CSV source, validated by the unchanged native book."""
import hashlib
from pathlib import Path
from .sdk import Book, Event, HEADER, integer
from .replay import MAX_EVENT_ROWS


class CSVEvents:
    """Read one complete event plus one row ahead. No whole-file size limit.

    Row/event limits bound parsing memory. The digest is authoritative only at
    EOF; close the source on early exit (ReplayStream does this automatically).
    """
    def __init__(self, path, *, max_row_bytes=4096):
        self.path = Path(path)
        self.max_row_bytes = integer(max_row_bytes, "max_row_bytes", 64, 65536)
        self.bytes_read = self.events_read = 0
        self.complete = False
        self.sha256 = None
        self._hash = hashlib.sha256()
        self._file = None
        self._generator = self._read()

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._generator)

    def close(self):
        self._generator.close()
        if self._file is not None:
            self._file.close()

    def _line(self):
        line = self._file.readline(self.max_row_bytes + 1)
        if len(line) > self.max_row_bytes:
            raise ValueError("CSV row exceeds declared byte limit")
        self.bytes_read += len(line)
        self._hash.update(line)
        return line

    def _read(self):
        with self.path.open("rb") as self._file:
            if self._line() != HEADER.encode("ascii"):
                raise ValueError("invalid CSV header")
            book = Book()
            pending = self._line()
            if not pending:
                raise ValueError("empty input")
            while pending:
                raw, rows = [], []
                event_bytes = 0
                key = None
                while pending:
                    fields = pending.decode("ascii").rstrip("\n").split(",")
                    if len(fields) != 7:
                        raise ValueError("expected seven CSV fields")
                    event_id = int(fields[0])
                    if key is not None and event_id != key:
                        break
                    key = event_id
                    if len(rows) >= MAX_EVENT_ROWS:
                        raise ValueError("event exceeds native row bound")
                    if event_bytes + len(pending) > 64 * 1024**2 - len(HEADER):
                        raise ValueError("event exceeds native input byte limit")
                    event_bytes += len(pending)
                    raw.append(pending)
                    rows.append(fields)
                    pending = self._line()
                # Preserve raw lexical validation, not normalized Python ints.
                book._native.apply(book._handle, HEADER + b"".join(raw).decode("ascii"))
                e, x, t, kind, *_ = rows[0]
                event = Event(int(e), int(x), int(t), kind,
                              tuple((r[4], int(r[5]), int(r[6])) for r in rows))
                self.events_read += 1
                yield event
            self.complete = True
            self.sha256 = self._hash.hexdigest()
