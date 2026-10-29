import threading
import unittest

from queuecraft.reference import BOOK_HEADER, INPUT_HEADER, I64_MAX, Reference, parse_decimal, parse_events, replay


def transaction(event, kind="S", rows=(("B", 100, 10), ("A", 102, 10)), receive=None, exchange=-1):
    timestamp = event if receive is None else receive
    return INPUT_HEADER + "\n" + "".join(
        f"{event},{exchange},{timestamp},{kind},{side},{price},{quantity}\n"
        for side, price, quantity in rows
    )


class ReferenceTests(unittest.TestCase):
    def book(self):
        book = Reference()
        book.apply(transaction(0))
        return book

    def test_exact_complete_trace_has_all_levels_and_price_priority(self):
        text = transaction(0, rows=(("A", 104, 7), ("B", 98, 4), ("A", 102, 3), ("B", 100, 5)))
        text += transaction(1, "U", (("B", 99, 6), ("A", 104, 0))).split("\n", 1)[1]
        expected = BOOK_HEADER + "\n" + "".join(
            f"{event},-1,{event},1,{side},{price},{quantity}\n"
            for event, rows in ((0, (("B", 100, 5), ("B", 98, 4), ("A", 102, 3), ("A", 104, 7))),
                                (1, (("B", 100, 5), ("B", 99, 6), ("B", 98, 4), ("A", 102, 3))))
            for side, price, quantity in rows
        )
        self.assertEqual(replay(text), expected)

    def test_partial_buy_spans_prices_and_fee_rounds_per_fill(self):
        book = Reference()
        book.apply(transaction(0, rows=(("B", 100, 20), ("A", 102, 3), ("A", 104, 2))))
        result = book.take("buy", 7, 1)
        self.assertEqual(result["fills"], [
            {"price": 102, "quantity": 3, "notional": 306, "fee": 1},
            {"price": 104, "quantity": 2, "notional": 208, "fee": 1},
        ])
        self.assertEqual((result["filled"], result["remaining"], result["cash"], result["inventory"], result["fees"]),
                         (5, 2, -516, 5, 2))

    def test_sell_and_buy_conserve_signed_cash_and_inventory(self):
        book = self.book()
        sold = book.take("sell", 4, 10_000)
        self.assertEqual((sold["cash"], sold["inventory"], sold["fees"]), (396, -4, 4))
        bought = book.take("buy", 4, 10_000)
        self.assertEqual((bought["cash"], bought["inventory"], bought["fees"]), (-17, 0, 9))

    def test_repeat_order_cannot_reuse_liquidity(self):
        book = self.book()
        self.assertEqual(book.take("buy", 8)["filled"], 8)
        self.assertEqual(book.take("buy", 8)["filled"], 2)
        self.assertEqual(book.take("buy", 8)["filled"], 0)
        self.assertEqual(book.asks[102], 10)

    def test_absolute_increase_preserves_consumed_amount(self):
        book = self.book()
        book.take("buy", 8)
        book.apply(transaction(1, "U", (("A", 102, 15),)))
        self.assertEqual(book.take("buy", 20)["filled"], 7)

    def test_absolute_decrease_clamps_consumption(self):
        book = self.book()
        book.take("buy", 8)
        book.apply(transaction(1, "U", (("A", 102, 5),)))
        self.assertEqual(book.take("buy", 1)["filled"], 0)
        book.apply(transaction(2, "U", (("A", 102, 8),)))
        self.assertEqual(book.take("buy", 20)["filled"], 3)

    def test_deletion_and_reappearance_remove_consumption(self):
        book = self.book()
        book.take("buy", 8)
        book.apply(transaction(1, "U", (("A", 102, 0),)))
        self.assertEqual(book.take("buy", 1)["filled"], 0)
        book.apply(transaction(2, "U", (("A", 102, 10),)))
        self.assertEqual(book.take("buy", 20)["filled"], 10)

    def test_snapshot_retains_consumption_on_surviving_prices(self):
        book = self.book()
        book.take("buy", 8)
        book.apply(transaction(1))
        self.assertEqual(book.take("buy", 10)["filled"], 2)

    def test_gap_disables_fill_ignores_updates_and_requires_snapshot(self):
        book = self.book()
        book.take("buy", 8)
        invalid = book.apply(transaction(1, "G", (("B", 1, 0),)))
        self.assertEqual(invalid, BOOK_HEADER + "\n1,-1,1,0,-,0,0\n")
        with self.assertRaises(ValueError):
            book.take("buy", 1)
        book.apply(transaction(2, "U", (("A", 102, 200),)))
        self.assertFalse(book.valid)
        book.apply(transaction(3))
        self.assertEqual(book.take("buy", 10)["filled"], 2)

    def test_first_update_remains_invalid(self):
        book = Reference()
        book.apply(transaction(0, "U", (("A", 102, 1),)))
        self.assertFalse(book.valid)
        book.apply(transaction(1))
        self.assertTrue(book.valid)

    def test_liquidity_fraction_is_floor_and_zero_does_not_fill(self):
        book = self.book()
        self.assertEqual(book.take("buy", 10, liquidity_ppm=0)["filled"], 0)
        self.assertEqual(book.take("buy", 10, liquidity_ppm=333_333)["filled"], 3)
        self.assertEqual(book.take("buy", 10, liquidity_ppm=333_333)["filled"], 2)

    def test_failed_crossing_transaction_rolls_back_every_level(self):
        book = self.book()
        before = book.checkpoint()
        with self.assertRaises(ValueError):
            book.apply(transaction(1, "U", (("B", 99, 99), ("B", 102, 3))))
        self.assertEqual(book.checkpoint(), before)

    def test_execution_overflow_rolls_back_earlier_valid_fill(self):
        book = Reference()
        book.apply(transaction(0, rows=(("B", 1, 5), ("A", 2, 1), ("A", I64_MAX, 2))))
        before = book.checkpoint()
        with self.assertRaises(OverflowError):
            book.take("buy", 3)
        self.assertEqual(book.checkpoint(), before)

    def test_large_depth_uses_wide_liquidity_numerator(self):
        book = Reference()
        book.apply(transaction(0, rows=(("B", 1, I64_MAX), ("A", 2, I64_MAX))))
        self.assertEqual(book.take("buy", 1)["filled"], 1)

    def test_fee_rounding_uses_wide_numerator(self):
        book = Reference()
        book.apply(transaction(0, rows=(("B", 1, 2), ("A", 10**15, 1))))
        result = book.take("buy", 1, 1_000_000)
        self.assertEqual(result["cash"], -(2 * 10**15))

    def test_invalid_fragments_never_mutate_existing_state(self):
        book = self.book()
        before = book.checkpoint()
        bad = [
            transaction(1).rstrip("\n"),
            transaction(1).replace("1,-1,1,S,A,102,10", "1,-1,1,S,A,102"),
            transaction(1).replace("1,-1,1,S,A", "1,-1,2,S,A"),
            transaction(1).replace("1,-1,1,S,A", "1,-1,1,U,A"),
            transaction(1, rows=(("B", 100, 1), ("B", 100, 2), ("A", 102, 1))),
            transaction(2),
            transaction(1, receive=0).replace(",0,S,A,", ",-1,S,A,"),
            transaction(1, "G"),
            transaction(1, rows=(("B", 100, 1),)),
            transaction(1, rows=(("B", 100, 0), ("A", 102, 1))),
            transaction(1).replace(",102,", ",+102,"),
            transaction(1).replace(",102,", ",1e2,"),
            transaction(1).replace(",102,", f",{I64_MAX + 1},"),
        ]
        for text in bad:
            with self.subTest(text=text):
                with self.assertRaises((ValueError, OverflowError)):
                    book.apply(text)
                self.assertEqual(book.checkpoint(), before)

    def test_receive_monotonic_and_exchange_continuity(self):
        book = Reference()
        book.apply(transaction(0, receive=100, exchange=50))
        with self.assertRaises(ValueError):
            book.apply(transaction(1, receive=99, exchange=51))
        with self.assertRaises(ValueError):
            book.apply(transaction(1, receive=101, exchange=49))
        book.apply(transaction(1, "G", (("B", 1, 0),), receive=101, exchange=0))
        book.apply(transaction(2, receive=102, exchange=1))
        self.assertTrue(book.valid)

    def test_exact_decimal_boundaries_and_tick_rejection(self):
        self.assertEqual(parse_decimal("1.250", 2), 125)
        self.assertEqual(parse_decimal("-0.001", 3), -1)
        self.assertEqual(parse_decimal(str(I64_MAX), 0), I64_MAX)
        for text, scale in (("0.001", 2), ("+1", 0), ("1e2", 0), ("1.", 2), (".1", 2), ("NaN", 2), ("1", 19)):
            with self.subTest(text=text, scale=scale), self.assertRaises(ValueError):
                parse_decimal(text, scale)
        with self.assertRaises(OverflowError):
            parse_decimal(str(I64_MAX + 1), 0)

    def test_checkpoint_restore_is_independent(self):
        book = self.book()
        book.take("buy", 8)
        restored = Reference.restore(book.checkpoint())
        self.assertEqual(restored.take("buy", 10), book.take("buy", 10))
        restored.apply(transaction(1, "U", (("A", 103, 1),)))
        self.assertNotEqual(restored.snapshot(), book.snapshot())

    def test_single_writer_ownership(self):
        book = self.book()
        failures = []
        def other_thread():
            try:
                book.snapshot()
            except ValueError as error:
                failures.append(str(error))
        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join()
        self.assertEqual(len(failures), 1)

    def test_parser_rejects_interleaving_and_empty_content(self):
        row0 = transaction(0).split("\n", 1)[1]
        row1 = transaction(1).split("\n", 1)[1]
        with self.assertRaises(ValueError):
            parse_events(INPUT_HEADER + "\n" + row0 + row1 + row0)
        with self.assertRaises(ValueError):
            parse_events(INPUT_HEADER + "\n")


if __name__ == "__main__":
    unittest.main()
