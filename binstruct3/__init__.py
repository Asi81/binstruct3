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

    def validate_value(self, obj):
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


def raw_packer(fmt: str) -> Type[Packer]:
    class RawPacker(Packer):
        _format_str = fmt
        _sz = struct.calcsize(_format_str)

        def __init__(self, default_val=None):
            self._default_val = default_val

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

    return RawPacker


int8 = raw_packer("b")
uint8 = raw_packer("B")
int16 = raw_packer("h")
uint16 = raw_packer("H")
int32 = raw_packer("i")
uint32 = raw_packer("I")
int64 = raw_packer("q")
uint64 = raw_packer("Q")


def chars(byte_size: int, encoding: Optional[str] = None, terminate_at_first_zero=True) -> Type[Packer]:
    cls = raw_packer(str(byte_size) + "s")
    encoding = encoding or locale.getpreferredencoding()

    class CharsPacker(cls):
        def unpack(self, stream):
            val = cls.unpack(self, stream)
            val = self._decode(val)
            return val

        @staticmethod
        def _decode(val):
            val = val.decode(encoding)
            if terminate_at_first_zero:
                idx = val.find("\x00")
                return val if idx == -1 else val[:idx]
            return val.rstrip('\x00')

        @staticmethod
        def _encode(val):
            val = val.encode(encoding)
            if len(val) < byte_size:
                val += b"\x00" * (byte_size - len(val))
            return val

        def validate_value(self, obj):
            if obj is not None:
                val = self._encode(obj)
                cls.validate_value(self, val)

        def pack(self, stream, obj):
            try:
                val = self._encode(obj)
                cls.pack(self, stream, val)
            except Exception as e:
                raise Binstruct3Error(str(e))

    return CharsPacker


def struct_packer(cls: Type[Packable]):
    class StructPacker(Packer):

        def unpack(self, stream: BinaryIO):
            return cls.load(stream)

        def pack(self, stream: BinaryIO, obj):
            obj.dump(stream)
            pass

        def byte_size(self, obj) -> int:
            return obj.byte_size()

        def default_value(self):
            return cls.load(None)

        def validate_value(self, obj):
            if not isinstance(obj, cls):
                raise Binstruct3Error(f"value {str(obj)} is not of {cls.__bases__[0].__name__} class")

    return StructPacker


def array(count: int, packer: Union[Packer, Type[Packer], Type[Packable]]):
    class ArrayPacker(Packer):
        _packer = get_packer(packer)
        _cnt = count

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

    return ArrayPacker


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
    if inspect.isclass(obj):
        if issubclass(obj, Packer):
            return obj()
        elif issubclass(obj, Packable):
            return struct_packer(obj)()
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
