import unittest
from usporedba import normalize, size

def row(**kwargs):
    result=dict(chain='Plodine',name='MLIJEKO 1 L',price=.8,unit='KOM',quantity='',available='DOSTUPNO',source_unit_price=.8,special_price=None)
    result.update(kwargs);return result

class ComparisonTests(unittest.TestCase):
    def test_pack_is_not_kilogram(self):
        r=normalize(row(name='PILECI BATAK 500 G',price=2.79,source_unit_price=5.58),'batak')
        self.assertEqual(r['normalized_price'],5.58)
        self.assertEqual(r['pack_quantity'],.5)
        self.assertEqual(r['sale_mode'],'pakiranje')

    def test_weight_price_not_divided_by_label(self):
        r=normalize(row(name='BATAK 500 G',price=5.15,unit='KG',source_unit_price=None),'batak')
        self.assertEqual(r['normalized_price'],5.15)
        self.assertEqual(r['sale_mode'],'vaganje')
        self.assertIsNone(r['pack_quantity'])

    def test_multipack(self):
        self.assertEqual(size('MLIJEKO 6X1 L (120/PAL)'),(6,'l'))
        r=normalize(row(name='MLIJEKO 6X1 L',price=5.4,source_unit_price=.9),'mlijeko')
        self.assertEqual(r['normalized_price'],.9)

    def test_ambiguous_weight_and_conflict(self):
        r=normalize(row(chain='Lidl',name='Svježi pileći batak, cca. 500g',unit='ca. 500g',quantity='1',price=4.09,source_unit_price=4.09),'batak')
        self.assertIsNone(r['normalized_price'])
        r=normalize(row(name='MLIJEKO 6X1 L',price=.9,source_unit_price=.9),'mlijeko')
        self.assertIsNone(r['normalized_price'])
        r=normalize(row(name='BATAK 500 G I 1 KG',price=4,source_unit_price=None),'batak')
        self.assertIsNone(r['normalized_price'])

    def test_explicit_units_and_special_price(self):
        r=normalize(row(chain='SPAR / INTERSPAR',name='PILEĆI BATAK 500 g',unit='kg',quantity='0,5000',price=2.19,source_unit_price=4.38),'batak')
        self.assertEqual(r['normalized_price'],4.38)
        r=normalize(row(chain='Eurospin',name='SVINJSKI VRAT 500g',unit='KG',quantity='0,5',price=2.49,special_price=2.49,special_unit_price=4.98,source_unit_price=7.78),'vratina')
        self.assertEqual(r['normalized_price'],4.98)

    def test_milk_density_and_filters(self):
        r=normalize(row(chain='Lidl',name='Trajno mlijeko 2,8%',unit='1l',quantity='1.031',price=.69,source_unit_price=.69),'mlijeko')
        self.assertEqual(r['normalized_price'],.69)
        self.assertEqual(r['fat'],'2.8')
        self.assertEqual(r['milk_type'],'trajno')
        self.assertEqual(normalize(row(name='SV. VRAT B.K.'),'vratina')['bone'],'bez kosti')
        self.assertEqual(normalize(row(name='PUREĆI BATAK SKK RFZ'),'batak')['species'],'pureće')
        self.assertEqual(normalize(row(name='PILEĆI BATAK SA ZABATKOM'),'batak')['species'],'pileće')

if __name__=='__main__':unittest.main()
