import io, json, tempfile, unittest, zipfile
from datetime import date
from pathlib import Path
from pretraga import parse,toilet_paper
from osvjezi import links,validate_csv
from trgovci import index_files,location,xml_to_csv,download_studenac,download_files,TOMMY_INDEX,KONZUM_INDEX
from usporedba import normalize

def xml(address='Trg Fontana 8/2 BUZET'):
    item='<Proizvod><NazivProizvoda>MLIJEKO 1 L</NazivProizvoda><MarkaProizvoda>Marka</MarkaProizvoda><JedinicaMjere>kom</JedinicaMjere><MaloprodajnaCijena>1.2</MaloprodajnaCijena><MaloprodajnaCijenaAkcija>0.8</MaloprodajnaCijenaAkcija><CijenaZaJedinicuMjere>0.8</CijenaZaJedinicuMjere><Barkod>4006381333931</Barkod></Proizvod>'
    return f'<Proizvodi><ProdajniObjekt><Adresa>{address}</Adresa><Proizvodi>{item*100}</Proizvodi></ProdajniObjekt></Proizvodi>'.encode()

class NewChainsTests(unittest.TestCase):
    def test_toilet_paper_abbreviations_do_not_match_kitchen_paper(self):
        for name in ('TP ZEWA CLASSIC SOFT 3SL 16/1','TOAL. PAP. VIOLETA BRESKVA 3-SL 10 kom','PAPIR TOAL.8/1 VIOLETA 2SL'):
            self.assertTrue(toilet_paper(name),name)
        for name in ('KUHINJSKI PAPIR ZEWA','PAPIR UBRUSI','PAPAR BIJELI','TUNA RIO MARE'):
            self.assertFalse(toilet_paper(name),name)
    def test_tommy_fields_and_current_special_price(self):
        blob=b'BARKOD_ARTIKLA,NAZIV_ARTIKLA,BRAND,JEDINICA_MJERE,NETO_KOLICINA,MPC,MPC_POSEBNA_PRODAJA,CIJENA_PO_JM\n4006381333931,MLIJEKO 4X1 L,Marka,kom,4,,3.2,0.8\n'
        r=list(parse('Tommy','sample',blob,'https://example.com'))[0]
        self.assertEqual((r['brand'],r['barcode'],r['price']),('Marka','4006381333931',3.2))
        self.assertEqual(normalize(r,'mlijeko')['normalized_price'],0.8)
        r.update(chain='Konzum',unit='kg',quantity='0.50 kg',name='BATAK',price=2.0,source_unit_price=4.0)
        self.assertEqual(normalize(r,'batak')['normalized_price'],4.0)

    def test_xml_addresses_special_prices_and_foreign_stores(self):
        city,address,blob=xml_to_csv(xml())
        self.assertEqual((city,address),('Buzet','Trg Fontana 8/2'))
        self.assertEqual(validate_csv('Studenac','sample',blob,'https://example.com'),100)
        r=list(parse('Studenac','sample',blob,'https://example.com'))[0]
        self.assertEqual(r['price'],0.8);self.assertEqual(r['barcode'],'4006381333931')
        self.assertEqual(normalize(r,'mlijeko')['normalized_price'],0.8)
        self.assertEqual(xml_to_csv(xml('Bijela uvala 5 FUNTANA'))[:2],('Funtana','Bijela uvala 5'))
        self.assertIsNone(xml_to_csv(xml('Plinjanska 67 PLOČE')))
        with self.assertRaises(ValueError):xml_to_csv(b'<!DOCTYPE test>'+xml())

    def test_konzum_pagination_and_commas_in_address(self):
        u=KONZUM_INDEX+'?date=2026-10-10&page=1';u2=KONZUM_INDEX+'?date=2026-10-10&page=2'
        first='/cjenici/download?title=SUPERMARKET,KOPARSKA 1 52100 PULA,1,2,10.10.2026, 05-21.CSV'
        second='/cjenici/download?title=SUPERMARKET,CARLOTTA GRISI 5, SVETI ANTON 52466 NOVIGRAD,3274,100038,10.10.2026, 05-22.CSV'
        pages={u:f'<a href="{first}">CSV</a><a href="{u2}">2</a>',u2:f'<a href="{second}">CSV</a><a href="{u}">1</a>'}
        dt,index,entries=index_files('Konzum',date(2026,10,10),lambda url:pages[url].encode(),links)
        self.assertEqual(dt,'2026-10-10');self.assertEqual(len(entries),2)
        self.assertEqual({e['city'] for e in entries},{'Pula','Novigrad'})
        self.assertIsNone(location('Konzum','SUPERMARKET,LABINSKA 51A 51000 RIJEKA,1,2,10.10.2026, 05-21.CSV'))

    def test_tommy_hydra_pagination_and_incomplete_index(self):
        u=TOMMY_INDEX+'?date=2026-10-10&page=1&itemsPerPage=200&channelCode=general'
        u2=TOMMY_INDEX+'?date=2026-10-10&page=2'
        item={'fileName':'SUPERMARKET, BRAJDE 9, 52465 TAR, 1, 2, 20261010 0530','@id':'/api/v2/shop/store-prices-tables/file'}
        data={u:{'hydra:totalItems':1,'hydra:member':[],'hydra:view':{'hydra:next':u2}},u2:{'hydra:member':[item]}}
        _,_,entries=index_files('Tommy',date(2026,10,10),lambda url:json.dumps(data[url]).encode(),links)
        self.assertEqual(entries[0]['city'],'Tar')
        data[u]['hydra:totalItems']=2
        with self.assertRaisesRegex(ValueError,'potpun'):index_files('Tommy',date(2026,10,10),lambda url:json.dumps(data[url]).encode(),links)

    def test_studenac_archive_validates_date_and_selects_only_istria(self):
        def archive(day):
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w') as z:
                z.writestr(f'SUPERMARKET-BUZET-{day}.xml',xml())
                z.writestr(f'SUPERMARKET-FUNTANA-{day}.xml',xml('Bijela uvala 5 FUNTANA'))
                z.writestr(f'SUPERMARKET-PLOCE-{day}.xml',xml('Plinjanska 67 PLOČE'))
            return out.getvalue()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            result=download_studenac(date(2026,10,10),lambda u:archive('2026-10-10'),validate_csv,root,root)
            self.assertEqual(len(result['files']),2)
            with self.assertRaisesRegex(ValueError,'Datum'):download_studenac(date(2026,10,10),lambda u:archive('2026-10-09'),validate_csv,root,root)

    def test_failed_file_never_publishes_incomplete_chain(self):
        u=TOMMY_INDEX+'?date=2026-10-10&page=1&itemsPerPage=200&channelCode=general'
        item={'fileName':'SUPERMARKET, BRAJDE 9, 52465 TAR, 1, 2, 20261010 0530','@id':'/api/v2/shop/store-prices-tables/file'}
        def fetch(url):
            if url==u:return json.dumps({'hydra:totalItems':1,'hydra:member':[item]}).encode()
            raise TimeoutError('offline')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'nisu preuzeti svi'):download_files('Tommy',date(2026,10,10),fetch,links,validate_csv,Path(d),Path(d))

if __name__=='__main__':unittest.main()
