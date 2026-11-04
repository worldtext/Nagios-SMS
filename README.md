Nagios-SMS-WT
=============

Plugin for Nagios to send SMS text message notifications via
[world-text.com](https://www.world-text.com).

This is the Python 3 plugin, using bearer authentication. It replaces the
Perl `notify_worldtext_sms.pl`, which used the account id and API key in the
query string (that version remains in the git history). See
[Migrating from the Perl plugin](#migrating-from-the-perl-plugin).

Requirements
------------

Python 3.6 or later. Standard library only, so there is nothing to install and
nothing to pin — it runs on a bare monitoring host.

Getting a token
---------------

Create an API token in the customer portal at
<https://portal.world-text.com/account/api-tokens/>, ticking the **http**
interface. That interface is what lets the token be used against the HTTP API at
all; without it every send is refused with HTTP 403.

A token can be given an expiry date and revoked at any time. It is displayed
once, when created, and cannot be recovered afterwards — only a SHA-256 digest
is stored.

Usage
-----

    notify_worldtext_sms.py -T TOKEN -d DESTINATION -t "MESSAGE"

Options:

| Option | Meaning |
|---|---|
| `-T`, `--token` | API bearer token. Prefer the `WORLDTEXT_TOKEN` environment variable, see below. |
| `-d`, `--dstaddr` | Destination number, full international format without `+`. |
| `-t`, `--txt` | Message text. |
| `-s`, `--srcaddr` | Originator shown to the recipient. Default `Nagios`. |
| `--sim` | Simulate: validate and price the message without sending it, at no cost. |
| `--base-url` | API base URL. Default `https://sms.world-text.com/v2.0`. |
| `--timeout` | HTTP timeout in seconds. Default 20. |

Keeping the token out of the process table
------------------------------------------

A `--token` argument is visible to every user on the host through `ps(1)`, and
is stored in your Nagios configuration. Exporting `WORLDTEXT_TOKEN` instead
avoids both problems:

    define command {
            command_name notify-by-sms
            command_line /usr/bin/env WORLDTEXT_TOKEN=TOKEN $USER1$/notify_worldtext_sms.py -d $CONTACTPAGER$ -t "$NOTIFICATIONTYPE$ $SERVICESTATE$ $SERVICEDESC$ Host($HOSTNAME$) Info($SERVICEOUTPUT$) Date($SHORTDATETIME$)"
    }

The plugin uses `--token` if both are set. If your Nagios configuration is
world-readable, use a [resource macro](https://assets.nagios.com/downloads/nagioscore/docs/nagioscore/4/en/macrolist.html)
such as `$USER3$` to hold the token rather than writing it inline.

Nagios configuration
--------------------

Define the commands:

    define command {
            command_name notify-by-sms
            command_line $USER1$/notify_worldtext_sms.py -d $CONTACTPAGER$ -t "$NOTIFICATIONTYPE$ $SERVICESTATE$ $SERVICEDESC$ Host($HOSTNAME$) Info($SERVICEOUTPUT$) Date($SHORTDATETIME$)"
    }

    define command {
            command_name host-notify-by-sms
            command_line $USER1$/notify_worldtext_sms.py -d $CONTACTPAGER$ -t "$NOTIFICATIONTYPE$ $HOSTSTATE$ Host($HOSTALIAS$) Info($HOSTOUTPUT$) Time($SHORTDATETIME$)"
    }

In your contacts, set `pager` to the contact's mobile number in full
international format:

    define contact {
            contact_name                    engineer
            alias                           Support Engineer
            service_notification_period     24x7
            host_notification_period        24x7
            service_notification_options    w,u,c,r
            host_notification_options       d,u,r
            service_notification_commands   notify-by-email,notify-by-sms
            host_notification_commands      host-notify-by-email,host-notify-by-sms
            email                           engineer@mydomain.com
            pager                           447987xxxxxx
    }

Test the command from the shell before wiring it up, and use `--sim` first so
you are not billed for a message you are only testing:

    WORLDTEXT_TOKEN=... ./notify_worldtext_sms.py -d 447987654321 -t "test" --sim

Exit codes
----------

Nagios plugin convention:

| Code | Meaning |
|---|---|
| 0 | OK — the API accepted the message |
| 2 | CRITICAL — rejected, unauthorised, or the API could not be reached |
| 3 | UNKNOWN — no token, or a bad command line |

Nagios does not act on the exit code of a *notification* command, but it does
log it, and the message is useful when a page does not arrive.

Migrating from the Perl plugin
------------------------------

The Perl plugin took an account id and API key:

    notify_worldtext_sms.pl -i ACCOUNTID -k APIKEY -d $CONTACTPAGER$ -t "..."

Both are replaced by a single token, so the command becomes:

    notify_worldtext_sms.py -d $CONTACTPAGER$ -t "..."

with `WORLDTEXT_TOKEN` set. The account API key still works for other legacy
integrations, but it is not used here.

The output format changed slightly, and failures now return a non-zero exit
code rather than always returning 0.

Testing
-------

    python3 test_notify_worldtext_sms.py

The tests run against a stub server on localhost: no account, no credentials,
no network. They cover the bearer header, the environment variable, the
permission and authentication failures, simulation, and that the token never
reaches stdout.

Licence
-------

BSD 3-Clause. See [LICENSE](LICENSE).
