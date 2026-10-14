"""Read-only Jurassic Park archive access. No game files are modified."""
from pathlib import Path
import sys, hashlib, threading, json
from collections import Counter
ROOT=Path(__file__).resolve().parent
DATA_ROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else ROOT
sys.path.insert(0,str(ROOT/'vendor'/'telltale'))
from telltale.ttarch import TtarchArchive
DEFAULT=r'C:\Program Files (x86)\Telltale Games\Jurassic Park The Game\GameData'

class Library:
    def __init__(self,path=DEFAULT):
        self.path=Path(path); self.items={}; self.archives={}; self.lock=threading.RLock()
        self.cache=DATA_ROOT/'cache'; self.cache.mkdir(exist_ok=True)
        self.errors=[]
    def scan(self):
        for p in sorted(self.path.rglob('*.ttarch')):
            # Keep each episode's primary packs; localized variants remain available.
            try:
                archive=TtarchArchive(str(p),game_key='jurassicpark')
                aid=str(p.relative_to(self.path)).replace('\\','/')
                self.archives[aid]=archive
                for e in archive.list_files():
                    key=hashlib.sha256((aid+'|'+e.name).encode()).hexdigest()[:24]
                    ext=Path(e.name).suffix.lower()
                    cat=('Models' if ext=='.d3dmesh' else 'Textures' if ext=='.d3dtx' else 'Animations' if ext=='.anm' else 'Skeletons' if ext=='.skl' else 'Voice' if ext=='.vox' else ('Music' if e.name.lower().startswith('mus_') else 'Voice' if e.name.lower().startswith(('vox_','vo_')) else 'Sounds') if ext in ('.aud','.wav','.ogg','.mp3') else 'Other')
                    self.items[key]={'id':key,'name':e.name,'size':e.size,'category':cat,'archive':aid,'episode':p.parts[-2] if 'Localized' not in p.parts else p.parent.name,'extension':ext,'entry':e}
            except Exception as ex:self.errors.append({'archive':str(p),'error':str(ex)})
        return self
    def public(self,item):return {k:v for k,v in item.items() if k!='entry'}
    def get(self,key):
        if key not in self.items:raise ValueError('Unknown asset')
        return self.items[key]
    def read(self,key):
        item=self.get(key)
        p=self.cache/(key+item['extension'])
        with self.lock:
            if not p.exists():p.write_bytes(self.archives[item['archive']].read_file(item['entry']))
        return p.read_bytes()
    def find(self,name,near=None):
        candidates=[x for x in self.items.values() if x['name'].lower()==name.lower()]
        if near:candidates.sort(key=lambda x:(x['archive']!=near['archive'],x['episode']!=near['episode'],'Localized' in x['archive']))
        return candidates[0] if candidates else None
    def summary(self):
        return {'path':str(self.path),'counts':dict(Counter(x['category'] for x in self.items.values())),'total':len(self.items),'archives':len(self.archives),'errors':self.errors}
