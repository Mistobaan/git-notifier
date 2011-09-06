from git_notifier import git

import sys

print "\n".join(git("status"))

