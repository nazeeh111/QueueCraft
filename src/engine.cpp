#include "queuecraft/engine.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace queuecraft {
namespace {
[[noreturn]] void fail(const char* text) { throw std::invalid_argument(text); }
void level_valid(const Level& level, char kind) {
    if (level.side != 'B' && level.side != 'A') fail("side must be B or A");
    if (level.price <= 0 || level.quantity < 0) fail("price must be positive and quantity nonnegative");
    if (kind == 'S' && level.quantity == 0) fail("snapshot quantities must be positive");
}
void event_valid(const Event& event) {
    if (event.id < 0 || event.exchange_ns < -1 || event.receive_ns < 0) fail("invalid event ID or timestamp");
    if (event.kind != 'S' && event.kind != 'U' && event.kind != 'G') fail("kind must be S, U or G");
    if (event.levels.empty() || event.levels.size() > max_event_rows) fail("invalid event row count");
    std::set<std::pair<char, Integer>> seen;
    for (const auto& level : event.levels) {
        level_valid(level, event.kind);
        if (!seen.emplace(level.side, level.price).second) fail("duplicate side/price in message");
    }
    if (event.kind == 'G' && (event.levels.size() != 1 || event.levels[0].side != 'B' ||
        event.levels[0].price != 1 || event.levels[0].quantity != 0)) fail("gap row must be B,1,0");
}
void reconcile(std::map<Integer, Integer>& consumed, const std::map<Integer, Integer>& recorded) {
    for (auto it = consumed.begin(); it != consumed.end();) {
        auto level = recorded.find(it->first);
        if (level == recorded.end()) it = consumed.erase(it);
        else { it->second = std::min(it->second, level->second); ++it; }
    }
}
Integer fee_for(Integer notional, Integer ppm) {
    // Wide intermediates avoid rejecting a representable fee solely because
    // multiplying its numerator in int64 would overflow.
    __int128 numerator = static_cast<__int128>(notional) * ppm;
    __int128 fee = (numerator + 999'999) / 1'000'000;
    if (fee > std::numeric_limits<Integer>::max()) throw std::overflow_error("fee overflows int64");
    return static_cast<Integer>(fee);
}
std::array<std::string_view, 7> split(std::string_view row) {
    std::array<std::string_view, 7> fields;
    std::size_t start = 0;
    for (std::size_t i = 0; i < fields.size(); ++i) {
        auto end = row.find(',', start);
        fields[i] = row.substr(start, end == std::string_view::npos ? end : end - start);
        if (end == std::string_view::npos) {
            if (i != fields.size() - 1) fail("CSV requires exactly seven fields");
            return fields;
        }
        start = end + 1;
    }
    fail("CSV requires exactly seven fields");
}
}

Integer checked_add(Integer a, Integer b) {
    Integer result;
    if (__builtin_add_overflow(a, b, &result)) throw std::overflow_error("addition overflows int64");
    return result;
}
Integer checked_sub(Integer a, Integer b) {
    Integer result;
    if (__builtin_sub_overflow(a, b, &result)) throw std::overflow_error("subtraction overflows int64");
    return result;
}
Integer checked_mul(Integer a, Integer b) {
    Integer result;
    if (__builtin_mul_overflow(a, b, &result)) throw std::overflow_error("multiplication overflows int64");
    return result;
}
Integer parse_integer(std::string_view value) {
    if (value.empty() || value.front() == '+' || value == "-0") fail("invalid integer syntax");
    Integer result{};
    auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
    if (parsed.ec == std::errc::result_out_of_range) throw std::overflow_error("integer overflows int64");
    if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()) fail("invalid integer syntax");
    return result;
}
Integer parse_decimal(std::string_view value, int scale) {
    if (scale < 0 || scale > 18 || value.empty()) fail("scale must be 0..18 and decimal nonempty");
    bool negative = value.front() == '-';
    if (negative) value.remove_prefix(1);
    if (value.empty()) fail("invalid decimal syntax");
    auto point = value.find('.');
    auto whole = value.substr(0, point);
    auto fraction = point == std::string_view::npos ? std::string_view{} : value.substr(point + 1);
    if (whole.empty() || (point != std::string_view::npos && fraction.empty())) fail("invalid decimal syntax");
    if (fraction.size() > static_cast<std::size_t>(scale)) {
        for (std::size_t i = static_cast<std::size_t>(scale); i < fraction.size(); ++i)
            if (fraction[i] != '0') fail("decimal violates tick/lot scale");
    }
    __int128 raw = 0;
    for (char c : whole) {
        if (c < '0' || c > '9') fail("invalid decimal syntax");
        raw = raw * 10 + c - '0';
        if (raw > static_cast<__int128>(std::numeric_limits<Integer>::max()) + 1)
            throw std::overflow_error("decimal overflows int64");
    }
    for (int i = 0; i < scale; ++i) {
        raw = raw * 10;
        if (static_cast<std::size_t>(i) < fraction.size()) {
            char c = fraction[static_cast<std::size_t>(i)];
            if (c < '0' || c > '9') fail("invalid decimal syntax");
            raw += c - '0';
        }
        if (raw > static_cast<__int128>(std::numeric_limits<Integer>::max()) + 1)
            throw std::overflow_error("decimal overflows int64");
    }
    // Validate trailing zero precision as digits too, including scale=0.
    for (char c : fraction) if (c < '0' || c > '9') fail("invalid decimal syntax");
    if (negative) raw = -raw;
    if (raw < std::numeric_limits<Integer>::min() || raw > std::numeric_limits<Integer>::max())
        throw std::overflow_error("decimal overflows int64");
    return static_cast<Integer>(raw);
}

std::vector<Event> parse_csv(std::string_view text, bool require_zero) {
    if (text.size() > max_bytes) fail("CSV exceeds 64 MiB");
    if (!text.starts_with(input_header)) fail("CSV header mismatch or missing LF");
    if (text.back() != '\n') fail("truncated CSV: missing final LF");
    text.remove_prefix(input_header.size());
    if (text.empty()) fail("CSV contains no events");
    std::vector<Event> result;
    std::size_t rows = 0;
    while (!text.empty()) {
        auto end = text.find('\n');
        auto fields = split(text.substr(0, end));
        if (++rows > max_rows) fail("CSV exceeds row bound");
        Integer id = parse_integer(fields[0]);
        Integer exchange = parse_integer(fields[1]);
        Integer receive = parse_integer(fields[2]);
        if (fields[3].size() != 1 || fields[4].size() != 1) fail("kind and side require one character");
        char kind = fields[3][0];
        Level level{fields[4][0], parse_integer(fields[5]), parse_integer(fields[6])};
        if (result.empty() || id != result.back().id) {
            if (!result.empty()) {
                event_valid(result.back());
                if (id != checked_add(result.back().id, 1)) fail("event IDs are not contiguous");
                if (receive < result.back().receive_ns) fail("receive timestamp regressed");
            } else if (require_zero && id != 0) fail("first event ID must be zero");
            result.push_back(Event{id, exchange, receive, kind, {}});
        }
        Event& event = result.back();
        if (event.exchange_ns != exchange || event.receive_ns != receive || event.kind != kind)
            fail("event rows disagree on timestamps or kind");
        if (event.levels.size() >= max_event_rows) fail("event exceeds row bound");
        event.levels.push_back(level);
        text.remove_prefix(end + 1);
    }
    event_valid(result.back());
    return result;
}

Engine::Engine() : owner_(std::this_thread::get_id()) {}
void Engine::check_owner() const {
    if (std::this_thread::get_id() != owner_) throw std::logic_error("Engine belongs to another thread");
}
bool Engine::valid() const { check_owner(); return valid_; }
Integer Engine::event_id() const { check_owner(); return id_; }
Integer Engine::receive_time() const { check_owner(); return receive_; }
Integer Engine::cash() const { check_owner(); return cash_; }
Integer Engine::inventory() const { check_owner(); return inventory_; }
Integer Engine::fees() const { check_owner(); return fees_; }

void Engine::apply(const Event& event) {
    check_owner();
    event_valid(event);
    if (event.id != checked_add(id_, 1)) fail("event ID duplicate or gap: insert explicit G and resynchronize");
    if (event.receive_ns < receive_) fail("receive timestamp regressed");
    if (valid_ && event.kind != 'G' && event.exchange_ns != -1 && exchange_ != -1 && event.exchange_ns < exchange_)
        fail("exchange timestamp regressed within contiguous session");
    if (event.kind == 'G') {
        valid_ = false; id_ = event.id; exchange_ = event.exchange_ns; receive_ = event.receive_ns;
        return;
    }
    if (!valid_ && event.kind == 'U') {
        // Absolute deltas cannot repair a missing snapshot. Keep invalid until S.
        id_ = event.id; exchange_ = event.exchange_ns; receive_ = event.receive_ns;
        return;
    }
    auto bids = event.kind == 'S' ? std::map<Integer, Integer>{} : bids_;
    auto asks = event.kind == 'S' ? std::map<Integer, Integer>{} : asks_;
    for (const auto& level : event.levels) {
        auto& side = level.side == 'B' ? bids : asks;
        if (level.quantity == 0) side.erase(level.price);
        else side[level.price] = level.quantity;
    }
    if (bids.size() > max_levels || asks.size() > max_levels) fail("book exceeds level bound");
    if (event.kind == 'S' && (bids.empty() || asks.empty())) fail("snapshot requires both sides");
    if (!bids.empty() && !asks.empty() && bids.rbegin()->first >= asks.begin()->first) fail("crossed or locked book");
    // All allocation and validation occurs on local copies, including overlay.
    auto consumed_bids = consumed_bids_;
    auto consumed_asks = consumed_asks_;
    reconcile(consumed_bids, bids); reconcile(consumed_asks, asks);
    bids_.swap(bids); asks_.swap(asks);
    consumed_bids_.swap(consumed_bids); consumed_asks_.swap(consumed_asks);
    valid_ = true; id_ = event.id; exchange_ = event.exchange_ns; receive_ = event.receive_ns;
}

Result Engine::take(std::string_view side, Integer quantity, Integer fee_ppm, Integer liquidity_ppm) {
    check_owner();
    if (side != "buy" && side != "sell") fail("order side must be buy or sell");
    if (quantity <= 0) fail("order quantity must be positive");
    if (fee_ppm < 0 || fee_ppm > 1'000'000) fail("fee_ppm must be 0..1000000");
    if (liquidity_ppm < 0 || liquidity_ppm > 1'000'000) fail("liquidity_ppm must be 0..1000000");
    Result result{{}, 0, quantity, cash_, inventory_, fees_, id_, exchange_, receive_};
    if (!valid_) return result;
    bool buy = side == "buy";
    auto consumed = buy ? consumed_asks_ : consumed_bids_;
    auto fill_level = [&](Integer price, Integer recorded) {
        Integer used = consumed.contains(price) ? consumed.at(price) : 0;
        Integer available = static_cast<Integer>(static_cast<__int128>(checked_sub(recorded, used)) * liquidity_ppm / 1'000'000);
        Integer fill_quantity = std::min(result.remaining, available);
        if (fill_quantity == 0) return;
        Integer notional = checked_mul(price, fill_quantity);
        Integer fee = fee_for(notional, fee_ppm);
        // Copy-first updates mean overflow anywhere leaves the whole order inert.
        result.cash = buy ? checked_sub(result.cash, checked_add(notional, fee)) : checked_add(result.cash, checked_sub(notional, fee));
        result.inventory = buy ? checked_add(result.inventory, fill_quantity) : checked_sub(result.inventory, fill_quantity);
        result.fees = checked_add(result.fees, fee);
        result.filled = checked_add(result.filled, fill_quantity);
        result.remaining = checked_sub(result.remaining, fill_quantity);
        consumed[price] = checked_add(used, fill_quantity);
        result.fills.push_back({price, fill_quantity, notional, fee});
    };
    if (buy) {
        for (const auto& [price, recorded] : asks_) { fill_level(price, recorded); if (!result.remaining) break; }
    } else {
        for (auto it = bids_.rbegin(); it != bids_.rend(); ++it) { fill_level(it->first, it->second); if (!result.remaining) break; }
    }
    if (buy) consumed_asks_.swap(consumed); else consumed_bids_.swap(consumed);
    cash_ = result.cash; inventory_ = result.inventory; fees_ = result.fees;
    return result;
}

std::string Engine::snapshot() const {
    check_owner();
    std::ostringstream out;
    out << output_header;
    auto prefix = [&] { out << id_ << ',' << exchange_ << ',' << receive_ << ',' << (valid_ ? 1 : 0) << ','; };
    if (!valid_ || (bids_.empty() && asks_.empty())) {
        prefix(); out << "-,0,0\n";
    } else {
        for (auto it = bids_.rbegin(); it != bids_.rend(); ++it) { prefix(); out << "B," << it->first << ',' << it->second << '\n'; }
        for (const auto& [price, quantity] : asks_) { prefix(); out << "A," << price << ',' << quantity << '\n'; }
    }
    return out.str();
}

std::string replay(std::string_view text) {
    auto events = parse_csv(text);
    Engine engine;
    std::string out(output_header);
    for (const auto& event : events) {
        engine.apply(event);
        auto state = engine.snapshot();
        out += state.substr(output_header.size());
        // Output can be larger than input, but must still have a deterministic
        // memory boundary. Streaming C++ clients can use apply/snapshot instead.
        if (out.size() > 256 * 1024 * 1024) fail("replay trace exceeds 256 MiB; stream individual events");
    }
    return out;
}

Result execute(std::string_view text, std::string_view side, Integer quantity, RecordingBounds bounds, Integer latency_ns,
               Integer fee_ppm, Integer liquidity_ppm) {
    if (bounds.end_ns < 0) fail("recording end must be nonnegative");
    if (latency_ns < 0) fail("latency must be nonnegative");
    if (side != "buy" && side != "sell") fail("order side must be buy or sell");
    if (quantity <= 0 || fee_ppm < 0 || fee_ppm > 1'000'000 || liquidity_ppm < 0 || liquidity_ppm > 1'000'000)
        fail("invalid order or scenario parameters");
    auto events = parse_csv(text);
    // Validate the complete recording contract before any hypothetical order.
    // Never infer coverage from events.back(): appending a future payload must
    // not change an already covered arrival in a quiet prefix.
    for (const auto& event : events)
        if (event.receive_ns > bounds.end_ns) fail("event exceeds declared recording coverage");
    Engine engine;
    Integer arrival = -1;
    for (std::size_t i = 0; i < events.size(); ++i) {
        if (arrival != -1 && events[i].receive_ns > arrival) return engine.take(side, quantity, fee_ppm, liquidity_ppm);
        engine.apply(events[i]);
        if (arrival == -1 && engine.valid()) arrival = checked_add(events[i].receive_ns, latency_ns);
        bool last_tie = i + 1 == events.size() || events[i + 1].receive_ns > arrival;
        if (arrival != -1 && events[i].receive_ns == arrival && last_tie) return engine.take(side, quantity, fee_ppm, liquidity_ppm);
    }
    if (arrival != -1 && arrival <= bounds.end_ns)
        return engine.take(side, quantity, fee_ppm, liquidity_ppm);
    // Arrival outside explicit coverage: no invented final book liquidity.
    return Result{{}, 0, quantity, 0, 0, 0, engine.event_id(), -1, engine.receive_time()};
}
}  // namespace queuecraft
