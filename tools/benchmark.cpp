#include "queuecraft/engine.hpp"
#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fcntl.h>
#include <fstream>
#include <iostream>
#include <limits>
#include <new>
#include <sstream>
#include <stdexcept>
#include <sys/resource.h>
#include <unistd.h>

namespace allocation_counter {
thread_local bool enabled = false;
thread_local std::uint64_t calls = 0, bytes = 0;
void account(std::size_t size) { if (enabled) { ++calls; bytes += size; } }
}
void* operator new(std::size_t size) {
    allocation_counter::account(size);
    void* pointer = std::malloc(size ? size : 1);
    if (!pointer) throw std::bad_alloc();
    return pointer;
}
void* operator new[](std::size_t size) { return ::operator new(size); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
void operator delete[](void* p, std::size_t) noexcept { std::free(p); }
void* operator new(std::size_t size, std::align_val_t alignment) {
    allocation_counter::account(size);
    void* pointer = nullptr;
    if (posix_memalign(&pointer, static_cast<std::size_t>(alignment), size ? size : 1) != 0) throw std::bad_alloc();
    return pointer;
}
void* operator new[](std::size_t size, std::align_val_t alignment) { return ::operator new(size, alignment); }
void operator delete(void* p, std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p, std::align_val_t) noexcept { std::free(p); }
void operator delete(void* p, std::size_t, std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p, std::size_t, std::align_val_t) noexcept { std::free(p); }

namespace {
using Clock = std::chrono::steady_clock;
using queuecraft::Integer;
volatile std::uint64_t observation_sink = 0;
void sink(std::uint64_t value) { observation_sink = value; }
std::string event_csv(const queuecraft::Event& event, Integer id) {
    std::ostringstream text;
    text << queuecraft::input_header;
    for (const auto& level : event.levels) text << id << ',' << event.exchange_ns << ',' << event.receive_ns << ',' << event.kind << ',' << level.side << ',' << level.price << ',' << level.quantity << '\n';
    return text.str();
}
std::string prefix_csv(const std::vector<queuecraft::Event>& events, std::size_t count) {
    std::string text(queuecraft::input_header);
    for (std::size_t i = 0; i < count; ++i) text += event_csv(events[i], static_cast<Integer>(i)).substr(queuecraft::input_header.size());
    return text;
}
void write_all(int descriptor, const std::string& bytes) {
    std::size_t sent = 0;
    while (sent < bytes.size()) {
        ssize_t written = ::write(descriptor, bytes.data() + sent, bytes.size() - sent);
        if (written < 0) { if (errno == EINTR) continue; throw std::runtime_error("persistence write failed"); }
        if (!written) throw std::runtime_error("persistence write made no progress");
        sent += static_cast<std::size_t>(written);
    }
}
bool valid_hash(const std::string& text) {
    if (text.size() != 64) return false;
    return std::all_of(text.begin(), text.end(), [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); });
}
template<class Action>
void measure(const char* name, std::size_t samples, std::size_t events_per_op, std::size_t bytes_per_op,
             bool& first, Action action) {
    std::vector<std::int64_t> durations; durations.reserve(samples);
    allocation_counter::calls = 0; allocation_counter::bytes = 0;
    auto start = Clock::now();
    for (std::size_t i = 0; i < samples; ++i) {
        auto before = Clock::now();
        allocation_counter::enabled = true;
        try { action(i); } catch (...) { allocation_counter::enabled = false; throw; }
        allocation_counter::enabled = false;
        durations.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - before).count());
    }
    auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count();
    auto calls = allocation_counter::calls, bytes = allocation_counter::bytes;
    std::sort(durations.begin(), durations.end());
    auto quantile = [&](double p) { return durations[static_cast<std::size_t>(std::ceil(p * static_cast<double>(samples))) - 1]; };
    if (!first) std::cout << ',';
    first = false;
    std::cout << "\n{\"stage\":\"" << name << "\",\"samples\":" << samples << ",\"events_per_operation\":" << events_per_op
        << ",\"bytes_per_operation\":" << bytes_per_op << ",\"elapsed_ns\":" << elapsed
        << ",\"operations_per_second\":" << static_cast<double>(samples) * 1e9 / static_cast<double>(elapsed)
        << ",\"events_per_second\":" << static_cast<double>(samples * events_per_op) * 1e9 / static_cast<double>(elapsed)
        << ",\"p50_ns\":" << quantile(0.5) << ",\"p95_ns\":" << quantile(0.95) << ",\"p99_ns\":" << quantile(0.99)
        << ",\"p999_ns\":" << quantile(0.999) << ",\"allocation_calls\":" << calls << ",\"allocated_bytes\":" << bytes << '}';
}
}

int main(int argc, char** argv) {
    try {
        if (argc != 5) throw std::invalid_argument("usage: cpp-benchmark INPUT.csv FRESH_TEMP_DIRECTORY INPUT_SHA256 SOURCE_TREE_SHA256");
        if (!valid_hash(argv[3]) || !valid_hash(argv[4])) throw std::invalid_argument("hash arguments must be SHA256 hex supplied by runner");
        std::filesystem::path input(argv[1]), temporary(argv[2]);
        if (std::filesystem::file_size(input) > queuecraft::max_bytes) throw std::invalid_argument("input too large");
        std::ifstream file(input, std::ios::binary);
        if (!file) throw std::runtime_error("input read failed");
        std::string source; std::array<char, 64 * 1024> buffer{};
        while (file) {
            file.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
            auto bytes = static_cast<std::size_t>(file.gcount());
            if (bytes > queuecraft::max_bytes - source.size()) throw std::invalid_argument("input exceeds bound during read");
            source.append(buffer.data(), bytes);
        }
        if (file.bad()) throw std::runtime_error("input read failed");
        auto events = queuecraft::parse_csv(source);
        queuecraft::Engine validator; for (const auto& event : events) validator.apply(event);
        if (events.empty() || events.front().kind != 'S') throw std::invalid_argument("benchmark requires initial full snapshot");
        auto message = event_csv(events.front(), 0);
        auto count = std::min<std::size_t>(10, events.size());
        auto short_trace = prefix_csv(events, count);
        if (!std::filesystem::create_directory(temporary)) throw std::invalid_argument("temp directory must be fresh");
        auto persistence = temporary / "append.raw";
        int descriptor = ::open(persistence.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_APPEND, 0600);
        if (descriptor < 0) throw std::runtime_error("cannot create persistence file");
        bool first = true;
        std::cout << "{\"schema\":1,\"input_sha256\":\"" << argv[3] << "\",\"source_tree_sha256\":\"" << argv[4]
            << "\",\"clock\":\"steady_clock nanoseconds\",\"threads\":1,\"allocation_instrumentation\":\"global new/new[] requested calls and bytes; enabled inside measured operation; instrumentation overhead included\","
            << "\"durability\":\"append uses unbuffered write syscall; fsync stage appends then fsync each sample; no physical-device/F_FULLFSYNC guarantee\","
            << "\"tail_method\":\"nearest rank; p999 has10 tail observations at10000 samples; repeated same recording is a systems microbenchmark\",\"stages\":[";
        measure("real_snapshot_parser", 10'000, 1, message.size(), first, [&](std::size_t) { auto value = queuecraft::parse_csv(message); sink(value.front().levels.size()); });
        queuecraft::Engine burst;
        burst.apply({0, -1, 0, 'S', {{'B', 99, 1'000}, {'A', 101, 1'000}, {'A', 102, 1'000}}});
        queuecraft::Event update{0, -1, 0, 'U', {{'A', 101, 1'000}}};
        measure("synthetic_burst_absolute_update", 20'000, 1, 0, first, [&](std::size_t i) {
            update.id = static_cast<Integer>(i + 1); update.receive_ns = static_cast<Integer>(i + 1);
            update.levels[0].quantity = 1'000 + static_cast<Integer>(i % 100);
            burst.apply(update); sink(static_cast<std::uint64_t>(burst.event_id()));
        });
        measure("persistence_append_write", 10'000, 1, message.size(), first, [&](std::size_t) { write_all(descriptor, message); });
        measure("persistence_append_fsync", 10'000, 1, message.size(), first, [&](std::size_t) {
            write_all(descriptor, message); if (::fsync(descriptor) != 0) throw std::runtime_error("fsync failed");
        });
        if (::close(descriptor) != 0) throw std::runtime_error("close failed");
        measure("real_ten_event_complete_trace_replay", 10'000, count, short_trace.size(), first, [&](std::size_t) { auto value = queuecraft::replay(short_trace); sink(value.size()); });
        measure("real_ten_event_parse_book_ioc_trace", 10'000, count, short_trace.size(), first, [&](std::size_t) {
            auto parsed = queuecraft::parse_csv(short_trace); queuecraft::Engine engine;
            std::size_t observed = 0;
            for (const auto& event : parsed) { engine.apply(event); auto result = engine.take("buy", 1, 1'000, 500'000); observed += result.fills.size(); observed += engine.snapshot().size(); }
            sink(observed);
        });
        rusage usage{}; if (::getrusage(RUSAGE_SELF, &usage) != 0) throw std::runtime_error("getrusage failed");
#ifdef __APPLE__
        std::uint64_t rss_bytes = static_cast<std::uint64_t>(usage.ru_maxrss);
#else
        std::uint64_t rss_bytes = static_cast<std::uint64_t>(usage.ru_maxrss) * 1024;
#endif
        std::cout << "\n],\"peak_process_rss_bytes\":" << rss_bytes << ",\"peak_rss_scope\":\"whole process including source loading, parsed archive and every stage; OS high-water mark\",\"status\":\"pass\"}\n";
        // This is the exact disposable file created by this run, never input.
        if (::unlink(persistence.c_str()) != 0) throw std::runtime_error("temporary persistence cleanup failed");
        std::filesystem::remove(temporary);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "cpp-benchmark: " << error.what() << '\n';
        return 2;
    }
}
