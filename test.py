import unittest
import testbms
import testmime
import testsample
import os

def suite(): 
  s = unittest.TestSuite()
  s.addTest(testbms.suite())
  s.addTest(testmime.suite())
  s.addTest(testsample.suite())
  return s

if __name__ == '__main__':
  try: os.remove('test/milter.log')
  except: pass
  unittest.TextTestRunner().run(suite())