"""Publish-once behaviour for approved reports, with Discord replaced by a recorder."""
import tempfile
import unittest
from pathlib import Path
from gaffergpt.database import Database
from gaffergpt.reporter import Reporter
from gaffergpt.weekly_intake import save_submission
from gaffergpt.publisher import PublishError,publication,publish_report
from gaffergpt.tests.test_mvp_recap import SourceWriter


class Recorder:
    def __init__(self,fail_at=None):
        self.calls=[];self.fail_at=fail_at
    async def __call__(self,token,channel_id,content,images,nonce,title=None):
        if self.fail_at==len(self.calls):
            self.fail_at=None;raise PublishError('Discord refused the post (status 500). Nothing further was sent.')
        self.calls.append(dict(token=token,channel=channel_id,content=content,images=len(images),nonce=nonce,title=title))
        return str(9000+len(self.calls))


async def text_channel(token,channel_id,title=None,since=None):
    return False,None


class Forum:
    """A forum channel, optionally already holding the post an interrupted publish opened."""
    def __init__(self,opened=None):
        self.opened=opened;self.searched=[]
    async def __call__(self,token,channel_id,title=None,since=None):
        if title:self.searched.append(title)
        return True,self.opened if title else None


class PublisherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(Path(self.tmp.name)/'pep.db')
        self.rid=self.db.open_report('2026-10-12T04:00:00+00:00','2026-10-19T04:00:00+00:00',42)['report_id']
        save_submission(self.db,self.rid,42,30,'2026-10-15 | Official Home | Chelsea | 3-1\n2026-10-15 | Official Away | Chelsea | 2-2')
        ids=[m['match_id'] for m in self.db.period_matches('2026-10-12','2026-10-19',True)]
        self.db.replace_page_selection(self.rid,ids,ids);self.db.confirm_report(self.rid)
        Reporter(self.db,writer=SourceWriter()).generate(self.rid)
    def tearDown(self):
        del self.db;self.tmp.cleanup()
    def approve(self):
        self.db.execute("UPDATE weekly_reports SET status='approved' WHERE report_id=?",(self.rid,))

    async def test_unapproved_or_unconfigured_report_is_never_posted(self):
        post=Recorder()
        with self.assertRaises(PublishError):await publish_report(self.db,self.rid,'rt-token',77,post,text_channel)
        self.approve()
        with self.assertRaises(PublishError):await publish_report(self.db,self.rid,'',77,post,text_channel)
        with self.assertRaises(PublishError):await publish_report(self.db,self.rid,'rt-token',0,post,text_channel)
        self.assertEqual(post.calls,[]);self.assertIsNone(publication(self.db,self.rid))

    async def test_publishes_cover_then_article_once(self):
        self.approve();post=Recorder()
        ids,fresh,where=await publish_report(self.db,self.rid,'rt-token',77,post,text_channel)
        self.assertTrue(fresh);self.assertEqual(len(ids),len(post.calls));self.assertEqual(where,'77/'+ids[0])
        first=post.calls[0]
        self.assertEqual((first['token'],first['channel'],first['images']),('rt-token',77,1))
        self.assertTrue(all(c['images']==0 for c in post.calls[1:]))
        text='\n\n'.join(c['content'] for c in post.calls)
        self.assertIn('RT Football Media',text);self.assertIn('3–1',text)
        self.assertNotIn('APPROVED',text);self.assertNotIn('DRAFT',text)
        again,fresh,_=await publish_report(self.db,self.rid,'rt-token',77,post,text_channel)
        self.assertFalse(fresh);self.assertEqual(again,ids);self.assertEqual(len(post.calls),len(ids))
        self.assertEqual(publication(self.db,self.rid)['state'],'published')

    async def test_interrupted_publish_resumes_without_repeating(self):
        self.approve();post=Recorder(fail_at=0)
        with self.assertRaises(PublishError):await publish_report(self.db,self.rid,'rt-token',77,post,text_channel)
        self.assertEqual(publication(self.db,self.rid)['state'],'publishing');self.assertEqual(post.calls,[])
        with self.assertRaises(PublishError):await publish_report(self.db,self.rid,'rt-token',88,post,text_channel)
        ids,fresh,where=await publish_report(self.db,self.rid,'rt-token',77,post,text_channel)
        self.assertTrue(fresh);self.assertEqual(len(post.calls),len(ids))
        self.assertEqual(len({c['nonce'] for c in post.calls}),len(post.calls))

    async def test_forum_channel_gets_one_post_titled_with_the_headline(self):
        self.approve();post=Recorder();forum=Forum();title=self.db.report(self.rid)['title']
        ids,fresh,where=await publish_report(self.db,self.rid,'rt-token',77,post,forum)
        first=post.calls[0]
        self.assertEqual((first['channel'],first['title'],first['images']),(77,title,1))
        self.assertFalse(first['content'].startswith(title));self.assertIn('RT Football Media',first['content'])
        # The rest of the article goes inside the post, not into the forum as new posts.
        self.assertTrue(all(c['channel']==ids[0] and c['title'] is None for c in post.calls[1:]))
        self.assertEqual(where,f'{ids[0]}/{ids[0]}')
        again,fresh,where=await publish_report(self.db,self.rid,'rt-token',77,post,forum)
        self.assertFalse(fresh);self.assertEqual(again,ids);self.assertEqual(where,f'{ids[0]}/{ids[0]}')
        self.assertEqual(sum(1 for c in post.calls if c['title']),1)

    async def test_forum_post_opened_by_an_interrupted_publish_is_not_opened_again(self):
        self.approve();post=Recorder();forum=Forum(opened='555')
        ids,fresh,_=await publish_report(self.db,self.rid,'rt-token',77,post,forum)
        self.assertTrue(fresh);self.assertEqual(ids[0],'555')
        self.assertEqual(forum.searched,[self.db.report(self.rid)['title']])
        self.assertTrue(all(c['channel']=='555' and c['title'] is None for c in post.calls))


if __name__=='__main__':
    unittest.main()
