import inspect
import io
import struct

# simple storage class descriptor
from abc import ABC, abstractmethod
from typing import Type, Union, Any, Optional



class PackableError(Exception):
    pass


class FieldError(PackableError):
    def __init__(self, field_name, error_msg):
        super().__init__(f"field {field_name}: {error_msg}")
        self.field_name = field_name


# ABC for transforming python-object to and from bytes
class Packer(ABC):

    @abstractmethod
    def unpack(self, stream):
        pass

    @abstractmethod
    def pack(self, stream, obj):
        pass

    @abstractmethod
    def byte_size(self, obj):
        pass

    @abstractmethod
    def default_value(self):
        pass

    def validate_value(self,obj):
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

    def byte_size(self, instance):
        pass


# Packable interface
class Packable:

    def fields(self):
        supercls = type(self).__mro__[1]
        for name, obj in supercls.__dict__.items():
            if isinstance(obj, Field):
                yield name, obj

    def load(self, stream: Optional[Any] = None):
        for name, obj in self.fields():
            obj.fill(self, stream)

    def to_bytes(self):
        out = io.BytesIO()
        self.dump(out)
        return out.getvalue()

    def dump(self, stream):
        stream = self.get_stream(stream)
        for name, obj in self.fields():
            obj.write(self, stream)

    def byte_size(self):
        ret = 0
        for name, field in self.fields():
            ret += field.byte_size(self)
        return ret

    def zeroise(self):
        c = bytes(self.byte_size())
        self.load(self.get_stream(c))

    @staticmethod
    def get_stream(obj):
        if isinstance(obj, (bytes, bytearray)):
            obj = io.BytesIO(obj)
        return obj

    @classmethod
    def create(cls, stream, count=1):
        stream = cls.get_stream(stream)

        if not (isinstance(count, int)):
            raise ValueError("count should be int")
        if count < 1:
            raise ValueError("count should be >= 0")

        ret = []
        for i in range(count):
            obj = cls()
            obj.load(stream)
            ret.append(obj)
        if count == 1:
            return ret[0]
        return ret


def raw_packer(fmt: str):
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
                raise PackableError(str(e))
            return val

        def pack(self, stream, obj):
            try:
                dat = struct.pack(self._format_str, obj)
            except struct.error as e:
                raise PackableError(str(e))
            stream.write(dat)

        def byte_size(self, obj):
            return self._sz

        def default_value(self):
            return self._default_val

        def validate_value(self,obj):
            try:
                struct.pack(self._format_str, obj)
            except struct.error as e:
                raise PackableError(str(e))

    return RawPacker


int8 = raw_packer("b")
uint8 = raw_packer("B")
int16 = raw_packer("h")
uint16 = raw_packer("H")
int32 = raw_packer("i")
uint32 = raw_packer("I")
int64 = raw_packer("q")
uint64 = raw_packer("Q")


def chars(length: int):
    return raw_packer(str(length) + "s")


def struct_packer(cls: Type[Packable]):
    class StructPacker(Packer):

        def unpack(self, stream):
            obj = cls()
            obj.load(stream)
            return obj

        def pack(self, stream, obj):
            obj.dump(stream)
            pass

        def byte_size(self, obj):
            return obj.byte_size()

        def default_value(self):
            return self.unpack(None)

    return StructPacker


def array(count: int, obj: Union[Packer, Type[Packer], Type[Packable]]):
    class ArrayPacker(Packer):
        _packer = get_packer(obj)
        _cnt = count

        def unpack(self, stream):
            ret = []
            try:
                for i in range(self._cnt):
                    ret.append(self._packer.unpack(stream))
            except PackableError as e:
                raise PackableError(f"element {i}: {str(e)}")
            return ret

        def pack(self, stream, obj):
            itr = iter(obj)
            for i in range(self._cnt):
                try:
                    val = next(itr)
                    self._packer.pack(stream, val)
                except StopIteration:
                    PackableError(f"Incomplete array:  needed {self._cnt} values, present {i} values")
                except PackableError as e:
                    raise PackableError(f"element {i}: {str(e)}")


        def byte_size(self, obj):
            return sum(self._packer.byte_size(x) for x in obj)

        def default_value(self):
            return [self._packer.default_value() for i in range(self._cnt)]

    return ArrayPacker


class PackerField(Field):
    def __init__(self, obj: Packer):
        super().__init__()
        self._packer = obj

    def fill(self, instance, inpstream: Optional[Any] = None):
        try:
            if inpstream:
                val = self._packer.unpack(inpstream)
            else:
                val = self._packer.default_value()
            self.__set__(instance, val)
        except PackableError as e:
            raise FieldError(self.storage, str(e))

    def write(self, instance, out_stream):
        try:
            obj = self.__get__(instance, type(instance))
            self._packer.pack(out_stream, obj)
        except PackableError as e:
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
def packable(cls) -> Type[Packable]:
    # initializing packed fields
    for name, obj in cls.__dict__.items():
        try:
            pack = get_packer(obj)
            fld = create_field(pack)
            setattr(cls, name, fld)
            fld.storage = f"{cls.__name__}.{name}"
        except ValueError:
            pass

    # add Packable mixin to our class
    class MyPackable(cls, Packable):

        def __init__(self, *args):

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
