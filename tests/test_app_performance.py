import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import Api

class QueueSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.api=Api()
        self.rows=[dict(path=f'{i}.nif',name=f'{i}.nif',status='waiting',size=i,detail='',result={'large':[1]*100}) for i in range(1000)]
        self.api._update(rows=self.rows)
    def test_incremental_counts_cover_transitions_and_empty_status_removal(self):
        self.api._change_row(self.rows[0],status='converting')
        self.api._change_row(self.rows[0],status='done',detail='verified')
        snap=self.api.snapshot()
        self.assertEqual(snap['status_counts'],{'waiting':999,'done':1})
        self.assertEqual(len(snap['rows']),250)
        self.assertNotIn('result',snap['rows'][0])
    def test_revision_reuses_page_but_updates_on_changed_row_and_offset(self):
        snap=self.api.snapshot(row_offset=0)
        args=(0,0,250,snap['rows_revision'],snap['row_offset'])
        cached=self.api.snapshot(*args)
        self.assertTrue(cached['rows_unchanged']);self.assertNotIn('rows',cached)
        self.api._change_row(self.rows[2],detail='new detail')
        fresh=self.api.snapshot(*args)
        self.assertFalse(fresh['rows_unchanged']);self.assertEqual(fresh['rows'][2]['detail'],'new detail')
        changed_page=self.api.snapshot(0,250,250,fresh['rows_revision'],fresh['row_offset'])
        self.assertEqual(changed_page['rows'][0]['name'],'250.nif')
        changed_limit=self.api.snapshot(0,0,500,fresh['rows_revision'],0)
        self.assertEqual(len(changed_limit['rows']),500)
    def test_queue_replacement_and_follow_cursor_invalidate_cached_page(self):
        old=self.api.snapshot()
        self.api._update(completed=400)
        page=self.api.snapshot(0,-1,250,old['rows_revision'],old['row_offset'])
        self.assertEqual(page['row_offset'],390);self.assertFalse(page['rows_unchanged'])
        self.api.state['rows']=[]
        snap=self.api.snapshot(0,-1,250,page['rows_revision'],page['row_offset'])
        self.assertEqual(snap['rows'],[]);self.assertEqual(snap['status_counts'],{})
    def test_logs_are_ordered_and_bounded_without_repeated_delivery(self):
        for i in range(2100):self.api._log(str(i))
        snap=self.api.snapshot()
        self.assertEqual(len(snap['logs']),2000);self.assertEqual(snap['logs'][0]['id'],101)
        self.assertEqual(self.api.snapshot(snap['log_total'])['logs'],[])
        self.api._log('last');self.assertEqual(self.api.snapshot(2100)['logs'][0]['message'],'last')

if __name__=='__main__':unittest.main()
