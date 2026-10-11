import tempfile
import unittest
from pathlib import Path
from gaffergpt.database import Database
from gaffergpt.weekly_intake import save_submission
from gaffergpt.reporter import Reporter
from gaffergpt.article_writer import SportsWriter, editorial_packet

class SportsArticleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/'db.sqlite')
        self.rid=self.db.open_report('2026-10-05T04:00:00+00:00','2026-10-12T04:00:00+00:00','1')['report_id']
        save_submission(self.db,self.rid,'1','guild','2026-10-06 | Practice | Chelsea | 2-1\n2026-10-07 | Practice | Arsenal | 0-3')
        ids=[r['match_id'] for r in self.db.rows('SELECT match_id FROM matches')]
        self.db.replace_page_selection(self.rid,ids,ids[:1]);self.db.confirm_report(self.rid)
    def tearDown(self):self.tmp.cleanup()
    def test_writer_gets_only_selected_facts_and_readable_dates(self):
        class Writer:
            def write(inner,packet):
                self.assertEqual(len(packet['matches']),1)
                self.assertEqual(packet['matches'][0]['opponent'],'Chelsea')
                self.assertNotIn('match_id',packet['matches'][0])
                self.assertIn('October 5',packet['period'])
                return 'Blues find a training-ground lift','Birmingham beat Chelsea 2–1 in practice.'
        article=Reporter(self.db,writer=Writer()).generate(self.rid)
        self.assertIn('Blues find a training-ground lift',article)
        self.assertNotIn('PLAYER STATS',article)
        self.assertNotIn('end exclusive',article)
        self.assertEqual(self.db.report(self.rid)['status'],'draft')
    def test_provider_failure_preserves_confirmed_report_for_retry(self):
        class Writer:
            def write(self,packet):raise RuntimeError('provider unavailable')
        with self.assertRaises(RuntimeError):Reporter(self.db,writer=Writer()).generate(self.rid)
        self.assertEqual(self.db.report(self.rid)['status'],'confirmed')
        self.assertFalse(self.db.report(self.rid)['article'])
    def test_provider_uses_structured_article_output(self):
        payload=SportsWriter('test').payload('{}')
        self.assertEqual(payload['text']['format']['schema']['required'],['title','body'])
        self.assertIn('500–750',payload['instructions'])

    def test_legacy_outfield_conceded_stats_never_reach_writer(self):
        packet={'observations':{'player_statistics':{'Practice':[
            {'player':'Outfield','appearances':4,'goals_conceded':10,'clean_sheets':1,'metric_samples':{'goals_conceded':4}},
            {'player':'Keeper','appearances':2,'goalkeeper_appearances':2,'goals_conceded':3}]}}}
        clean=editorial_packet(packet)['observations']['player_statistics']['Practice']
        self.assertNotIn('goals_conceded',clean[0])
        self.assertNotIn('clean_sheets',clean[0])
        self.assertEqual(clean[1]['goals_conceded'],3)
        self.assertEqual(packet['observations']['player_statistics']['Practice'][0]['goals_conceded'],10)

    def test_recap_reset_preserves_matches_and_is_one_time(self):
        from gaffergpt.recap_reset import reset_recap
        self.db.set_setting('recap_preview:old','{"report_id":'+str(self.rid)+'}')
        self.db.set_setting(f'weekly_excel:{self.rid}','old workbook')
        self.assertTrue(reset_recap(self.db,self.rid,'1','test'))
        self.assertEqual(len(self.db.selected(self.rid)),0)
        self.assertEqual(len(self.db.rows('SELECT * FROM matches')),2)
        self.assertEqual(self.db.report(self.rid)['status'],'selecting')
        self.assertEqual(self.db.setting('weekly_dm_awaiting'),str(self.rid))
        self.assertFalse(reset_recap(self.db,self.rid,'1','test'))
        self.assertFalse(self.db.setting('recap_preview:old'))

class FinishedArticleTests(unittest.TestCase):
    def test_known_broken_grammar_is_rejected(self):
        from gaffergpt.article_writer import check_finished_prose
        for broken in ('one goals and one assists across one practice appearances',
                       'before a commanding the win', 'Those the results'):
            with self.assertRaises(ValueError):
                check_finished_prose({'title':'Birmingham find goals','body':('Birmingham played practice football. '*15)+broken},{})

    def test_audit_is_about_rendered_language_and_attribution(self):
        import json
        payload=SportsWriter('test').payload(json.dumps({'desk_task':'audit_finished_article'}))
        self.assertIn('correct player and fixture',payload['instructions'])
        self.assertIn('FINISHED article',payload['instructions'])

    def test_failed_final_review_retries_before_returning(self):
        import json
        calls=[]
        prose=('Birmingham’s practice programme brought contrasting results, with attacking contributions providing the clearest individual talking points. '
               'The fixtures belong to the training ground rather than the competitive record. '
               'For supporters, the immediate interest lies in those contributions; league conclusions will need competitive evidence.')
        class Writer(SportsWriter):
            async def advise(self,analysis,formation=''):
                request=json.loads(analysis);calls.append(request)
                if request.get('desk_task')=='audit_finished_article':
                    audits=sum(c.get('desk_task')=='audit_finished_article' for c in calls)
                    return json.dumps({'title':'FAIL' if audits==1 else 'PASS','body':'Remove repetition' if audits==1 else ''})
                return json.dumps({'title':'Birmingham weigh contrasting practice returns','body':prose})
        title,body=Writer('test').write({'matches':[],'observations':{},'management':{}})
        self.assertEqual(body,prose)
        self.assertEqual(sum(c.get('desk_task')=='audit_finished_article' for c in calls),2)
        self.assertEqual(calls[-1]['finished_article']['body'],prose)
        self.assertEqual(calls[-2]['validation_feedback'],'Remove repetition')

    def test_equivalent_decimal_display_does_not_reject_correct_rating(self):
        from gaffergpt.article_writer import check_finished_prose
        check_finished_prose({'title':'Birmingham review practice returns',
            'body':('The training fixtures offered a useful snapshot of the club’s results. '*5)+'A player averaged 8.1.'},
            {'rating':'A player averaged 8.10.'})

class NewspaperQualityTests(unittest.TestCase):
    def setUp(self):
        self.packet={'matches':[], 'management':{'player_name':'TraapxLit'},
                     'observations':{'player_statistics':{'Practice':[
                         {'player':'TraapxLit','goals':7,'assists':2,'appearances':3,'average_rating':8.633333},
                         {'player':'DaddyGray10420','goals':3,'assists':6,'appearances':4,'dribbles_completed':80},
                         {'player':'Third','goals':1,'assists':0,'appearances':1},
                         {'player':'Fourth','goals':1,'assists':0,'appearances':1}]}}}
    def test_previous_roll_call_and_policy_ending_are_rejected(self):
        from gaffergpt.article_writer import check_feature_quality
        for body in ('TraapxLit scored seven goals. Other contributors',
                     'TraapxLit scored seven goals. The week produced a non-negligible volume of goals conceded.',
                     'TraapxLit scored seven goals. Those are the confirmed figures; any conclusions belong to the coaching staff.',
                     'TraapxLit DaddyGray10420 Third Fourth'):
            with self.assertRaises(ValueError):check_feature_quality({'body':body},self.packet)
    def test_opening_must_feature_main_story(self):
        from gaffergpt.article_writer import check_feature_quality
        with self.assertRaises(ValueError):
            check_feature_quality({'body':'Birmingham played four games.\n\nTraapxLit scored seven goals.'},self.packet)
        check_feature_quality({'body':'TraapxLit scored seven goals during a mixed practice block.'},self.packet)
    def test_story_brief_excludes_roster_and_secondary_metrics(self):
        from gaffergpt.article_writer import feature_facts
        facts=' '.join(feature_facts(self.packet).values())
        self.assertIn('TraapxLit',facts);self.assertIn('DaddyGray10420',facts)
        self.assertNotIn('Third',facts);self.assertNotIn('Fourth',facts)
        self.assertNotIn('dribbles',facts);self.assertIn('8.63',facts)
