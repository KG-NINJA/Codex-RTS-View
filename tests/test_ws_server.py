import unittest

import ws_server


class TestWsServer(unittest.TestCase):
    def test_ws_accept_key_rfc_example(self):
        # RFC 6455 example
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        accept = ws_server.ws_accept_key(key)
        self.assertEqual(accept, "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_encode_ws_text_small_payload(self):
        b = ws_server.encode_ws_text("hi")
        self.assertEqual(b[0], 0x81)  # FIN + text
        self.assertEqual(b[1], 2)
        self.assertEqual(b[2:], b"hi")

    def test_encode_ws_text_126_payload(self):
        s = "a" * 126
        b = ws_server.encode_ws_text(s)
        self.assertEqual(b[0], 0x81)
        self.assertEqual(b[1], 126)
        self.assertEqual(int.from_bytes(b[2:4], "big"), 126)
        self.assertEqual(b[4:], s.encode("utf-8"))

    def test_parse_http_headers_basic(self):
        req = (
            b"GET / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Key: abc\r\n"
            b"\r\n"
        )
        h = ws_server.parse_http_headers(req)
        self.assertEqual(h["host"], "localhost")
        self.assertEqual(h["upgrade"], "websocket")
        self.assertEqual(h["connection"], "Upgrade")
        self.assertEqual(h["sec-websocket-key"], "abc")


if __name__ == "__main__":
    unittest.main()
