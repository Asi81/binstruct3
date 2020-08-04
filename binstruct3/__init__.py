import copy
import inspect
import io
import struct
import locale

# simple storage class descriptor
from abc import ABC, abstractmethod
from typing import Type, Union, Any, Optional, BinaryIO, Generator, Tuple


class Binstruct3Error(Exception):
    pass


class FieldError(Binstruct3Error):
    def __init__(self, field_name, error_msg):
        super().__init__(f"field {field_name}: {error_msg}")
        self.field_name = field_name


# ABC for transforming python-object to and from bytes
class Packer(ABC):

    @abstractmethod
    def unpack(self, stream: BinaryIO):
        pass

    @abstractmethod
    def pack(self, stream: BinaryIO, obj):
        pass

    @abstractmethod
    def byte_size(self, obj) -> int:
        pass

    @abstractmethod
    def default_value(self):
        pass

    @abstractmethod
    def validate_value(self, obj):
        pass

    @abstractmethod
    def __call__(self, *args, **kwargs) -> "Packer":
        pass


class Field:
    def __init__(self):
        super().__init__()
        self.storage = ""

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return getattr(instance, self.storage)

    def __set__(self, instance, value):
        setattr(instance, self.storage, value)

    def fill(self, instance, inpstream: Optional[Any] = None):
        pass

    def write(self, instance, outstream):
        pass

    def byte_size(self, instance) -> int:
        pass


# Packable interface
class Packable:

    def fields(self) -> Generator[Tuple[str, Field], None, None]:
        supercls = type(self).__mro__[1]
        for name, obj in supercls.__dict__.items():
            if isinstance(obj, Field):
                yield name, obj

    def reload(self, stream: Union[BinaryIO, bytes, bytearray, None] = None):
        align = getattr(self, "_align", 1)
        stream = self.get_stream(stream)
        start = stream.tell() if stream else 0
        for name, obj in self.fields():
            obj.fill(self, stream)
            if stream:
                offs = stream.tell() - start
                skip = (align - offs % align) % align
                if skip:
                    stream.read(skip)

    def to_bytes(self) -> bytes:
        out = io.BytesIO()
        self.dump(out)
        return out.getvalue()

    def dump(self, stream: BinaryIO):
        align = getattr(self, "_align", 1)
        stream = self.get_stream(stream)
        start = stream.tell()
        for name, obj in self.fields():
            obj.write(self, stream)
            offs = stream.tell() - start
            skip = (align - offs % align) % align
            if skip:
                stream.write(b"\x00" * skip)

    def byte_size(self) -> int:
        ret = 0
        align = getattr(self, "_align", 1)
        for name, field in self.fields():
            ret += field.byte_size(self)
            skip = (align - ret % align) % align
            ret += skip
        return ret

    def zeroise(self):
        c = bytes(self.byte_size())
        self.reload(self.get_stream(c))


    def clone(self) -> "Packable":
        return copy.deepcopy(self)

    @staticmethod
    def get_stream(obj):
        if isinstance(obj, (bytes, bytearray)):
            obj = io.BytesIO(obj)
        return obj

    @classmethod
    def load(cls, stream: Union[BinaryIO, bytes, bytearray, None], count: int = 1):
        stream = cls.get_stream(stream)

        if not (isinstance(count, int)):
            raise ValueError("count should be int")
        if count < 1:
            raise ValueError("count should be > 0")

        ret = []
        for i in range(count):
            obj = cls()
            obj.reload(stream)
            ret.append(obj)
        if count == 1:
            return ret[0]
        return ret


class RawPacker(Packer):

    def __init__(self, format_str: str, default_val=None):
        super().__init__()
        self._format_str = format_str
        self._default_val = default_val
        self._sz = struct.calcsize(self._format_str)

    def unpack(self, stream):
        try:
            dat = stream.read(self._sz)
            val = struct.unpack(self._format_str, dat)
            if len(val) == 1:
                val = val[0]
        except struct.error as e:
            raise Binstruct3Error(str(e))
        return val

    def pack(self, stream, obj):
        try:
            dat = struct.pack(self._format_str, obj)
        except struct.error as e:
            raise Binstruct3Error(str(e))
        stream.write(dat)

    def byte_size(self, obj):
        return self._sz

    def default_value(self):
        return self._default_val

    def validate_value(self, obj):
        if obj is not None:
            try:
                struct.pack(self._format_str, obj)
            except struct.error as e:
                raise Binstruct3Error(str(e))

    def __call__(self, default_val=None):
        default_val = default_val or self._default_val
        return RawPacker(self._format_str, default_val)

    def __getitem__(self, item: int) -> "ArrayPacker":
        return ArrayPacker(self, item, defining=1)


int8 = RawPacker("b")
uint8 = RawPacker("B")
int16 = RawPacker("h")
uint16 = RawPacker("H")
int32 = RawPacker("i")
uint32 = RawPacker("I")
int64 = RawPacker("q")
uint64 = RawPacker("Q")


class CharsPacker(RawPacker):

    def __init__(self, default_val=None, byte_size: int = 1, encoding: Optional[str] = None,
                 terminate_at_first_zero: bool = True, defining:int = 0):
        super().__init__(format_str=str(byte_size) + "s", default_val=default_val)
        self._encoding = encoding or locale.getdefaultlocale()[1]
        self._terminate_at_first_zero = terminate_at_first_zero
        self._defining = defining

    def unpack(self, stream):
        val = RawPacker.unpack(self, stream)
        val = self._decode(val)
        return val

    def _decode(self, val):
        val = val.decode(self._encoding)
        if self._terminate_at_first_zero:
            idx = val.find("\x00")
            return val if idx == -1 else val[:idx]
        return val.rstrip('\x00')

    def _encode(self, val: str):
        val = val.encode(self._encoding)
        if len(val) < self._sz:
            val += b"\x00" * (self._sz - len(val))
        return val

    def validate_value(self, obj):
        if obj is not None:
            val = self._encode(obj)
            RawPacker.validate_value(self, val)

    def pack(self, stream, obj):
        try:
            val = self._encode(obj)
            RawPacker.pack(self, stream, val)
        except Exception as e:
            raise Binstruct3Error(str(e))

    def __getitem__(self, count) -> "CharsPacker":
        if self._sz == 1 and not self._defining:
            return CharsPacker(None, count, self._encoding, self._terminate_at_first_zero, defining = 1)
        if self._defining:
            packer = CharsPacker(None, count)
            return ArrayPacker(packer, self._sz)

        return ArrayPacker(self,count, defining=1)

    def __call__(self, default_val=None, byte_size=None, encoding: Optional[str] = None, terminate_at_first_zero=None):
        byte_size = byte_size or self._sz
        default_val = default_val or self._default_val
        terminate_at_first_zero = terminate_at_first_zero or self._terminate_at_first_zero
        encoding = encoding or self._encoding
        return CharsPacker(default_val, byte_size, encoding, terminate_at_first_zero)


char = CharsPacker()


class StructPacker(Packer):

    def __init__(self, obj: Packable):
        super().__init__()
        self._packable = obj.clone()

    def unpack(self, stream: BinaryIO):
        return self._packable.__class__.load(stream)

    def pack(self, stream: BinaryIO, obj):
        obj.dump(stream)
        pass

    def byte_size(self, obj) -> int:
        return obj.byte_size()

    def default_value(self):
        return self._packable.clone()

    def validate_value(self, obj):
        if not isinstance(obj, self._packable.__class__):
            raise Binstruct3Error(f"value {str(obj)} is not of {self._packable.__class__.__bases__[0].__name__} class")

    def __call__(self, *args, **kwargs):
        return StructPacker(self._packable)


class ArrayPacker(Packer):

    def __init__(self, obj: Union[Packer, Type[Packable]], count: int, defining: int = 0):
        super().__init__()
        self._packer = get_packer(obj)
        self._cnt = count
        self._defining = defining

    def unpack(self, stream):
        ret = []
        for i in range(self._cnt):
            try:
                ret.append(self._packer.unpack(stream))
            except Binstruct3Error as e:
                raise Binstruct3Error(f"element {i}: {str(e)}")
        return ret

    def pack(self, stream, obj):
        itr = iter(obj)
        for i in range(self._cnt):
            try:
                val = next(itr)
                self._packer.pack(stream, val)
            except StopIteration:
                Binstruct3Error(f"Incomplete array:  needed {self._cnt} values, present {i} values")
            except Binstruct3Error as e:
                raise Binstruct3Error(f"element {i}: {str(e)}")

    def byte_size(self, obj):
        return sum(self._packer.byte_size(x) for x in obj)

    def default_value(self):
        return [self._packer.default_value()] * self._cnt

    def validate_value(self, obj):
        if len(obj) != self._cnt:
            raise Binstruct3Error(f"Wrong array size:  needed {self._cnt} values, present {len(obj)} values")
        for i in range(self._cnt):
            self._packer.validate_value(obj[i])

    def __getitem__(self, item: int) -> "ArrayPacker":

        if self._defining:
            new_packer = copy.deepcopy(self)
            packer = new_packer
            packer._defining += 1
            for i in range(self._defining - 1):
                packer = packer._packer
                packer._defining += 1
            packer._packer = ArrayPacker(packer._packer, item, defining=1)
            return new_packer

        return ArrayPacker(self, item, defining=1)

    def __call__(self, *args, **kwargs):
        return ArrayPacker(self._packer, self._cnt)

    def __str__(self):
        return f"ArrayPacker {self._packer}[{self._cnt}]"


def array(count: int, packer: Union[Packer, Type[Packable]]):
    return ArrayPacker(packer, count)


class PackerField(Field):
    def __init__(self, obj: Packer):
        super().__init__()
        self._packer = obj

    def __set__(self, instance, value):
        try:
            self._packer.validate_value(value)
        except Binstruct3Error as e:
            raise FieldError(self.storage, str(e))
        setattr(instance, self.storage, value)

    def fill(self, instance, inpstream: Optional[Any] = None):
        try:
            if inpstream:
                val = self._packer.unpack(inpstream)
            else:
                val = self._packer.default_value()
            self.__set__(instance, val)
        except Binstruct3Error as e:
            raise FieldError(self.storage, str(e))

    def write(self, instance, out_stream):
        try:
            obj = self.__get__(instance, type(instance))
            self._packer.pack(out_stream, obj)
        except Binstruct3Error as e:
            raise FieldError(self.storage, str(e))

    def byte_size(self, instance):
        obj = self.__get__(instance, type(instance))
        return self._packer.byte_size(obj)


def get_packer(obj: Union[Packer, Type[Packer], Type[Packable]]):
    if isinstance(obj, Packer):
        return obj
    if isinstance(obj, Packable):
        return StructPacker(obj)
    if inspect.isclass(obj):
        if issubclass(obj, Packer):
            return obj()
        elif issubclass(obj, Packable):
            return StructPacker(obj())
    raise ValueError("argument obj has incorrect type")


def create_field(packer: Packer):
    return PackerField(packer)


# returns the subclass of Packable. It has attributes of Field inside, to read, write data from binaries and
# to save them in storage


def packable(align: int):
    def _packable(cls) -> Type[Packable]:
        # initializing packed fields
        for name, val in cls.__dict__.items():
            try:
                pack = get_packer(val)
                fld = create_field(pack)
                setattr(cls, name, fld)
                fld.storage = f"{cls.__name__}.{name}"
            except ValueError:
                pass

        # add Packable mixin to our class
        class MyPackable(cls, Packable):

            def __init__(self, *args):

                self._align = align

                for name, field in self.fields():
                    field.fill(self)

                if "__init__" in cls.__dict__.keys():
                    super().__init__(*args)
                else:
                    for (name, field), val in zip(self.fields(), args):
                        field.__set__(self, val)

            def __repr__(self):
                dats = []
                for nm, obj in cls.__dict__.items():
                    if isinstance(obj, Field):
                        dats.append(f"{nm} = {obj.__get__(self, type(self))}")
                vals = ', '.join(dats)
                return f"{cls.__name__}({vals})"

        return MyPackable

    return _packable
