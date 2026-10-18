# Contributing to msgpackc

Thank you for helping! This project follows the conventions of MicroPython
itself ([CODECONVENTIONS.md](https://github.com/micropython/micropython/blob/master/CODECONVENTIONS.md)
and [CONTRIBUTING.md](https://github.com/micropython/micropython/blob/master/CONTRIBUTING.md)),
so that the module reads like any other part of MicroPython and could be
proposed upstream one day.

## Reporting a problem

Open an issue with:

- the MicroPython version and board (`import os; os.uname()`);
- the smallest code that shows the problem, and the data if it is about
  unpacking (as `bytes` or hex);
- what you expected and what happened (the full traceback).

If the problem is a crash or a security issue caused by crafted data, see
[SECURITY.md](SECURITY.md) instead.

## Making a change

1. Set up the tools once: `make setup` (see [docs/INSTALL.md](docs/INSTALL.md)).
2. Make your change. Keep it small and focused: one fix or one feature per
   pull request.
3. Add or update tests (see below). A fix comes with a test that fails
   without it.
4. Run the checks:
   ```bash
   make lint          # code style
   make test-quick    # all host tests, short version (make test for the full one)
   make test-sanitize # if you changed C code
   ```
5. If you can, run the tests on a board too (`make test-device`, see
   [docs/HARDWARE_TESTING.md](docs/HARDWARE_TESTING.md)), and say on which
   board in the pull request.
6. Update the documentation (`docs/USAGE.md` for anything visible from
   Python) and `CHANGELOG.md`.

## Code style

- **C**: the MicroPython style, enforced with its own uncrustify
  configuration: `make format` formats, `make lint` checks. In short:
  4 spaces, `static` for everything that is not exported, `MP_ERROR_TEXT()`
  around every exception message, `mp_` and `MP_` names only for MicroPython
  APIs (this module uses `msgpackc_`, `pk_` and `up_`).
- **Python**: formatted with `ruff format` and checked with `ruff check`
  (the versions MicroPython uses, pinned in `pyproject.toml`).
- Comments explain *why*, not what. English everywhere.
- Code must build without warnings on every port: the unix port builds with
  `-Werror`.

## Tests

| change | test to add |
|---|---|
| a behaviour visible from Python | a case in `tests/mp/` (self-checking, with a `.exp` file) |
| packing or unpacking | also check `tests/diff/diff_umsgpack.py` still passes, or document the new difference in `docs/USAGE.md` |
| a crash or memory error | a reproducer in `tests/mp/msgpackc_safety.py` |

The files of `tests/mp/` follow the MicroPython test format: a script and
its expected output, run by `micropython/tests/run-tests.py` on the unix port
and on boards. Generate the `.exp` file by running the test, then **read it
and check every line by hand** before committing it:

```bash
build/unix-standard/micropython tests/mp/msgpackc_new.py > tests/mp/msgpackc_new.py.exp
```

Tests must also pass on small boards: keep their memory use low (or print
`SKIP` when the heap is too small, as `msgpackc_large.py` does).

## Commits

As in MicroPython:

- The first line starts with the path of what changes, then a short
  description ending with a period, at most 72 characters:
  ```
  cmodules/msgpackc: Validate the length of ext data before reading it.
  ```
  ```
  docs/INSTALL: Explain how to find the serial port on WSL.
  ```
- Then a blank line and, if useful, an explanation of the why, wrapped at
  75 characters.
- **Sign off** every commit (`git commit -s`), which adds
  `Signed-off-by: Your Name <your@email>`. By signing off you certify the
  [Developer Certificate of Origin](https://developercertificate.org/): you
  wrote the change, or have the right to submit it under the project's MIT
  license.

## Licence

msgpackc is MIT licensed (see [LICENSE](LICENSE)). Contributions are accepted
under the same licence. Code taken from elsewhere must have a compatible
licence and keep its copyright notice.
