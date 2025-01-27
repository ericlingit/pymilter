## @package mime
# This module provides a "defang" function to replace naughty attachments.
#
# We also provide workarounds for bugs in the email module that comes
# with python.  The "bugs" fixed mostly come up only with malformed
# messages - but that is what you have when dealing with spam.

# Author: Stuart D. Gathman <stuart@bmsi.com>
# Copyright 2001,2002,2003,2004,2005 Business Management Systems, Inc.
# This code is under the GNU General Public License.  See COPYING for details.

import email
import re
import socket
import sys
import zipfile
from io import BytesIO, StringIO
from email import message_from_binary_file, encoders
from email.message import Message
from email.generator import BytesGenerator

import Milter
from Milter.sgmllib import SGMLParser as HTMLParser


if not getattr(Message, "as_bytes", None):
    Message.as_bytes = Message.as_string

## Return a list of filenames in a zip file.
# Embedded zip files are recursively expanded.
def zipnames(txt):
    fp = BytesIO(txt)
    zipf = zipfile.ZipFile(fp, "r")
    names = []
    for nm in zipf.namelist():
        names.append(("zipname", nm))
        if nm.lower().endswith(".zip"):
            names += zipnames(zipf.read(nm))
    return names


## Fix multipart handling in email.Generator.
class MimeGenerator(BytesGenerator):
    def _dispatch(self, msg):
        # Get the Content-Type: for the message, then try to dispatch to
        # self._handle_<maintype>_<subtype>().  If there's no handler for the
        # full MIME type, then dispatch to self._handle_<maintype>().  If
        # that's missing too, then dispatch to self._writeBody().
        main = msg.get_content_maintype()
        if msg.is_multipart() and main.lower() != "multipart":
            self._handle_multipart(msg)
        else:
            BytesGenerator._dispatch(self, msg)


def unquote(s):
    """Remove quotes from a string."""
    if len(s) > 1:
        if s.startswith('"'):
            if s.endswith('"'):
                s = s[1:-1]
            else:  # remove garbage after trailing quote
                try:
                    s = s[1 : s[1:].index('"') + 1]
                except:
                    return s
            return s.replace("\\\\", "\\").replace('\\"', '"')
        if s.startswith("<") and s.endswith(">"):
            return s[1:-1]
    return s


def _unquotevalue(value):
    if isinstance(value, tuple):
        return value[0], value[1], unquote(value[2])
    else:
        return unquote(value)


## Enhance email.message.Message
#
# Tracks modifications to headers of body or any part independently.
class MimeMessage(Message):
    """Version of email.Message.Message compatible with old mime module"""

    def __init__(self, fp=None, seekable=1):
        Message.__init__(self)
        self.submsg = None
        self.modified = False
        ## @var headerchange
        # Provide a headerchange event for integration with Milter.
        #   The headerchange attribute can be assigned a function to be called when
        #   changing headers.  The signature is:
        #   headerchange(msg,name,value) -> None
        self.headerchange = None

    def get_param(self, param, failobj=None, header="content-type", unquote=True):
        val = Message.get_param(self, param, failobj, header, unquote)
        if val != failobj and param == "boundary" and unquote:
            # unquote boundaries an extra time, test case testDefang5
            return _unquotevalue(val)
        return val

    getfilename = Message.get_filename
    ismultipart = Message.is_multipart
    getheaders = Message.get_all
    gettype = Message.get_content_type
    getparam = Message.get_param

    def getparams(self):
        return self.get_params([])

    def getname(self):
        return self.get_param("name")

    def getnames(self, scan_zip=False):
        """Return a list of (attr,name) pairs of attributes that IE might
        interpret as a name - and hence decide to execute this message."""
        names = []
        for attr, val in self.get_params([], "content-type", False):
            if isinstance(val, tuple):
                # It's an RFC 2231 encoded parameter
                newvalue = _unquotevalue(val)
                if val[0]:
                    val = unicode(newvalue[2], newvalue[0])
                else:
                    val = unicode(newvalue[2])
            else:
                val = _unquotevalue(val.strip())
            names.append((attr, val))
        names += [("filename", self.get_filename())]
        if scan_zip:
            for key, name in tuple(names):  # copy by converting to tuple
                if name and name.lower().endswith(".zip"):
                    txt = self.get_payload(decode=True)
                    if txt.strip():
                        names += zipnames(txt)
        return names

    def ismodified(self):
        "True if this message or a subpart has been modified."
        if not self.is_multipart():
            if isinstance(self.submsg, Message):
                return self.submsg.ismodified()
            return self.modified
        if self.modified:
            return True
        for i in self.get_payload():
            if i.ismodified():
                return True
        return False

    def dump(self, file, unixfrom=False):
        "Write this message (and all subparts) to a file"
        g = MimeGenerator(file)
        g.flatten(self, unixfrom=unixfrom)

    def as_bytes(self, unixfrom=False):
        "Return the entire formatted message as a string."
        fp = BytesIO()
        self.dump(fp, unixfrom=unixfrom)
        return fp.getvalue()

    def getencoding(self):
        return self.get("content-transfer-encoding", None)

    # Decode body to stream according to transfer encoding, return encoding name
    def decode(self, filt):
        try:
            filt.write(self.get_payload(decode=True))
        except:
            pass
        return self.getencoding()

    def get_payload_decoded(self):
        return self.get_payload(decode=True)

    def __setitem__(self, name, value):
        rc = Message.__setitem__(self, name, value)
        self.modified = True
        if self.headerchange:
            self.headerchange(self, name, str(value))
        return rc

    def __delitem__(self, name):
        if self.headerchange:
            self.headerchange(self, name, None)
        rc = Message.__delitem__(self, name)
        self.modified = True
        return rc

    def get_payload(self, i=None, decode=False):
        msg = self.submsg
        if msg is None:
            t = self.get_content_type().lower()
            if t == "message/rfc822" or t.startswith("multipart/"):
                msg = super().get_payload()
                self.submsg = msg
        if isinstance(msg, Message) and msg.ismodified():
            self.set_payload([msg])
        return Message.get_payload(self, i, decode)

    def set_payload(self, val, charset=None):
        self.modified = True
        try:
            val.seek(0)
            val = val.read()
        except:
            pass
        Message.set_payload(self, val, charset)
        self.submsg = None

    def get_submsg(self):
        t = self.get_content_type().lower()
        if t == "message/rfc822" or t.startswith("multipart/"):
            if not self.submsg:
                txt = self.get_payload()
                if type(txt) is bytes:
                    self.submsg = email.message_from_bytes(txt, MimeMessage)
                    for part in self.submsg.walk():
                        part.modified = False
                elif type(txt) is str:
                    txt = self.get_payload(decode=True)
                    self.submsg = email.message_from_string(txt, MimeMessage)
                    for part in self.submsg.walk():
                        part.modified = False
                else:
                    self.submsg = txt[0]
            return self.submsg
        return None


def message_from_file(fp):
    msg = message_from_binary_file(fp, MimeMessage)
    for part in msg.walk():
        part.modified = False
    assert not msg.ismodified()
    return msg


extlist = "".join(
    """
ade,adp,asd,asx,asp,bas,bat,chm,cmd,com,cpl,crt,dll,exe,hlp,hta,inf,ins,isp,js,
jse,lnk,mdb,mde,msc,msi,msp,mst,ocx,pcd,pif,reg,scr,sct,shs,url,vb,vbe,vbs,wsc,
wsf,wsh 
""".split()
)
bad_extensions = ["." + x for x in extlist.split(",")]


def check_ext(name):
    "Check a name for dangerous Winblows extensions."
    if not name:
        return name
    lname = name.lower()
    for ext in bad_extensions:
        if lname.endswith(ext):
            return name
    return None


virus_msg = """This message appeared to contain a virus.
It was originally named '%s', and has been removed.
A copy of your original message was saved as '%s:%s'.
See your administrator.
"""


def check_name(msg, savname=None, ckname=check_ext, scan_zip=False):
    "Replace attachment with a warning if its name is suspicious."
    try:
        for key, name in msg.getnames(scan_zip):
            badname = ckname(name)
            if badname:
                if key == "zipname":
                    badname = msg.get_filename()
                break
        else:
            return Milter.CONTINUE
    except zipfile.BadZipfile:
        # a ZIP that is not a zip is very suspicious
        badname = msg.get_filename()
    hostname = socket.gethostname()
    msg.set_payload(virus_msg % (badname, hostname, savname))
    del msg["content-type"]
    del msg["content-disposition"]
    del msg["content-transfer-encoding"]
    name = "WARNING.TXT"
    msg["Content-Type"] = "text/plain; name=" + name
    return Milter.CONTINUE


def check_attachments(msg, check, lev=None):
    """Scan attachments.
    msg	MimeMessage
    check	function(MimeMessage): int
            Return CONTINUE, REJECT, ACCEPT
    """
    if msg.is_multipart():
        if not lev:
            lev = []
        lev.append(1)
        if msg.get_content_type().endswith("/rfc822"):
            foo = 1
        for i in msg.get_payload():
            print("chkm", lev, msg.get_content_type())
            rc = check_attachments(i, check, lev=lev)
            if rc != Milter.CONTINUE:
                return rc
            lev[-1] += 1
        return Milter.CONTINUE
    print("chk", lev, msg.get_content_type())
    return check(msg)


# save call context for Python without nested_scopes
class _defang:
    def __init__(self, scan_html=True):
        self.scan_html = scan_html

    def _chk_name(self, msg):
        rc = check_name(msg, self._savname, self._check, self.scan_zip)
        if self.scan_html:
            check_html(msg, self._savname)  # remove scripts from HTML
        if self.scan_rfc822:
            msg = msg.get_submsg()
            if isinstance(msg, Message):
                return check_attachments(msg, self._chk_name)
        return rc

    def __call__(
        self, msg, savname=None, check=check_ext, scan_rfc822=True, scan_zip=False
    ):
        """Compatible entry point.
        Replace all attachments with dangerous names."""
        self._savname = savname
        self._check = check
        self.scan_rfc822 = scan_rfc822
        self.scan_zip = scan_zip
        check_attachments(msg, self._chk_name)
        if msg.ismodified():
            return True
        return False


# emulate old defang function
defang = _defang()

declname = re.compile(r"[a-zA-Z][-_.a-zA-Z0-9]*\s*")
declstringlit = re.compile(r'(\'[^\']*\'|"[^"]*")\s*')


class SGMLFilter(HTMLParser):
    """Parse HTML and pass through all constructs unchanged.  It is intended for
    derived classes to implement exceptional processing for selected cases.
    """

    def __init__(self, out):
        HTMLParser.__init__(self)
        self.out = out

    def handle_comment(self, comment):
        self.out.write(f"<!--{comment}-->")

    def unknown_starttag(self, tag, attr):
        if hasattr(self, "get_starttag_text"):
            self.out.write(self.get_starttag_text())
        else:
            self.out.write(f"<{tag}")
            for (key, val) in attr:
                self.out.write(f' {key}="{val}"')
            self.out.write(">")

    def handle_data(self, data):
        self.out.write(data)

    def handle_entityref(self, ref):
        self.out.write(f"&{ref};")

    def handle_charref(self, ref):
        self.out.write(f"&#{ref};")

    def unknown_endtag(self, tag):
        self.out.write(f"</{tag}>")

    def handle_special(self, data):
        self.out.write(f"<!{data}>")

    def write(self, buf):
        "Act like a writer.  Why doesn't HTMLParser do this by default?"
        self.feed(buf)

    # Python-2.1 sgmllib rejects illegal declarations.  Since various Microsoft
    # products accept and output them, we need to pass them through -
    # at least until we discover that MS will execute them.
    # sgmlop-1.1 will not use this method, but calls handle_special to
    # do what we want.
    def parse_declaration(self, i):
        rawdata = self.rawdata
        n = len(rawdata)
        j = i + 2
        while j < n:
            c = rawdata[j]
            if c == ">":
                # end of declaration syntax
                self.handle_special(rawdata[i + 2 : j])
                return j + 1
            if c in "\"'":
                m = declstringlit.match(rawdata, j)
                if not m:
                    # incomplete or an error?
                    return -1
                j = m.end()
            elif c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
                m = declname.match(rawdata, j)
                if not m:
                    # incomplete or an error?
                    return -1
                j = m.end()
            else:
                j += 1
        # end of buffer between tokens
        return -1


class HTMLScriptFilter(SGMLFilter):
    "Remove scripts from an HTML document."

    def __init__(self, out):
        SGMLFilter.__init__(self, out)
        self.ignoring = 0
        self.modified = False
        self.msg = "<!-- WARNING: embedded script removed -->"

    def start_script(self, unused):
        # print('beg script', unused)
        self.ignoring += 1
        self.modified = True

    def end_script(self):
        # print('end script')
        self.ignoring -= 1
        if not self.ignoring:
            self.out.write(self.msg)

    def handle_data(self, data):
        if not self.ignoring:
            SGMLFilter.handle_data(self, data)

    def handle_comment(self, comment):
        if not self.ignoring:
            SGMLFilter.handle_comment(self, comment)


def check_html(msg, savname=None):
    "Remove scripts from HTML attachments."
    msgtype = msg.get_content_type().lower()
    # check for more MSIE braindamage
    if msgtype == "application/octet-stream":
        for (attr, name) in msg.getnames():
            if name and name.lower().endswith(".htm"):
                msgtype = "text/html"
    if msgtype == "text/html":
        out = StringIO()
        htmlfilter = HTMLScriptFilter(out)
        try:
            htmlfilter.write(msg.get_payload(decode=True).decode())
            htmlfilter.close()
        # except sgmllib.SGMLParseError:
        except:
            mimetools.copyliteral(msg.get_payload(), open("debug.out", "wb"))
            htmlfilter.close()
            hostname = socket.gethostname()
            msg.set_payload(
                f"An HTML attachment could not be parsed.  The original is saved as '{hostname}:{savname}'"
            )
            del msg["content-type"]
            del msg["content-disposition"]
            del msg["content-transfer-encoding"]
            name = "WARNING.TXT"
            msg["Content-Type"] = "text/plain; name=" + name
            return Milter.CONTINUE
        if htmlfilter.modified:
            msg.set_payload(out)  # remove embedded scripts
            del msg["content-transfer-encoding"]
            encoders.encode_quopri(msg)
    return Milter.CONTINUE


if __name__ == "__main__":

    def _list_attach(msg):
        t = msg.get_content_type()
        p = msg.get_payload(decode=True)
        print(msg.get_filename(), msg.get_content_type(), type(p))
        msg = msg.get_submsg()
        if isinstance(msg, Message):
            return check_attachments(msg, _list_attach)
        return Milter.CONTINUE

    for fname in sys.argv[1:]:
        with open(fname, "rb") as fp:
            msg = message_from_file(fp)
        email.iterators._structure(msg)
        check_attachments(msg, _list_attach)
