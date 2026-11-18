# -*- coding: utf-8 -*-
"""
Declarative binary serialization framework for MT Framework MHGU
Adapted from AsteriskAmpersand's MHW Mod3 plugin Cstruct.py
"""
from collections import OrderedDict
import struct

def chunks(l, n):
    for i in range(0, len(l), n):
        yield l[i:i + n]

def HalfToFloat(h):
    s = int((h >> 15) & 0x00000001)
    e = int((h >> 10) & 0x0000001f)
    f = int(h & 0x000003ff)
    if s == 0 and e == 0 and f == 0:
        return 0.0
    return ((-1) ** s) * (2 ** (e - 15)) * (1.0 + f / 1024.0)

def floatToHalf(fValue):
    Src = struct.unpack('<I', struct.pack('<f', fValue))[0]
    Sign = (Src >> 31) & 1
    exponent = ((Src >> 23) & 0xFF) - 127 + 15
    Mantissa = Src & 0x007FFFFF
    if 0 <= exponent <= 30:
        Result = (Sign << 15) | (exponent << 10) | ((Mantissa + 0x00001000) >> 13)
    else:
        if Src == 0:
            Result = 0
        elif exponent <= 0:
            if exponent <= -10:
                Result = 0
            else:
                Mantissa = (Mantissa | 0x00800000) >> (1 - exponent)
                Result = (Sign << 15) | ((Mantissa + 0x00002000) >> 13)
        else:
            if exponent == 255 - 127 + 15:
                Result = (Sign << 15) | 0x7C00 | (Mantissa >> 13) if Mantissa else (Sign << 15) | 0x7C00
            else:
                if (Mantissa & 0x00001000):
                    Mantissa = Mantissa + 0x00002000
                    if (Mantissa & 0x00800000):
                        Mantissa = 0
                        exponent += 1
                if exponent >= 30:
                    Result = (Sign << 15) | 0x7C00
                else:
                    Result = (Sign << 15) | (exponent << 10) | (Mantissa >> 13)
    return Result

class TypeFactory:
    @staticmethod
    def le(typename, packchar):
        return {'size': struct.calcsize('<' + packchar),
                'deserializer': lambda x: struct.unpack('<' + packchar, x)[0],
                'serializer': lambda x: struct.pack('<' + packchar, x)}

    @staticmethod
    def be(typename, packchar):
        return {'size': struct.calcsize('>' + packchar),
                'deserializer': lambda x: struct.unpack('>' + packchar, x)[0],
                'serializer': lambda x: struct.pack('>' + packchar, x)}

    @staticmethod
    def halfFloatLE():
        return {'size': 2,
                'deserializer': lambda x: HalfToFloat(struct.unpack('<H', x)[0]) * 2.0,
                'serializer': lambda x: struct.pack('<H', floatToHalf(x))}

    @staticmethod
    def halfFloatBE():
        return {'size': 2,
                'deserializer': lambda x: HalfToFloat(struct.unpack('>H', x)[0]),
                'serializer': lambda x: struct.pack('>H', floatToHalf(x))}

class Cstruct:
    CTypesLE = {
        "byte":       TypeFactory.le("byte", 'b'),
        "int8":       TypeFactory.le("int8", 'b'),
        "ubyte":      TypeFactory.le("ubyte", 'B'),
        "uint8":      TypeFactory.le("uint8", 'B'),
        "short":      TypeFactory.le("short", 'h'),
        "int16":      TypeFactory.le("int16", 'h'),
        "ushort":     TypeFactory.le("ushort", 'H'),
        "uint16":     TypeFactory.le("uint16", 'H'),
        "long":       TypeFactory.le("long", 'i'),
        "int32":      TypeFactory.le("int32", 'i'),
        "int":        TypeFactory.le("int", 'i'),
        "ulong":      TypeFactory.le("ulong", 'I'),
        "uint32":     TypeFactory.le("uint32", 'I'),
        "uint":       TypeFactory.le("uint", 'I'),
        "quad":       TypeFactory.le("quad", 'q'),
        "int64":      TypeFactory.le("int64", 'q'),
        "uquad":      TypeFactory.le("uquad", 'Q'),
        "uint64":     TypeFactory.le("uint64", 'Q'),
        "hfloat":     TypeFactory.halfFloatLE(),
        "float":      TypeFactory.le("float", 'f'),
        "double":     TypeFactory.le("double", 'd'),
        "char":       TypeFactory.le("char", 'c'),
        "bool":       TypeFactory.le("bool", '?'),
    }

    CTypesBE = {
        "byte":       TypeFactory.be("byte", 'b'),
        "int8":       TypeFactory.be("int8", 'b'),
        "ubyte":      TypeFactory.be("ubyte", 'B'),
        "uint8":      TypeFactory.be("uint8", 'B'),
        "short":      TypeFactory.be("short", 'h'),
        "int16":      TypeFactory.be("int16", 'h'),
        "ushort":     TypeFactory.be("ushort", 'H'),
        "uint16":     TypeFactory.be("uint16", 'H'),
        "long":       TypeFactory.be("long", 'i'),
        "int32":      TypeFactory.be("int32", 'i'),
        "int":        TypeFactory.be("int", 'i'),
        "ulong":      TypeFactory.be("ulong", 'I'),
        "uint32":     TypeFactory.be("uint32", 'I'),
        "uint":       TypeFactory.be("uint", 'I'),
        "quad":       TypeFactory.be("quad", 'q'),
        "int64":      TypeFactory.be("int64", 'q'),
        "uquad":      TypeFactory.be("uquad", 'Q'),
        "uint64":     TypeFactory.be("uint64", 'Q'),
        "hfloat":     TypeFactory.halfFloatBE(),
        "float":      TypeFactory.be("float", 'f'),
        "double":     TypeFactory.be("double", 'd'),
        "char":       TypeFactory.be("char", 'c'),
        "bool":       TypeFactory.be("bool", '?'),
    }

    @staticmethod
    def isArrayType(typeStr):
        return '[' in typeStr

    @staticmethod
    def arrayType(typeStr, ctypes):
        base = typeStr[:typeStr.index('[')]
        size = int(typeStr[typeStr.index('[') + 1:typeStr.index(']')])
        baseType = ctypes[base]
        if base != "char":
            return {
                'size': size * baseType['size'],
                'deserializer': lambda x: [baseType['deserializer'](chunk) for chunk in chunks(x, baseType['size'])],
                'serializer': lambda x: b''.join(map(baseType['serializer'], x))
            }
        else:
            return {
                'size': size * baseType['size'],
                'deserializer': lambda x: b''.join([baseType['deserializer'](chunk) for chunk in chunks(x, baseType['size'])]).decode('ascii', errors='replace').rstrip('\x00'),
                'serializer': lambda x: (x if isinstance(x, bytes) else x.encode('ascii', errors='replace')).ljust(size, b'\x00')
            }

    def __init__(self, fields, big_endian=False):
        self.struct = OrderedDict()
        self.ctypes = Cstruct.CTypesBE if big_endian else Cstruct.CTypesLE
        for name in fields:
            if fields[name] in self.ctypes:
                self.struct[name] = self.ctypes[fields[name]]
            elif Cstruct.isArrayType(fields[name]):
                self.struct[name] = Cstruct.arrayType(fields[name], self.ctypes)
            else:
                raise ValueError("Unknown type: %s" % fields[name])

    def __len__(self):
        return sum(self.struct[e]['size'] for e in self.struct)

    def marshall(self, data):
        return {name: op['deserializer'](data.read(op['size'])) for name, op in self.struct.items()}

    def serialize(self, data):
        return b''.join(op['serializer'](data[name]) for name, op in self.struct.items())

class PyCStruct:
    def __init__(self, data=None, big_endian=False, **kwargs):
        self._big_endian = big_endian
        self._cstruct = Cstruct(self.fields, big_endian)
        if data is not None:
            self.marshall(data)
        elif kwargs:
            for attr, value in kwargs.items():
                self.__setattr__(attr, value)
        else:
            for f in self.fields:
                self.__setattr__(f, 0)

    def __len__(self):
        return len(self._cstruct)

    def marshall(self, data):
        for attr, value in self._cstruct.marshall(data).items():
            self.__setattr__(attr, value)

    def serialize(self):
        return self._cstruct.serialize({key: self.__getattribute__(key) for key in self.fields})

    def construct(self, data):
        for field in self.fields:
            if field in data:
                self.__setattr__(field, data[field])
            elif field in self.defaultProperties:
                self.__setattr__(field, self.defaultProperties[field])
            elif field in self.requiredProperties:
                raise KeyError("Required property missing: %s" % field)
            else:
                self.__setattr__(field, None)

    def verify(self):
        for attr in self.fields:
            val = self.__getattribute__(attr)
            if val is None:
                raise AssertionError("Attribute %s is not initialized." % attr)

    defaultProperties = {}
    requiredProperties = {}

