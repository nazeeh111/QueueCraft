CXX = clang++
AR = ar
CPPFLAGS = -Iinclude
CXXFLAGS = -std=c++20 -O2 -Wall -Wextra -Wpedantic -pthread
BUILD = build
PREFIX ?= /usr/local

.PHONY: all test sanitize tsan fuzz install clean
all: $(BUILD)/libqueuecraft.a $(BUILD)/queuecraft-core

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/engine.o: src/engine.cpp include/queuecraft/engine.hpp | $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c src/engine.cpp -o $@

$(BUILD)/libqueuecraft.a: $(BUILD)/engine.o
	$(AR) rcs $@ $<

$(BUILD)/queuecraft-core: src/main.cpp include/queuecraft/engine.hpp $(BUILD)/libqueuecraft.a | $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) src/main.cpp $(BUILD)/libqueuecraft.a -o $@

install: all
	mkdir -p $(DESTDIR)$(PREFIX)/include/queuecraft $(DESTDIR)$(PREFIX)/lib $(DESTDIR)$(PREFIX)/bin
	cp include/queuecraft/engine.hpp $(DESTDIR)$(PREFIX)/include/queuecraft/
	cp $(BUILD)/libqueuecraft.a $(DESTDIR)$(PREFIX)/lib/
	cp $(BUILD)/queuecraft-core $(DESTDIR)$(PREFIX)/bin/

$(BUILD)/core-tests: src/engine.cpp tests/cpp/test_engine.cpp include/queuecraft/engine.hpp | $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) src/engine.cpp tests/cpp/test_engine.cpp -o $@

$(BUILD)/cpp-benchmark: tools/benchmark.cpp include/queuecraft/engine.hpp $(BUILD)/libqueuecraft.a | $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) tools/benchmark.cpp $(BUILD)/libqueuecraft.a -o $@

test: $(BUILD)/core-tests
	$(BUILD)/core-tests

sanitize: | $(BUILD)
	$(CXX) $(CPPFLAGS) -std=c++20 -O1 -g -Wall -Wextra -pthread -fsanitize=address,undefined -fno-omit-frame-pointer src/engine.cpp tests/cpp/test_engine.cpp -o $(BUILD)/core-sanitize
	ASAN_OPTIONS=detect_leaks=0 $(BUILD)/core-sanitize

tsan: | $(BUILD)
	$(CXX) $(CPPFLAGS) -std=c++20 -O1 -g -Wall -Wextra -pthread -fsanitize=thread src/engine.cpp tests/cpp/test_engine.cpp -o $(BUILD)/core-tsan
	$(BUILD)/core-tsan

fuzz: | $(BUILD)
	$(CXX) $(CPPFLAGS) -std=c++20 -O1 -g -pthread -fsanitize=fuzzer,address,undefined -fno-omit-frame-pointer src/engine.cpp tests/cpp/fuzz_parser.cpp -o $(BUILD)/parser-fuzz
	mkdir -p $(BUILD)/fuzz-corpus
	printf 'event,exchange_ns,receive_ns,kind,side,price,quantity\n0,-1,0,S,B,99,10\n0,-1,0,S,A,101,10\n' > $(BUILD)/fuzz-corpus/snapshot.csv
	$(BUILD)/parser-fuzz -runs=20000 -max_len=4096 $(BUILD)/fuzz-corpus

clean:
	rm -f $(BUILD)/queuecraft-core $(BUILD)/core-tests $(BUILD)/core-sanitize $(BUILD)/core-tsan $(BUILD)/engine.o $(BUILD)/libqueuecraft.a $(BUILD)/parser-fuzz
