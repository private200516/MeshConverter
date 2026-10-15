"""Conservative named FO4 flag <-> FO76 CRC mappings from niftools/nifxml.

Only flags with a direct named equivalent are represented. PBR, no-exposure,
refraction-falloff, hair tint, and FO4 specular are intentionally not guessed.
The layouts/names are supported by the schema; visual equality in both games
still requires matching materials and runtime validation.
"""

# CRC: (FO4 flag word, bit, schema name). The word is one-based.
COMMON_FLAGS = {
    3744563888: (1, 1, 'SKINNED'),
    2333069810: (1, 3, 'VERTEX_ALPHA'),
    442246519: (1, 4, 'GRAYSCALE_TO_PALETTE_COLOR'),
    2901038324: (1, 5, 'GRAYSCALE_TO_PALETTE_ALPHA'),
    3980660124: (1, 6, 'FALLOFF'),
    2893749418: (1, 7, 'ENVMAP'),
    3448946507: (1, 8, 'RGB_FALLOFF'),
    1563274220: (1, 9, 'CAST_SHADOWS'),
    314919375: (1, 10, 'FACE'),
    2548465567: (1, 12, 'MODELSPACENORMALS'),
    1957349758: (1, 15, 'REFRACTION'),
    1483897208: (1, 21, 'SKIN_TINT'),
    3849131744: (1, 26, 'DECAL'),
    1576614759: (1, 27, 'DYNAMIC_DECAL'),
    2150459555: (1, 29, 'EXTERNAL_EMITTANCE'),
    3503164976: (1, 30, 'SOFT_EFFECT'),
    1740048692: (1, 31, 'ZBUFFER_TEST'),
    3166356979: (2, 0, 'ZBUFFER_WRITE'),
    2896726515: (2, 2, 'LOD_OBJECTS'),
    2994043788: (2, 3, 'NOFADE'),
    759557230: (2, 4, 'TWO_SIDED'),
    348504749: (2, 5, 'VERTEXCOLORS'),
    2399422528: (2, 6, 'GLOWMAP'),
    3196772338: (2, 7, 'TRANSFORM_CHANGED'),
    2078326675: (2, 17, 'WEAPON_BLOOD'),
    3473438218: (2, 30, 'EFFECT_LIGHTING'),
}


def fo76_to_fo4(hashes1, hashes2):
    flags = [0, 0]
    for value in (*hashes1, *hashes2):
        if value not in COMMON_FLAGS:
            raise ValueError('FO76 shader flag has no verified FO4 equivalent: ' + str(value))
        word, bit, _ = COMMON_FLAGS[value]
        flags[word - 1] |= 1 << bit
    return tuple(flags)


def fo4_to_fo76(flag1, flag2):
    if any(not isinstance(flag, int) or flag < 0 or flag > 0xffffffff for flag in (flag1, flag2)):
        raise ValueError('FO4 shader flags must be unsigned 32-bit words')
    remaining = [flag1, flag2]
    hashes = [[], []]
    for crc, (word, bit, _) in sorted(COMMON_FLAGS.items(), key=lambda item: item[1][:2]):
        if remaining[word - 1] & (1 << bit):
            hashes[word - 1].append(crc)
            remaining[word - 1] &= ~(1 << bit)
    if any(remaining):
        raise ValueError('FO4 shader flags have no verified FO76 equivalent: ' + ', '.join(hex(f) for f in remaining))
    return tuple(hashes[0]), tuple(hashes[1])
