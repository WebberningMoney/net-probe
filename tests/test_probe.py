import asyncio
import probe

SAMPLE_OK = """PING 1.1.1.1 (1.1.1.1): 56 data bytes
64 bytes from 1.1.1.1: icmp_seq=0 ttl=57 time=12.345 ms

--- 1.1.1.1 ping statistics ---
1 packets transmitted, 1 packets received, 0.0% packet loss"""
SAMPLE_FAIL = """PING 10.255.255.1 (10.255.255.1): 56 data bytes

--- 10.255.255.1 ping statistics ---
1 packets transmitted, 0 packets received, 100.0% packet loss"""


def test_parse():
    assert probe.parse_ping_output(SAMPLE_OK) == 12.345
    assert probe.parse_ping_output(SAMPLE_FAIL) is None
    assert probe.parse_ping_output("time<1 ms") == 1.0


def test_cmd_uses_macos_flags():
    assert probe.build_ping_cmd("1.1.1.1", 1) == \
        ["ping", "-n", "-c", "1", "-W", "1000", "-t", "2", "1.1.1.1"]


def _run(coro):
    return asyncio.run(coro)


def test_ping_once_with_fake_runner():
    async def ok(cmd): return 0, SAMPLE_OK
    async def fail(cmd): return 2, SAMPLE_FAIL
    async def boom(cmd): raise FileNotFoundError("ping")
    assert _run(probe.ping_once("1.1.1.1", 1, ok)) == 12.345
    assert _run(probe.ping_once("x", 1, fail)) is None
    assert _run(probe.ping_once("x", 1, boom)) is None
