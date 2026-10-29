#include "queuecraft/engine.hpp"
#include <array>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>

int main(int argc, char** argv) {
    try {
        if (argc < 3 || argc > 8) throw std::invalid_argument("usage: queuecraft-core INPUT.csv OUTPUT_DIRECTORY [buy|sell] [quantity] [latency_ns] [fee_ppm] [liquidity_ppm]");
        std::filesystem::path input(argv[1]), output(argv[2]);
        if (std::filesystem::file_size(input) > queuecraft::max_bytes) throw std::invalid_argument("input exceeds 64 MiB");
        std::ifstream stream(input, std::ios::binary);
        if (!stream) throw std::runtime_error("cannot read input");
        // Bound the actual read, including a file that grows after stat().
        std::string text;
        std::array<char, 64 * 1024> buffer{};
        while (stream) {
            stream.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
            auto count = static_cast<std::size_t>(stream.gcount());
            if (count > queuecraft::max_bytes - text.size()) throw std::invalid_argument("input exceeds 64 MiB during read");
            text.append(buffer.data(), count);
        }
        if (stream.bad()) throw std::runtime_error("input read failed");
        std::string trace = queuecraft::replay(text);
        queuecraft::Result result;
        bool order = argc >= 4;
        if (order) result = queuecraft::execute(text, argv[3], argc >= 5 ? queuecraft::parse_integer(argv[4]) : 1,
            argc >= 6 ? queuecraft::parse_integer(argv[5]) : 0, argc >= 7 ? queuecraft::parse_integer(argv[6]) : 0,
            argc >= 8 ? queuecraft::parse_integer(argv[7]) : 1'000'000);
        if (!std::filesystem::create_directory(output)) throw std::runtime_error("output exists; choose a fresh directory");
        auto write = [&](const char* name, const std::string& contents) {
            std::ofstream file(output / name, std::ios::binary);
            file << contents;
            file.close();
            if (!file) throw std::runtime_error("output write failed; incomplete output retained");
        };
        write("books.csv", trace);
        if (order) {
            std::ostringstream fills;
            fills << "event,price,quantity,notional,fee\n";
            for (const auto& fill : result.fills) fills << result.event << ',' << fill.price << ',' << fill.quantity << ',' << fill.notional << ',' << fill.fee << '\n';
            write("fills.csv", fills.str());
            std::ostringstream ledger;
            ledger << "event,exchange_ns,receive_ns,filled,remaining,cash,inventory,fees\n" << result.event << ',' << result.exchange_ns << ',' << result.receive_ns << ','
                << result.filled << ',' << result.remaining << ',' << result.cash << ',' << result.inventory << ',' << result.fees << '\n';
            write("ledger.csv", ledger.str());
        }
        std::cout << "books=" << (output / "books.csv").string() << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "queuecraft-core: " << error.what() << '\n';
        return 2;
    }
}
