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
