# GPL-3.0. See LICENSE and THIRD_PARTY.md.
"""Restricted FO76 static BSTriShape -> FO4 converter. Never overwrites input."""
import sys,struct,json,math,hashlib
from pathlib import Path
from inspect_nif import Nif,Reader
from havok.bhk_autopack import pack_compressed_mesh
from havok.bhk_autounpack import parse_bytes
P=lambda f,*a:struct.pack('<'+f,*a)
def sized(s):
 b=s.encode('utf8',errors='surrogateescape'); return P('I',len(b))+b
IDENTITY=(0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,1.)
LIGHT=bytes.fromhex('00000000ffffffff00000000ffffffff010240808100000000000000000000000000803f0000803f030000000000000000000000000000000000803f02000000030000000000803f000000000000803f0000803f0000803f0000803f0000803f9a99993effff7f7f000000000000803f0000a0409a99193f3333b33fcdcc4c3e0000803fcdcccc3f00000000')
class Writer:
 def __init__(self,bs=130):
  if bs not in (130,155):raise ValueError('Writer supports only FO4 BS130 or FO76 BS155')
  self.bs=bs;self.blocks=[];self.strings=[]
 def sid(self,s):
  if not s:return -1
  if s not in self.strings:self.strings.append(s)
  return self.strings.index(s)
 def add(self,t,b=b''):
  i=len(self.blocks);self.blocks.append((t,b));return i
 def set(self,i,b):self.blocks[i]=(self.blocks[i][0],b)
 def net(self,name):return P('iIi',self.sid(name),0,-1)
 def av(self,name,transform,collision=-1,extra=(),flags=14,ctrl=-1):
  return P('iI',self.sid(name),len(extra))+b''.join(P('i',x) for x in extra)+P('iI13fi',ctrl,flags,*transform,collision)
 def save(self,path):
  types=list(dict.fromkeys(t for t,b in self.blocks));n=len(self.blocks)
  h=b'Gamebryo File Format, Version 20.2.0.7\n'+P('IBIII',0x14020007,1,12,n,self.bs)
  author=b'Mesh Converter\0';h+=P('B',len(author))+author
  h+=P('I',0) if self.bs>130 else P('B',1)+b'\0'
  for s in (b'\0',b'\0'):h+=P('B',len(s))+s
  h+=P('H',len(types))+b''.join(sized(t) for t in types)
  h+=P('H'*n,*[types.index(t) for t,b in self.blocks])+P('I'*n,*[len(b) for t,b in self.blocks])
  h+=P('II',len(self.strings),max((len(s.encode('utf8',errors='surrogateescape')) for s in self.strings),default=0))+b''.join(sized(s) for s in self.strings)+P('I',0)
  path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(h+b''.join(b for t,b in self.blocks)+P('Ii',1,0))
def geometry(n,d):
 b=n.blocks[d['id']];stride=(d['desc']&15)*4; attr=d['desc']>>44
 assert attr&1 and not attr&0x40,'Skinned/unsupported vertices'
 off=d['dataoffset'];fmt='3f' if attr&0x400 else '3e'
 vs=[struct.unpack_from('<'+fmt,b,off+i*stride) for i in range(d['vertices'])]
 ts=list(struct.iter_unpack('<3H',b[off+d['vertices']*stride:off+d['datasize']]))
 assert len(ts)==d['triangles'] and all(max(t)<len(vs) for t in ts)
 return vs,ts
NODE_TYPES={'NiNode','BSFadeNode','BSValueNode'}
SHAPE_TYPES={'BSTriShape','BSSubIndexTriShape'}
EXTRA_TYPES={'BSXFlags','BSBound','BSInvMarker','NiStringExtraData','NiStringsExtraData',
 'NiIntegerExtraData','NiBooleanExtraData','NiFloatExtraData','NiBinaryExtraData',
 'BSConnectPoint::Parents','BSConnectPoint::Children','BSFurnitureMarker','BSFurnitureMarkerNode'}
# These shared layouts are fully parsed before copying. BinaryExtraData is an
# opaque payload and does not gain skin/animation/reverse support from this set.
COMMON_EXTRA_TYPES=EXTRA_TYPES-{'NiBinaryExtraData'}
STATIC_TYPES=NODE_TYPES|SHAPE_TYPES|EXTRA_TYPES|{'BSLightingShaderProperty','BSEffectShaderProperty',
 'BSShaderTextureSet','NiAlphaProperty','bhkNPCollisionObject','bhkPhysicsSystem'}

def extra_count(r,minimum_entry_size):
 count=r.u()
 if count>(len(r.b)-r.p)//minimum_entry_size:raise ValueError('Extra-data array count exceeds remaining payload')
 return count

def validate_extra(n,typ,b):
 """Only copy extras whose FO4/FO76 layouts and references are understood."""
 r=Reader(b);n.name(r.i())
 if typ in ('BSXFlags','NiIntegerExtraData'):r.u()
 elif typ=='NiStringExtraData':n.name(r.i())
 elif typ=='NiStringsExtraData':
  for _ in range(extra_count(r,4)):r.s()
 elif typ=='NiBooleanExtraData':
  if r.get('B')[0] not in (0,1):raise ValueError('Invalid boolean extra')
 elif typ=='NiFloatExtraData':
  if not math.isfinite(r.get('f')[0]):raise ValueError('Non-finite float extra')
 elif typ=='NiBinaryExtraData':r.read(r.u())
 elif typ=='BSBound':
  values=r.get('6f')
  if not all(math.isfinite(v) for v in values):raise ValueError('Non-finite BSBound')
 elif typ=='BSInvMarker':
  values=r.get('3Hf')
  if not math.isfinite(values[-1]):raise ValueError('Non-finite inventory zoom')
 elif typ=='BSConnectPoint::Parents':
  for _ in range(extra_count(r,40)):
   r.s();r.s()
   if not all(math.isfinite(v) for v in r.get('8f')):raise ValueError('Non-finite connect point')
 elif typ=='BSConnectPoint::Children':
  if r.get('B')[0] not in (0,1):raise ValueError('Invalid connect point flag')
  for _ in range(extra_count(r,4)):r.s()
 elif typ in ('BSFurnitureMarker','BSFurnitureMarkerNode'):
  for _ in range(extra_count(r,20)):
   values=r.get('4f2H')
   if not all(math.isfinite(v) for v in values[:4]):raise ValueError('Non-finite furniture marker')
 else:raise ValueError('Unsupported extra: '+typ)
 if r.p!=len(b):raise ValueError('Unparsed extra fields: '+typ)

def material_path(value):
 value=value.replace('\\','/');start=value.lower().rfind('/materials/')
 if start>=0:value=value[start+1:]
 if ':' in value:raise ValueError('Unrecognized absolute material path: '+value)
 return value

def convert(src,dest,material_prefix=None,collision=True,dry_run=False,_nif=None):
 from convert_preserved import shape as parse_shape, effect
 src=Path(src);dest=Path(dest)
 if src.resolve()==dest.resolve():raise ValueError('Input and output must differ')
 if dest.exists():raise FileExistsError(dest)
 n=_nif if _nif is not None else Nif(src)
 if n.bs!=155:raise ValueError('Only FO76 BS155 models can use the static route')
 if n.groups or len(n.roots)!=1:raise ValueError('Static conversion needs one root and no block groups')
 unknown={n.types[t] for t in n.indices}-STATIC_TYPES
 if unknown:raise ValueError('Static route does not support: '+', '.join(sorted(unknown)))
 ds={d['id']:d for d in n.inspect()};source_root=n.roots[0]
 if source_root not in ds or ds[source_root]['type'] not in NODE_TYPES:raise ValueError('Expected a node root')
 w=Writer();w.strings=list(n.strings);mapping={};active=set();parents={};shapes=[];notes=[]
 root=w.add(ds[source_root]['type']);mapping[source_root]=root
 def extra(old):
  typ=n.types[n.indices[old]]
  if typ not in EXTRA_TYPES:raise ValueError('Unsupported node extra: '+typ)
  if old in mapping:return mapping[old]
  validate_extra(n,typ,n.blocks[old]);idx=w.add(typ,n.blocks[old]);mapping[old]=idx;return idx
 def shader(old,d):
  if old<0:raise ValueError('Shape has no shader')
  typ=n.types[n.indices[old]];r=Reader(n.blocks[old]);nd=n.net(r)
  if nd['extra'] or nd['ctrl']!=-1:raise ValueError('Shader controller or extra data needs a dedicated route')
  material=material_path(nd['name']);stem=Path(material).stem
  if material_prefix and material:material='Materials/'+material_prefix+'/'+Path(material).name.lower()
  tp='textures/'+material_prefix+'/'+stem if material_prefix else ''
  if typ=='BSLightingShaderProperty':
   if not material or r.p!=len(r.b):raise ValueError('Embedded FO76 lighting shader is not yet supported')
   tx=[tp+'_d.dds',tp+'_n.dds','','','','','',tp+'_s.dds',''] if tp else ['']*9
   txidx=w.add('BSShaderTextureSet',P('I',9)+b''.join(sized(t) for t in tx))
   sh=bytearray(LIGHT);struct.pack_into('<i',sh,4,w.sid(material));struct.pack_into('<i',sh,40,txidx);struct.pack_into('<i',sh,60,-1)
   flags1=struct.unpack_from('<I',sh,16)[0]&~((1<<1)|(1<<4)|(1<<5))
   struct.pack_into('<I',sh,16,flags1);struct.pack_into('<I',sh,20,1|(32 if (d['desc']>>44)&32 else 0))
   return w.add(typ,bytes(sh))
  if typ=='BSEffectShaderProperty':
   sh,detail=effect(n,n.blocks[old],[d]);sh=P('i',w.sid(material))+sh[4:]
   notes.append(detail);return w.add(typ,sh)
  raise ValueError('Unsupported shader: '+typ)
 def visit(old):
  if old==-1:return -1
  if old in active:raise ValueError('Scene graph contains a cycle')
  if old in mapping and old!=source_root:return mapping[old]
  if old not in ds:raise ValueError('Unsupported scene graph block '+str(old))
  d=ds[old];typ=d['type']
  if typ not in NODE_TYPES|SHAPE_TYPES:raise ValueError('Unsupported scene node: '+typ)
  if d['ctrl']!=-1:raise ValueError('Node controllers must use the animation route')
  if d['collision']!=-1 and n.types[n.indices[d['collision']]]!='bhkNPCollisionObject':raise ValueError('Unsupported collision object')
  active.add(old);idx=root if old==source_root else w.add(typ);mapping[old]=idx
  extras=[extra(i) for i in d['extra']]
  av=w.av(d['name'],d['transform'],extra=extras,flags=d['flags'])
  if typ in NODE_TYPES:
   r=Reader(n.blocks[old]);n.av(r);children=list(r.array('i',r.u()));suffix=r.read(len(r.b)-r.p)
   if typ=='BSValueNode':
    if len(suffix)!=5:raise ValueError('Invalid BSValueNode value/flags payload')
   elif suffix:raise ValueError('Unparsed node fields: '+typ)
   converted=[]
   for child in children:
    if child!=-1:
     if child in parents:raise ValueError('Multiple parent nodes are not supported by static collision rebuilding')
     parents[child]=old
    converted.append(visit(child))
   w.set(idx,av+P('I',len(converted))+b''.join(P('i',c) for c in converted)+suffix)
  else:
   validated=parse_shape(n,old)
   if validated['skin']!=-1:raise ValueError('Skinned geometry requires the skin-preserving route')
   shidx=shader(d['shader'],d);alpha=-1
   if d['alpha']!=-1:
    if n.types[n.indices[d['alpha']]]!='NiAlphaProperty':raise ValueError('Invalid alpha property type')
    ar=Reader(n.blocks[d['alpha']]);ad=n.net(ar);tail=ar.read(3)
    if ar.p!=len(ar.b) or ad['extra'] or ad['ctrl']!=-1:raise ValueError('Unsupported alpha property')
    alpha=w.add('NiAlphaProperty',w.net(ad['name'])+tail)
   data=n.blocks[old][d['dataoffset']:d['tailoffset']];tail=n.blocks[old][d['tailoffset']:]
   w.set(idx,av+P('4fiiiQIHI',*d['bound'],-1,shidx,alpha,d['desc'],d['triangles'],d['vertices'],len(data))+data+tail)
   shapes.append((old,idx,d))
  active.remove(old);return idx
 visit(source_root)
 unreachable=[i for i,d in ds.items() if d['type'] in NODE_TYPES|SHAPE_TYPES and i not in mapping]
 if unreachable:raise ValueError('Unreachable scene nodes would be lost: '+str(unreachable[:8]))
 verts=[];faces=[];seen={};degenerate=0
 def world(v,old):
  while old!=source_root:
   tf=ds[old]['transform'];x,y,z=v;rot=tf[3:12];sc=tf[12]
   v=tuple(tf[j]+sc*(rot[j*3]*x+rot[j*3+1]*y+rot[j*3+2]*z) for j in range(3));old=parents[old]
  return v
 if collision and shapes:
  for old,idx,d in shapes:
   vs,ts=geometry(n,d);remap=[]
   for v in vs:
    v=world(v,old);key=tuple(round(x/69.99125,7) for x in v)
    if key not in seen:seen[key]=len(verts);verts.append(key)
    remap.append(seen[key])
   for t in ts:
    f=tuple(remap[k] for k in t)
    if len(set(f))<3:degenerate+=1;continue
    a,b,c=[verts[k] for k in f];ab=[b[j]-a[j] for j in range(3)];ac=[c[j]-a[j] for j in range(3)]
    cross=[ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0]]
    if sum(x*x for x in cross)<1e-18:degenerate+=1;continue
    faces.append(f)
  faces=list(dict.fromkeys(faces))
 collision_built=bool(collision and faces)
 if collision and shapes and not faces:notes.append('No nondegenerate triangles; collision was not generated.')
 if 'bhkPhysicsSystem' in n.types:notes.append('Source Havok data is not preserved. Collision, when requested, is rebuilt as a static render-geometry approximation; physics motion and constraints are not converted.')
 # The original root transform remains intact. The new body is in root-local space.
 root_extras=[extra(i) for i in ds[source_root]['extra']]
 bsx_ids=[i for i in root_extras if w.blocks[i][0]=='BSXFlags']
 if len(bsx_ids)>1:raise ValueError('Root has multiple BSXFlags blocks')
 if bsx_ids:
  i=bsx_ids[0];name,flags=struct.unpack('<iI',w.blocks[i][1]);w.set(i,P('iI',name,(flags&~2)|(2 if collision_built else 0)))
 elif collision_built:
  i=w.add('BSXFlags',P('iI',w.sid('BSX'),2));root_extras.append(i)
 r=Reader(w.blocks[root][1]);r.i();r.array('i',r.u());r.read(64);root_tail=w.blocks[root][1][r.p:]
 root_d=ds[source_root]
 w.set(root,w.av(root_d['name'],root_d['transform'],extra=root_extras,flags=root_d['flags'])+root_tail)
 info=dict(shapes=len(shapes),vertices=sum(d['vertices'] for _,_,d in shapes),triangles=sum(d['triangles'] for _,_,d in shapes),route='static',partitioned_shapes=sum(d['type']=='BSSubIndexTriShape' for _,_,d in shapes),helper_only=not bool(shapes),root_transform_preserved=True,geometry_bytes_preserved=True,collision_rebuilt='FO4 hk_2014.1.0 compressed triangle mesh' if collision_built else None,collision_triangles=len(faces) if collision_built else 0,collision_degenerate_removed=degenerate,dropped_addon_nodes=[],notes=notes)
 if dry_run:return info
 if collision_built:
  hk=pack_compressed_mesh(verts,faces);parsed=parse_bytes(hk)
  if len(parsed)!=1 or len(parsed[0].faces)!=len(faces):raise ValueError('Collision roundtrip failed')
  co=w.add('bhkNPCollisionObject');phys=w.add('bhkPhysicsSystem',P('I',len(hk))+hk);w.set(co,P('iHiI',root,128,phys,0))
  rb=bytearray(w.blocks[root][1]);struct.pack_into('<i',rb,68+4*len(root_extras),co);w.set(root,bytes(rb))
 w.save(dest);out=Nif(dest);od={d['id']:d for d in out.inspect()}
 if out.bs!=130:raise ValueError('Output version validation failed')
 for old,idx,d in shapes:
  target=parse_shape(out,idx)
  if out.blocks[idx][target['dataoffset']:]!=n.blocks[old][d['dataoffset']:]:raise ValueError('Geometry or partition data changed')
 for old,idx in mapping.items():
  if old in ds and ds[old]['type'] in NODE_TYPES|SHAPE_TYPES:
   if od[idx]['transform']!=ds[old]['transform'] or od[idx]['flags']!=ds[old]['flags']:raise ValueError('Scene transform or flags changed')
 info.update(input=str(src),output=str(dest),source_sha256=n.source_sha256,source_blocks=n.count,output_blocks=len(w.blocks),materials=[s for s in w.strings if s.lower().endswith(('.bgsm','.bgem'))])
 return info
