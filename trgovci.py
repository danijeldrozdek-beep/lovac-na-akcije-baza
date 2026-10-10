"""Official Konzum/Tommy indexes and Studenac XML, limited to verified Istrian stores."""
import csv, hashlib, io, json, re, time, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit, parse_qs
from pretraga import norm

TOMMY_INDEX='https://spiza.tommy.hr/api/v2/shop/store-prices-tables'
KONZUM_INDEX='https://www.konzum.hr/cjenici'
STUDENAC_ARCHIVE='https://www.studenac.hr/cjenici/PROIZVODI-{date}.zip'
# Municipality names are used only to interpret addresses actually present in the XML.
ISTRIA=['Buzet','Funtana','Pula','Poreč','Rovinj','Umag','Pazin','Labin','Novigrad','Vodnjan','Medulin','Fažana','Vrsar','Tar','Višnjan','Vižinada','Žminj','Bale','Buje','Brtonigla','Barban','Svetvinčenat','Raša','Nedešćina','Banjole','Ližnjan','Marčana','Kršan','Motovun','Grožnjan','Oprtalj','Cerovlje','Lupoglav','Sveti Petar u Šumi','Tinjan','Pićan','Gračišće','Karojba','Lanišće','Kanfanar','Sveti Lovreč','Kaštelir','Labinci']

def filename_date(name):
    for pattern,fmt in [(r'(20\d{2}-\d{2}-\d{2})','%Y-%m-%d'),(r'(\d{2}\.\d{2}\.20\d{2})','%d.%m.%Y'),(r'(20\d{6})','%Y%m%d')]:
        m=re.search(pattern,name)
        if m:
            try:return datetime.strptime(m[1],fmt).date()
            except ValueError:pass
    return None

def location(chain,name):
    parts=[p.strip() for p in name.split(',')]
    if chain=='Tommy' and len(parts)>=6:
        m=re.fullmatch(r'(52\d{3})\s+(.+)',parts[2])
        if m:return m[2].title(),parts[1]
    if chain=='Konzum' and len(parts)>=6:
        m=re.fullmatch(r'(.+?)\s+(52\d{3})\s+(.+)',', '.join(parts[1:-4]))
        if m:return m[3].title(),m[1]
    return None

def index_files(chain,today,fetch,extract_links):
    for offset in range(7):
        day=today-timedelta(days=offset)
        entries=[]
        if chain=='Tommy':
            url=TOMMY_INDEX+f'?date={day.isoformat()}&page=1&itemsPerPage=200&channelCode=general'
            members=[];seen=set();expected=None
            while url:
                if url in seen or len(seen)>=30:raise ValueError('Neispravna paginacija Tommy indeksa.')
                if urlsplit(url).netloc!='spiza.tommy.hr':raise ValueError('Tommy indeks izlazi sa službenog poslužitelja.')
                seen.add(url);data=json.loads(fetch(url).decode('utf-8-sig'))
                members+=data.get('hydra:member',[])
                if expected is None:expected=data.get('hydra:totalItems')
                next_url=data.get('hydra:view',{}).get('hydra:next')
                url=urljoin(TOMMY_INDEX,next_url) if next_url else None
            if expected is not None and len(members)!=expected:raise ValueError('Tommy indeks nije potpun.')
            for item in members:
                name=item['fileName'];loc=location(chain,name)
                if not loc:continue
                if filename_date(name)!=day:raise ValueError('Tommy datum datoteke ne odgovara indeksu.')
                url=urljoin(TOMMY_INDEX,item['@id'])
                if urlsplit(url).netloc!='spiza.tommy.hr':raise ValueError('Neslužbena Tommy datoteka.')
                entries.append(dict(name=name,url=url,city=loc[0],address=loc[1]))
            index_url=TOMMY_INDEX+f'?date={day.isoformat()}&page=1&itemsPerPage=200&channelCode=general'
        else:
            index_url=KONZUM_INDEX+f'?date={day.isoformat()}&page=1'
            pending=[index_url];seen=set();downloads=set()
            while pending:
                url=pending.pop(0)
                if url in seen:continue
                if len(seen)>=30:raise ValueError('Previše stranica Konzum indeksa.')
                seen.add(url)
                if getattr(fetch,'official_fetch',False):time.sleep(1)
                html=fetch(url).decode('utf-8',errors='replace')
                for link in extract_links(html,url):
                    p=urlsplit(link);q=parse_qs(p.query)
                    if p.netloc!='www.konzum.hr':continue
                    if p.path=='/cjenici' and q.get('date')==[day.isoformat()] and q.get('page',[''])[0].isdigit() and link not in seen:pending.append(link)
                    if p.path=='/cjenici/download' and 'title' in q:downloads.add(link)
            for url in sorted(downloads):
                name=parse_qs(urlsplit(url).query)['title'][0];loc=location(chain,name)
                if not loc:continue
                if filename_date(name)!=day:raise ValueError('Konzum datum datoteke ne odgovara indeksu.')
                entries.append(dict(name=name,url=url,city=loc[0],address=loc[1]))
        if entries:return day.isoformat(),index_url,sorted(entries,key=lambda e:e['name'])
    raise ValueError('Nema istarskih cjenika u zadnjih 7 dana za '+chain)

def download_files(chain,today,fetch,extract_links,validate,folder,root,previous=None):
    dt,url,entries=index_files(chain,today,fetch,extract_links)
    if previous and dt<previous['date']:raise ValueError('Izvor nudi stariji cjenik.')
    files=[];hashes=[]
    # Konzum sometimes returns 404 for files advertised by its current index.
    # Use bounded paced passes, and publish the chain only when ALL selected files pass.
    pending=list(enumerate(entries));last_error=None
    max_attempts=12 if chain=='Konzum' else 3
    for attempt in range(max_attempts):
        failures=[]
        for i,entry in pending:
            if getattr(fetch,'official_fetch',False) and chain=='Konzum':time.sleep(1)
            try:
                blob=fetch(entry['url']);validate(chain,entry['name'],blob,entry['url'])
                path=folder/f'{i}.csv';path.write_bytes(blob)
                files.append(dict(name=entry['name'],source=entry['url'],city=entry['city'],address=entry['address'],path=path.relative_to(root).as_posix()))
                hashes.append((entry['name'],hashlib.sha256(blob).hexdigest()))
            except Exception as e:
                last_error=e;failures.append((i,entry))
                print(f'{chain}: pokušaj {attempt+1}, {entry["city"]}, {entry["address"]}: {str(e)[:100]}',flush=True)
        pending=failures
        if not pending:break
        if getattr(fetch,'official_fetch',False) and attempt<max_attempts-1:time.sleep(15 if chain=='Konzum' else 5)
    if pending:raise ValueError(f'{chain}: nisu preuzeti svi cjenici ({len(pending)}/{len(entries)}). {str(last_error)[:130]}')
    digest=hashlib.sha256(json.dumps(sorted(hashes),ensure_ascii=False).encode()).hexdigest()
    return dict(date=dt,url=url,sha256=digest,files=sorted(files,key=lambda e:e['name']))

def xml_to_csv(blob):
    if b'<!DOCTYPE' in blob.upper() or b'<!ENTITY' in blob.upper():raise ValueError('Neispravan XML cjenik.')
    root=ET.fromstring(blob)
    stores=root.findall('./ProdajniObjekt')
    if len(stores)!=1:raise ValueError('XML mora sadržavati jednu poslovnicu.')
    store=stores[0];address=store.findtext('Adresa','').strip()
    loc=next((city for city in sorted(ISTRIA,key=len,reverse=True) if norm(address).endswith(' '+norm(city))),None)
    if not loc:return None
    street=address[:len(address)-len(loc)].strip()
    mapping={'NazivProizvoda':'naziv proizvoda','MarkaProizvoda':'marka proizvoda','NetoKolicina':'neto kolicina','JedinicaMjere':'jedinica mjere','MaloprodajnaCijena':'maloprodajna cijena','CijenaZaJedinicuMjere':'cijena za jedinicu mjere','MaloprodajnaCijenaAkcija':'MPC za vrijeme posebnog oblika prodaje','Barkod':'barkod'}
    output=io.StringIO();writer=csv.DictWriter(output,fieldnames=list(mapping.values()));writer.writeheader()
    products=store.findall('./Proizvodi/Proizvod')
    if len(products)<100:raise ValueError('XML nema dovoljno proizvoda.')
    for product in products:writer.writerow({v:product.findtext(k,'').strip() for k,v in mapping.items()})
    return loc,street,output.getvalue().encode('utf-8')

def download_studenac(today,fetch,validate,folder,root,previous=None):
    for offset in range(7):
        day=today-timedelta(days=offset);url=STUDENAC_ARCHIVE.format(date=day.isoformat())
        try:blob=fetch(url)
        except HTTPError as e:
            if e.code==404:continue
            raise
        if previous and day.isoformat()<previous['date']:raise ValueError('Studenac nudi stariji cjenik.')
        files=[]
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            entries=[f for f in z.infolist() if f.filename.lower().endswith('.xml')]
            if sum(f.file_size for f in entries)>300*1024*1024:raise ValueError('Prevelika XML arhiva.')
            for entry in entries:
                if filename_date(entry.filename)!=day:raise ValueError('Datum XML-a ne odgovara arhivi.')
                converted=xml_to_csv(z.read(entry))
                if not converted:continue
                city,address,csv_blob=converted
                validate('Studenac',entry.filename,csv_blob,url)
                path=folder/f'{len(files)}.csv';path.write_bytes(csv_blob)
                files.append(dict(name=entry.filename,path=path.relative_to(root).as_posix(),source=url,city=city,address=address))
        if files:return dict(date=day.isoformat(),url=url,sha256=hashlib.sha256(blob).hexdigest(),files=files)
    raise ValueError('Studenac nema istarskog cjenika u zadnjih 7 dana.')

# Addresses checked against diskont.hr/diskont-stanic-{city}/ on 10.10.2026.
STANIC_STORES={
 '731':('Poreč','Mate Vlašića 26/52'), '732':('Vodnjan','Ga Dalla Zonca BB'),
 '733':('Umag','Ulica Ernesta Miloša 8A'), '734':('Pula','Bože Gumpca 34'),
 '739':('Pula','Rizzijeva ulica 59'), '7302':('Medulin','Munida 23'),
 '7307':('Rovinj','Fažanska ulica 3C'), '7308':('Labin','Štrmac 324')}


def xlsx_to_csv(blob):
    """Read sparse worksheet cells by their references, never shift empty columns."""
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        if sum(f.file_size for f in z.infolist())>30_000_000:raise ValueError('Prevelik Excel cjenik.')
        def xml(path):
            b=z.read(path)
            if b'<!DOCTYPE' in b or b'<!ENTITY' in b:raise ValueError('Nedopušten XML.')
            return ET.fromstring(b)
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(t.text or '' for t in si.findall('.//s:t',ns)) for si in xml('xl/sharedStrings.xml').findall('s:si',ns)]
        worksheet=xml('xl/worksheets/sheet1.xml')
        rows=[]
        for row in worksheet.findall('s:sheetData/s:row',ns):
            values={}
            for cell in row.findall('s:c',ns):
                letters=re.match(r'[A-Z]+',cell.get('r',''))
                if not letters:raise ValueError('Nedostaje Excel oznaka ćelije.')
                col=0
                for ch in letters[0]:col=col*26+ord(ch)-64
                v=cell.find('s:v',ns);value=v.text if v is not None else ''.join(t.text or '' for t in cell.findall('s:is//s:t',ns))
                if cell.get('t')=='s':value=strings[int(value)]
                values[col-1]=value or ''
            rows.append(values)
    if not rows:raise ValueError('Prazan Excel cjenik.')
    headers={i:norm(v) for i,v in rows[0].items()}
    required={'naziv','barkod','mp cijena','jedinica mjere'}
    if not required.issubset(set(headers.values())):raise ValueError('Promijenjen Stanić Excel format.')
    out=io.StringIO();w=csv.writer(out,delimiter=';')
    w.writerow(['naziv','marka','barkod','neto kolicina','jedinica mjere','MPC','MPC za vrijeme posebnog oblika prodaje','cijena za jedinicu mjere'])
    for values in rows[1:]:
        r={headers[i]:v for i,v in values.items() if i in headers}
        if not r.get('naziv'):continue
        w.writerow([r.get(k,'') for k in ('naziv','marka','barkod','neto kolicina','jedinica mjere','mp cijena','mpc u vrij pos obl prodaje','cijena za jedinicu mjere')])
    return out.getvalue().encode('utf-8')


def extra_index(chain,today,fetch,extract_links):
    from html import unescape
    if chain=='Kaufland':
        page='https://www.kaufland.hr/akcije-novosti/popis-mpc.html'
        html=fetch(page).decode('utf-8');m=re.search(r"data-props='([^']*dataUrlAssets[^']*)'",html)
        if not m:raise ValueError('Nije pronađen službeni Kaufland indeks.')
        index=urljoin(page,json.loads(unescape(m[1]))['settings']['dataUrlAssets'])
        if urlsplit(index).netloc!='www.kaufland.hr':raise ValueError('Neslužben Kaufland indeks.')
        entries=[]
        for f in json.loads(fetch(index)):
            m=re.fullmatch(r'(?:Hipermarket|Supermarket)_(.+)_(Pula|Umag|Porec|Rovinj)_(\d+)_(\d{8})_([0-9-]+)\.csv',f['label'])
            if not m:continue
            dt=datetime.strptime(m[4],'%d%m%Y').date()
            if not today-timedelta(days=6)<=dt<=today:continue
            url=urljoin(page,f['path'])
            if urlsplit(url).netloc!='www.kaufland.hr' or urlsplit(url).path.rsplit('/',1)[1]!=f['label']:raise ValueError('Neslužben Kaufland cjenik.')
            city='Poreč' if m[2]=='Porec' else m[2]
            entries.append(dict(name=f['label'],url=url,city=city,address=m[1].replace('_',' '),date=dt.isoformat()))
    else:
        page='https://diskont.hr/cjenici/';html=fetch(page).decode('utf-8')
        maps=[u for u in extract_links(html,page) if urlsplit(u).netloc=='drive.google.com' and '/drive/folders/' in u]
        if not maps:raise ValueError('Nema službene Stanić mape.')
        # First map is full price lists, second is restricted prices only.
        index=maps[0];html=fetch(index).decode('utf-8');entries=[]
        for m in re.finditer(r'aria-label="(MP_[^"]+\.xlsx) Microsoft Excel Shared"[^>]*ssk=\x27[^\x27]*:([A-Za-z0-9_-]{20,})-0-\d+\x27',html):
            name,fid=m.groups();parts=re.fullmatch(r'MP_(\d+)_(.+)_(\d{2}-\d{2}-\d{4})-\d+\.xlsx',name)
            if not parts or parts[1] not in STANIC_STORES:continue
            dt=datetime.strptime(parts[3],'%d-%m-%Y').date()
            if not today-timedelta(days=6)<=dt<=today:continue
            city,address=STANIC_STORES[parts[1]]
            if norm(city) not in norm(parts[2]):raise ValueError('Stanić oznaka grada se promijenila.')
            entries.append(dict(name=name,url='https://drive.google.com/uc?export=download&id='+fid,city=city,address=address,date=dt.isoformat(),store_id=parts[1]))
    if not entries:raise ValueError('Nema aktualnih istarskih cjenika za '+chain)
    dt=max(e['date'] for e in entries);entries=[e for e in entries if e['date']==dt]
    if chain=='Stanić' and {e['store_id'] for e in entries}!=set(STANIC_STORES):raise ValueError('Stanić popis nije potpun za podržane poslovnice.')
    return dt,index,sorted(entries,key=lambda e:e['name'])


def download_extra(chain,today,fetch,extract_links,validate,folder,root,previous=None):
    dt,index,entries=extra_index(chain,today,fetch,extract_links)
    if previous and dt<previous['date']:raise ValueError('Izvor nudi stariji cjenik.')
    files=[];hashes=[]
    for i,e in enumerate(entries):
        blob=fetch(e['url']);content=xlsx_to_csv(blob) if chain=='Stanić' else blob
        validate(chain,e['name'],content,e['url'])
        path=folder/f'{i}.csv';path.write_bytes(content)
        files.append(dict(name=e['name'],source=e['url'],city=e['city'],address=e['address'],path=path.relative_to(root).as_posix()))
        hashes.append((e['name'],hashlib.sha256(blob).hexdigest()))
    return dict(date=dt,url=index,sha256=hashlib.sha256(json.dumps(hashes,ensure_ascii=False).encode()).hexdigest(),files=files)
