"""Prepare the full offline SQLite catalogue for the native Android app."""
import gzip, json, re, sqlite3, sys
from pathlib import Path
from pretraga import ROOT, parse, norm, match
from usporedba import size, normalize, store_info

def unit_info(row):
    unit=norm(row['unit']);found=size(row['unit']) if row['chain']=='Lidl' else size(row['name']) or size(row.get('quantity',''))
    basis='l' if unit in ('l','lt','ml') else 'kg' if unit in ('kg','g') else found[1] if found else None
    if basis:
        r=normalize(row,'mlijeko' if basis=='l' else 'batak')
        return r['compare_unit'],r['normalized_price'],r['normalization_note']
    # Counts refer to declared pieces, never convert washes, rolls or sheets to pieces.
    amounts=set(int(x) for x in re.findall(r'\b(\d+)\s*(?:kom|komada|komad|pcs)\b',norm(row['name'])))
    if unit in ('kom','komad','komada','ko'):
        if len(amounts)>1:return '',None,'Broj komada nije jednoznačan.'
        count=next(iter(amounts)) if amounts else 1
        if count>0:return 'kom',round(row['price']/count,4),'Broj komada iz naziva' if amounts else 'Prodajna jedinica KOM; provjeri pakiranje'
    return '',None,'Nije potvrđena usporediva jedinica.'

def export():
    manifest=json.loads((ROOT/'cjenici-stanje.json').read_text(encoding='utf-8'))
    assets=ROOT/'android/app/src/main/assets';assets.mkdir(parents=True,exist_ok=True)
    path=ROOT/'katalog-staging.sqlite';path.unlink(missing_ok=True)
    db=sqlite3.connect(path)
    db.executescript('''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
    CREATE TABLE products(id INTEGER PRIMARY KEY,name TEXT,brand TEXT,search_name TEXT,tags TEXT);
    CREATE TABLE stores(id INTEGER PRIMARY KEY,chain TEXT,city TEXT,address TEXT,date TEXT,source TEXT);
    CREATE TABLE offers(product_id INTEGER,store_id INTEGER,price REAL,unit TEXT,unit_price REAL,availability TEXT,note TEXT,barcode TEXT);
    CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);''')
    products={};count=0;store_count=0;tag_count=0
    for chain,info in manifest['chains'].items():
        for f in info['files']:
            city,address=store_info(chain,f['name']);city=f.get('city',city);address=f.get('address',address)
            city={'Porec':'Poreč','Fazana':'Fažana','Zminj':'Žminj','Nedescina':'Nedešćina','Novigrad(Cittanova)':'Novigrad'}.get(city,city)
            store_count+=1
            db.execute('INSERT INTO stores VALUES(?,?,?,?,?,?)',(store_count,chain,city,address,info['date'],f['source']))
            rows=[]
            for row in parse(chain,f['name'],(ROOT/f['path'].replace('\\','/')).read_bytes(),f['source']):
                key=(row['name'],row['brand'])
                if key not in products:
                    pid=len(products)+1
                    tags='|'+ '|'.join(k for k in ('mlijeko','batak','vratina','svinjetina','jaja','kava','krumpir','secer','ulje') if match(k,row['name'])==1)+'|'
                    db.execute('INSERT INTO products VALUES(?,?,?,?,?)',(pid,*key,norm(row['name']+' '+row['brand']),tags))
                    products[key]=pid
                unit,per,note=unit_info(row)
                # Paper, detergents, nappies and pet items have incomparable package sizes.
                n=norm(row['name'])
                if unit=='kom' and re.search(r'\b(papir\w*|toal\w*|ubrusi|pelene|pijesak|vlaz\w*|deterd\w*|prasak|omeks\w*)\b',n):
                    unit='';per=None;note='Pakiranje se uspoređuje prema broju komada, doza ili listova; jedinica nije potvrđena.'
                avail='nedostupno' if norm(row['available'])=='nedostupno' else 'dostupno' if norm(row['available'])=='dostupno' else 'nepoznato'
                rows.append((products[key],store_count,row['price'],unit,per,avail,note,row['barcode']))
                count+=1
            db.executemany('INSERT INTO offers VALUES(?,?,?,?,?,?,?,?)',rows);db.commit()
            print(chain,city,'artikli:',len(rows),flush=True)
    # Same barcode/name/price repeated within a store is a duplicate listing.
    db.executescript('''DELETE FROM offers WHERE rowid NOT IN (SELECT MIN(rowid) FROM offers GROUP BY product_id,store_id,price,unit,unit_price,availability,barcode);
    CREATE INDEX offers_product ON offers(product_id);
    CREATE INDEX offers_store ON offers(store_id);''')
    meta={'date_min':min(x['date'] for x in manifest['chains'].values()),'date_max':max(x['date'] for x in manifest['chains'].values()),'products':str(len(products)),'stores':str(store_count),'chains':str(len(manifest['chains'])),'raw_rows':str(count),'schema':'1'}
    db.executemany('INSERT INTO metadata VALUES(?,?)',meta.items());db.commit()
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    meta['offers']=str(db.execute('SELECT COUNT(*) FROM offers').fetchone()[0]);db.close()
    with path.open('rb') as src,gzip.open(ROOT/'katalog-staging.bin','wb',compresslevel=6) as dst:
        import shutil;shutil.copyfileobj(src,dst)
    path.replace(ROOT/'katalog.sqlite')
    (ROOT/'katalog-staging.bin').replace(assets/'katalog.bin')
    import hashlib
    with (assets/'katalog.bin').open('rb') as packed:
        (assets/'katalog-verzija.txt').write_text(hashlib.file_digest(packed,'sha256').hexdigest(),encoding='utf-8')
    (assets/'pretraga-pravila.json').write_bytes((ROOT/'pretraga-pravila.json').read_bytes())
    (ROOT/'KATALOG-STATUS.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(meta,flush=True)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');export()


