#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace queuecraft {
using Integer = std::int64_t;
inline constexpr std::size_t max_bytes = 64 * 1024 * 1024;
inline constexpr std::size_t max_rows = 1'000'000;
inline constexpr std::size_t max_event_rows = 20'000;
inline constexpr std::size_t max_levels = 10'000;
inline constexpr std::string_view input_header = "event,exchange_ns,receive_ns,kind,side,price,quantity\n";
inline constexpr std::string_view output_header = "event,exchange_ns,receive_ns,valid,side,price,quantity\n";

// All public integer operations reject overflow. A decimal scale is the number
// of fractional decimal places, not a floating point multiplier.
Integer checked_add(Integer a, Integer b);
Integer checked_sub(Integer a, Integer b);
Integer checked_mul(Integer a, Integer b);
Integer parse_integer(std::string_view value);
Integer parse_decimal(std::string_view value, int scale);

struct Level {
    char side{};  // B bid, A ask
    Integer price{};
    Integer quantity{};
};
struct Event {
    Integer id{};
    Integer exchange_ns{-1};  // -1 means not supplied by archive
    Integer receive_ns{};
    char kind{};  // S complete snapshot, U absolute updates, G gap
    std::vector<Level> levels;
};

// Bounded strict CSV. File-level parsing requires IDs to start at zero;
// incremental applications pass require_zero=false and Engine checks continuity.
std::vector<Event> parse_csv(std::string_view text, bool require_zero = true);

struct Fill {
    Integer price{};
    Integer quantity{};
    Integer notional{};
    Integer fee{};
};
struct Result {
    std::vector<Fill> fills;
    Integer filled{};
    Integer remaining{};
    Integer cash{};
    Integer inventory{};
    Integer fees{};
    Integer event{-1};
    Integer exchange_ns{-1};
    Integer receive_ns{-1};
};

// A single-writer state machine. The constructing thread owns every operation.
// Calls from another thread are rejected before reading or changing mutable
// state. Synchronization/dispatch is the embedding application's responsibility.
class Engine {
public:
    Engine();
    Engine(const Engine&) = delete;
    Engine& operator=(const Engine&) = delete;
    void apply(const Event& event);
    Result take(std::string_view side, Integer quantity, Integer fee_ppm = 0,
                Integer liquidity_ppm = 1'000'000);
    std::string snapshot() const;
    bool valid() const;
    Integer event_id() const;
    Integer receive_time() const;
    Integer cash() const;
    Integer inventory() const;
    Integer fees() const;
private:
    void check_owner() const;
    std::thread::id owner_;
    bool valid_{};
    Integer id_{-1};
    Integer exchange_{-1};
    Integer receive_{-1};
    Integer cash_{};
    Integer inventory_{};
    Integer fees_{};
    std::map<Integer, Integer> bids_, asks_, consumed_bids_, consumed_asks_;
};

std::string replay(std::string_view text);
// Immediate IOC observes first valid book, arrives after latency, applies all
// observations tied with arrival first. No fill beyond recorded coverage.
Result execute(std::string_view text, std::string_view side, Integer quantity,
               Integer latency_ns = 0, Integer fee_ppm = 0,
               Integer liquidity_ppm = 1'000'000);
}  // namespace queuecraft
