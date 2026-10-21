"""Offline test source. Intentionally not executed in the initial pre-test delivery."""
import argparse
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'skills/clord-dispatch/scripts/dispatch.py'
spec = importlib.util.spec_from_file_location('dispatch', SOURCE)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class DispatchTests(unittest.TestCase):
    def test_repo_newline_is_rejected(self):
        with self.assertRaises(d.DispatchError):
            d.repo_url('https://github.com/OWNER/REPO\n日本語の本文')

    def test_body_newline_does_not_join_repo(self):
        text = d.payload('git@github.com:OWNER/REPO.git', '\n日本語\n次の行', 'task-001')
        self.assertTrue(text.startswith('!clord repo:git@github.com:OWNER/REPO.git 日本語\n'))
        self.assertTrue(text.endswith('Dispatch-ID: task-001'))

    def test_shell_options_are_not_repo_urls(self):
        for value in ('--upload-pack=x', 'file:///tmp/repo', 'https://other.invalid/a/b', 'https://github.com/a/b x'):
            with self.subTest(value=value), self.assertRaises(d.DispatchError):
                d.repo_url(value)

    def test_utf16_length_limit(self):
        with self.assertRaises(d.DispatchError):
            d.payload('https://github.com/a/b', '🐑' * 1000, 'key')

    def test_no_route_fallback(self):
        with self.assertRaises(d.DispatchError):
            d.route({'routes': {'demo': {}}}, 'other-project')

    def test_body_does_not_accept_handwritten_prefix(self):
        with self.assertRaises(d.DispatchError):
            d.payload('https://github.com/a/b', '!clord do a task', 'key')

    def test_key_cannot_escape_receipt_directory(self):
        for key in ('../secret', '/tmp/key', '', 'a\nb'):
            with self.subTest(key=key), self.assertRaises(d.DispatchError):
                d.valid_key(key)

    def test_state_ignores_non_bot_status(self):
        bot = object.__new__(d.Discord)
        bot.bot_id = '10'
        bot.messages = lambda _: [{'id': '123', 'author': {'id': '99'}, 'content': 'Session running'}]
        self.assertEqual(bot.state('1')['state'], 'unknown')

    def test_error_is_not_started(self):
        bot = object.__new__(d.Discord)
        bot.bot_id = '10'
        bot.messages = lambda _: [{'id': '123', 'author': {'id': '10'}, 'content': '', 'embeds': [{'title': '❌ Error', 'description': 'Clone failed'}]}]
        self.assertEqual(bot.state('1')['state'], 'error')

    def test_unmatched_announcement_cannot_claim_thread(self):
        class Bot:
            bot_id = '10'
            def messages(self, channel):
                if channel == '20':
                    return [{'id': '102', 'author': {'id': '10'}, 'content': 'Session started → <#30>'}]
                return [{'id': '103', 'author': {'id': '10'}, 'content': 'Dispatch-ID: different-key'}]
            def validate_thread(self, route, thread):
                pass
        receipt = {'marker': 'our-key', 'message_id': '100', 'state': 'sent_unconfirmed'}
        d.observe(Bot(), {'channel_id': '20'}, receipt, 0)
        self.assertNotIn('thread_id', receipt)
        self.assertEqual(receipt['state'], 'sent_unconfirmed')

    def test_dry_run_has_no_network_or_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root/'config.json'; body = root/'body.md'
            cfg.write_text(json.dumps({'state_dir': str(root/'state'), 'routes': {'demo': {'channel_id': '20', 'guild_id': '40'}}}))
            body.write_text('Do a harmless task.')
            args = argparse.Namespace(config=str(cfg), command='new', route='demo', repo='https://github.com/a/b', key='dry', file=str(body), summary='Demo', origin='test-origin', wait=0, dry_run=True)
            with patch.object(d, 'request', side_effect=AssertionError('Network forbidden')), contextlib.redirect_stdout(io.StringIO()) as out:
                d.execute(args)
            self.assertTrue(json.loads(out.getvalue())['dry_run'])
            self.assertFalse((root/'state').exists())

    def test_uncertain_receipt_prevents_repost(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); state = root/'state'; state.mkdir()
            cfg = root/'config.json'; body = root/'body.md'
            cfg.write_text(json.dumps({'state_dir': str(state), 'routes': {'demo': {'channel_id': '20', 'guild_id': '40'}}}))
            body.write_text('Do a harmless task.')
            (state/'same-key.json').write_text(json.dumps({'state': 'sending', 'key': 'same-key'}))
            args = argparse.Namespace(config=str(cfg), command='new', route='demo', repo='https://github.com/a/b', key='same-key', file=str(body), summary='Demo', origin='test-origin', wait=0, dry_run=False)
            with patch.object(d, 'Discord', side_effect=AssertionError('Should not make network calls')), contextlib.redirect_stdout(io.StringIO()) as out:
                d.execute(args)
            self.assertTrue(json.loads(out.getvalue())['duplicate_blocked'])

    def test_followup_holds_even_when_status_says_finished(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); cfg = root/'config.json'; body = root/'body.md'
            cfg.write_text(json.dumps({'state_dir': str(root/'state'), 'routes': {'demo': {'channel_id': '20', 'guild_id': '40'}}}))
            body.write_text('Optional extra information.')
            args = argparse.Namespace(config=str(cfg), command='followup', route='demo', thread='30', key='followup-1', file=str(body), origin='test-origin', dry_run=False, interrupt_approved=False)
            with patch.object(d, 'Discord') as cls, contextlib.redirect_stdout(io.StringIO()) as out:
                cls.return_value.state.return_value = {'state': 'finished'}
                d.execute(args)
                cls.return_value.webhook.assert_not_called()
            self.assertTrue(json.loads(out.getvalue())['held'])

    def test_http_errors_do_not_echo_secrets(self):
        from urllib.error import HTTPError
        err = HTTPError('https://discord.com/api/webhooks/1/SECRET', 403, 'bad', None, io.BytesIO(b'SECRET'))
        with patch.object(d.urllib.request, 'urlopen', side_effect=err):
            with self.assertRaises(d.DispatchError) as cm:
                d.request('https://discord.com/api/webhooks/1/SECRET')
        self.assertNotIn('SECRET', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
