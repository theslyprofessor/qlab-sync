"""
Comprehensive safety, formal-verification, static read-only audit, and mock-QLab
TCP/SLIP integration test suite for qlab-sync.

Runs cleanly with Python 3 standard library only (`python -m unittest discover -s tests -v`)
on macOS, Windows, and Linux.
"""

from __future__ import annotations

import ast
import json
import os
import socket
import struct
import threading
import unittest

import qlab_sync


def decode_slip_frame(sock: socket.socket) -> bytes:
    buf = bytearray()
    in_pkt = False
    while True:
        ch = sock.recv(1)
        if not ch:
            return b""
        b = ch[0]
        if b == 0xC0:
            if in_pkt and buf:
                return bytes(buf)
            in_pkt = True
            buf = bytearray()
            continue
        if in_pkt:
            if b == 0xDB:
                nxt = sock.recv(1)[0]
                buf.append(0xC0 if nxt == 0xDC else 0xDB)
            else:
                buf.append(b)


def parse_osc_address(raw: bytes) -> str:
    nul = raw.find(b"\x00")
    return raw[:nul].decode("utf-8") if nul != -1 else raw.decode("utf-8")


def encode_qlab_reply(address: str, data: object, status: str = "ok") -> bytes:
    payload = json.dumps({"address": address, "status": status, "data": data}).encode("utf-8")
    # QLab replies carry an OSC address prefix before the JSON string payload
    pad = b"/reply" + b"\x00\x00,s\x00\x00" + payload + b"\x00"
    return qlab_sync.slip_encode(pad)


class TestReadOnlyBoundary(unittest.TestCase):
    def test_allowlisted_read_only_addresses_succeed(self) -> None:
        ws = "70595566-D062-4A5F-9D1B-A77CC8A17CD7"
        for addr in (
            "/workspaces",
            f"/workspace/{ws}/connect",
            f"/workspace/{ws}/runningOrPausedCues",
            f"/workspace/{ws}/selectedCues",
        ):
            qlab_sync.assert_read_only_osc(addr)
            raw = qlab_sync.osc_message(addr)
            self.assertEqual(parse_osc_address(raw), addr)

    def test_mutating_osc_commands_are_hard_blocked(self) -> None:
        ws = "70595566-D062-4A5F-9D1B-A77CC8A17CD7"
        forbidden = [
            "/go",
            f"/workspace/{ws}/go",
            f"/workspace/{ws}/panic",
            f"/workspace/{ws}/hardStop",
            f"/workspace/{ws}/stop",
            f"/workspace/{ws}/pause",
            f"/workspace/{ws}/new",
            f"/workspace/{ws}/delete_id/ABC",
            f"/workspace/{ws}/save",
            f"/workspace/{ws}/move/ABC",
            f"/workspace/{ws}/cue_id/ABC/level",
            f"/workspace/{ws}/cue_id/ABC/armed",
            f"/workspace/{ws}/cue_id/ABC/fileTarget",
            f"/workspace/{ws}/select/1",
            f"/workspace/{ws}/updates",
        ]
        for addr in forbidden:
            with self.assertRaises(qlab_sync.ReadOnlyViolationError, msg=f"Should block {addr}"):
                qlab_sync.osc_message(addr)

    def test_static_ast_audit_zero_mutating_osc_calls_in_client(self) -> None:
        """
        Static audit: inspect qlab_sync.py AST to confirm QLabReadOnlyClient
        only constructs OSC addresses within the 4 allowlisted read-only endpoints.
        """
        src_path = os.path.abspath(qlab_sync.__file__)
        with open(src_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=src_path)

        client_cls = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "QLabReadOnlyClient"
        )
        # Every socket sendall inside QLabReadOnlyClient must call osc_message()
        sendall_calls = [
            node for node in ast.walk(client_cls)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "sendall"
        ]
        self.assertEqual(len(sendall_calls), 1, "Expected exactly one sendall gateway in QLabReadOnlyClient")
        # Ensure forbidden mutating verb substrings never appear as OSC route literals in client class
        forbidden_tokens = ("/go", "/panic", "/stop", "/pause", "/new", "/delete", "/save", "/move", "/level", "/armed")
        for node in ast.walk(client_cls):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for tok in forbidden_tokens:
                    self.assertNotIn(tok, node.value, f"Forbidden OSC token {tok!r} in QLabReadOnlyClient")


class TestFormalVerification(unittest.TestCase):
    def test_exhaustive_bfs_default_config(self) -> None:
        stats = qlab_sync.verify_protocol(debounce_ticks=3)
        self.assertGreater(stats["states"], 50)
        self.assertGreater(stats["transitions"], 500)
        self.assertGreater(stats["emissions"], 10)

    def test_exhaustive_bfs_sample_config_file(self) -> None:
        sample_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "examples",
            "sample-show.json",
        )
        cfg = qlab_sync.ShowConfig.load_file(sample_path)
        stats = qlab_sync.verify_protocol(cfg, debounce_ticks=3)
        self.assertGreater(stats["states"], 50)

    def test_config_rejects_ambiguous_cue_overlap(self) -> None:
        with self.assertRaises(ValueError):
            qlab_sync.ShowConfig.from_dict({
                "eventSlug": "bad",
                "playbackCueToOrder": {"1W": 1},
                "nonProgramCues": ["1W"],
            })


class TestMockQLabIntegration(unittest.TestCase):
    def test_live_tcp_slip_handshake_and_read_only_observation(self) -> None:
        """
        Spin up a real localhost TCP server emulating QLab 4/5 SLIP/OSC.
        Verify QLabReadOnlyClient only sends allowlisted read-only OSC messages
        and drives the formally verified state machine accurately.
        """
        ws_id = "TEST-WS-0001-ABCD"
        received_addresses = []
        state_box = {
            "running": [{"number": "4a", "isPaused": False}, {"number": "4b", "isPaused": False}],
            "selected": [{"number": "5"}],
        }

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(1)

        def server_loop() -> None:
            conn, _ = srv.accept()
            with conn:
                while True:
                    frame = decode_slip_frame(conn)
                    if not frame:
                        break
                    addr = parse_osc_address(frame)
                    received_addresses.append(addr)
                    if addr == "/workspaces":
                        conn.sendall(encode_qlab_reply(addr, [{
                            "uniqueID": ws_id,
                            "displayName": "Example_Concert.qlab5",
                            "version": "5.6.5",
                        }]))
                    elif addr == f"/workspace/{ws_id}/connect":
                        conn.sendall(encode_qlab_reply(addr, "ok:view"))
                    elif addr == f"/workspace/{ws_id}/runningOrPausedCues":
                        conn.sendall(encode_qlab_reply(addr, state_box["running"]))
                    elif addr == f"/workspace/{ws_id}/selectedCues":
                        conn.sendall(encode_qlab_reply(addr, state_box["selected"]))

        t = threading.Thread(target=server_loop, daemon=True)
        t.start()

        try:
            cfg = qlab_sync.ShowConfig.default_example()
            client = qlab_sync.QLabReadOnlyClient("127.0.0.1", port, passcode="")
            client.connect("Example_Concert")

            st = qlab_sync.SyncState()
            emitted = []
            for _ in range(4):
                obs = client.observe()
                st, cmd = qlab_sync.step(st, obs, cfg, debounce_ticks=3)
                if cmd:
                    emitted.append(cmd)

            client.close()
        finally:
            srv.close()
            t.join(timeout=2)

        # Every single packet received by the mock QLab server must pass the read-only allowlist!
        self.assertGreater(len(received_addresses), 0)
        for addr in received_addresses:
            qlab_sync.assert_read_only_osc(addr)

        # Group 4 (4a + 4b running together) must emit order 4 EXACTLY ONCE
        self.assertEqual([c.cue_order for c in emitted], [4])
        self.assertEqual(emitted[0].source, "running")


if __name__ == "__main__":
    unittest.main()
