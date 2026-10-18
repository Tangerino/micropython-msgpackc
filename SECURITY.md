# Security

msgpackc is designed to unpack untrusted data (messages from a network, a
radio, a serial line) on small devices. Bad data must only ever raise an
exception: a crash, a hang, a read or write outside a buffer, or memory use
far beyond the size of the data is a bug, and a security issue if it can be
triggered remotely.

## Reporting

Please report such issues **privately**, through GitHub's
[private vulnerability reporting](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
of this repository, rather than in a public issue. Include the data that
triggers the problem (hex is fine), the MicroPython version and the board.

You should get an answer within a week. Once fixed, the issue is disclosed in
the release notes, with credit to you unless you prefer otherwise.

## Supported versions

Fixes are made on the latest release.
