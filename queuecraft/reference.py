"""Slow independent integer reference for the public QueueCraft book contract.

This module deliberately uses dictionaries, copies and Python integers.  It does
not import the native engine and is an oracle for complete transition traces,
not an alternate fast implementation.
"""

from __future__ import annotations

import copy
import re
import threading
from dataclasses import dataclass

INPUT_HEADER = "event,exchange_ns,receive_ns,kind,side,price,quantity"
BOOK_HEADER = "event,exchange_ns,receive_ns,valid,side,price,quantity"
I64_MIN, I64_MAX = -(1 << 63), (1 << 63) - 1
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 1_000_000
MAX_EVENT_ROWS = 20_000
MAX_LEVELS = 10_000
PPM = 1_000_000


def checked(value: int) -> int:
    """Require an exact signed 64-bit integer without wrapping."""
    if type(value) is not int:
        raise ValueError("an integer is required")
    if not I64_MIN <= value <= I64_MAX:
        raise OverflowError("signed 64-bit integer overflow")
    return value


def _integer(text: str) -> int:
    if not re.fullmatch(r"-?[0-9]+", text, re.ASCII):
        raise ValueError("CSV integers must be plain ASCII decimals")
    value = checked(int(text))
    if text.startswith("-") and value == 0:
        raise ValueError("negative zero is not a normalized integer")
    return value


def parse_decimal(text: str, scale: int) -> int:
    """Convert an exact decimal to integer units; scale is decimal places 0..18."""
    checked(scale)
    if not 0 <= scale <= 18:
        raise ValueError("scale must be decimal places between zero and eighteen")
    if not isinstance(text, str) or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", text, re.ASCII):
        raise ValueError("plain decimal required")
    negative = text.startswith("-")
    unsigned = text[1:] if negative else text
    whole, _, fraction = unsigned.partition(".")
    numerator = int(whole + fraction) * (10 ** scale)
    denominator = 10 ** len(fraction)
    value, remainder = divmod(numerator, denominator)
    if remainder:
        raise ValueError("decimal violates unit increment")
    return checked(-value if negative else value)


@dataclass(frozen=True)
class Event:
    event: int
    exchange_ns: int
    receive_ns: int
    kind: str
    levels: tuple[tuple[str, int, int], ...]

    def csv(self) -> str:
        return INPUT_HEADER + "\n" + "".join(
            f"{self.event},{self.exchange_ns},{self.receive_ns},{self.kind},{side},{price},{quantity}\n"
            for side, price, quantity in self.levels
        )


def parse_events(text: str) -> list[Event]:
    """Validate a bounded normalized file into immutable event transactions.

    Cross-event continuity is checked by ``Reference.apply``. This parser may
    therefore also consume a one-event fragment with its original event ID.
    """
    if not isinstance(text, str):
        raise ValueError("input must be text")
    if not text.endswith("\n"):
        raise ValueError("input requires a final LF")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("input exceeds 64 MiB")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or lines[0] != INPUT_HEADER:
        raise ValueError("exact normalized CSV header required")
    if len(lines) < 2:
        raise ValueError("at least one event is required")
    if len(lines) - 1 > MAX_ROWS:
        raise ValueError("input exceeds row bound")
    events: list[Event] = []
    current: tuple[int, int, int, str] | None = None
    levels: list[tuple[str, int, int]] = []
    seen: set[tuple[str, int]] = set()
    closed_ids: set[int] = set()
    for line in lines[1:]:
        fields = line.split(",")
        if len(fields) != 7:
            raise ValueError("exactly seven fields required")
        event, exchange, receive = (_integer(value) for value in fields[:3])
        kind, side = fields[3:5]
        price, quantity = (_integer(value) for value in fields[5:])
        if event < 0 or exchange < -1 or receive < 0:
            raise ValueError("invalid event ID or timestamp")
        if kind not in {"S", "U", "G"} or side not in {"B", "A"}:
            raise ValueError("invalid event kind or side")
        if price <= 0 or quantity < 0:
            raise ValueError("price positive and quantity nonnegative required")
        key = (event, exchange, receive, kind)
        if current is not None and event != current[0]:
            events.append(Event(*current, tuple(levels)))
            closed_ids.add(current[0])
            levels, seen = [], set()
            current = None
        if current is None:
            if event in closed_ids:
                raise ValueError("interleaved event rows")
            current = key
        elif key != current:
            raise ValueError("one event must have identical timestamps and kind")
        if (side, price) in seen:
            raise ValueError("duplicate level in event")
        seen.add((side, price))
        levels.append((side, price, quantity))
        if len(levels) > MAX_EVENT_ROWS:
            raise ValueError("event exceeds row bound")
    if current is not None:
        events.append(Event(*current, tuple(levels)))
    return events


class Reference:
    """Transactional, single-owner book with a conservative consumed overlay."""

    def __init__(self) -> None:
        self.bids: dict[int, int] = {}
        self.asks: dict[int, int] = {}
        self.consumed: dict[str, dict[int, int]] = {"B": {}, "A": {}}
        self.valid = False
        self.event = -1
        self.exchange_ns = -1
        self.receive_ns = -1
        self.cash = self.inventory = self.fees = 0
        self._owner = threading.get_ident()

    def _check_owner(self) -> None:
        if threading.get_ident() != self._owner:
            raise ValueError("book belongs to another thread")

    def apply(self, event_csv: str) -> str:
        self._check_owner()
        events = parse_events(event_csv)
        if len(events) != 1:
            raise ValueError("apply requires exactly one event")
        event = events[0]
        if event.event != self.event + 1:
            raise ValueError("event IDs must be contiguous from zero")
        if event.receive_ns < self.receive_ns:
            raise ValueError("receive timestamp moved backwards")
        if self.valid and event.exchange_ns >= 0 and self.exchange_ns >= 0 and event.exchange_ns < self.exchange_ns and event.kind != "G":
            raise ValueError("exchange timestamp moved backwards")
        if event.kind == "G":
            if event.levels != (("B", 1, 0),):
                raise ValueError("gap requires one B,1,0 sentinel row")
            self.valid = False
            self.event, self.exchange_ns, self.receive_ns = event.event, event.exchange_ns, event.receive_ns
            return self.snapshot()
        if event.kind == "U" and not self.valid:
            self.event, self.exchange_ns, self.receive_ns = event.event, event.exchange_ns, event.receive_ns
            return self.snapshot()
        bids, asks = ({}, {}) if event.kind == "S" else (self.bids.copy(), self.asks.copy())
        for side, price, quantity in event.levels:
            if event.kind == "S" and quantity == 0:
                raise ValueError("snapshot cannot contain zero quantity")
            levels = bids if side == "B" else asks
            if quantity:
                levels[price] = quantity
            else:
                levels.pop(price, None)
        if event.kind == "S" and (not bids or not asks):
            raise ValueError("two-sided book required")
        if len(bids) > MAX_LEVELS or len(asks) > MAX_LEVELS:
            raise ValueError("book exceeds depth bound")
        if bids and asks and max(bids) >= min(asks):
            raise ValueError("crossed or locked book")
        consumed = {
            side: {price: min(amount, book[price]) for price, amount in self.consumed[side].items() if price in book}
            for side, book in (("B", bids), ("A", asks))
        }
        self.bids, self.asks, self.consumed = bids, asks, consumed
        self.valid = True
        self.event, self.exchange_ns, self.receive_ns = event.event, event.exchange_ns, event.receive_ns
        return self.snapshot()

    def snapshot(self) -> str:
        self._check_owner()
        if not self.valid:
            return BOOK_HEADER + f"\n{self.event},{self.exchange_ns},{self.receive_ns},0,-,0,0\n"
        prefix = f"{self.event},{self.exchange_ns},{self.receive_ns},1"
        return BOOK_HEADER + "\n" + "".join(
            f"{prefix},{side},{price},{levels[price]}\n"
            for side, levels, reverse in (("B", self.bids, True), ("A", self.asks, False))
            for price in sorted(levels, reverse=reverse)
        )

    def take(self, side: str, quantity: int, fee_ppm: int = 0, liquidity_ppm: int = PPM) -> dict:
        self._check_owner()
        checked(quantity)
        checked(fee_ppm)
        checked(liquidity_ppm)
        if side not in {"buy", "sell"} or quantity <= 0:
            raise ValueError("buy/sell and positive quantity required")
        if not 0 <= fee_ppm <= PPM or not 0 <= liquidity_ppm <= PPM:
            raise ValueError("fee and liquidity must be between zero and one million ppm")
        if not self.valid:
            raise ValueError("cannot execute against invalid book")
        book_side = "A" if side == "buy" else "B"
        levels = self.asks if side == "buy" else self.bids
        used = self.consumed[book_side].copy()
        cash, inventory, fees = self.cash, self.inventory, self.fees
        remaining = quantity
        fills = []
        for price in sorted(levels, reverse=side == "sell"):
            available = checked((levels[price] - used.get(price, 0)) * liquidity_ppm // PPM)
            size = min(available, remaining)
            if size == 0:
                continue
            notional = checked(price * size)
            # Wide intermediate is allowed for exact fee rounding, final values checked.
            fee = checked((notional * fee_ppm + PPM - 1) // PPM)
            cash = checked(cash - checked(notional + fee)) if side == "buy" else checked(cash + checked(notional - fee))
            inventory = checked(inventory + size) if side == "buy" else checked(inventory - size)
            fees = checked(fees + fee)
            used[price] = checked(used.get(price, 0) + size)
            remaining -= size
            fills.append({"price": price, "quantity": size, "notional": notional, "fee": fee})
            if remaining == 0:
                break
        self.cash, self.inventory, self.fees = cash, inventory, fees
        self.consumed[book_side] = used
        return {
            "fills": fills, "filled": quantity - remaining, "remaining": remaining,
            "cash": cash, "inventory": inventory, "fees": fees, "event": self.event,
            "exchange_ns": self.exchange_ns, "receive_ns": self.receive_ns,
        }

    def checkpoint(self) -> dict:
        """Return an independent copy for failed-transition and restore checks."""
        self._check_owner()
        return copy.deepcopy({key: value for key, value in self.__dict__.items() if key != "_owner"})

    @classmethod
    def restore(cls, state: dict) -> "Reference":
        result = cls()
        expected = set(result.__dict__) - {"_owner"}
        if not isinstance(state, dict) or set(state) != expected:
            raise ValueError("invalid reference checkpoint schema")
        result.__dict__.update(copy.deepcopy(state))
        return result


def replay(text: str) -> str:
    reference = Reference()
    traces = [BOOK_HEADER + "\n"]
    for event in parse_events(text):
        traces.append(reference.apply(event.csv()).split("\n", 1)[1])
    return "".join(traces)
