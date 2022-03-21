Forked from [sdgathman/pymilter](https://github.com/sdgathman/pymilter).
The contents of this readme has been modified to work with postfix.

# Abstract

This is a python extension module to enable python scripts to attach to
Sendmail's libmilter API, enabling filtering of messages as they arrive.
Since it's a script, you can do anything you want to the message - screen
out viruses, collect statistics, add or modify headers, etc.  You can, at
any point, tell Sendmail to reject, discard, or accept the message.

Additional python modules provide for navigating and modifying MIME parts,
and sending DSNs or doing CBVs.

# Requirements

- [Postfix](https://www.postfix.org/)
- [Python](https://docs.python.org/3/) >= 3.6
- [Pymilter](https://pypi.python.org/pypi/pymilter/)

# Quick Installation

This part assumes a host running Ubuntu 20.04 64-bit.

1. Install postfix:
    - `sudo apt install postfix`
1. Install libmilter-dev:
    - `sudo apt install libmilter-dev`
1. Create a python environment and activate it
    - `python3 -m venv venv`
    - `source venv/bin/activate`
1. Install this module
    - `pip install pymilter`
    - or `python setup.py install`
1. Configure postfix. Edit `/etc/postfix/main.cf` and add these lines:
    ```
    milter_default_action = tempfail
    milter_protocol = 6
    smtpd_milters = inet:localhost:9999
    non_smtpd_milters = $smtpd_milters
    ```
    - This tells postfix to use a milter located at `localhost:9999`.
    - We're using `tempfail` to deliberately fail mail delivery if the milter doesn't connect or work. This is here to help us diagnose problems.
1. Restart postfix:
    - `sudo systemctl restart postfix`
1. Clone this repo:
    - `git clone https://github.com/ericlingit/pymilter.git`
1. Create a python venv:
    - `cd pymilter`
    - `python3 -m venv venv`
    - `source venv/bin/activate`
1. Run sample.py. This starts a sample milter process and listens for requests at `localhost:9999`:
    - `python sample.py`

Monitor postfix logs for errors: `less /var/log/mail.log`

That's it. Incoming mail will cause the milter to print some things.
Edit and play. See spfmilter.py for a functional SPF milter, or see bms.py for an complex milter used in production.


# Authors

Jim Niemira (urmane@urmane.org) wrote the original C module and some quick
and dirty python to use it. Stuart D. Gathman (stuart@gathman.org) took that
kludge and added threading and context objects to it, wrote a proper OO
wrapper (Milter.py) that handles attachments, did lots of testing, packaged
it with distutils, and generally transformed it from a quick hack to a
real, usable Python extension.
