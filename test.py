import os
import unittest

import testcfg
import testgrey
import testmime
import testpolicy
import testsample
import testutils


def suite():
    s = unittest.TestSuite()
    s.addTest(testmime.suite())
    s.addTest(testsample.suite())
    s.addTest(testutils.suite())
    s.addTest(testgrey.suite())
    s.addTest(testcfg.suite())
    s.addTest(testpolicy.suite())
    return s


if __name__ == "__main__":
    try:
        os.remove("test/milter.log")
    except:
        pass
    unittest.TextTestRunner().run(suite())
