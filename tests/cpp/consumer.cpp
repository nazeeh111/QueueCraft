#include <queuecraft/engine.hpp>
#include <iostream>

// This consumer needs only the installed public header and static library.
int main() {
    queuecraft::Engine engine;
    engine.apply({0, -1, 100, 'S', {{'B', 499, 10}, {'A', 501, 8}}});
    auto result = engine.take("buy", 3, 1'000);
    if (result.filled != 3 || result.cash != -1505 || result.inventory != 3 || result.fees != 2) return 1;
    std::cout << "installed C++ SDK: filled=" << result.filled << " cash=" << result.cash << " fees=" << result.fees << '\n';
    return 0;
}
