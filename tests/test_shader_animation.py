"""Tests shader target semantics, key integrity and malformed reference rejection."""
import math
import struct
import tempfile
import unittest
from pathlib import Path
from test_animated import fixture
from inspect_nif import Nif, Reader
from convert_models import P
from converter import convert_file
from convert_animated import validate_animation, ANIM
from shader_animation import (validate_shared_block, validate_interpolator_links,
                              animation_semantics, convert_controller_block)


def shader_fixture(path, lighting=False, color=False, variable=None, mutate=None):
    def configure(w):
        typ = ('BSLighting' if lighting else 'BSEffect') + 'ShaderProperty'
        ctrl_type = typ + ('ColorController' if color else 'FloatController')
        controller = w.add(ctrl_type)
        interpolator = w.add('NiPoint3Interpolator' if color else 'NiFloatInterpolator')
        data = w.add('NiPosData' if color else 'NiFloatData')
        w.blocks[8] = (typ, w.net('Materials/demo.' + ('bgsm' if lighting else 'bgem'))[:-4] + P('i',controller))
        variable_value = variable if variable is not None else (1 if lighting else 0) if color else (3 if lighting else 13)
        w.set(controller, P('iH4fiiI', -1, 76, 1, 0, 0, 2, 8, interpolator, variable_value))
        width = 3 if color else 1
        w.set(interpolator, P('f' * width + 'i', *([0] * width), data))
        w.set(data, P('II', 2, 2) + P('f' * (1 + width * 3), 0, *([0] * width * 3))
                    + P('f' * (1 + width * 3), 2, *([1] * width * 3)))
        if mutate:
            mutate(w, controller, interpolator, data)
    fixture(path, configure)


class ShaderAnimationTests(unittest.TestCase):
    def test_both_shader_families_roundtrip_semantics_and_keys(self):
        for lighting in (False, True):
            for color in (False, True):
                with self.subTest(lighting=lighting, color=color), tempfile.TemporaryDirectory() as td:
                    source, fo4, fo76 = [Path(td)/x for x in ('source.nif','fo4.nif','fo76.nif')]
                    shader_fixture(source, lighting, color)
                    convert_file(source, fo4, collision=False)
                    convert_file(fo4, fo76, direction='4-to-76', collision=False)
                    a, b, c = Nif(source), Nif(fo4), Nif(fo76)
                    for target in (b, c):
                        self.assertEqual(animation_semantics(validate_animation(a)[0]), animation_semantics(validate_animation(target)[0]))
                    for i,t in enumerate(a.indices):
                        if a.types[t].endswith(('Data','Interpolator')):
                            self.assertEqual(a.blocks[i], c.blocks[i])
                    r = Reader(b.blocks[8])
                    if lighting:
                        r.u()
                    self.assertEqual(b.net(r)['ctrl'], 9)
                    self.assertEqual(c.net(Reader(c.blocks[8]))['ctrl'], 9)
                    if not color:
                        self.assertEqual(struct.unpack_from('<I', b.blocks[9], 30)[0], 11 if lighting else 8)
                        self.assertEqual(struct.unpack_from('<I', c.blocks[9], 30)[0], 3 if lighting else 13)

    def test_unknown_variable_rejected_without_published_output(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td)/'source.nif', Path(td)/'target.nif'
            shader_fixture(src, variable=99)
            with self.assertRaisesRegex(ValueError, '参数'):
                convert_file(src, dst, collision=False)
            self.assertFalse(dst.exists())
            self.assertFalse(list(Path(td).glob('*.tmp')))

    def test_truncated_controller_invalid_target_and_nonfinite_keys_rejected(self):
        mutations = [lambda w,c,i,d: w.set(c, w.blocks[c][1][:-1]),
                     lambda w,c,i,d: w.set(c, w.blocks[c][1][:22]+P('i',0)+w.blocks[c][1][26:]),
                     lambda w,c,i,d: w.set(d, w.blocks[d][1][:12]+P('f',math.nan)+w.blocks[d][1][16:])]
        for mutate in mutations:
            with tempfile.TemporaryDirectory() as td:
                src, dst=Path(td)/'source.nif',Path(td)/'target.nif'
                shader_fixture(src, mutate=mutate)
                with self.assertRaises(ValueError):
                    convert_file(src, dst, collision=False)
                self.assertFalse(dst.exists())

    def test_bool_keys_and_manager_blend_parsed(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'source.nif'
            def add(w):
                c=w.add('NiVisController'); i=w.add('NiBoolTimelineInterpolator'); d=w.add('NiBoolData')
                w.set(c,P('iH4fii',-1,76,1,0,0,1,0,i));w.set(i,P('Bi',2,d));w.set(d,P('IIfBfB',2,5,0,0,1,1))
                w.add('NiBlendFloatInterpolator',P('BBff',1,2,0,-3.4028234663852886e38))
            fixture(src,add)
            n=Nif(src); reports,_=validate_animation(n)
            self.assertTrue(any(r.get('keys')==2 and r['type']=='NiBoolData' for r in reports))
            self.assertTrue(any(r.get('manager_controlled') for r in reports))

    def test_sequence_controller_identifier_tracks_remapped_parameter(self):
        for identifier in ('13','8'):
            with tempfile.TemporaryDirectory() as td:
                source, fo4, fo76=[Path(td)/x for x in ('source.nif','fo4.nif','fo76.nif')]
                def managed(w,c,i,d):
                    names=[w.sid(x) for x in ('Triangle','BSEffectShaderProperty','BSEffectShaderPropertyFloatController',identifier,'')]
                    sequence=P('iIIiiB5ifiI3fiiH',w.sid('Idle'),1,1,i,c,0,*names,1,-1,0,1,0,2,-1,-1,0)
                    w.add('NiControllerSequence',sequence)
                shader_fixture(source,mutate=managed)
                convert_file(source,fo4,collision=False)
                convert_file(fo4,fo76,direction='4-to-76',collision=False)
                for file,expected in ((fo4,'8'),(fo76,'13')):
                    n=Nif(file);block=next(n.blocks[i] for i,t in enumerate(n.indices) if n.types[t]=='NiControllerSequence')
                    self.assertEqual(n.name(struct.unpack_from('<i',block,33)[0]),expected)

    def test_blend_cycles_rejected(self):
        with self.assertRaisesRegex(ValueError, '循环'):
            validate_interpolator_links([{'block':1,'children':[2]},{'block':2,'children':[1]}])


if __name__ == '__main__':
    unittest.main()