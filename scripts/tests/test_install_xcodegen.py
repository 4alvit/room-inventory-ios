"""XcodeGen acquisition boundaries with no network or native tool execution."""
from __future__ import annotations

from contextlib import nullcontext, redirect_stdout
from email.message import Message
from email.utils import formatdate
import hashlib
import importlib.util
import io
from pathlib import Path
import signal
import ssl
import tempfile
import time
import unittest
from unittest.mock import Mock, call, patch
import urllib.error


SPEC = importlib.util.spec_from_file_location(
    "install_xcodegen_under_test", Path(__file__).resolve().parents[1] / "install-xcodegen.py"
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)
PAYLOAD = b"injected archive bytes, never extracted"
PAYLOAD_DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Response:
    def __init__(self, payload=PAYLOAD, before_read=None):
        self.payload = payload
        self.before_read = before_read
        self.read_sizes = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, size):
        self.read_sizes.append(size)
        if self.before_read is not None:
            self.before_read()
        return self.payload[:size]


def headers(*values):
    result = Message()
    for value in values:
        result["Retry-After"] = value
    return result


def http_error(status, *retry_after):
    body = io.BytesIO(b"injected error response")
    error = urllib.error.HTTPError(installer.URL, status, "injected", headers(*retry_after), body)
    return error, body


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.sleep = Mock(side_effect=self.clock.advance)
        self.opener = Mock()
        self.stdout = io.StringIO()
        self.wall_clock = Mock(return_value=1_700_000_000.0)
        self.timer = self.enterContext(patch.object(installer, "acquisition_deadline", side_effect=lambda _: nullcontext()))
        self.enterContext(patch.object(installer, "DIGEST", PAYLOAD_DIGEST))
        self.enterContext(patch.object(installer.urllib.request, "urlopen", side_effect=AssertionError("real network forbidden")))
        self.enterContext(patch.object(installer.subprocess, "check_output", side_effect=AssertionError("native execution forbidden")))

    def download(self, **kwargs):
        with redirect_stdout(self.stdout):
            return installer.download_payload(
                opener=self.opener, clock=self.clock, sleep=self.sleep,
                wall_clock=self.wall_clock, **kwargs
            )

    def test_direct_success_is_one_bounded_closed_read_without_stdout(self):
        response = Response()
        self.opener.return_value = response
        self.assertEqual(self.download(), PAYLOAD)
        self.opener.assert_called_once_with(installer.URL, timeout=60.0)
        self.assertEqual(response.read_sizes, [32 * 1024 * 1024 + 1])
        self.assertTrue(response.closed)
        self.sleep.assert_not_called()
        self.timer.assert_called_once_with(60.0)
        self.assertEqual(self.stdout.getvalue(), "")

    def test_each_transient_status_retries_only_after_closing_error(self):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                error, body = http_error(status)
                response = Response()
                self.opener.reset_mock(side_effect=True)
                self.opener.side_effect = [error, response]
                def wait(seconds):
                    self.assertTrue(body.closed)
                    self.clock.advance(seconds)
                self.sleep.reset_mock()
                self.sleep.side_effect = wait
                self.assertEqual(self.download(), PAYLOAD)
                self.assertEqual(self.opener.call_count, 2)
                self.sleep.assert_called_once_with(1.0)
                self.assertTrue(response.closed)

    def test_two_retries_share_one_budget_and_use_one_then_two_second_backoff(self):
        first, first_body = http_error(504)
        second, second_body = http_error(503)
        response = Response()
        self.opener.side_effect = [first, second, response]
        self.assertEqual(self.download(), PAYLOAD)
        self.assertEqual(self.sleep.call_args_list, [call(1.0), call(2.0)])
        self.assertEqual([c.kwargs["timeout"] for c in self.opener.call_args_list], [60.0, 59.0, 57.0])
        self.assertTrue(first_body.closed and second_body.closed and response.closed)
        self.timer.assert_called_once_with(60.0)

    def test_exhausted_transient_error_propagates_closed_without_fourth_attempt(self):
        failures = [http_error(504) for _ in range(3)]
        self.opener.side_effect = [error for error, _ in failures]
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.download()
        self.assertIs(caught.exception, failures[-1][0])
        self.assertEqual(self.opener.call_count, 3)
        self.assertEqual(self.sleep.call_args_list, [call(1.0), call(2.0)])
        self.assertTrue(all(body.closed for _, body in failures))

    def test_nontransient_http_errors_are_terminal_and_closed(self):
        for status in (400, 401, 403, 404, 410, 501):
            with self.subTest(status=status):
                error, body = http_error(status)
                self.opener.reset_mock(side_effect=True)
                self.opener.side_effect = error
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.download()
                self.assertIs(caught.exception, error)
                self.opener.assert_called_once()
                self.assertTrue(body.closed)
        self.sleep.assert_not_called()

    def test_transport_tls_and_timeout_errors_are_not_retried(self):
        failures = (urllib.error.URLError("connection reset"), ssl.SSLError("certificate"), TimeoutError("transport"))
        for error in failures:
            with self.subTest(error=type(error).__name__):
                self.opener.reset_mock(side_effect=True)
                self.opener.side_effect = error
                with self.assertRaises(type(error)) as caught:
                    self.download()
                self.assertIs(caught.exception, error)
                self.opener.assert_called_once()
        self.sleep.assert_not_called()

    def test_body_failure_is_terminal_and_response_is_closed(self):
        error = OSError("truncated response")
        response = Response(before_read=Mock(side_effect=error))
        self.opener.return_value = response
        with self.assertRaises(OSError) as caught:
            self.download()
        self.assertIs(caught.exception, error)
        self.assertTrue(response.closed)
        self.opener.assert_called_once()
        self.sleep.assert_not_called()

    def test_archive_limit_accepts_exact_bound_and_rejects_extra_byte(self):
        with patch.object(installer, "MAX_ARCHIVE_BYTES", len(PAYLOAD)):
            exact = Response()
            self.opener.return_value = exact
            self.assertEqual(self.download(), PAYLOAD)
            self.assertEqual(exact.read_sizes, [len(PAYLOAD) + 1])
            self.assertTrue(exact.closed)
            oversized = Response(PAYLOAD + b"x")
            self.opener.reset_mock()
            self.opener.return_value = oversized
            with self.assertRaisesRegex(ValueError, "exceeds"):
                self.download()
            self.assertEqual(oversized.read_sizes, [len(PAYLOAD) + 1])
            self.assertTrue(oversized.closed)
            self.opener.assert_called_once()
        self.sleep.assert_not_called()

    def test_wrong_digest_is_terminal_including_short_or_empty_body(self):
        for payload in (b"", PAYLOAD[:-1], b"different archive"):
            with self.subTest(payload=payload):
                response = Response(payload)
                self.opener.reset_mock()
                self.opener.return_value = response
                with self.assertRaisesRegex(SystemExit, "digest mismatch"):
                    self.download()
                self.assertTrue(response.closed)
                self.opener.assert_called_once()
        self.sleep.assert_not_called()

    def test_retry_after_is_respected_and_reduces_next_request_timeout(self):
        for value in ("5", formatdate(self.wall_clock.return_value + 5, usegmt=True)):
            with self.subTest(value=value):
                error, body = http_error(429, value)
                self.opener.reset_mock(side_effect=True)
                self.sleep.reset_mock()
                self.opener.side_effect = [error, Response()]
                self.assertEqual(self.download(), PAYLOAD)
                self.sleep.assert_called_once_with(5.0)
                self.assertEqual(self.opener.call_args.kwargs["timeout"], 55.0)
                self.assertTrue(body.closed)

    def test_invalid_retry_after_is_terminal_with_closed_error(self):
        for values in (("bad date",), ("1", "2")):
            with self.subTest(values=values):
                error, body = http_error(503, *values)
                self.opener.reset_mock(side_effect=True)
                self.opener.side_effect = error
                with self.assertRaises(ValueError):
                    self.download()
                self.assertTrue(body.closed)
                self.opener.assert_called_once()
        self.sleep.assert_not_called()

    def test_server_delay_at_or_beyond_deadline_is_not_clipped_or_slept(self):
        for delay in ("60", "61"):
            with self.subTest(delay=delay):
                error, body = http_error(503, delay)
                self.opener.reset_mock(side_effect=True)
                self.opener.side_effect = error
                with self.assertRaises(TimeoutError):
                    self.download()
                self.opener.assert_called_once()
                self.assertTrue(body.closed)
        self.sleep.assert_not_called()

    def test_elapsed_request_time_consumes_same_retry_budget(self):
        error, body = http_error(504)
        response = Response()
        def open_response(*args, **kwargs):
            if self.opener.call_count == 1:
                self.clock.advance(50)
                raise error
            return response
        self.opener.side_effect = open_response
        self.assertEqual(self.download(), PAYLOAD)
        self.assertEqual([c.kwargs["timeout"] for c in self.opener.call_args_list], [60.0, 9.0])
        self.assertTrue(body.closed)

    def test_oversleep_prevents_next_request(self):
        error, body = http_error(504)
        self.opener.side_effect = [error, Response()]
        self.sleep.side_effect = lambda _: self.clock.advance(60)
        with self.assertRaises(TimeoutError):
            self.download()
        self.opener.assert_called_once()
        self.sleep.assert_called_once_with(1.0)
        self.assertTrue(body.closed)

    def test_late_open_closes_response_without_reading_body(self):
        response = Response()
        def late_open(*args, **kwargs):
            self.clock.advance(60)
            return response
        self.opener.side_effect = late_open
        with self.assertRaises(TimeoutError):
            self.download()
        self.assertEqual(response.read_sizes, [])
        self.assertTrue(response.closed)
        self.opener.assert_called_once()

    def test_late_body_is_closed_and_never_accepted(self):
        response = Response(before_read=lambda: self.clock.advance(60))
        self.opener.return_value = response
        with self.assertRaises(TimeoutError):
            self.download()
        self.assertTrue(response.closed)
        self.opener.assert_called_once()
        self.sleep.assert_not_called()

    def test_late_digest_is_never_accepted(self):
        response = Response()
        self.opener.return_value = response
        digest = Mock()
        def late_digest():
            self.clock.advance(60)
            return PAYLOAD_DIGEST
        digest.hexdigest.side_effect = late_digest
        with patch.object(installer.hashlib, "sha256", return_value=digest):
            with self.assertRaises(TimeoutError):
                self.download()
        self.assertTrue(response.closed)
        self.opener.assert_called_once()
        self.sleep.assert_not_called()


class RetryDelayTests(unittest.TestCase):
    def test_missing_or_short_server_delay_does_not_shorten_backoff(self):
        for attempt in (1, 2):
            for value in (None, headers(), headers("0"), headers("1")):
                with self.subTest(attempt=attempt, headers=value):
                    self.assertEqual(installer.retry_delay(value, attempt, 1_700_000_000), float(attempt))

    def test_integer_and_http_date_delays(self):
        now = 1_700_000_000
        self.assertEqual(installer.retry_delay(headers(" 12 "), 1, now), 12.0)
        self.assertEqual(installer.retry_delay(headers(formatdate(now + 12, usegmt=True)), 2, now), 12.0)
        self.assertEqual(installer.retry_delay(headers(formatdate(now - 12, usegmt=True)), 2, now), 2.0)

    def test_malformed_nonfinite_or_ambiguous_delays_are_rejected(self):
        values = ("", "-1", "1.5", "NaN", "infinity", "nonsense", "9" * 400,
                  "Tue, 14 Nov 2023 22:13:25")
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    installer.retry_delay(headers(value), 1, 1_700_000_000)
        with self.assertRaises(ValueError):
            installer.retry_delay(headers("1", "2"), 1, 1_700_000_000)


@unittest.skipUnless(hasattr(signal, "ITIMER_REAL"), "Unix real timer required")
class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.get_timer = self.enterContext(patch.object(installer.signal, "getitimer", return_value=(0.0, 0.0)))
        self.previous_handler = object()
        self.enterContext(patch.object(installer.signal, "getsignal", return_value=self.previous_handler))
        self.set_handler = self.enterContext(patch.object(installer.signal, "signal"))
        self.set_timer = self.enterContext(patch.object(installer.signal, "setitimer"))

    def test_invalid_budget_does_not_modify_signal_state(self):
        for seconds in (0, -1, float("inf"), float("-inf"), float("nan")):
            with self.subTest(seconds=seconds):
                with self.assertRaises(ValueError):
                    with installer.acquisition_deadline(seconds):
                        self.fail("invalid budget admitted")
        self.set_handler.assert_not_called()
        self.set_timer.assert_not_called()

    def test_existing_deadline_or_periodic_timer_is_preserved(self):
        for current in ((2.0, 0.0), (0.0, 2.0), (2.0, 2.0)):
            with self.subTest(timer=current):
                self.get_timer.return_value = current
                with self.assertRaises(RuntimeError):
                    with installer.acquisition_deadline(60):
                        self.fail("existing timer replaced")
        self.set_handler.assert_not_called()
        self.set_timer.assert_not_called()

    def test_success_disarms_timer_and_restores_previous_handler(self):
        with installer.acquisition_deadline(60):
            self.set_timer.assert_called_once_with(signal.ITIMER_REAL, 60)
            self.assertIsNot(self.set_handler.call_args.args[1], self.previous_handler)
        self.assertEqual(self.set_timer.call_args_list, [call(signal.ITIMER_REAL, 60), call(signal.ITIMER_REAL, 0)])
        self.set_handler.assert_called_with(signal.SIGALRM, self.previous_handler)

    def test_exception_disarms_timer_restores_handler_and_propagates(self):
        error = OSError("injected acquisition failure")
        with self.assertRaises(OSError) as caught:
            with installer.acquisition_deadline(60):
                raise error
        self.assertIs(caught.exception, error)
        self.set_timer.assert_called_with(signal.ITIMER_REAL, 0)
        self.set_handler.assert_called_with(signal.SIGALRM, self.previous_handler)

    def test_arm_failure_also_restores_previous_handler(self):
        error = OSError("injected timer failure")
        self.set_timer.side_effect = [error, None]
        with self.assertRaises(OSError) as caught:
            with installer.acquisition_deadline(60):
                self.fail("failed timer admitted")
        self.assertIs(caught.exception, error)
        self.set_timer.assert_called_with(signal.ITIMER_REAL, 0)
        self.set_handler.assert_called_with(signal.SIGALRM, self.previous_handler)


@unittest.skipUnless(hasattr(signal, "ITIMER_REAL"), "Unix real timer required")
class RealDeadlineTests(unittest.TestCase):
    def test_stalled_injected_open_is_interrupted_and_timer_state_restored(self):
        if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
            self.skipTest("preserve an existing process timer")
        previous_handler = signal.getsignal(signal.SIGALRM)
        def stalled_open(*args, **kwargs):
            time.sleep(2)
            self.fail("stalled open outlived acquisition deadline")
        opener = Mock(side_effect=stalled_open)
        with patch.object(installer.urllib.request, "urlopen", side_effect=AssertionError("real network forbidden")):
            with self.assertRaises(TimeoutError):
                installer.download_payload(opener=opener, timeout=0.05)
        opener.assert_called_once()
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))
        self.assertIs(signal.getsignal(signal.SIGALRM), previous_handler)


class InstallationBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory(prefix="xcodegen-acquisition-test-"))
        self.destination = Path(temporary) / "tools" / "xcodegen"
        self.enterContext(patch.object(installer, "DESTINATION", self.destination))
        self.download = self.enterContext(patch.object(installer, "download_payload"))
        self.native = self.enterContext(patch.object(installer.subprocess, "check_output", side_effect=AssertionError("native execution forbidden")))

    def test_valid_cache_needs_no_download_and_prints_only_executable_path(self):
        executable = self.destination / "xcodegen" / "bin" / "xcodegen"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(PAYLOAD)
        (self.destination / "receipt.sha256").write_text(PAYLOAD_DIGEST + "\n")
        output = io.StringIO()
        with redirect_stdout(output):
            installer.main()
        self.assertEqual(output.getvalue(), str(executable) + "\n")
        self.download.assert_not_called()
        self.native.assert_not_called()

    def test_failed_acquisition_never_creates_installation_or_runs_binary(self):
        self.download.side_effect = TimeoutError("injected failed acquisition")
        output = io.StringIO()
        with patch.object(installer.tempfile, "mkdtemp") as temporary:
            with redirect_stdout(output), self.assertRaises(TimeoutError):
                installer.main()
            temporary.assert_not_called()
        self.native.assert_not_called()
        self.assertFalse(self.destination.exists())
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
