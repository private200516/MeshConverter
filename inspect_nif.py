"""Bounded reader for common FO4/FO76 NIF containers; parsing is not compatibility."""
import json
import hashlib
import math
import struct
import sys
from pathlib import Path

class Reader:
    def __init__(self, b):
        self.b = b
        self.p = 0
    def read(self, n):
        if n < 0 or n > len(self.b) - self.p:
            raise ValueError(f'Truncated data at {self.p}: requested {n} bytes')
        value = self.b[self.p:self.p+n]
        self.p += n
        return value
    def get(self, fmt):
        return struct.unpack('<'+fmt, self.read(struct.calcsize('<'+fmt)))
    def u(self): return self.get('I')[0]
    def i(self): return self.get('i')[0]
    def array(self, fmt, count):
        if count < 0 or count > (len(self.b)-self.p)//struct.calcsize('<'+fmt):
            raise ValueError('Array count exceeds remaining data')
        return self.get(fmt*count)
    def s(self):
        return self.read(self.u()).decode('utf-8', errors='surrogateescape').rstrip('\0')
    def exp(self): return self.read(self.get('B')[0])

class Nif:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.stat().st_size > 512*1024*1024:
            raise ValueError('NIF exceeds the 512 MiB per-file conversion limit')
        raw = self.path.read_bytes()
        self.source_sha256 = hashlib.sha256(raw).hexdigest()
        r = Reader(raw)
        newline = r.b.find(b'\n', 0, 256)
        if newline < 0 or not r.b.startswith(b'Gamebryo File Format, Version 20.2.0.7'):
            raise ValueError('Expected a Gamebryo 20.2.0.7 NIF header')
        self.magic = r.read(newline+1)
        self.ver,self.endian,self.user,self.count = r.get('IBII')
        if (self.ver,self.endian,self.user)!=(0x14020007,1,12):
            raise ValueError('Only little-endian Bethesda User12 / 20.2.0.7 containers are supported')
        self.bs = r.u()
        if self.bs < 103:
            raise ValueError(f'Unsupported Bethesda stream version {self.bs}')
        if self.count == 0 or self.count > len(r.b)//6:
            raise ValueError('Invalid block count')
        self.author = r.exp()
        if self.bs>130: self.unk = r.u()
        else: self.process = r.exp()
        self.export = r.exp()
        self.maxpath = r.exp()
        type_count = r.get('H')[0]
        if not type_count or type_count>(len(r.b)-r.p)//4:
            raise ValueError('Invalid block type count')
        self.types = [r.s() for _ in range(type_count)]
        self.indices = r.array('H',self.count)
        if any(index>=len(self.types) for index in self.indices):
            raise ValueError('Invalid block type index')
        self.sizes = r.array('I',self.count)
        string_count = r.u()
        self.maxlen = r.u()
        if string_count>(len(r.b)-r.p)//4: raise ValueError('Invalid string count')
        self.strings = [r.s() for _ in range(string_count)]
        self.groups = list(r.array('I',r.u()))
        if sum(self.sizes)>len(r.b)-r.p-4:
            raise ValueError('Block sizes exceed available payload')
        self.blocks = [r.read(n) for n in self.sizes]
        self.footer = r.read(len(r.b)-r.p)
        footer = Reader(self.footer)
        self.roots = list(footer.array('i',footer.u()))
        if footer.p!=len(footer.b) or not self.roots: raise ValueError('Invalid NIF root footer')
        for root in self.roots: self.ref(root,nullable=False)
    def name(self,n):
        if n==-1: return ''
        if not 0<=n<len(self.strings): raise ValueError(f'Invalid string-table index {n}')
        return self.strings[n]
    def ref(self,index,nullable=True):
        if nullable and index==-1: return index
        if not 0<=index<self.count: raise ValueError(f'Invalid block reference {index}')
        return index
    def net(self,r):
        name_id = r.i()
        extra = list(r.array('i',r.u()))
        ctrl = r.i()
        for index in extra: self.ref(index,nullable=False)
        self.ref(ctrl)
        return dict(name=self.name(name_id),nameid=name_id,extra=extra,ctrl=ctrl)
    def av(self,r):
        d=self.net(r)
        d.update(flags=r.u(),transform=r.get('13f'),collision=r.i())
        if not all(math.isfinite(value) for value in d['transform']):
            raise ValueError('Non-finite node transform')
        self.ref(d['collision'])
        d['avend']=r.p
        return d
    def inspect(self):
        out=[]
        for i,(t,b) in enumerate(zip(self.indices,self.blocks)):
            typ=self.types[t];r=Reader(b);d=dict(id=i,type=typ,size=len(b))
            if typ in ('NiNode','BSValueNode','BSTriShape','BSSubIndexTriShape','BSMeshLODTriShape','BSFadeNode'):
                d.update(self.av(r))
                if typ in ('NiNode','BSValueNode','BSFadeNode'):
                    d['children']=list(r.array('i',r.u()))
                    for child in d['children']: self.ref(child)
                else:
                    d['bound']=r.get('4f');d['boundend']=r.p
                    if self.bs>=155: d['bbox']=r.get('6f')
                    d['skin'],d['shader'],d['alpha']=r.get('iii')
                    for field in ('skin','shader','alpha'): self.ref(d[field])
                    d['desc']=r.get('Q')[0]
                    d['triangles'],d['vertices'],d['datasize']=r.get('IHI');d['dataoffset']=r.p
                    expected=(d['desc']&15)*4*d['vertices']+6*d['triangles']
                    if d['datasize']!=expected: raise ValueError(f'Inconsistent vertex data length in block {i}')
                    r.read(d['datasize']);d['tailoffset']=r.p
                    if typ=='BSMeshLODTriShape':
                        d['lod_sizes']=r.get('3I')
                        if sum(d['lod_sizes'])!=d['triangles']:
                            raise ValueError(f'LOD triangle counts do not match geometry in block {i}')
                        if r.p!=len(b): raise ValueError(f'Unexpected BSMeshLODTriShape suffix in block {i}')
                    if typ=='BSTriShape' and r.p!=len(b): raise ValueError(f'Unexpected BSTriShape suffix in block {i}')
            elif typ=='bhkNPCollisionObject':
                d.update(target=r.i(),flags=r.get('H')[0],data=r.i(),body=r.u())
                self.ref(d['target'],nullable=False);self.ref(d['data'],nullable=False)
                if r.p!=len(b): raise ValueError('Unexpected collision-object suffix')
            elif typ=='BSXFlags': d.update(name=self.name(r.i()),value=r.u())
            else: continue
            out.append(d)
        return out

    def validate(self):
        """Validate common graph references and all supported triangle payloads."""
        from convert_preserved import shape, skin_instance, validate_weights
        descriptors = self.inspect()
        shapes = []
        skins = {i:skin_instance(self,i) for i,t in enumerate(self.indices)
                 if self.types[t] == 'BSSkin::Instance'}
        for d in descriptors:
            if d['type'] in ('BSTriShape','BSSubIndexTriShape','BSMeshLODTriShape'):
                parsed = shape(self,d['id'])
                if parsed['skin'] != -1:
                    if parsed['skin'] not in skins:
                        raise ValueError('Shape references an invalid skin instance')
                    validate_weights(self,d['id'],parsed,skins[parsed['skin']])
                shapes.append(parsed)
        return dict(bs=self.bs, blocks=self.count, roots=self.roots,
                    shapes=len(shapes), vertices=sum(d['vertices'] for d in shapes),
                    triangles=sum(d['triangles'] for d in shapes),
                    validation='supported_binary_structures', game_verified=False)

if __name__=='__main__':
    for path in sys.argv[1:]:
        n=Nif(path)
        print(json.dumps(dict(file=path,bs=n.bs,roots=n.roots,blocks=n.inspect()),ensure_ascii=True,indent=2))
