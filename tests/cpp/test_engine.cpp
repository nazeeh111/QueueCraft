#include "queuecraft/engine.hpp"
#include <atomic>
#include <cassert>
#include <fstream>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <thread>
#include <type_traits>

using namespace queuecraft;
namespace {
std::size_t assertions = 0;
void require(bool condition) { ++assertions; if (!condition) throw std::runtime_error("test assertion failed"); }
template<class Action> void reject(Action action) {
    ++assertions;
    bool rejected = false;
    try { action(); } catch (const std::exception&) { rejected = true; }
    if (!rejected) throw std::runtime_error("expected rejection");
}
Event snapshot(Integer id = 0, Integer time = 0) {
    return {id, -1, time, 'S', {{'B', 99, 10}, {'A', 101, 7}, {'A', 102, 6}}};
}
std::string fixture() {
    return std::string(input_header) + "0,-1,0,S,B,99,10\n0,-1,0,S,A,101,7\n0,-1,0,S,A,102,6\n1,-1,10,U,A,101,9\n2,-1,20,U,A,101,0\n";
}
void arithmetic() {
    constexpr auto hi = std::numeric_limits<Integer>::max();
    constexpr auto lo = std::numeric_limits<Integer>::min();
    require(checked_add(4, -8) == -4);
    require(checked_sub(lo, -1) == lo + 1);
    require(checked_mul(hi, 1) == hi);
    reject([&] { checked_add(hi, 1); });
    reject([&] { checked_sub(lo, 1); });
    reject([&] { checked_mul(lo, -1); });
    require(parse_integer("-9223372036854775808") == lo);
    require(parse_decimal("-9223372036854775808", 0) == lo);
    require(parse_decimal("1.2500", 2) == 125);
    require(parse_decimal("0.000000000000000001", 18) == 1);
    require(parse_decimal("-0.01", 2) == -1);
    require(parse_decimal("10.00", 0) == 10);
    for (const auto& value : {"", "+1", "1e2", "1 ", " 1", ".1", "1.", "NaN", "1.001", "1.0x", "--1"})
        reject([&] { parse_decimal(value, 2); });
    reject([&] { parse_decimal("9223372036854775808", 0); });
    reject([&] { parse_decimal("9223372036854775807", 1); });
    reject([&] { parse_decimal("1", 19); });
}
void parser() {
    auto events = parse_csv(fixture());
    require(events.size() == 3 && events[0].levels.size() == 3);
    auto text = fixture();
    // Every byte prefix without complete final line is rejected. A complete
    // event prefix is allowed only when its terminal event itself is complete.
    for (std::size_t length = 0; length < text.size(); ++length) {
        if (!length || text[length - 1] != '\n') reject([&] { parse_csv(std::string_view(text).substr(0, length)); });
    }
    for (const auto& body : {
        "0,-1,0,S,B,99,10\n0,-1,0,S,B,99,11\n",
        "0,-1,0,S,B,99,10,extra\n",
        "0,-1,0,S,B,99\n",
        "0,-1,0,S,B,99,10\n0,-1,1,S,A,101,2\n",
        "0,-1,0,S,B,99,10\n2,-1,1,U,A,101,2\n",
        "0,-1,1,S,B,99,10\n1,-1,0,U,A,101,2\n",
        "0,-1,0,S,B,99,0\n",
        "0,-1,0,X,B,99,1\n",
        "0,-1,0,G,B,2,0\n",
        "0,-1,0,S,Q,99,1\n",
        "0,-1,0,S,B,-99,1\n",
        "0,-1,0,S,B,99,-1\n",
        "0,-1,0,S,B,99,1\r\n",
        "0,-1,0,S,B,99,9223372036854775808\n"})
        reject([&] { parse_csv(std::string(input_header) + body); });
    reject([&] { parse_csv(std::string(max_bytes + 1, 'x')); });
    reject([&] { parse_csv(std::string(input_header) + std::string(100'000, ',') + "\n"); });
}
void book() {
    Engine engine;
    require(!engine.valid());
    engine.apply(snapshot());
    auto before = engine.snapshot();
    require(before.find("0,-1,0,1,B,99,10") != std::string::npos);
    reject([&] { engine.apply(snapshot()); });
    require(engine.snapshot() == before);
    reject([&] { engine.apply({1, -1, 1, 'U', {{'A', 98, 1}}}); });
    require(engine.snapshot() == before);
    reject([&] { engine.apply({1, -1, 1, 'U', {{'B', 101, 1}}}); });
    require(engine.snapshot() == before);
    reject([&] { engine.apply({1, -1, 1, 'U', {{'A', 103, 1}, {'A', 103, 3}}}); });
    require(engine.snapshot() == before);
    engine.apply({1, -1, 1, 'U', {{'A', 101, 0}}});
    require(engine.snapshot().find(",A,101,") == std::string::npos);
    engine.apply({2, -1, 2, 'U', {{'A', 102, 0}, {'B', 99, 0}}});
    require(engine.valid());
    require(engine.take("buy", 4).filled == 0);
    engine.apply(snapshot(3, 3));
    require(engine.valid());
    engine.apply({4, -1, 4, 'G', {{'B', 1, 0}}});
    require(!engine.valid());
    require(engine.take("buy", 4).filled == 0);
    engine.apply({5, -1, 5, 'U', {{'A', 101, 100}}});
    require(!engine.valid());
    engine.apply(snapshot(6, 6));
    require(engine.valid());
    auto invalid_snapshot = snapshot(7, 7); invalid_snapshot.levels = {{'B', 99, 10}};
    reject([&] { engine.apply(invalid_snapshot); });
    require(engine.event_id() == 6);
    Engine timestamp;
    auto first = snapshot(); first.exchange_ns = 100; timestamp.apply(first);
    auto second = snapshot(1, 2); second.exchange_ns = 99;
    reject([&] { timestamp.apply(second); });
    require(timestamp.event_id() == 0);
    reject([&] { timestamp.apply(snapshot(1, -1)); });
    auto huge = snapshot(1, 2); huge.levels.clear();
    for (Integer i = 1; i <= 10'001; ++i) huge.levels.push_back({'B', i, 1});
    huge.levels.push_back({'A', 20'000, 1});
    reject([&] { timestamp.apply(huge); });
    require(timestamp.event_id() == 0);
}
void ledger() {
    Engine engine; engine.apply(snapshot());
    auto first = engine.take("buy", 9, 1'000);
    require(first.filled == 9 && first.remaining == 0 && first.fills.size() == 2);
    require(first.fills[0].price == 101 && first.fills[0].quantity == 7 && first.fills[0].fee == 1);
    require(first.fills[1].price == 102 && first.fills[1].quantity == 2 && first.fills[1].fee == 1);
    require(first.cash == -913 && first.inventory == 9 && first.fees == 2);
    auto second = engine.take("buy", 9);
    require(second.filled == 4 && second.remaining == 5 && second.cash == -1321 && second.inventory == 13);
    require(engine.take("buy", 1).filled == 0);
    // Snapshot does not magically refill the hypothetical consumption overlay.
    engine.apply(snapshot(1, 1));
    require(engine.take("buy", 1).filled == 0);
    engine.apply({2, -1, 2, 'G', {{'B', 1, 0}}}); engine.apply(snapshot(3, 3));
    require(engine.take("buy", 1).filled == 0);
    engine.apply({4, -1, 4, 'U', {{'A', 101, 0}}});
    engine.apply({5, -1, 5, 'U', {{'A', 101, 3}}});
    require(engine.take("buy", 3).filled == 3);
    auto sale = engine.take("sell", 4, 10'000);
    require(sale.filled == 4 && sale.fills[0].price == 99 && sale.fills[0].fee == 4);
    require(sale.inventory == 12 && sale.cash == -1232 && sale.fees == 6);
    Engine haircut; haircut.apply(snapshot());
    require(haircut.take("buy", 30, 0, 500'000).filled == 6);
    require(haircut.take("buy", 30, 0, 0).filled == 0);
    for (auto side : {"buyy", ""}) reject([&] { engine.take(side, 1); });
    reject([&] { engine.take("buy", 0); });
    reject([&] { engine.take("buy", 1, -1); });
    reject([&] { engine.take("buy", 1, 0, 1'000'001); });
    // Overflow in a later level must undo all earlier hypothetical fills too.
    Engine overflow;
    auto maximum = std::numeric_limits<Integer>::max();
    overflow.apply({0, -1, 0, 'S', {{'B', 1, 2}, {'A', 3, 1}, {'A', maximum, 2}}});
    reject([&] { overflow.take("buy", 3); });
    require(overflow.cash() == 0 && overflow.inventory() == 0 && overflow.fees() == 0);
    require(overflow.take("buy", 1).filled == 1);
    // Very large recorded depth with small quantity must not overflow haircut.
    Engine depth; depth.apply({0, -1, 0, 'S', {{'B', 1, maximum}, {'A', 2, maximum}}});
    require(depth.take("buy", 1, 0, 500'000).filled == 1);
}
void timing() {
    static_assert(!std::is_convertible_v<Integer, RecordingBounds>);
    auto text = fixture();
    constexpr RecordingBounds bounds{20};  // Declared fixture recording interval.
    auto immediate = execute(text, "buy", 8, bounds, 0);
    require(immediate.filled == 8 && immediate.fills[0].quantity == 7 && immediate.fills[1].price == 102);
    require(execute(text, "buy", 8, bounds, 10).fills.size() == 1);
    require(execute(text, "buy", 8, bounds, 11).fills.size() == 1);
    require(execute(text, "buy", 8, bounds, 20).filled == 6);
    require(execute(text, "buy", 8, bounds, 21).filled == 0);
    reject([&] { execute(text, "buy", 8, bounds, -1); });
    auto ties = std::string(input_header) + "0,-1,0,S,B,99,5\n0,-1,0,S,A,101,5\n1,-1,0,U,A,101,1\n";
    require(execute(ties, "buy", 5, RecordingBounds{0}).filled == 1);
    auto prefix = std::string(input_header) + "0,-1,0,S,B,99,5\n0,-1,0,S,A,101,5\n";
    auto extended = prefix + "1,-1,10,U,A,101,1\n";
    require(execute(prefix, "buy", 5, RecordingBounds{10}).cash == execute(extended, "buy", 5, RecordingBounds{10}).cash);
    auto future = prefix + "1,-1,2,S,B,299,1\n1,-1,2,S,A,301,1\n";
    auto quiet = execute(prefix, "buy", 5, RecordingBounds{2}, 1);
    auto appended = execute(future, "buy", 5, RecordingBounds{2}, 1);
    require(quiet.filled == 5 && quiet.cash == -505 && quiet.fills.size() == 1);
    require(quiet.cash == appended.cash && quiet.inventory == appended.inventory && quiet.filled == appended.filled && quiet.fees == appended.fees);
    require(quiet.remaining == appended.remaining && quiet.event == appended.event && quiet.exchange_ns == appended.exchange_ns && quiet.receive_ns == appended.receive_ns);
    require(quiet.fills[0].price == appended.fills[0].price && quiet.fills[0].quantity == appended.fills[0].quantity);
    require(execute(prefix, "buy", 5, RecordingBounds{1}, 1).filled == 5);
    require(execute(prefix, "buy", 5, RecordingBounds{0}, 1).filled == 0);
    require(execute(prefix, "buy", 5, RecordingBounds{2}, 3).filled == 0);
    reject([&] { execute(prefix, "buy", 5, RecordingBounds{-1}, 0); });
    reject([&] { execute(future, "buy", 5, RecordingBounds{1}, 1); });
    reject([&] { execute(prefix, "buy", 5, RecordingBounds{2}, 1, -1); });
    reject([&] { execute(prefix, "buy", 5, RecordingBounds{2}, 1, 0, 1'000'001); });
    auto gap = prefix + "1,-1,1,G,B,1,0\n";
    auto recovery = gap + "2,-1,2,S,B,100,5\n2,-1,2,S,A,103,5\n";
    require(execute(gap, "buy", 5, RecordingBounds{2}, 1).filled == 0);
    require(execute(recovery, "buy", 5, RecordingBounds{2}, 1).filled == 0);
    require(execute(recovery, "buy", 5, RecordingBounds{2}, 2).fills[0].price == 103);
    auto tied_recovery = gap + "2,-1,1,S,B,100,5\n2,-1,1,S,A,103,5\n";
    require(execute(tied_recovery, "buy", 5, RecordingBounds{2}, 1).fills[0].price == 103);
    auto tied_gap = prefix + "1,-1,1,S,B,100,5\n1,-1,1,S,A,103,5\n2,-1,1,G,B,1,0\n";
    require(execute(tied_gap, "buy", 5, RecordingBounds{2}, 1).filled == 0);
    // Failed standalone requests have no shared state or consumption side effects.
    reject([&] { execute(future, "buy", 5, RecordingBounds{0}, 0); });
    require(execute(prefix, "buy", 5, RecordingBounds{2}, 1).cash == quiet.cash);
    require(replay(text) == replay(text));
}
void ownership() {
    Engine engine; engine.apply(snapshot());
    std::atomic<int> rejected{0};
    std::thread other([&] {
        try { engine.take("buy", 1); } catch (const std::logic_error&) { ++rejected; }
        try { engine.snapshot(); } catch (const std::logic_error&) { ++rejected; }
        try { engine.apply(snapshot(1, 1)); } catch (const std::logic_error&) { ++rejected; }
    });
    other.join();
    require(rejected == 3 && engine.inventory() == 0 && engine.event_id() == 0);
    // Shutdown from the owner repeatedly frees maps; capsules are separately
    // stressed by Python tests in the package-level suite.
    for (int i = 0; i < 500; ++i) { Engine disposable; disposable.apply(snapshot()); disposable.take("buy", 1); }
    require(engine.take("buy", 1).filled == 1);
}
void deterministic_fuzz() {
    std::mt19937 random(30491);
    std::uniform_int_distribution<int> byte(0, 127);
    const auto seed = fixture();
    for (int trial = 0; trial < 12'000; ++trial) {
        auto text = seed;
        int edits = 1 + static_cast<int>(random() % 6);
        while (edits--) text[random() % text.size()] = static_cast<char>(byte(random));
        try { auto events = parse_csv(text); Engine engine; for (const auto& event : events) engine.apply(event); }
        catch (const std::exception&) {}
    }
    require(true);
}
}
int main() {
    try {
        arithmetic(); parser(); book(); ledger(); timing(); ownership(); deterministic_fuzz();
        std::cout << "core assertions=" << assertions << " parser mutations=12000 status=pass\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << " after " << assertions << " assertions\n"; return 1; }
}
