#!/usr/bin/env python3
"""C-lord Discord dispatcher. Python stdlib; explicit routes; durable send receipts."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

API = 'https://discord.com/api/v10'
CONFIG = Path(os.environ.get('CLORD_DISPATCH_CONFIG', '~/.config/clord-dispatch/config.json')).expanduser()


class DispatchError(Exception):
    pass


def emit(value):
    print(json.dumps(value, ensure_ascii=False))


def load_config(path):
    try:
        c = json.loads(Path(path).expanduser().read_text())
    except (OSError, ValueError):
        raise DispatchError('Cannot read config; install a private config using examples/config.example.json')
    if not isinstance(c.get('routes'), dict) or not c['routes']:
        raise DispatchError('Config needs explicit routes')
    return c


def token(c):
    name = c.get('bot_token_env', 'CLORD_DISCORD_BOT_TOKEN')
    value = os.environ.get(name)
    if not value and c.get('bot_token_env_file'):
        try:
            for line in Path(c['bot_token_env_file']).expanduser().read_text().splitlines():
                if line.startswith(name + '='):
                    value = line.split('=', 1)[1].strip().strip('\"\'')
                    break
        except OSError:
            pass
    if not value:
        raise DispatchError('Bot token reference is not available; do not print or commit credentials')
    return value


def route(c, name):
    r = c['routes'].get(name)
    if not isinstance(r, dict):
        raise DispatchError('Unknown route; use routes. No fallback destination is allowed')
    for key in ('channel_id', 'guild_id'):
        if not re.fullmatch(r'[0-9]+', str(r.get(key, ''))):
            raise DispatchError('Route requires numeric guild_id and channel_id')
    return r


def repo_url(value):
    # This helper deliberately supports GitHub only, never arbitrary git hosts/options.
    if not re.fullmatch(r'(?:https://github\.com/|git@github\.com:)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', value):
        raise DispatchError('Repository must be one whitespace-free GitHub HTTPS or SSH URL')
    return value


def payload(repo, body, marker):
    repo_url(repo)
    if not body.strip() or body.lstrip().startswith('!clord'):
        raise DispatchError('Body must be nonempty task text, without !clord or repo: prefix')
    # C-lord currently splits repo: at a literal space. Keep that separator on one line.
    text = '!clord repo:' + repo + ' ' + body.strip() + '\n\nDispatch-ID: ' + marker
    if len(text.encode('utf-16-le')) // 2 > 2000:
        raise DispatchError('Dispatch exceeds Discord 2000 UTF-16 code units; shorten the task')
    return text


def request(url, method='GET', body=None, secret=None):
    headers = {'User-Agent': 'clord-openclaw-skill/0.1', 'Content-Type': 'application/json'}
    if secret:
        headers['Authorization'] = 'Bot ' + secret
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read() or b'{}')
    except urllib.error.HTTPError as e:
        # Do not print response bodies, webhook URLs, tokens, or retry mutations.
        raise DispatchError('Discord HTTP ' + str(e.code) + '; inspect the receipt before retrying')
    except (OSError, ValueError):
        raise DispatchError('Discord request outcome unavailable; do not blindly resend')


class Discord:
    def __init__(self, c):
        self.secret = token(c)
        self.bot_id = self.api('/users/@me')['id']

    def api(self, path):
        return request(API + path, secret=self.secret)

    def validate_parent(self, r):
        ch = self.api('/channels/' + str(r['channel_id']))
        if ch.get('type') != 0 or str(ch.get('guild_id')) != str(r['guild_id']):
            raise DispatchError('Route is not the expected guild text channel; no send performed')

    def validate_thread(self, r, thread):
        ch = self.api('/channels/' + thread)
        if ch.get('type') != 11 or str(ch.get('parent_id')) != str(r['channel_id']) or str(ch.get('guild_id')) != str(r['guild_id']):
            raise DispatchError('Thread is not under the selected route; no send performed')
        if ch.get('thread_metadata', {}).get('archived'):
            raise DispatchError('Thread is archived; do not assume it has a live C-lord session')

    def webhook(self, r):
        hooks = self.api('/channels/' + str(r['channel_id']) + '/webhooks')
        # Use only existing incoming hooks; never create one or pick an unrelated route.
        hooks = [h for h in hooks if h.get('type') == 1 and h.get('token') and str(h.get('channel_id')) == str(r['channel_id'])]
        if r.get('webhook_id'):
            hooks = [h for h in hooks if h['id'] == str(r['webhook_id'])]
        if len(hooks) != 1:
            raise DispatchError('Select one existing incoming webhook_id in private route config')
        return API + '/webhooks/' + hooks[0]['id'] + '/' + hooks[0]['token']

    def messages(self, channel, limit=100):
        return self.api('/channels/' + channel + '/messages?limit=' + str(limit))

    def state(self, thread):
        messages = self.messages(thread)
        for m in messages:  # Discord returns newest first. Only trust C-lord-authored status.
            if m.get('author', {}).get('id') != self.bot_id:
                continue
            text = m.get('content', '')
            for e in m.get('embeds', []):
                text += '\n' + e.get('title', '') + '\n' + e.get('description', '')
            # Narrow, observed status strings; ordinary prose does not establish completion.
            if '❌ Error' in text:
                return {'state': 'error', 'evidence_message_id': m['id']}
            if 'Session running' in text or '⚙️ 作業中' in text or 'Interrupted. Starting with new instruction' in text:
                return {'state': 'running', 'evidence_message_id': m['id']}
            if 'Claude has finished' in text:
                return {'state': 'finished', 'evidence_message_id': m['id']}
        return {'state': 'unknown', 'reason': 'No recognized recent status; not proof of an idle or live session'}


@contextmanager
def store(c):
    directory = Path(c.get('state_dir', '~/.local/state/clord-dispatch')).expanduser()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    lock = directory / 'receipts.lock'
    with lock.open('a') as f:
        os.chmod(lock, 0o600)
        fcntl.flock(f, fcntl.LOCK_EX)
        yield directory


def save(path, value):
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def valid_key(key):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', key):
        raise DispatchError('Use an operation key of 1-80 safe letters, digits, dot, dash, underscore')
    return key


def observe(d, r, receipt, seconds):
    marker = receipt['marker']
    end = time.monotonic() + seconds
    while True:
        thread = receipt.get('thread_id')
        if not thread:
            for m in d.messages(str(r['channel_id'])):
                if int(m['id']) <= int(receipt['message_id']) or m.get('author', {}).get('id') != d.bot_id:
                    continue
                hit = re.search(r'Session started\s*→\s*<#([0-9]+)>', m.get('content', ''))
                if not hit:
                    continue
                candidate = hit.group(1)
                d.validate_thread(r, candidate)
                # Do not associate another concurrent dispatch's thread by timestamp alone.
                if any('Dispatch-ID: ' + marker in x.get('content', '') and x.get('author', {}).get('id') == d.bot_id for x in d.messages(candidate)):
                    receipt['thread_id'] = thread = candidate
                    break
        if thread:
            receipt['observation'] = d.state(thread)
            receipt['state'] = 'started' if receipt['observation']['state'] == 'running' else 'thread_observed'
            if receipt['observation']['state'] in ('running', 'error', 'finished'):
                return receipt
        if time.monotonic() >= end:
            return receipt
        time.sleep(min(2, max(0, end-time.monotonic())))


def execute(a):
    c = load_config(a.config)
    if a.command == 'routes':
        emit({'routes': [{'name': name, 'channel_id': route(c, name)['channel_id'], 'repo': r.get('repo')} for name, r in c['routes'].items()]})
        return
    if a.command == 'receipt':
        with store(c) as directory:
            p = directory / (valid_key(a.key) + '.json')
            if not p.exists():
                raise DispatchError('No receipt for this key')
            emit(json.loads(p.read_text()))
        return
    r = route(c, a.route)
    if a.command == 'status':
        d = Discord(c)
        d.validate_thread(r, a.thread)
        emit({'thread_id': a.thread, **d.state(a.thread)})
        return
    if a.command == 'observe':
        with store(c) as directory:
            p = directory / (valid_key(a.key) + '.json')
            if not p.exists():
                raise DispatchError('No receipt for this key')
            receipt = json.loads(p.read_text())
            if receipt.get('route') != a.route or not receipt.get('message_id'):
                raise DispatchError('Receipt does not match route or has no confirmed message')
            d = Discord(c)
            d.validate_parent(r)
            observe(d, r, receipt, a.wait)
            save(p, receipt)
            emit(receipt)
        return
    body = Path(a.file).read_text()
    key = valid_key(a.key)
    if a.command == 'new':
        repo = repo_url(a.repo or r.get('repo', ''))
        content = payload(repo, body, key)
        if not a.summary.strip() or len(a.summary.encode('utf-16-le')) // 2 > 2000:
            raise DispatchError('Supply a nonempty summary within Discord length limit')
    else:
        repo, content = None, body.strip()
        if not content or len(content.encode('utf-16-le')) // 2 > 2000:
            raise DispatchError('Follow-up must contain 1-2000 UTF-16 code units')
    digest = hashlib.sha256(json.dumps([a.command, a.route, repo, getattr(a, 'thread', None), content], ensure_ascii=False).encode()).hexdigest()
    if a.dry_run:
        emit({'dry_run': True, 'network_calls': 0, 'route': a.route, 'channel_id': r['channel_id'], 'repo': repo, 'key': key, 'payload_sha256': digest, 'utf16_units': len(content.encode('utf-16-le'))//2, 'note': 'Local validation only; route binding, webhook, and session have not been checked'})
        return
    with store(c) as directory:
        p = directory / (key + '.json')
        if p.exists():
            emit({'duplicate_blocked': True, 'receipt': json.loads(p.read_text())})
            return
        d = Discord(c)
        d.validate_parent(r)
        if a.command == 'followup':
            d.validate_thread(r, a.thread)
            state = d.state(a.thread)
            if not a.interrupt_approved:
                # Discord status alone cannot prove sessions.db liveness; hold by default.
                emit({'held': True, 'thread_id': a.thread, **state, 'reason': 'Follow-up can interrupt work or be dropped by a dead session. Obtain explicit interruption/reply authority and independently verify session liveness; then use --interrupt-approved.'})
                return
        base = d.webhook(r)
        receipt = {'key': key, 'operation': a.command, 'route': a.route, 'repo': repo, 'origin': a.origin, 'payload_sha256': digest, 'marker': key, 'state': 'sending', 'created_at': int(time.time())}
        # Record before the mutation. An uncertain outcome must not become a duplicate retry.
        save(p, receipt)
        url = base + '?wait=true'
        if a.command == 'followup':
            url += '&thread_id=' + urllib.parse.quote(a.thread, safe='')
        m = request(url, 'POST', {'content': content, 'allowed_mentions': {'parse': []}})
        receipt.update(message_id=m['id'], state='sent_unconfirmed')
        if a.command == 'followup':
            receipt['thread_id'] = a.thread
        save(p, receipt)
        if a.command == 'new':
            observe(d, r, receipt, a.wait)
            save(p, receipt)
            if receipt.get('state') == 'started':
                try:
                    request(base + '/messages/' + m['id'], 'PATCH', {'content': a.summary, 'allowed_mentions': {'parse': []}})
                    receipt['summary_updated'] = True
                except DispatchError:
                    receipt['summary_updated'] = False
                save(p, receipt)
        emit(receipt)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default=str(CONFIG))
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('routes')
    rec = sub.add_parser('receipt'); rec.add_argument('--key', required=True)
    status = sub.add_parser('status'); status.add_argument('--route', required=True); status.add_argument('--thread', required=True)
    obs = sub.add_parser('observe'); obs.add_argument('--route', required=True); obs.add_argument('--key', required=True); obs.add_argument('--wait', type=int, choices=range(0,31), default=0)
    for name in ('new', 'followup'):
        a = sub.add_parser(name)
        for field in ('route', 'key', 'file', 'origin'):
            a.add_argument('--' + field, required=True)
        a.add_argument('--dry-run', action='store_true')
        if name == 'new':
            a.add_argument('--repo'); a.add_argument('--summary', required=True); a.add_argument('--wait', type=int, choices=range(0,31), default=20)
        else:
            a.add_argument('--thread', required=True)
            a.add_argument('--interrupt-approved', action='store_true')
    try:
        execute(p.parse_args())
    except (DispatchError, OSError, KeyError, ValueError) as e:
        if isinstance(e, DispatchError):
            emit({'error': str(e)})
        else:
            emit({'error': 'Local input or response shape error; inspect config, files, and receipt without resending'})
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
