import unittest

import git_notifier

class FakeProvider(object):

    def get(self, varname):
        if varname != 'required.invalid':
            return None
        else:
            return "some non int variable"

class TestConfig(unittest.TestCase):

    def setUp(self):
        self.cfg = git_notifier.Config(FakeProvider())

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


if __name__ == '__main__':
    unittest.main()
