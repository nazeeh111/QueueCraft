# Initial sanitizer availability failure

The first executed `make sanitize` used `ASAN_OPTIONS=detect_leaks=1`. The Apple runtime aborted before tests with:

```
AddressSanitizer: detect_leaks is not supported on this platform.
make: *** [sanitize] Abort trap: 6
```

The supported run disables LeakSanitizer and retains AddressSanitizer plus UndefinedBehaviorSanitizer. Its actual output is `cpp-asan-ubsan.log`. This failure was a runtime capability limit; no leak-check result is claimed. ThreadSanitizer ran separately in `cpp-tsan.log`.

An additional attempted coverage-guided fuzz build failed because the installed Xcode toolchain lacks `libclang_rt.fuzzer_osx.a`; the exact compiler/linker output remains in `cpp-libfuzzer.log`. The C++ unit executable independently executes 12,000 seeded parser mutations under both supported sanitizers. The optional `make fuzz` target is usable with a toolchain that ships libFuzzer.
