import io,json,tempfile,unittest,zipfile
from pathlib import Path
from datetime import date
from pretraga import parse
from trgovci import xlsx_to_csv,extra_index
from osvjezi import links
from pivac import catalogues,verified_offers

class ExtraChainsTests(unittest.TestCase):
 def test_sparse_excel_preserves_price_columns(self):
  rows='<row r="1"><c r="A1" t="inlineStr"><is><t>Naziv</t></is></c><c r="B1" t="inlineStr"><is><t>Barkod</t></is></c><c r="C1" t="inlineStr"><is><t>Marka</t></is></c><c r="D1" t="inlineStr"><is><t>MP cijena</t></is></c><c r="E1" t="inlineStr"><is><t>Jedinica mjere</t></is></c><c r="F1" t="inlineStr"><is><t>MPC u vrij. pos. obl. prodaje</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>Mlijeko 1 L</t></is></c><c r="B2" t="inlineStr"><is><t>0123456789012</t></is></c><c r="D2"><v>1.49</v></c><c r="E2" t="inlineStr"><is><t>KOMAD</t></is></c><c r="F2"><v>0.99</v></c></row>'
  out=io.BytesIO()
  with zipfile.ZipFile(out,'w') as z:z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+rows+'</sheetData></worksheet>')
  r=list(parse('Stanić','test',xlsx_to_csv(out.getvalue()),'https://diskont.hr'))[0]
  self.assertEqual((r['price'],r['brand'],r['barcode']),(0.99,'','0123456789012'))
 def test_kaufland_tab_delimiter_and_special_price(self):
  b='naziv proizvoda\tmarka proizvoda\tmaloprod.cijena(EUR)\tMPC poseb.oblik prod\tcijena jed.mj.(EUR)\tjedinica mjere\tbarkod\tDostupan/Nedostupan\nMlijeko 1L\tMarka\t1,49\t0,99\t0,99\tKOM\t0123456789012\tdostupno\n'.encode()
  r=list(parse('Kaufland','test',b,'https://www.kaufland.hr'))[0]
  self.assertEqual((r['price'],r['source_unit_price'],r['available']),(0.99,0.99,'dostupno'))
 def test_kaufland_selects_latest_date_not_last_index_item(self):
  page='https://www.kaufland.hr/akcije-novosti/popis-mpc.html';idx='https://www.kaufland.hr/index.json'
  def item(dt):
   name='Hipermarket_Jurja_Zakna_3_Pula_2630_'+dt+'_7-30.csv';return dict(label=name,path='/'+name)
  data={page:b"<div data-props='{\"settings\":{\"dataUrlAssets\":\"/index.json\"}}'></div>",idx:json.dumps([item('10102026'),item('09102026'),item('11102026')]).encode()}
  dt,_,entries=extra_index('Kaufland',date(2026,10,10),data.__getitem__,links)
  self.assertEqual(dt,'2026-10-10');self.assertEqual(len(entries),1)
 def test_stanic_incomplete_supported_store_list_rejected(self):
  page='https://diskont.hr/cjenici/';idx='https://drive.google.com/drive/folders/test'
  data={page:('<a href="'+idx+'">Cijene</a>').encode(),idx:b'<div aria-label="MP_734_DISKONT PULA_10-10-2026-050000.xlsx Microsoft Excel Shared" ssk=\'5:auSv138:1G4YgjOF3v_IIwKp0_uOdWTGS9f3EADfX-0-16\'>'}
  with self.assertRaisesRegex(ValueError,'potpun'):extra_index('Stanić',date(2026,10,10),data.__getitem__,links)
 def test_pivac_catalogue_dates_and_empty_offers(self):
  h='<div class="views-row"><time datetime="2026-10-05T12:00:00Z">05/10/2026</time><time datetime="2026-10-11T12:00:00Z">11/10/2026</time>'
  self.assertEqual(catalogues(h)[0]['valid_until'],'2026-10-11')
  with self.assertRaises(ValueError):catalogues('No dates')
 def test_pivac_requires_price_units_validity_and_real_location_source(self):
  offer=dict(name='Batak',price=2.99,unit='kg',valid_from='2026-10-05',valid_until='2026-10-11',source='https://pivac.hr/hr/akcijski-katalozi',locations=[])
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'offers.json';p.write_text(json.dumps({'offers':[offer]}))
   with self.assertRaisesRegex(ValueError,'poslovnice'):verified_offers(p)
   offer['locations']=[dict(city='Pula',address='Test',source='https://example.com')];p.write_text(json.dumps({'offers':[offer]}))
   with self.assertRaisesRegex(ValueError,'poslovnica'):verified_offers(p)

if __name__=='__main__':unittest.main()
