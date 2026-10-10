"""Build an atomic static HTTPS feed. Upload the generated files to hosting separately."""
import argparse, hashlib, importlib.util, json, os, shutil, sys
from pathlib import Path
from datetime import datetime, timezone
from pretraga import ROOT
from osvjezi import refresh, read_state, PAGES

def publish(update=True):
    if update:
        refresh(print,build_screen=False)
    state=read_state()
    missing=set(PAGES)-set(state['chains'])
    if missing:
        raise ValueError('Nema ispravnog cjenika za: '+', '.join(sorted(missing))+'. Javna baza nije zamijenjena.')
    version={k:(v['date'],v['sha256']) for k,v in state['chains'].items()}
    # Rebuild when parsing/normalization changes, even if source files stay the same.
    version['parser']=hashlib.sha256(b''.join((ROOT/p).read_bytes() for p in ('pretraga.py','usporedba.py','izvezi-katalog.py','trgovci.py'))).hexdigest()
    fingerprint=hashlib.sha256(json.dumps(version,sort_keys=True).encode()).hexdigest()
    folder=ROOT/'internet-katalog';folder.mkdir(exist_ok=True)
    current=folder/'manifest.json'
    old=json.loads(current.read_text(encoding='utf-8')) if current.exists() else {}
    if old.get('source_version')==fingerprint and (folder/old['file']).is_file():
        print('Katalog se nije promijenio.');return old
    spec=importlib.util.spec_from_file_location('exporter',ROOT/'izvezi-katalog.py')
    exporter=importlib.util.module_from_spec(spec);spec.loader.exec_module(exporter);exporter.export()
    source=ROOT/'android/app/src/main/assets/katalog.bin'
    with source.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
    name=f'katalog-{digest}.bin';temp=folder/'upload.tmp'
    shutil.copyfile(source,temp);os.replace(temp,folder/name)
    meta=json.loads((ROOT/'KATALOG-STATUS.json').read_text(encoding='utf-8'))
    manifest=dict(schema=1,file=name,sha256=digest,compressed_bytes=source.stat().st_size,
                  database_bytes=(ROOT/'katalog.sqlite').stat().st_size,source_version=fingerprint,
                  published_at=datetime.now(timezone.utc).isoformat(),date_min=meta['date_min'],date_max=meta['date_max'],
                  **{key:int(meta[key]) for key in ('products','stores','offers')})
    temp=folder/'manifest.tmp';temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,current)
    print('Spremno za HTTPS hosting:',current,flush=True)
    return manifest

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--bez-osvjezavanja',action='store_true')
    args=parser.parse_args();publish(not args.bez_osvjezavanja)
