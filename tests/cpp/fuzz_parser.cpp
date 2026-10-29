#include "queuecraft/engine.hpp"
#include <cstddef>
#include <cstdint>
#include <exception>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    try {
        auto events = queuecraft::parse_csv(std::string_view(reinterpret_cast<const char*>(data), size));
        queuecraft::Engine engine;
        for (const auto& event : events) {
            engine.apply(event);
            if (engine.valid()) {
                engine.take("buy", 3, 1'000, 500'000);
                engine.take("sell", 2, 2'000, 1'000'000);
            }
        }
    } catch (const std::exception&) {}
    return 0;
}
