"""CPU fault cases for the proposed, NOT DEPLOYED paired polling fix."""
import unittest
def proposed_poll(event,initial_lower,clock,sleep):
    lower=initial_lower
    while True:
        qa=clock();done=event();qb=clock()
        if done:return lower,qb
        lower=qa;sleep(.0001)
class Bounds(unittest.TestCase):
    def test_already_done_preserves_safe_earlier_lower(self):
        stamps=iter([210,220]);lo,hi=proposed_poll(lambda:True,100,lambda:next(stamps),lambda _:None)
        self.assertEqual((lo,hi),(100,220));self.assertTrue(lo<=150<=hi)
    def test_false_query_uses_begin_not_after_query(self):
        answers=iter([False,True]);stamps=iter([110,120,160,170]);lo,hi=proposed_poll(lambda:next(answers),100,lambda:next(stamps),lambda _:None)
        self.assertEqual((lo,hi),(110,170));self.assertTrue(lo<=115<=hi)
if __name__=='__main__':unittest.main(verbosity=2)
