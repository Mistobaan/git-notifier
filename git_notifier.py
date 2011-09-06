#! /usr/bin/env python

import optparse
import os
import shutil
import socket
import sys
import subprocess
import tempfile
import time
import re
import smtplib
from cStringIO import StringIO
from email.MIMEText import MIMEText
from email.MIMEMultipart import MIMEMultipart

VERSION   = "0.3-13"  # Filled in automatically.

Name      = "git-notifier"
CacheFile = ".%s.dat" % Name
Separator = "\n>---------------------------------------------------------------\n"
NoDiff    = "[nodiff]"
NoMail    = "[nomail]"

gitolite = "GL_USER" in os.environ
whoami = os.environ["LOGNAME"]
sender = gitolite and os.environ["GL_USER"] or whoami



class Mailer(object):
    def __init__(self, smtp_host, smtp_port,
                 sender, sender_password, recipients,ssl=False):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.sender = sender
        self.sender_password = sender_password
        self.recipients = recipients
        self.ssl = ssl

    def send(self, subject, reply_to, message):
        if not self.recipients:
            return

        mime_text = MIMEMultipart() 
        mime_text['From'] = self.sender
        mime_text['Reply-To'] = reply_to
        mime_text['To'] = ', '.join(self.recipients)
        mime_text['Subject'] = subject

        mime_html = MIMEText(message, 'html') #, _charset='utf-8')

        mime_text.attach(mime_html)
        
        server = smtplib.SMTP(self.smtp_host, self.smtp_port)
        if self.ssl:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.sender, self.sender_password)

        server.sendmail(self.sender, self.recipients, 
                        mime_text.as_string())
        server.quit()

class Hunk(object):
  """ Parses hunks starting with @@ -R +R @@ """

  def __init__(self):
    self.start_src=None 
    self.lines_src=None
    self.start_tgt=None
    self.lines_tgt=None
    self.invalid=False
    self.text=[]

  def append(self, line):
      self.text.append(line)

  def __str__(self):
      return '\n'.join(self.text)      

class Patch(object):

  def __init__(self):
    self.source = None 
    self.target = None
    self.hunks = []
    self.hunkends = []
    self.header = []
    self.type = None

CSSFILE_TEMPLATE = '''\
td.linenos { background-color: #f0f0f0; padding-right: 10px; }
span.lineno { background-color: #f0f0f0; padding: 0 5px 0 5px; }
pre { line-height: 125%%; }
body .gd { color: #000000; background-color: #ffdddd }
body .ge { font-style: italic }
body .gr { color: #aa0000 }
body .gh { color: #999999 }
body .gi { color: #000000; background-color: #ddffdd }
'''

DOC_HEADER = '''\
<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN"
   "http://www.w3.org/TR/html4/strict.dtd">

<html>
<head>
  <title>title</title>
  <meta http-equiv="content-type" content="text/html; charset=None">
  <style type="text/css">
''' + CSSFILE_TEMPLATE + '''
  </style>
</head>
<body>
<h2>title</h2>

'''

DOC_FOOTER = '''\
</body>
</html>
'''

class GitDiffParser(object):
    def __init__(self):
        pass

    def parse(self, difftxt):
        state = 'toplevel'
        hunks = []
        for line in difftxt.split('\n'):
            if state == 'toplevel':
                if line.startswith("@@"):
                    state = 'hunk'
                    new_hunk = Hunk()

            if state == 'hunk':
                if line.startswith("\ No newline at end of file"):
                    state='toplevel'
                    hunks.append(new_hunk)
                else:
                    new_hunk.append(line)
        return hunks

def patch2html(patch):
    html = StringIO()
    parser = GitDiffParser()
    html.write(DOC_HEADER)
    hucks = parser.parse(patch)
    for h in hucks:
        html.write("<pre><div>")
        for line in h.text:
            if line.startswith("-"):
                html.write('<span class="gd">'+ line + "</span>\n")
            elif line.startswith("+"):
                html.write('<span class="gi">'+ line +"</span>\n")
            else:
                html.write('<span class="gh">'+ line +"</span>\n")
        html.write("</div></pre>")

    html.write(DOC_FOOTER)
    return html.getvalue()

class GitReport(object):

    def __init__(self):
        pass

    def checkChanges(self):
        pass
    
#-------------------------------------------------------------------------------
class State(object):

    def __init__(self):
        self.clear()

    def getHeads(self):
        for (rev, head) in [head.split() for head in git("show-ref --heads")]:
            if head.startswith("refs/heads/"):
                head = head[11:]
            self.heads[head] = rev

    def getTags(self):
        for (rev, tag) in [head.split() for head in git("show-ref --tags")]:
            # We are only interested in annotaged tags.
            type = git("cat-file -t %s" % rev)[0]

            if type == "tag":
                if tag.startswith("refs/tags/"):
                    tag= tag[10:]

                self.tags[tag] = rev

    def getReachableRefs(self):
        for rev in git(["rev-list"] + self.heads.keys() + self.tags.keys()):
            self.revs.add(rev)

    @classmethod
    def getCurrent(klass):
        state = State()
        state.getHeads()
        state.getTags()
        state.getReachableRefs()
        return state

    def clear(self):
        self.heads = {}
        self.tags = {}
        self.revs = set()
        self.diffs = set()

        self.reported = set() # Revs reported this run so far.

    def writeTo(self, file):
        if os.path.exists(CacheFile):
            try:
                shutil.move(CacheFile, CacheFile + ".bak")
            except IOError:
                pass

        out = open(file, "w")

        for (head, ref) in self.heads.items():
            print >>out, "head", head, ref

        for (tag, ref) in self.tags.items():
            print >>out, "tag", tag, ref

        for rev in self.revs:
            print >>out, "rev", rev

    def readFrom(self, file):
        self.clear()

        for line in open(file):

            line = line.strip()
            if not line or line.startswith("#"):
                continue

            m = line.split()

            if len(m) == 3:
                (type, key, val) = (m[0], m[1], m[2])
            else:
                # No heads.
                (type, key, val) = (m[0], m[1], "")

            if type == "head":
                self.heads[key] = val

            elif type == "tag":
                self.tags[key] = val

            elif type == "rev":
                self.revs.add(key)

            elif type == "diff":
                self.diffs.add(key)

            else:
                error("unknown type %s in cache file" % type)


def log(msg):
    print >>Config.log, "%s - %s" % (time.asctime(), msg)

def error(msg):
    log("Error: %s" % msg)
    sys.exit(1)

def git(args, stdout_to=subprocess.PIPE, all=False):
    if isinstance(args, tuple) or isinstance(args, list):
        args = " ".join(args)
        
    try:
        child = subprocess.Popen("git " + args, shell=True, stdin=None, stdout=stdout_to, stderr=subprocess.PIPE)
        (stdout, stderr) = child.communicate()
    except OSError, e:
        error("cannot start git: %s" % str(e))

    if child.returncode != 0 and stderr:
        if stderr:
            msg = ": %s" % stderr
        else:
            msg = ""
        error("git child failed with exit code %d%s" % (child.returncode, msg))

    if stdout_to != subprocess.PIPE:
        return []

    if not all:
        return [line.strip() for line in stdout.split("\n") if line]
    else:
        return stdout.split("\n")

Tmps = []

def makeTmp():
    global Tmps

    (fd, fname) = tempfile.mkstemp(prefix="%s-" % Name, suffix=".tmp")
    Tmps += [fname]

    return (os.fdopen(fd, "w"), fname)

def deleteTmps():
    for tmp in Tmps:
        os.unlink(tmp)

def mailTag(key, value):
    return "%-11s: %s" % (key, value)

def generateMailHeader(subject):

    repo = Config.repouri

    if not repo:

        if gitolite:
            # Gitolite version.
            repo = "ssh://%s@%s/%s" % (whoami, Config.hostname, os.path.basename(os.getcwd()))
        else:
            # Standard version.
            repo = "ssh://%s/%s" % (Config.hostname, os.path.basename(os.getcwd()))

        if repo.endswith(".git"):
            repo = repo[0:-4]

    (out, fname) = makeTmp()

    if Config.replyto:
        replyto = "Reply-To: %s\n" % Config.replyto
    else:
        replyto = ""        

    email_header = False
    if email_header:
        print >>out, """From: %s
    To: %s
    Subject: %s %s
    %sX-Git-Repository: %s
    X-Mailer: %s %s

    %s

    """ % (Config.sender, Config.mailinglist, Config.emailprefix, subject, replyto, repo,
           Name, VERSION, mailTag("Repository", repo)),

    return (out, fname)

def sendMail(out, fname):
    out.close()

    txtmail = open(fname).read()

    if Config.debug:
        for line in txtmail.split("\n"):
            print line

    elif Config.use_sendmail:
        stdin = subprocess.Popen("/usr/sbin/sendmail -t", shell=True, stdin=subprocess.PIPE).stdin
        for line in txtmail.split("\n"):
            print >>stdin, line
        stdin.close()
    else:
        mailer.send("git oun commit", "git.noreply@acemetrix.com", txtmail)

    # Wait a bit in case we're going to send more mails. Otherwise, the mails
    # get sent back-to-back and are likely to end up with identical timestamps,
    # which may then make them appear to have arrived in the wrong order.
    if not Config.debug:
        time.sleep(2)

def entryAdded(key, value, rev):
    log("New %s %s" % (key, value))

    (out, fname) = generateMailHeader("%s '%s' created" % (key, value))

    print >>out, mailTag("New %s" % key, value)
    print >>out, mailTag("Referencing", rev)

    sendMail(out, fname)

def entryDeleted(key, value):
    log("Deleted %s %s" % (key, value))

    (out, fname) = generateMailHeader("%s '%s' deleted" % (key, value))

    print >>out, mailTag("Deleted %s" % key, value)

    sendMail(out, fname)

# Sends a mail for a notification consistent of two parts: (1) the output of a
# show command, and (2) the output of a diff command.
def sendChangeMail(rev, subject, heads, show_cmd, diff_cmd):

    (out, fname) = generateMailHeader(subject)

    if len(heads) > 1:
        multi = "es"
    else:
        multi = ""
        
    heads = ",".join(heads)

    #print >>out, mailTag("On branch%s" % multi, heads)

    if Config.link:
        url = Config.link.replace("%s", rev)
        #print >>out, mailTag("Link", url)

    footer = ""
    show = git(show_cmd)

    for line in show:
        if NoDiff in line:
            break

        if NoMail in line:
            return

    else:
        (tmp, tname) = makeTmp()
        diff = git(diff_cmd, stdout_to=tmp)
        tmp.close()
        
        size = os.path.getsize(tname)

        if size > Config.maxdiffsize:
            footer = "\nDiff suppressed because of size. To see it, use:\n\n    git %s" % diff_cmd
            tname = None

    #print >>out, Separator

    result = git(show_cmd, all=True)

    for line in result:
        if line == "---":
            #print >>out, Separator
            pass
        else:
            #print >>out, line
            pass

    # print >>out, Separator


    if tname:
        data = open(tname).read()
        txtfile = patch2html(data)
        out.write(txtfile)

    #print >>out, footer

    if Config.debug:
        pass
        #print >>out, "-- "
        #print >>out, "debug: show_cmd = git %s" % show_cmd
        #print >>out, "debug: diff_cmd = git %s" % diff_cmd

    sendMail(out, fname)

# Sends notification for a specific revision.
def commit(current, rev, force=False, subject_head=None):
    if rev in current.reported and not force:
        # Already reported in this run of the script.
        log("Flagged revision %s for notification, but already reported this time" % rev)
        return

    log("New revision %s" % rev)
    current.reported.add(rev)

    heads = [head.split()[-1] for head in git("branch --contains=%s" % rev)]
    if not subject_head:
        subject_head = ",".join(heads)

    subject = git("show '--pretty=format:%%s (%%h)' -s %s" % rev)
    subject = "%s: %s" % (subject_head, subject[0])

    show_cmd = "show -s --no-color --find-copies-harder --pretty=medium %s" % rev
    diff_cmd = "diff-tree --patch-with-stat --no-color --find-copies-harder --ignore-space-at-eol %s" % rev

    sendChangeMail(rev, subject, heads, show_cmd, diff_cmd)

# Sends a diff between two revisions.
#
# Only used in manual mode now.
def diff(head, first, last):
    # We record a pseudo-revision to avoid sending the same diff twice.
    rev = "%s-%s" % (head, last)
    if not rev in current.diffs:
        log("New diff revision %s" % rev)
        current.diffs.add(rev)

    log("Diffing %s..%s" % (first, last))

    subject = git("show '--pretty=format:%%s (%%h)' -s %s" % last)
    subject = "%s diff: %s" % (head, subject[0])

    heads = [head]

    show_cmd = "show -s --no-color --find-copies-harder --pretty=medium %s" % last
    diff_cmd = "diff --patch-with-stat -m --no-color --find-copies-harder --ignore-space-at-eol %s %s" % (first, last)

    sendChangeMail(last, subject, heads, show_cmd, diff_cmd)

# Sends pair-wise diffs for a path of revisions. Also records all revision on
# the path as seen.
#
# Only used in manual mode now.
def diffPath(head, revs):
    last = None

    for rev in revs:
        if last:
            diff(head, last, rev)
        last = rev

# Sends a commit notifications for a set of revisions.
def reportPath(current, revs, force=False, subject_head=None):
    if not revs:
        return

    # Sort updates by time.
    revs = git("rev-list --no-walk --reverse --date-order %s" % " ".join(revs))

    for rev in revs:
        commit(current, rev, force=force, subject_head=subject_head)

# Sends a summary mail for a set of revisions.
def headMoved(head, path):
    log("Head moved: %s -> %s" % (head, path[-1]))

    subject = git("show '--pretty=format:%%s (%%h)' -s %s" % path[-1])

    (out, fname) = generateMailHeader("%s's head updated: %s" % (head, subject[0]))

    print >>out, "Branch '%s' now includes:" % head
    print >>out, ""

    for rev in path:
        print >>out, "    ", git("show -s --pretty=oneline --abbrev-commit %s" % rev)[0]

    sendMail(out, fname)

MAILINGLIST = 'hooks.mailinglist'
EMAILPREFIX = 'hooks.emailprefix'
SMTP_SUBJECT = 'hooks.smtp-subject'
SMTP_HOST = 'hooks.smtp-host'
SMTP_PORT = 'hooks.smtp-port'
SMTP_SENDER = 'hooks.smtp-sender'
SMTP_SENDER_PASSWORD = 'hooks.smtp-sender-password'
POST_RECEIVE_LOGFILE = 'hooks.post-receive-logfile'

ConfigValueError = ValueError

class GitConfigProvider(object):

    def get(self, name):
        p = subprocess.Popen(['git', 'config', '--get', name], 
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        # XXX: what if the program fails ?
        return stdout.strip()

ONE_MB_IN_BYTES = 1048576

class Config(object):
    email_regexp = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,4}$")

    Options = [
    # Name, argument, default, help,
    ("allchanges", True, set(), "branches for which *all* changes are to be reported"),
    ("debug", False, False, "enable debug output"),
    ("diff", True, None, "mail out diffs between two revisions"),
    ("emailprefix", True, "[git]", "Subject prefix for mails"),
    ("hostname", True, socket.gethostname(), "host where the repository is hosted"),
    ("log", True, "%s.log" % Name, "set log output"),
    ("mailinglist", True, whoami, "destination address for mails"),
    ("manual", True, None, "notifiy for a manually given set of revisions"),
    ("maxdiffsize", True, 50, "limit the size of diffs in mails (KB)"),
    ("noupdate", False, False, "do not update the state file"),
    ("repouri", True, None, "full URI for the repository"),
    ("sender", True, sender, "sender address for mails"),
    ("link", True, None, "Link to insert into mail, %s will be replaced with revision"),
    ("updateonly", False, False, "update state file only, no mails"),
    ("users", True, None, "location of a user-to-email mapping file"),
    ("replyto", True, None, "email address for reply-to header"),
    ]
    
    def __init__(self, provider):
        self._provider = provider
        self._config = {}
        self.use_sendmail = False
        self.maxdiffsize = ONE_MB_IN_BYTES

    def __getitem__(self, value):
        return self._config[value]
    
    def optional(self, variable):
        self._config[variable] = self._provider.get(variable)
        
    def required(self, variable, type_=str):
        v = self._provider.get(variable)
        if not v:
            raise ConfigValueError('This script requires the git variable <%s> to be set in order to work.' % variable)
        try:
            self._config[variable] = type_(v)
        except:
            raise ConfigValueError("The configured git variable <%s> must be of type:%r" % (variable, type_))

    def parse_emails(self,emails):
        return [r.strip() for r in re.split(r'[,|\s]+', emails) if r]
        
    def get_config_variables(self):
        self.optional(EMAILPREFIX)
        self.optional(SMTP_SUBJECT)
        self.required(SMTP_HOST)
        self.optional(SMTP_PORT)
        self.optional(SMTP_SENDER)
        self.optional(SMTP_SENDER_PASSWORD)
        self.recipients(MAILINGLIST)
        self.parse_emails()
        return config

    def load_args(self, args):

        self.parseArgs(args)

        if self.allchanges and not isinstance(self.allchanges, set):
            self.allchanges = set([head.strip() for head in self.allchanges.split(",")])

        if not self.debug:
            self.log = open(self.log, "a")
        else:
            self.log = sys.stderr

        if not self.users and "GL_ADMINDIR" in os.environ:
            users = os.path.join(os.environ["GL_ADMINDIR"], "conf/sender.cfg")
            if os.path.exists(users):
                self.users = users

        self.readUsers()

    def parseArgs(self, args):

        parser = optparse.OptionParser(version=VERSION)

        for (name, arg, default, help) in Options:
            defval = self._git_config(name, default)

            if isinstance(default, int):
                defval = int(defval)

            if not arg:
                defval = bool(defval)

            if not arg:
                if not default:
                    action = "store_true"
                else:
                    action = "store_false"
                parser.add_option("--%s" % name, action=action, dest=name, default=defval, help=help)

            else:
                if not isinstance(default, int):
                    type = "string"
                else:
                    type = "int"
                parser.add_option("--%s" % name, action="store", type=type, default=defval, dest=name, help=help)

        (options, args) = parser.parse_args(args)

        if len(args) != 0:
            parser.error("incorrect number of arguments")

        for (name, arg, default, help) in Options:
            self.__dict__[name] = options.__dict__[name]

    def readUsers(self):
        if self.users and os.path.exists(self.users):
            for line in open(self.users):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                m = line.split()

                if self.sender == m[0]:
                    self.sender = " ".join(m[1:])
                    break

    def _git_config(self, key, default):
        cfg = git(["config hooks.%s" % key])
        if cfg:
            return cfg[0]
        else:
            return default


if __name__ == "__main__":
    log("Running for %s" % os.getcwd())

    if Config.debug:
        for (name, arg, default, help) in Options:
            print >>sys.stderr, "[Option %s: %s]" % (name, Config.__dict__[name])

    config = Config()
    config.get_config_variables()
    config.get_args(sys.argv[1:])
    
    mailer = Mailer(config[SMTP_HOST], config[SMTP_PORT],
                    config[SMTP_SENDER], config[SMTP_SENDER_PASSWORD],
                    config[MAILINGLIST])

    cache = State()

    if os.path.exists(CacheFile):
        cache.readFrom(CacheFile)
        report = (not Config.updateonly)
    else:
        log("Initial run. Not generating any mails, just recording current state.")
        report = False

    current = State.getCurrent()

    if Config.diff:
        # Manual diff mode. The argument must be of the form "[old-rev..]new-rev".
        path = [rev.strip() for rev in Config.diff.split("..")]
        if len(path) == 1:
            path = ("%s~2" % path[0], path[0]) # sic! ~2.
        else:
            path = ("%s~1" % path[0], path[1])

        revs = git(["rev-list", "--reverse --date-order", path[1], "^%s" % path[0]])

        diffPath("<manual-diff>", revs)

        sys.exit(0)

    if Config.manual:
        # Manual report mode. The argument must be of the form "[old-rev..]new-rev".
        path = [rev.strip() for rev in Config.manual.split("..")]
        if len(path) == 1:
            path = ("%s~1" % path[0], path[0])

        revs = git(["rev-list", "--reverse --date-order", path[1], "^%s" % path[0]])
        reportPath(current, revs, force=True)

        sys.exit(0)

    if report:
        theReport = GitReport()
        # Check for changes to the set of heads.
        old = set(cache.heads.keys())
        new = set(current.heads.keys())

        for head in (new - old):
            entryAdded("branch", head, current.heads[head])

        for head in (old - new):
            entryDeleted("branch", head)

        stable_heads = new & old

        Config.allchanges = Config.allchanges & stable_heads

        # Check tags.
        old = set(cache.tags.keys())
        new = set(current.tags.keys())

        for tag in (new - old):
            entryAdded("tag", tag, current.tags[tag])

        for tag in (old - new):
            entryDeleted("tag", tag)

        # Notify for unreported commits.
        old = set(cache.revs)
        new = set(current.revs)
        new_revs = (new - old)
        reportPath(current, new_revs)

        # Do reports for the heads we want to see everything for.
        for head in stable_heads:
            old_rev = cache.heads[head]
            new_rev = current.heads[head]
            path = git(["rev-list", "--reverse --date-order", new_rev, "^%s" % old_rev])

            if head in Config.allchanges:
                # Want to see all commits for this head, even if already reported
                # in the past for some other. So we record these separately.
                reportPath(current, path, subject_head=head)
            else:
                # Just send a summary for heads that now include some new stuff.
                if len(set(path) - new_revs):
                    headMoved(head, path)

    if not Config.noupdate:
        current.writeTo(CacheFile)

    deleteTmps()
