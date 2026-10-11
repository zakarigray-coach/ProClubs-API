import unittest
from gaffergpt.article_facts import fact_registry,render_checked

class ArticleFactTests(unittest.TestCase):
    def setUp(self):
        self.packet={'matches':[{'match_type':'Practice','birmingham_score':a,'opponent_score':b,'opponent':o} for a,b,o in [(2,5,'Fresh'),(3,3,'Bandz'),(6,2,'LittleD'),(2,0,'Gougherton')]],
          'observations':{'player_statistics':{'Practice':[{'player':'DaddyGray10420','appearances':4,'dribbles_completed':80,'goals':3,'assists':6,'average_rating':7.95},
             {'player':'TraapxLit','appearances':3,'dribbles_completed':39,'goals':7,'average_rating':8.633333}]}},'management':{'player_name':'TraapxLit'}}
        self.facts=fact_registry(self.packet)
        self.prose=('Birmingham found goals and mixed results in the selected practice block. The results offered a useful contrast without settling questions about the team’s competitive form. '
           'The attacking contributions provide the clearest individual talking points. These were training fixtures, so competitive conclusions will have to wait. '
           'For now, the emphasis belongs on the recorded contributions and results, with the scorer earning the club’s recognition.')
    def result(self,extra):return {'title':'Blues find goals in mixed practice block','body':self.prose+' '+extra+' [[award]]'}
    def test_figures_are_bound_to_correct_player(self):
        title,body=render_checked(self.result('[[Practice_player_0_dribbles]] [[Practice_player_1_dribbles]]'),self.facts,self.packet)
        self.assertIn('DaddyGray10420 recorded 80 completed dribbles',body)
        self.assertIn('TraapxLit recorded 39 completed dribbles',body)
    def test_free_written_wrong_figures_blocked(self):
        for text in ('DaddyGray10420 completed 39 dribbles.','DaddyGray10420 completed thirteen dribbles.'):
            with self.assertRaises(ValueError):render_checked(self.result(text),self.facts,self.packet)
    def test_repeated_facts_and_unknown_references_blocked(self):
        for text in ('[[Practice_record]] [[Practice_record]]','[[made_up]]'):
            with self.assertRaises(ValueError):render_checked(self.result(text),self.facts,self.packet)
    def test_record_calculated_and_rating_rounded(self):
        self.assertIn('2 wins, 1 draw and 1 defeat',self.facts['Practice_record'])
        self.assertIn('13 goals and conceding 10',self.facts['Practice_record'])
        self.assertIn('8.63',self.facts['Practice_player_1_rating'])
