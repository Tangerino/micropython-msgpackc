# Changelog

All notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-18

First release.

- C module `msgpackc` for MicroPython v1.29: `dumps`, `dump`, `loads`,
  `load`, with umsgpack's options and exceptions and byte-identical output.
- `ext_serializable` decorator for user classes and built-in types,
  compatible with umsgpack's extension modules.
- `Unpacker`: incremental decoding with `feed()`, `next_raw()`, `reset()`
  and `max_buffer_size`.
- `ALoader` (Python, `python/msgpackc_aio.py`): asyncio decoding.
- `umsgpack` compatibility package (`python/umsgpack/`).
- Nesting limited to 32 levels (`MSGPACKC_MAX_DEPTH`).
- Build, flash, test and benchmark tooling for the unix port and ESP32
  boards, with a repo-local ESP-IDF v5.5.2.
- Ready-made firmware in each GitHub release, built by CI
  (`.github/workflows/release.yml`).
