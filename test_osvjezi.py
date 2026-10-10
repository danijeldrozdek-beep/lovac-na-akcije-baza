import io, json, tempfile, unittest, zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch
import osvjezi

class RefreshTests(unittest.TestCase):
    def test_latest_official_link_ignores_future_and_order(self):
        html='<option value="/cjenik_09.10.2026.zip">staro</option><option value="/cjenik_11.10.2026.zip">sutra</option><option value="/cjenik_10.10.2026.zip">danas</option>'
        links=osvjezi.links(html,'https://example.com/page')
        self.assertEqual(osvjezi.newest(links,date(2026,10,10)),('2026-10-10','https://example.com/cjenik_10.10.2026.zip'))
        self.assertEqual(osvjezi.dated('cjenici_10_10_2026_07_00_01.zip'),date(2026,10,10))

    def test_reject_html_and_truncated_price_list(self):
        with self.assertRaises(ValueError):osvjezi.validate_csv('Lidl','test.csv',b'<html>Error</html>','https://example.com')
        with self.assertRaises(ValueError):osvjezi.validate_csv('Lidl','test.csv',b'naziv;MPC\nmlijeko;1','https://example.com')

    def test_same_release_uses_cache_and_rejects_older_release(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'0.csv').write_text('cached')
            old={'date':'2026-10-10','url':'https://example.com/10.zip','sha256':'abc','files':[{'path':'0.csv'}]}
            with patch.object(osvjezi,'ROOT',p),patch.object(osvjezi,'discover',return_value=('2026-10-10',old['url'],'abc')):
                fresh,_=osvjezi.update_one('Plodine',old,p,date(2026,10,10),lambda u:self.fail('cached file downloaded again'))
                self.assertIs(fresh,old)
            with patch.object(osvjezi,'discover',return_value=('2026-10-09','https://example.com/9.zip',None)):
                with self.assertRaises(ValueError):osvjezi.update_one('Plodine',old,p,date(2026,10,10))

    def test_hash_mismatch_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):osvjezi.ingest('SPAR / INTERSPAR','2026-10-10','https://example.com/x.csv',b'bad',Path(d),'0'*64)
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_same_url_changed_etag_downloads_again(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'0.csv').write_text('old')
            old={'date':'2026-10-10','url':'https://example.com/x.csv','sha256':'old','files':[{'path':'0.csv'}],'remote_version':{'etag':'old'}}
            fetch=lambda url:b'new'
            fetch.official_fetch=True
            with patch.object(osvjezi,'ROOT',root),patch.object(osvjezi,'discover',return_value=('2026-10-10',old['url'],None)),patch.object(osvjezi,'remote_version',return_value={'etag':'new'}),patch.object(osvjezi,'ingest',return_value={'date':'2026-10-10'}) as ingest:
                new,_=osvjezi.update_one('Lidl',old,root,date(2026,10,10),fetch)
                ingest.assert_called_once()
                self.assertEqual(new['remote_version'],{'etag':'new'})

    def test_official_hash_does_not_require_head(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'0.csv').write_text('cached')
            old={'date':'2026-10-10','url':'https://example.com/x.csv','sha256':'abc','files':[{'path':'0.csv'}]}
            fetch=lambda url:self.fail('unchanged SHA downloaded')
            fetch.official_fetch=True
            with patch.object(osvjezi,'ROOT',root),patch.object(osvjezi,'discover',return_value=('2026-10-10',old['url'],'abc')),patch.object(osvjezi,'remote_version',side_effect=AssertionError('HEAD must not be required')):
                new,_=osvjezi.update_one('SPAR / INTERSPAR',old,root,date(2026,10,10),fetch)
                self.assertIs(new,old)

    def test_failed_source_keeps_previous_and_build_failure_keeps_page(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);statefile=root/'cjenici-stanje.json'
            previous={'chains':{'Plodine':{'date':'2026-10-09','files':[{'path':'old.csv'}]}},'status':[]}
            statefile.write_text(json.dumps(previous));page=root/'Lovac-na-akcije.html';page.write_text('previous page')
            seen=[]
            def broken_build(state,output):
                seen.append(state)
                raise ValueError('parser failed')
            with patch.object(osvjezi,'ROOT',root),patch.object(osvjezi,'STATE',statefile),patch.object(osvjezi,'update_one',side_effect=TimeoutError('offline')),patch.object(osvjezi,'build',side_effect=broken_build):
                with self.assertRaises(ValueError):osvjezi.refresh(today=date(2026,10,10))
            self.assertEqual(seen[0]['chains'],previous['chains'])
            self.assertTrue(all(not x['ok'] for x in seen[0]['status']))
            self.assertEqual(page.read_text(),'previous page')
            self.assertEqual(json.loads(statefile.read_text()),previous)

if __name__=='__main__':unittest.main()
