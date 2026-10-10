import gzip, hashlib, importlib.util, json, sqlite3, tempfile, unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('cloud',Path(__file__).with_name('cloud-run.py'))
cloud=importlib.util.module_from_spec(spec);spec.loader.exec_module(cloud)
spec=importlib.util.spec_from_file_location('publisher',Path(__file__).with_name('objavi-katalog.py'))
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)

class HostingTests(unittest.TestCase):
    def feed(self,root):
        dbfile=root/'test.sqlite'
        with closing(sqlite3.connect(dbfile)) as db:
            for table in ('products','stores','offers'):
                db.execute(f'CREATE TABLE {table}(id INTEGER)');db.execute(f'INSERT INTO {table} VALUES(1)')
            db.execute('CREATE TABLE metadata(key TEXT,value TEXT)')
            db.executemany('INSERT INTO metadata VALUES(?,?)',[('schema','1'),('date_min','2026-10-10'),('date_max','2026-10-10')])
            db.commit()
        blob=gzip.compress(dbfile.read_bytes());digest=hashlib.sha256(blob).hexdigest()
        folder=root/'internet-katalog';folder.mkdir();name=f'katalog-{digest}.bin';(folder/name).write_bytes(blob)
        manifest=dict(schema=1,file=name,sha256=digest,compressed_bytes=len(blob),database_bytes=dbfile.stat().st_size,products=1,stores=1,offers=1,date_min='2026-10-10',date_max='2026-10-10')
        (folder/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        return folder,manifest

    def test_valid_feed_and_corrupt_download(self):
        with tempfile.TemporaryDirectory() as d:
            folder,m=self.feed(Path(d));self.assertEqual(cloud.verify_feed(folder),m)
            path=folder/m['file'];blob=bytearray(path.read_bytes());blob[15]^=1;path.write_bytes(blob)
            with self.assertRaisesRegex(ValueError,'SHA'):cloud.verify_feed(folder)

    def test_reject_wrong_catalogue_counts(self):
        with tempfile.TemporaryDirectory() as d:
            folder,m=self.feed(Path(d));m['products']=2;(folder/'manifest.json').write_text(json.dumps(m),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'broj'):cloud.verify_feed(folder)

    def test_cleanup_keeps_referenced_prices_and_previous_feeds(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,m=self.feed(root)
            prices=root/'cjenici';prices.mkdir();(prices/'keep.csv').write_text('keep');(prices/'old.csv').write_text('old')
            for i in range(4):(folder/f'katalog-{str(i)*64}.bin').write_bytes(b'old')
            cloud.compact(root,{'chains':{'Test':{'files':[{'path':'cjenici\\keep.csv'}]}}})
            self.assertTrue((prices/'keep.csv').is_file());self.assertFalse((prices/'old.csv').exists())
            self.assertEqual(len(list(folder.glob('katalog-*.bin'))),3);self.assertTrue((folder/m['file']).exists())

    def test_unsafe_cache_path_stops_before_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);prices=root/'cjenici';prices.mkdir();(prices/'old.csv').write_text('old');(root/'outside.csv').write_text('outside')
            with self.assertRaisesRegex(ValueError,'putanja'):cloud.compact(root,{'chains':{'Test':{'files':[{'path':'outside.csv'}]}}})
            self.assertTrue((prices/'old.csv').exists());self.assertTrue((root/'outside.csv').exists())

    def test_bootstrap_and_export_failure_keep_published_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,m=self.feed(root);original=(folder/'manifest.json').read_bytes()
            with patch.object(publisher,'ROOT',root),patch.object(publisher,'read_state',return_value={'chains':{}}):
                with self.assertRaisesRegex(ValueError,'Nema ispravnog'):publisher.publish(False)
            for name in ('pretraga.py','usporedba.py'):(root/name).write_text('# fixture')
            (root/'izvezi-katalog.py').write_text("def export():\n    raise ValueError('Parser failed')\n")
            state={'chains':{k:dict(date='2026-10-10',sha256='new') for k in publisher.PAGES}}
            with patch.object(publisher,'ROOT',root),patch.object(publisher,'read_state',return_value=state):
                with self.assertRaisesRegex(ValueError,'Parser failed'):publisher.publish(False)
            self.assertEqual((folder/'manifest.json').read_bytes(),original)

if __name__=='__main__':unittest.main()
