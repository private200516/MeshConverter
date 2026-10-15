"""FO76 managed or standalone transform controllers -> FO4, preserving animation.
Rebuilds node-local animated collision; does not retain FO76 physical geometry.
GPL-3.0. Animation layout reference: niftools/nifxml.
"""
import struct,hashlib,math
from pathlib import Path
from inspect_nif import Nif,Reader
from convert_models import Writer,P,sized,LIGHT,COMMON_EXTRA_TYPES,validate_extra,material_path
from convert_preserved import shape,effect,finite,ref
from havok.bhk_autopack import pack_shapes
from havok.bhk_autounpack import parse_bytes,CollisionShape,PhysicsProps
from shader_animation import (SCALAR_CONTROLLERS, INTERPOLATORS, EXTRA_ANIM,
 validate_shared_block, validate_interpolator_links, effect_with_controller,
 convert_controller_block, convert_animation_block, validate_sequence_binding, animation_semantics)
CONTROLLERS={'NiControllerManager','NiMultiTargetTransformController','NiTransformController'}|SCALAR_CONTROLLERS
ANIM=CONTROLLERS|EXTRA_ANIM|{'NiControllerSequence','NiTransformInterpolator','NiTransformData','NiTextKeyExtraData','NiDefaultAVObjectPalette'}
NODES={'NiNode','BSFadeNode','BSValueNode'}
SHAPES={'BSTriShape','BSSubIndexTriShape'}
EXTRAS=COMMON_EXTRA_TYPES
ALLOWED=ANIM|NODES|SHAPES|EXTRAS|{'BSLightingShaderProperty','BSShaderTextureSet','BSEffectShaderProperty','NiAlphaProperty','bhkNPCollisionObject','bhkPhysicsSystem'}

def _done(r,label):
 if r.p!=len(r.b):raise ValueError(label+' 含未解析的尾部字段')

def _count(r,size):
 count=r.u()
 if count>(len(r.b)-r.p)//size:raise ValueError('动画数组数量超出块大小')
 return count

def _keys(r,width,count=None,kind=None,quaternion=False):
 if count is None:count=_count(r,4)
 if not count:return 0
 if kind is None:kind=r.u()
 if kind not in (1,2,3,5):raise ValueError('未支持的动画插值类型：'+str(kind))
 stride=1+width+(2*width if kind==2 and not quaternion else 0)+(3 if kind==3 else 0)
 if count>(len(r.b)-r.p)//(stride*4):raise ValueError('动画关键帧数量超出数据块')
 previous=-math.inf
 for _ in range(count):
  values=r.get('f'*stride);finite(values,'动画关键帧')
  if values[0]<previous:raise ValueError('动画关键帧时间未排序')
  previous=values[0]
 return count

def validate_animation(n):
 """Validate identical FO4/F76 controller layouts, references and key arrays."""
 reports=[];chains={};targets=set()
 for i,type_id in enumerate(n.indices):
  typ=n.types[type_id]
  if typ not in ANIM:continue
  if typ in EXTRA_ANIM:
   report=validate_shared_block(n,i,CONTROLLERS,NODES|SHAPES)
   if typ in SCALAR_CONTROLLERS:
    chains[i]=report['next'];targets.add(report['target'])
   reports.append(report);continue
  r=Reader(n.blocks[i]);report=dict(block=i,type=typ)
  if typ in CONTROLLERS:
   nxt,flags,frequency,phase,start,stop,target=r.get('iH4fi')
   finite((frequency,phase,start,stop),'控制器时间')
   ref(n,nxt,CONTROLLERS,'下一个控制器',True);ref(n,target,NODES|SHAPES,'控制器目标')
   chains[i]=nxt;report.update(target=target,frequency=frequency,start=start,stop=stop)
   if typ=='NiTransformController':
    interp=r.i();ref(n,interp,{'NiTransformInterpolator'},'变换插值器',True)
    report['interpolator']=interp;targets.add(target)
   elif typ=='NiMultiTargetTransformController':
    extra=r.array('i',r.get('H')[0])
    for idx in extra:
     ref(n,idx,NODES|SHAPES,'附加动画目标',True)
     if idx!=-1:targets.add(idx)
    report['targets']=list(extra)
   else:
    if r.get('B')[0] not in (0,1):raise ValueError('动画管理器布尔字段无效')
    sequences=r.array('i',r.u())
    for idx in sequences:ref(n,idx,{'NiControllerSequence'},'控制器序列')
    ref(n,r.i(),{'NiDefaultAVObjectPalette'},'动画对象调色板',True);report['sequences']=list(sequences)
  elif typ=='NiTransformInterpolator':
   # -FLT_MAX is the documented unset-component sentinel, and is finite.
   finite(r.get('8f'),'变换插值器');ref(n,r.i(),{'NiTransformData'},'变换关键帧数据',True)
  elif typ=='NiTransformData':
   count=_count(r,4);keys=0
   if count:
    kind=r.u()
    if kind==4:
     if count!=1:raise ValueError('XYZ 旋转关键帧计数应为 1')
     keys+=sum(_keys(r,1) for _ in range(3))
    else:keys+=_keys(r,4,count,kind,True)
   keys+=_keys(r,3)+_keys(r,1);report['keys']=keys
  elif typ=='NiControllerSequence':
   report['name']=n.name(r.i());count=_count(r,29);r.u()
   for _ in range(count):
    interp=r.i();ref(n,interp,{'NiTransformInterpolator'}|INTERPOLATORS,'序列插值器',True)
    ctrl=r.i();ref(n,ctrl,CONTROLLERS,'序列控制器',True);r.get('B')
    names=[n.name(r.i()) for _ in range(5)]
    validate_sequence_binding(n,interp,ctrl,names)
   weight=r.get('f')[0];ref(n,r.i(),{'NiTextKeyExtraData'},'序列文字事件',True)
   if r.u() not in (0,1,2):raise ValueError('序列循环类型无效')
   finite((weight,)+r.get('3f'),'序列时间');ref(n,r.i(),{'NiControllerManager'},'序列管理器',True);n.name(r.i())
   if r.get('H')[0]:raise ValueError('暂不支持外部动画注释数组')
  elif typ=='NiTextKeyExtraData':
   n.name(r.i())
   for _ in range(_count(r,8)):finite(r.get('f'),'文字事件时间');n.name(r.i())
  elif typ=='NiDefaultAVObjectPalette':
   ref(n,r.i(),NODES|SHAPES,'对象调色板根',True)
   for _ in range(_count(r,8)):r.s();ref(n,r.i(),NODES|SHAPES,'对象调色板目标')
  _done(r,typ);reports.append(report)
 for first in chains:
  seen=set();current=first
  while current!=-1:
   if current in seen:raise ValueError('控制器链包含循环引用')
   seen.add(current);current=chains[current]
 validate_interpolator_links(reports)
 if not chains:raise ValueError('缺少受支持的动画控制器')
 return reports,targets

def _scene(n):
 ds={}
 for i,type_id in enumerate(n.indices):
  typ=n.types[type_id];r=Reader(n.blocks[i])
  if typ in NODES|SHAPES:
   d=shape(n,i) if typ in SHAPES else n.av(r);d.update(id=i,type=typ)
   ref(n,d['ctrl'],CONTROLLERS,'节点控制器',True);ref(n,d['collision'],{'bhkNPCollisionObject'},'节点碰撞',True)
   for extra in d['extra']:ref(n,extra,EXTRAS|{'NiTextKeyExtraData'},'扩展数据')
   if typ in NODES:
    d['children']=list(r.array('i',r.u()))
    for child in d['children']:ref(n,child,NODES|SHAPES,'子节点',True)
    if typ=='BSValueNode':r.get('IB')
    _done(r,typ)
   else:
    if d['skin']!=-1:raise ValueError('此流程不处理蒙皮与节点动画组合')
    ref(n,d['shader'],{'BSLightingShaderProperty','BSEffectShaderProperty'},'网格着色器');ref(n,d['alpha'],{'NiAlphaProperty'},'透明属性',True)
   ds[i]=d
  elif typ=='bhkNPCollisionObject':
   target,flags,data,body=r.get('iHiI');ref(n,target,NODES|SHAPES,'碰撞目标');ref(n,data,{'bhkPhysicsSystem'},'物理数据');_done(r,typ)
   ds[i]=dict(id=i,type=typ,target=target,flags=flags,data=data,body=body)
  elif typ=='bhkPhysicsSystem':r.read(r.u());_done(r,typ)
  elif typ in EXTRAS:
   validate_extra(n,typ,n.blocks[i])
  elif typ=='NiAlphaProperty':
   metadata=n.net(r)
   if metadata['extra']:raise ValueError('透明属性包含未支持的关联')
   ref(n,metadata['ctrl'],{'BSNiAlphaPropertyTestRefController'},'透明属性控制器',True)
   r.get('HB');_done(r,typ)
 visited=set();active=set()
 def walk(index):
  if index in active:raise ValueError('场景节点包含循环引用')
  if index in visited:return
  active.add(index)
  for child in ds[index].get('children',[]):
   if child!=-1:walk(child)
  active.remove(index);visited.add(index)
 walk(0)
 if any(i not in visited for i,d in ds.items() if d['type'] in NODES|SHAPES):raise ValueError('场景包含未连接的网格或节点')
 for i,d in ds.items():
  if d['type'] in NODES|SHAPES and d['collision']!=-1:
   if ds[d['collision']]['target']!=i:raise ValueError('碰撞绑定与目标节点不一致')
 return ds

def _geometry(n,d):
 raw=n.blocks[d['id']];stride=(d['desc']&15)*4;fmt='<3f' if (d['desc']>>44)&0x400 else '<3e'
 start=d['dataoffset'];end=start+stride*d['vertices']
 return [struct.unpack_from(fmt,raw,start+i*stride) for i in range(d['vertices'])],list(struct.iter_unpack('<3H',raw[end:start+d['datasize']]))

def convert(src,dest,collision=True,dry_run=False,_nif=None):
 src=Path(src);dest=Path(dest);n=_nif if _nif is not None else Nif(src)
 if dest.exists() or src.resolve()==dest.resolve():raise ValueError('输出已存在或与源文件相同')
 if (n.bs,n.user,n.ver)!=(155,12,0x14020007):raise ValueError('仅支持 FO76 BS155')
 if n.groups or n.roots!=[0]:raise ValueError('仅支持无块组的单根节点模型')
 unknown={n.types[t] for t in n.indices}-ALLOWED
 if unknown:raise ValueError('未支持的动画节点：'+', '.join(sorted(unknown)))
 animation,targets=validate_animation(n);ds=_scene(n)
 w=Writer();w.strings=list(n.strings);w.blocks=[(n.types[t],b) for t,b in zip(n.indices,n.blocks)];shapes=[(i,d) for i,d in ds.items() if d['type'] in SHAPES];systems={};notes=[]
 for i,(typ,b) in enumerate(w.blocks.copy()):
  if typ in ANIM:w.set(i,convert_animation_block(n,i,130,w))
  if typ in SHAPES:
   d=ds[i];converted=bytearray(b[:d['boundend']]+b[d['boundend']+24:])
   if not collision:struct.pack_into('<i',converted,d['avend']-4,-1)
   w.set(i,bytes(converted))
  elif typ in NODES and not collision:
   converted=bytearray(b);struct.pack_into('<i',converted,ds[i]['avend']-4,-1);w.set(i,bytes(converted))
  elif typ=='BSXFlags' and not collision:
   name,flags=struct.unpack('<iI',b);w.set(i,P('iI',name,flags&~2))
  elif typ=='BSLightingShaderProperty':
   r=Reader(b);nd=n.net(r)
   if r.p!=len(b) or nd['extra'] or not nd['name']:raise ValueError('动画模型的着色器布局未支持')
   ref(n,nd['ctrl'],{'BSLightingShaderPropertyFloatController','BSLightingShaderPropertyColorController'},'光照着色器控制器',True)
   mat=nd['name'].replace('\\','/');k=mat.lower().rfind('/materials/')
   if k>=0:mat=mat[k+1:]
   if ':' in mat:raise ValueError('材质路径不能规整')
   tx=i+1
   if tx>=n.count or n.types[n.indices[tx]]!='BSShaderTextureSet':tx=w.add('BSShaderTextureSet',P('I',9)+P('I',0)*9)
   sh=bytearray(LIGHT);struct.pack_into('<i',sh,4,w.sid(mat));struct.pack_into('<i',sh,40,tx);struct.pack_into('<i',sh,60,-1)
   struct.pack_into('<i',sh,12,nd['ctrl'])
   colors={bool((d['desc']>>44)&32) for _,d in shapes if d['shader']==i}
   if len(colors)>1:raise ValueError('共享着色器的顶点颜色属性不一致')
   struct.pack_into('<I',sh,20,1|(32 if True in colors else 0));w.set(i,bytes(sh))
  elif typ=='BSShaderTextureSet':
   r=Reader(b);tx=[r.s() for _ in range(r.u())]
   if len(tx)!=15 or r.p!=len(b):raise ValueError('贴图引用布局未支持')
   w.set(i,P('I',9)+b''.join(sized(t) for t in tx[:9]))
  elif typ=='BSEffectShaderProperty':
   converted,note=effect_with_controller(n,b,[d for _,d in shapes if d['shader']==i])
   if note.get('external_material'):converted=P('i',w.sid(material_path(note['external_material'])))+converted[4:]
   w.set(i,converted);notes.append(note)
  elif typ=='bhkNPCollisionObject':
   d=ds[i];systems.setdefault(d['data'],[]).append(d)
  if typ in ('bhkNPCollisionObject','bhkPhysicsSystem') and not collision:
   # Retain block indices so all animation links remain byte-identical, but
   # replace detached FO76 physics with inert FO4-compatible integer metadata.
   w.blocks[i]=('NiIntegerExtraData',P('iI',w.sid('Removed FO76 physics'),0))
 def node_mesh(node):
  verts=[];faces=[]
  def transform(v,tf):
   return tuple(tf[j]+tf[12]*sum(tf[3+j*3+k]*v[k] for k in range(3)) for j in range(3))
  def visit(idx,chain,visited):
   if idx in visited:raise ValueError('循环节点引用')
   d=ds[idx];visited=visited|{idx}
   if idx!=node:chain=[d['transform']]+chain
   if d['type'] in SHAPES:
    vs,ts=_geometry(n,d);offset=len(verts)
    for v in vs:
     for tf in chain:v=transform(v,tf)
     verts.append(tuple(x/69.99125 for x in v))
    faces.extend(tuple(k+offset for k in t) for t in ts)
   else:
    for child in d.get('children',[]):
     if child!=-1:visit(child,chain,visited)
  visit(node,[],set())
  if not faces:raise ValueError('动画碰撞节点没有可见网格')
  return verts,faces
 body_reports=[]
 if collision and any(n.types[t]=='bhkPhysicsSystem' and i not in systems for i,t in enumerate(n.indices)):raise ValueError('未绑定的物理数据无法验证，请关闭碰撞转换')
 for system,links in (systems.items() if collision else []):
  links.sort(key=lambda d:d['body'])
  if [d['body'] for d in links]!=list(range(len(links))):raise ValueError('非连续或共享碰撞槽暂不支持')
  bodies=[]
  for link in links:
   target=link['target'];vs,ts=node_mesh(target)
   # FO4 BunExtDoor01 uses filter 2 and a motionCinfo with inverse mass=0,
   # inverse inertia=0 (keyframed). Pose is identity in each target's local space.
   motion=bytearray(112);struct.pack_into('<HH',motion,0,65535,1);struct.pack_into('<f',motion,8,1);struct.pack_into('<ff',motion,12,1.8446734e19,1.8446734e19);struct.pack_into('<f',motion,76,1)
   physics=PhysicsProps(is_dynamic=True,motion_id=0,collision_filter_info=2,mass=0,density=1,motion_cinfo_raw=bytes(motion))
   bodies.append(CollisionShape('compressed_mesh',ds[target]['name'],None,vs,ts,0,[],physics=physics))
   body_reports.append(dict(slot=link['body'],node=ds[target]['name'],vertices=len(vs),triangles=len(ts),node_local=True))
  # Preflight must exercise the same encoder/decoder as an actual conversion.
  hk=pack_shapes(bodies);decoded=parse_bytes(hk)
  if len(decoded)!=len(bodies) or any(not s.physics.is_dynamic or s.physics.mass!=0 for s in decoded):raise ValueError('动画碰撞回读失败')
  w.set(system,P('I',len(hk))+hk)
 sequences=[n.name(struct.unpack_from('<i',n.blocks[i])[0]) for i,t in enumerate(n.indices) if n.types[t]=='NiControllerSequence']
 if systems:notes.append('碰撞按渲染网格重建为节点局部零质量关键帧碰撞，未保留原始动力学参数。' if collision else '已移除碰撞绑定和 FO76 物理数据，动画块索引不变。')
 info=dict(shapes=len(shapes),vertices=sum(d['vertices'] for _,d in shapes),triangles=sum(d['triangles'] for _,d in shapes),sequences=sequences,animation_blocks=animation,animated_targets=sorted(targets),collision_rebuilt='FO4 keyframed node-local meshes' if collision and systems else None,collision_removed=bool(systems and not collision),collision_bodies=body_reports,notes=notes,route='animated',animation_runtime_verified=False)
 if dry_run:return info
 w.save(dest);out=Nif(dest)
 for i,t in enumerate(n.indices):
  if n.types[t] in ANIM or (collision and n.types[t] in NODES|{'BSXFlags','bhkNPCollisionObject','NiAlphaProperty'}):
   if out.blocks[i]!=(convert_animation_block(n,i,130,w) if n.types[t] in ANIM else n.blocks[i]):raise ValueError('动画或节点引用发生改变')
 out_animation,_=validate_animation(out)
 if animation_semantics(out_animation)!=animation_semantics(animation):raise ValueError('动画语义回读失败')
 _scene(out)
 for i,d in shapes:
  od=shape(out,i)
  if out.blocks[i][od['dataoffset']:]!=n.blocks[i][d['dataoffset']:]:raise ValueError('几何数据改变')
 if not collision and any(t in out.types for t in ('bhkNPCollisionObject','bhkPhysicsSystem')):raise ValueError('禁用碰撞后仍残留物理块')
 info.update(input=str(src),output=str(dest),source_sha256=n.source_sha256,animation_bytes_preserved=all(out.blocks[i]==n.blocks[i] for i,t in enumerate(n.indices) if n.types[t] in ANIM),animation_keys_preserved=True,shader_controller_variables_mapped=True,geometry_bytes_preserved=True)
 return info
