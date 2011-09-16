import unittest
import git_notifier

diffexample = """
diff --git a/scratchpad/gitnotifier.txt b/scratchpad/gitnotifier.txt
index a9867a2..86e310e 100644
--- a/scratchpad/gitnotifier.txt
+++ b/scratchpad/gitnotifier.txt
@@ -1,5 +1,2 @@
 test test
-more edits
-and diffs 
-and here
 some more..
"""
class TestGitParser(unittest.TestCase):
    
    def test_example1(self):
        parser = git_notifier.GitDiffParser()
        hunks = parser.parse(diffexample)
        self.assertEquals(1,len(hunks))
        
    def test_parse(self):
        html = git_notifier.patch2html(diffexample)
        self.assertTrue(html)
        
class FakeProvider(object):

    def get(self, varname):
        if varname != 'required.invalid':
            return None
        else:
            return "some non int variable"

class TestConfig(unittest.TestCase):

    def setUp(self):
        self.cfg = git_notifier.GitNotifierConfig(FakeProvider())

    def test_config_required(self):
        self.assertRaisesRegexp( git_notifier.ConfigValueError,
                                 "This script requires .*",
                                 self.cfg.required, "required", type_=int)
                
    def test_config_test_values(self):
        self.assertRaisesRegexp( git_notifier.ConfigValueError,
                                 "The configured git .* must be .* ",
                                 self.cfg.required, "required.invalid", type_=int)

    def assertSplitEmails(self, input, expected ):
        self.assertEquals( expected,  self.cfg.parse_emails(input) )
        
    def test_parse_emails_pipe_sep(self):
        expected = [ "myemail@domain.com","other@domain.com" ]
        input = "myemail@domain.com | other@domain.com"
        self.assertSplitEmails(input, expected)

    def test_parse_emails_comma_sep(self):
        expected = [ "myemail@domain.com","other@domain.com" ]
        input = "myemail@domain.com , other@domain.com"
        self.assertSplitEmails(input, expected)

    def test_parse_emails_space_sep(self):
        expected = [ "myemail@domain.com","other@domain.com" ]
        input = "myemail@domain.com other@domain.com"
        self.assertSplitEmails(input, expected)


class TestMail(unittest.TestCase):

    def get(self, key):        
        return "some_value"
    
    def test_mail_creation(self):
        cfg = git_notifier.GitNotifierConfig(self)
        cfg.get_config_variables() 
        cfg.parseArgs([])
        git_notifier.generateMailHeader(cfg,"Subject")
