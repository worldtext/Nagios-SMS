#!/usr/bin/env python3
"""Nagios notification plugin: send an SMS through the World Text HTTP API.

Authenticates with a bearer token. The old account id/API key pair is gone:
the token is a single secret, carries only the interfaces it was issued for
(you need `http`), and can be revoked or expired independently of your account.

The token is never printed. Prefer the WORLDTEXT_TOKEN environment variable
over --token, because a command line is visible to every user on the host via
ps(1) and is stored in the Nagios configuration file.

Python 3.6+, standard library only, so it runs on a bare monitoring host.
"""

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://sms.world-text.com/v2.0"
DEFAULT_TIMEOUT = 20.0
DEFAULT_SRCADDR = "Nagios"

# Nagios plugin exit codes.
OK = 0
CRITICAL = 2
UNKNOWN = 3

TOKEN_ENV = "WORLDTEXT_TOKEN"


class SendFailure(Exception):
    """A submission that did not result in a queued message."""

    def __init__(self, message, exit_code=CRITICAL):
        super().__init__(message)
        self.exit_code = exit_code


class NagiosArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that reports misuse as UNKNOWN, not CRITICAL.

    A broken command line is a configuration fault, which is what UNKNOWN
    means; CRITICAL would wrongly suggest the monitored host is the problem.
    """

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(UNKNOWN, "%s: error: %s\n" % (self.prog, message))


def parse_args(argv):
    p = NagiosArgumentParser(
        prog="notify_worldtext_sms.py",
        description="Send an SMS notification through the World Text HTTP API.",
        epilog="The token needs the 'http' interface. It may also be supplied "
               "in the %s environment variable, which keeps it out of the "
               "process table." % TOKEN_ENV,
    )
    p.add_argument("-T", "--token",
                   help="API bearer token (or set %s)" % TOKEN_ENV)
    p.add_argument("-d", "--dstaddr", required=True,
                   help="destination number in international format, e.g. 447989000001")
    p.add_argument("-t", "--txt", required=True, help="message text")
    p.add_argument("-s", "--srcaddr", default=DEFAULT_SRCADDR,
                   help="originator shown to the recipient (default: %(default)s)")
    p.add_argument("--sim", action="store_true",
                   help="simulate only; the message is not sent and costs nothing")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL,
                   help="API base URL (default: %(default)s)")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                   help="HTTP timeout in seconds (default: %(default)s)")
    return p.parse_args(argv)


def resolve_token(args):
    token = args.token or os.environ.get(TOKEN_ENV) or ""
    token = token.strip()
    if not token:
        raise SendFailure(
            "no API token: pass --token or set %s" % TOKEN_ENV, UNKNOWN)
    return token


def send_sms(token, args):
    """PUT the send request. Returns (msgid, credits) on success."""
    params = {
        "dstaddr": args.dstaddr,
        "txt": args.txt,
        "srcaddr": args.srcaddr,
    }
    if args.sim:
        # v2 simulates on the presence of the parameter whatever its value; v3
        # additionally requires it to read "true". Sending "true" satisfies
        # both, so --sim keeps working if --base-url is pointed at a v3 API.
        params["sim"] = "true"

    url = args.base_url.rstrip("/") + "/sms/send"
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="PUT",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "worldtext-nagios-sms/2.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        raise SendFailure(_describe_http_error(exc))
    except urllib.error.URLError as exc:
        raise SendFailure("cannot reach %s: %s" % (url, exc.reason))
    except socket.timeout:
        raise SendFailure("timed out after %gs contacting %s"
                          % (args.timeout, url))

    return _interpret(payload)


def _describe_http_error(exc):
    """Turn an HTTP error into something an operator can act on."""
    detail = ""
    try:
        parsed = json.loads(exc.read().decode("utf-8", "replace"))
        desc = parsed.get("desc")
        code = parsed.get("error")
        if desc:
            detail = ": %s" % desc
            if code:
                detail += " (error %s)" % code
    except Exception:
        pass

    if exc.code == 401:
        hint = "token missing, malformed, expired or revoked"
    elif exc.code == 403:
        hint = "token lacks the 'http' interface"
    elif exc.code == 429:
        hint = "rate limited; retry later"
    else:
        hint = "HTTP %d %s" % (exc.code, exc.reason)

    if exc.code in (401, 403):
        return "authorisation failed - %s%s" % (hint, detail)
    return "%s%s" % (hint, detail)


def _interpret(payload):
    """Parse the API envelope. Success is status '0'."""
    try:
        data = json.loads(payload.decode("utf-8", "replace"))
    except ValueError:
        raise SendFailure("API returned a response that is not JSON: %r"
                          % payload[:200])

    if str(data.get("status")) != "0":
        desc = data.get("desc") or "no description"
        code = data.get("error")
        raise SendFailure("message rejected by the API: %s%s"
                          % (desc, " (error %s)" % code if code else ""))

    results = data.get("result") or []
    if isinstance(results, dict):
        results = [results]
    msgid = credits = None
    if results:
        msgid = results[0].get("msgid")
        credits = results[0].get("credits")
    return msgid, credits


def main(argv):
    args = parse_args(argv)

    try:
        token = resolve_token(args)
        msgid, credits = send_sms(token, args)
    except SendFailure as exc:
        print(exc)
        return exc.exit_code

    parts = ["SMS sent to %s via World Text" % args.dstaddr]
    if args.sim:
        parts[0] += " (simulated)"
    if msgid:
        parts.append("msgid %s" % msgid)
    if credits:
        parts.append("%s credits" % credits)
    print(", ".join(parts))
    return OK


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(CRITICAL)
