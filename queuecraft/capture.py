"""Bounded, append-only raw-message journal for embedding read-only collectors.

No network client or credentials. A collector supplies original bytes and its
receive time. Failed CRC/truncated records are explicit errors requiring a new
snapshot/session, never silently repaired into valid continuity.
"""
from __future__ import annotations
import os
from pathlib import Path
import struct
import zlib

MAGIC=b"QCRAFT01\n"
MAX_MESSAGE=1_048_576
MAX_CAPTURE=64*1024**2


class RawCapture:
    def __init__(self,path:Path):
        self.file=Path(path).open("xb")
        self.file.write(MAGIC)
        self.size=len(MAGIC)
        self.last=-1

    def append(self,payload:bytes,receive_ns:int):
        if type(payload) is not bytes or not 0<len(payload)<=MAX_MESSAGE:
            raise ValueError("raw message must contain1..1048576 bytes")
        if type(receive_ns) is not int or not 0<=receive_ns<2**63 or receive_ns<self.last:
            raise ValueError("nonmonotone or invalid receive time")
        record=struct.pack("<qII",receive_ns,len(payload),zlib.crc32(payload))+payload
        if self.size+len(record)>MAX_CAPTURE:
            raise ValueError("capture exceeds64MiB; start a new session")
        self.file.write(record)
        self.file.flush()
        self.size+=len(record)
        self.last=receive_ns

    def close(self):
        if not self.file.closed:
            self.file.flush()
            os.fsync(self.file.fileno())
            self.file.close()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()


def read_capture(path:Path):
    path=Path(path)
    if path.stat().st_size>MAX_CAPTURE:raise ValueError("capture exceeds64MiB")
    with path.open("rb") as source:
        if source.read(len(MAGIC))!=MAGIC:raise ValueError("unknown raw journal format")
        last=-1
        consumed=len(MAGIC)
        while header:=source.read(16):
            if len(header)!=16:raise ValueError("truncated raw header; invalidate and resnapshot")
            timestamp,length,crc=struct.unpack("<qII",header)
            if timestamp<last or timestamp<0 or not 0<length<=MAX_MESSAGE:raise ValueError("corrupt raw header")
            consumed+=16+length
            if consumed>MAX_CAPTURE:raise ValueError("capture exceeds64MiB during read")
            payload=source.read(length)
            if len(payload)!=length or zlib.crc32(payload)!=crc:raise ValueError("truncated/corrupt raw message; invalidate and resnapshot")
            last=timestamp
            yield timestamp,payload
