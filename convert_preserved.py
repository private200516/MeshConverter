"""Schema-validated FO76 skins, partitions and simple effects -> FO4. GPL-3.0.
Schema: niftools/nifxml. Target skeletons are read from the user's chosen root.
Geometry, weights, bind poses and partitions are preserved, never retargeted.
External converted materials control appearance; runtime behavior is unverified.
"""
import struct,hashlib,math
from pathlib import Path
from inspect_nif import Nif,Reader
from convert_models import Writer,P,sized,LIGHT,COMMON_EXTRA_TYPES,validate_extra
from skin_reference import match_skeleton
from shader_flags import fo76_to_fo4
SKIN_SHADER=bytes.fromhex('010000000b00000000000000ffffffff930240801100000000000000000000000000803f0000803f110000000000000000000000000000000000803f09000000030000000000803f000000000000803f0000803f0000803f0000803f0000803f00000000ffff7f7f00000000000000000000a040000080bf000080bf000080bf000080bf000080bf000080bf0000803f0000')
ALLOWED={'NiNode','BSFadeNode','BSTriShape','BSSubIndexTriShape','BSSkin::Instance','BSSkin::BoneData','BSLightingShaderProperty','BSShaderTextureSet','BSEffectShaderProperty','NiAlphaProperty'}|COMMON_EXTRA_TYPES

def finite(values, label):
 if not all(math.isfinite(v) for v in values):raise ValueError(label+' 含非有限数值')

def ref(n,index,types,label,optional=False):
 if optional and index==-1:return
 if not 0<=index<n.count or n.types[n.indices[index]] not in types:raise ValueError(label+' 引用无效')

def segments(r,triangles):
 """Validate the identical FO4/F76 BSSubIndexTriShape tail in nifxml."""
 primitives,num,total=r.get('III')
 if primitives!=triangles or num>total or total>100000:raise ValueError('分区数量无效')
 seen=0;covered=0;end=0
 for index in range(num):
  start,count,parent,subs=r.get('IIII');seen+=1+subs
  if start%3 or start//3+count>triangles or (count and start//3<end):raise ValueError('分区三角范围无效')
  if parent!=0xffffffff and parent>=total:raise ValueError('分区父索引无效')
  if count:end=start//3+count
  covered+=count
  subend=start//3
  if subs>total:raise ValueError('子分区数量无效')
  for _ in range(subs):
   ss,sc,sp,unused=r.get('IIII')
   if ss%3 or ss//3<start//3 or ss//3+sc>start//3+count or (sc and ss//3<subend):raise ValueError('子分区三角范围无效')
   if sp!=0xffffffff and sp>=total:raise ValueError('子分区父索引无效')
   if sc:subend=ss//3+sc
 if seen!=total:raise ValueError('分区总数量不一致')
 ssf=''
 if num<total:
  shared_num,shared_total=r.get('II')
  if (shared_num,shared_total)!=(num,total):raise ValueError('共享分区数量不一致')
  starts=r.get('I'*num)
  if any(v>=total for v in starts):raise ValueError('共享分区索引无效')
  for _ in range(total):
   user,bone,cuts=r.get('III')
   if cuts>8:raise ValueError('分区切割参数数量无效')
   finite(r.get('f'*cuts),'分区切割参数')
  ssf=r.read(r.get('H')[0]).decode('utf8').rstrip('\0')
 return dict(segments=num,total_segments=total,ssf=ssf,unassigned_triangles=triangles-covered)

def shape(n,i):
 r=Reader(n.blocks[i]);d=n.av(r);d['bound']=r.get('4f');d['boundend']=r.p
 finite(d['transform']+d['bound'],'网格变换或包围球')
 if n.bs==155:
  bounds=r.get('6f');finite(bounds,'网格边界')
  if any(v<0 for v in bounds[3:]):raise ValueError('网格包围盒半尺寸不能为负')
 d['skin'],d['shader'],d['alpha']=r.get('iii');d['desc']=r.get('Q')[0];d['triangles'],d['vertices'],d['datasize']=r.get('IHI');d['dataoffset']=r.p
 stride=(d['desc']&15)*4
 if d['datasize']!=stride*d['vertices']+d['triangles']*6:raise ValueError('网格数据长度不一致')
 data=r.read(d['datasize']);tri=data[stride*d['vertices']:]
 if not d['vertices'] or any(max(t)>=d['vertices'] for t in struct.iter_unpack('<3H',tri)):raise ValueError('无效顶点或三角索引')
 attr=d['desc']>>44
 if not attr&1 or attr&~0x57b:raise ValueError('未支持的顶点属性布局：'+hex(attr))
 if attr&16 and not attr&8:raise ValueError('切线数据缺少对应法线字段')
 if (d['skin']!=-1)!=bool(attr&0x40):raise ValueError('顶点蒙皮标记与绑定引用不一致')
 # VertexDesc offsets are in four-byte units. Reject overlapping/truncated fields.
 fields=[(0,16 if attr&0x400 else 8,'position')]
 for flag,shift,size,label in ((2,8,4,'uv'),(8,16,4,'normal'),(16,20,4,'tangent'),(32,24,4,'color'),(64,28,12,'skin'),(256,36,4,'eye')):
  if attr&flag:fields.append((((d['desc']>>shift)&15)*4,size,label))
 spans=sorted(fields)
 if any(offset+size>stride for offset,size,_ in spans) or any(a[0]+a[1]>b[0] for a,b in zip(spans,spans[1:])):raise ValueError('顶点字段偏移重叠或超出步长')
 for v in range(d['vertices']):
  offset=v*stride
  finite(struct.unpack_from('<3f' if attr&0x400 else '<3e',data,offset),'顶点坐标')
  if attr&16:finite(struct.unpack_from('<f' if attr&0x400 else '<e',data,offset+(12 if attr&0x400 else 6)),'顶点副切线')
  if attr&2:finite(struct.unpack_from('<2e',data,offset+((d['desc']>>8)&15)*4),'顶点 UV')
 if n.types[n.indices[i]]=='BSSubIndexTriShape':d['segments']=segments(r,d['triangles'])
 if n.types[n.indices[i]]=='BSMeshLODTriShape':
  # Same-format parsing only. FO76 engine support has no reference evidence.
  d['lod_sizes']=r.get('3I')
  if sum(d['lod_sizes'])!=d['triangles']:raise ValueError('LOD triangle counts do not match geometry')
 if r.p!=len(r.b):raise ValueError('网格含未解析的尾部字段')
 return d

def skin_instance(n,i):
 r=Reader(n.blocks[i]);root,data,count=r.get('iiI')
 ref(n,root,{'NiNode','BSFadeNode'},'蒙皮根')
 ref(n,data,{'BSSkin::BoneData'},'骨骼数据')
 if not 1<=count<=256:raise ValueError('骨骼数量超出字节索引范围')
 ids=r.get('i'*count)
 if len(set(ids))!=count:raise ValueError('重复骨骼引用')
 names=[]
 for bone in ids:
  ref(n,bone,{'NiNode'},'骨骼');node=n.av(Reader(n.blocks[bone]));finite(node['transform'],'骨骼变换')
  if not node['name']:raise ValueError('绑定骨骼缺少名称')
  names.append(node['name'])
 if len(set(names))!=count:raise ValueError('重复骨骼名称')
 scales=r.u()
 if scales not in (0,count):raise ValueError('蒙皮缩放数量与骨骼数量不一致')
 finite(r.get('f'*(scales*3)),'蒙皮缩放')
 if r.p!=len(r.b):raise ValueError('蒙皮实例含未解析字段')
 br=Reader(n.blocks[data])
 if br.u()!=count:raise ValueError('骨骼变换数量与蒙皮实例不一致')
 for _ in range(count):
  transform=br.get('17f');finite(transform,'绑定姿势')
  if transform[3]<0 or transform[16]<=0:raise ValueError('绑定姿势包围球或缩放无效')
 if br.p!=len(br.b):raise ValueError('骨骼数据含未解析字段')
 return dict(root=root,data=data,ids=ids,names=names,count=count)

def validate_weights(n,i,d,skin):
 data=n.blocks[i];stride=(d['desc']&15)*4;offset=((d['desc']>>28)&15)*4
 for vertex in range(d['vertices']):
  values=struct.unpack_from('<4e4B',data,d['dataoffset']+stride*vertex+offset)
  weights,indices=values[:4],values[4:];finite(weights,'骨骼权重')
  if any(w<0 or w>1 for w in weights) or abs(sum(weights)-1)>0.01:raise ValueError('顶点权重无效或未归一化：'+str(vertex))
  if any(index>=skin['count'] for index in indices):raise ValueError('顶点骨骼索引越界：'+str(vertex))

def validate_graph(n,shapes,skins):
 nodes={}
 avtypes={'NiNode','BSFadeNode','BSTriShape','BSSubIndexTriShape'}
 for i,t in enumerate(n.indices):
  typ=n.types[t]
  if typ in COMMON_EXTRA_TYPES:
   validate_extra(n,typ,n.blocks[i])
  if typ not in avtypes:continue
  r=Reader(n.blocks[i]);d=n.av(r);finite(d['transform'],'节点变换')
  for extra in d['extra']:
   ref(n,extra,COMMON_EXTRA_TYPES,'扩展属性')
  if d['ctrl']!=-1 or d['collision']!=-1:raise ValueError('含控制器或物理绑定，当前保留流程不支持')
  children=[]
  if typ in ('NiNode','BSFadeNode'):
   count=r.u()
   if count>n.count:raise ValueError('节点子对象数量无效')
   children=list(r.get('i'*count))
   for child in children:ref(n,child,avtypes,'子节点',True)
   if r.p!=len(r.b):raise ValueError('节点含未解析字段')
  nodes[i]=[child for child in children if child!=-1]
 visited=set();active=set()
 def walk(i):
  if i in active:raise ValueError('节点包含循环引用')
  if i in visited:return
  active.add(i)
  for child in nodes.get(i,[]):walk(child)
  active.remove(i);visited.add(i)
 walk(0)
 required={i for i,_ in shapes}
 for skin in skins.values():required.update(skin['ids']);required.add(skin['root'])
 if not required<=visited:raise ValueError('网格或骨骼未连接到根节点')

def effect(n,b,owners=None):
 r=Reader(b);nd=n.net(r)
 if nd['extra'] or nd['ctrl']!=-1:raise ValueError('此特效属性暂不支持')
 if nd['name']:
  if r.p!=len(b) or not nd['name'].lower().endswith('.bgem'):raise ValueError('外部特效材质布局未支持')
  skinned={d['skin']!=-1 for d in (owners or [])};colored={bool((d['desc']>>44)&32) for d in (owners or [])}
  if len(skinned)>1 or len(colored)>1:raise ValueError('共享特效着色器的网格属性不一致')
  flag1=0x80000000 | (2 if True in skinned else 0);flag2=32 if True in colored else 0
  output=b+P('II4f',flag1,flag2,0,0,1,1)+sized('')
  output+=P('4B4f4fff',3,255,0,0,1,1,1,1,1,1,1,1,1,100)
  output+=sized('')*4+P('f',1)
  return output,dict(flags=[flag1,flag2],external_material=nd['name'],fallback='FO4 schema defaults; converted BGEM required')
 num1,num2=r.get('II');hashes1=r.array('I',num1);hashes2=r.array('I',num2)
 flag1,flag2=fo76_to_fo4(hashes1,hashes2)
 uv=r.read(16);texture=r.s();clamp=r.read(4);falloff=r.read(16);refraction=r.get('f')[0]
 color=r.read(16);scale_depth=r.read(8);textures=[r.s() for _ in range(4)];envscale=r.read(4)
 reflectance,lighting=r.s(),r.s();emittance=r.get('3f');gradient=r.s();luminance=r.get('4f')
 finite(struct.unpack('<4f',uv)+struct.unpack('<4f',falloff)+struct.unpack('<4f',color)+struct.unpack('<2f',scale_depth)+struct.unpack('<f',envscale)+(refraction,)+emittance+luminance,'特效参数')
 if r.p!=len(b) or refraction or reflectance or lighting or gradient or any(emittance):raise ValueError('该特效含尚未映射的 FO76 专属参数')
 output=b[:12]+P('II',flag1,flag2)+uv+sized(texture)+clamp+falloff+color+scale_depth+b''.join(sized(t) for t in textures)+envscale
 return output,dict(flags=[flag1,flag2],source_texture=texture,omitted_fo76_luminance=list(luminance))

def route(src):
 n=_nif if _nif is not None else Nif(src)
 if 'BSSkin::Instance' in n.types:return '骨骼蒙皮（需目标骨骼参照）'
 if 'BSSubIndexTriShape' in n.types:return '分区模型（试验）'
 if 'NiControllerManager' in n.types:return '节点动画（试验）'
 if any('Controller' in t or 'Interpolator' in t or 'Sequence' in t for t in n.types):return '节点动画（未支持）'
 for i,t in enumerate(n.indices):
  if n.types[t]=='BSEffectShaderProperty':
   r=Reader(n.blocks[i]);d=n.net(r)
   if not d['name']:return '特效模型（试验）'
 return '静态模型'

def convert(src,dest,collision=False,dry_run=False,reference_root=None,_nif=None):
 src=Path(src);dest=Path(dest);n=_nif if _nif is not None else Nif(src)
 if dest.exists() or src.resolve()==dest.resolve():raise ValueError('输出已存在或与源文件相同')
 if (n.bs,n.user,n.ver)!=(155,12,0x14020007):raise ValueError('仅支持 FO76 BS155 模型')
 unknown={n.types[t] for t in n.indices}-ALLOWED
 if unknown:raise ValueError('保留骨骼流程尚不支持：'+', '.join(sorted(unknown)))
 if n.groups or n.footer!=P('Ii',1,0):raise ValueError('当前保留流程需要单根节点且无块组')
 shapes=[(i,shape(n,i)) for i,t in enumerate(n.indices) if n.types[t] in ('BSTriShape','BSSubIndexTriShape')]
 skins={i:skin_instance(n,i) for i,t in enumerate(n.indices) if n.types[t]=='BSSkin::Instance'}
 validate_graph(n,shapes,skins)
 bones=list(dict.fromkeys(name for skin in skins.values() for name in skin['names']))
 reference=match_skeleton(reference_root,bones,src) if skins else None
 shader_owners={}
 for i,d in shapes:
  ref(n,d['shader'],{'BSLightingShaderProperty','BSEffectShaderProperty'},'着色器')
  ref(n,d['alpha'],{'NiAlphaProperty'},'透明属性',True)
  if d['skin']!=-1:
   if d['skin'] not in skins:raise ValueError('网格蒙皮实例引用无效')
   validate_weights(n,i,d,skins[d['skin']])
  shader_owners.setdefault(d['shader'],[]).append(d)
 w=Writer();w.strings=list(n.strings);w.blocks=[(n.types[t],b) for t,b in zip(n.indices,n.blocks)];notes=[]
 if reference:notes.append('保留原始绑定姿势和权重；目标骨骼名称已匹配，游戏内穿戴、动画和第一人称效果仍需验证。')
 unassigned=sum(d.get('segments',{}).get('unassigned_triangles',0) for _,d in shapes)
 if unassigned:notes.append(f'源模型有 {unassigned} 个三角形未分配到分区；原样保留，未自动重分区。')
 for i,(typ,b) in enumerate(w.blocks.copy()):
  if typ in ('NiNode','BSFadeNode','BSTriShape','BSSubIndexTriShape'):
   d=n.av(Reader(b))
   if d['ctrl']!=-1 or d['collision']!=-1:raise ValueError('含控制器或物理绑定，当前保留流程不支持')
   finite(d['transform'],'节点变换')
  if typ in ('BSTriShape','BSSubIndexTriShape'):
   d=next(d for idx,d in shapes if idx==i);w.set(i,b[:d['boundend']]+b[d['boundend']+24:])
  elif typ=='BSSkin::Instance':
   pass  # Fully parsed and validated before constructing the output.
  elif typ=='BSLightingShaderProperty':
   r=Reader(b);nd=n.net(r)
   if r.p!=len(b) or not nd['name'] or nd['ctrl']!=-1 or nd['extra']:raise ValueError('蒙皮流程仅支持外部材质引用')
   tx=i+1
   if tx>=n.count or n.types[n.indices[tx]]!='BSShaderTextureSet':tx=w.add('BSShaderTextureSet',P('I',9)+P('I',0)*9)
   owners=shader_owners.get(i,[])
   skinned={d['skin']!=-1 for d in owners};colored={bool((d['desc']>>44)&32) for d in owners}
   if len(skinned)>1 or len(colored)>1:raise ValueError('共享着色器的网格属性不一致，需要拆分属性后转换')
   sh=bytearray(SKIN_SHADER if True in skinned else LIGHT)
   material=nd['name'].replace('\\','/');start=material.lower().rfind('/materials/')
   if start>=0:material=material[start+1:]
   if ':' in material:raise ValueError('无法规整外部材质路径')
   struct.pack_into('<i',sh,4,w.sid(material));struct.pack_into('<i',sh,40,tx)
   # Fallback flags must not impose a palette or skin/color attribute that the
   # owning geometry does not have. Converted external materials take precedence.
   flags=struct.unpack_from('<I',sh,16)[0] & ~((1<<4)|(1<<5)|(1<<1))
   if True in skinned:flags|=1<<1
   flags2=struct.unpack_from('<I',sh,20)[0] & ~(1<<5)
   if True in colored:flags2|=1<<5
   struct.pack_into('<I',sh,16,flags);struct.pack_into('<I',sh,20,flags2);w.set(i,bytes(sh))
  elif typ=='BSShaderTextureSet':
   r=Reader(b);tx=[r.s() for _ in range(r.u())]
   if len(tx)!=15 or r.p!=len(b):raise ValueError('未验证的 FO76 贴图引用布局')
   w.set(i,P('I',9)+b''.join(sized(t) for t in tx[:9]))
  elif typ=='BSEffectShaderProperty':
   converted,detail=effect(n,b,shader_owners.get(i))
   material=detail.get('external_material')
   if material:
    material=material.replace('\\','/');start=material.lower().rfind('/materials/')
    if start>=0:material=material[start+1:]
    if ':' in material:raise ValueError('无法规整外部特效材质路径')
    converted=P('i',w.sid(material))+converted[4:]
   w.set(i,converted);notes.append(detail)
 if not shapes:raise ValueError('无可转换网格')
 info=dict(shapes=len(shapes),vertices=sum(d['vertices'] for _,d in shapes),triangles=sum(d['triangles'] for _,d in shapes),bones=bones,route='preserved',collision_rebuilt=None,notes=notes,skeleton_reference=reference,partitioned_shapes=sum('segments' in d for _,d in shapes),unassigned_partition_triangles=unassigned,skin_weights_validated=bool(skins))
 if dry_run:return info
 w.save(dest);out=Nif(dest)
 if out.bs!=130:raise ValueError('目标版本校验失败')
 for i,d in shapes:
  od=shape(out,i)
  if out.blocks[i][od['dataoffset']:]!=n.blocks[i][d['dataoffset']:]:raise ValueError('几何、蒙皮或分区数据改变')
 for i,t in enumerate(n.indices):
  if n.types[t] in COMMON_EXTRA_TYPES|{'NiNode','BSFadeNode','BSSkin::Instance','BSSkin::BoneData','NiAlphaProperty'}:
   if out.blocks[i]!=n.blocks[i]:raise ValueError('节点或绑定数据改变')
 info.update(input=str(src),output=str(dest),source_sha256=n.source_sha256,geometry_bytes_preserved=True,skin_and_segments_preserved=True)
 return info
