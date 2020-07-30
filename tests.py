import unittest

from binstruct3 import packable, int32, int8, array, chars, FieldError


@packable
class Point:
    x = int32(5)
    y = int32(6)


class StreamReadTests(unittest.TestCase):

    def test_reading_from_bytes(self):
        point = Point.load(b"\x01\x00\x00\x00\x02\x00\x00\x00")
        self.assertEqual(point.x, 1)
        self.assertEqual(point.y, 2)

    def test_reading_multiple_values(self):
        points = Point.load(b"\x01\x00\x00\x00\x02\x00\x00\x00" * 2, count=2)
        self.assertEqual(len(points), 2)
        for point in points:
            self.assertEqual(point.x, 1)
            self.assertEqual(point.y, 2)

    def test_zeroise_function(self):
        @packable
        class A:
            a = int8(32)
            p = Point

        a = A()
        self.assertEqual(a.a, 32)
        self.assertEqual(a.p.x, 5)
        self.assertEqual(a.p.y, 6)

        a.zeroise()
        self.assertEqual(a.a, 0)
        self.assertEqual(a.p.x, 0)
        self.assertEqual(a.p.y, 0)

    def test_insufficient_stream_size_exception(self):
        self.assertRaises(FieldError, Point.load, b"\x01\x00\x00\x00\x02\x00")


class WriteTests(unittest.TestCase):

    def test_wrong_field_exception(self):
        @packable
        class A:
            a = int32
            b = int32
            c = array(4, int8)
            d = chars(12)

        a = A()
        self.assertRaises(FieldError, a.to_bytes)

    def test_array_error_exception(self):
        @packable
        class A:
            g = array(4, int8)

        a = A()
        a.g[:3] = [1, 2, 3]
        self.assertRaises(FieldError, a.to_bytes)
        a.g[3] = 4
        a.to_bytes()


class InitializationTests(unittest.TestCase):

    def test_default_val(self):
        v = Point()
        self.assertEqual(v.x, 5)
        self.assertEqual(v.y, 6)

    def test_empty_val(self):
        @packable
        class A:
            a = int32

        v = A()
        self.assertEqual(v.a, None)

    def test_empty_array(self):
        @packable
        class A:
            a = array(4, int8)

        v = A()
        self.assertEqual(v.a, [None, ] * 4)

    def test_array_defaults(self):
        @packable
        class A:
            a = array(4, int8(5))

        v = A()
        for val in v.a:
            self.assertEqual(val, 5)

    def test_autoinit_function(self):
        @packable
        class MyStruct:
            a = int32(1)
            b = int32(2)
            c = int32(3)
            d = int32

        a = MyStruct(7, 8)

        self.assertEqual(a.a, 7)
        self.assertEqual(a.b, 8)
        self.assertEqual(a.c, 3)
        self.assertEqual(a.d, None)

    def test_init_function(self):
        @packable
        class MyStruct:
            a = int32(1)
            b = int32(2)
            c = int32(3)
            d = int32

            def __init__(self, x1, x2):
                self.c = x1
                self.d = x2

        a = MyStruct(7, 8)

        self.assertEqual(a.a, 1)
        self.assertEqual(a.b, 2)
        self.assertEqual(a.c, 7)
        self.assertEqual(a.d, 8)

    def test_set_wrong_val(self):

        @packable
        class A:
            a = int32
            b = int32

        a = A()
        try:
            a.b = "123"
        except FieldError:
            pass
        else:
            self.fail()

    def test_set_wrong_array(self):
        @packable
        class A:
            g = array(4, int8)

        a = A()

        try:
            a.g = [1, 2, 3, ""]
        except FieldError:
            pass
        else:
            self.fail()


    def todo_test_set_wrong_struct(self):
        class A:
            a = int8
        class B:
            b = A

        b = B()

        try:
            b.b = 5
        except FieldError:
            pass
        self.fail()



    def todo_test_set_wrong_val_in_array(self):
        # TODO: throwing exception on setting item in array is not implemented
        @packable
        class A:
            g = array(4, int8)

        a = A()

        try:
            a.g[1:3] = [1, 2, ""] #not implemented
        except FieldError:
            pass
        else:
            self.fail()



class CharsTests(unittest.TestCase):

    def test_init_empty_str(self):

        @packable
        class A:
            f1 = chars(20, encoding='latin-1')
            f2 = chars(12, encoding='latin-1')

        a = A()
        self.assertEqual(a.byte_size() ,32)
        a.zeroise()

        self.assertEqual(a.f1 ,"")
        self.assertEqual(a.f2 ,"")

    def test_init_str(self):
        @packable
        class A:
            f1 = chars(5, encoding='latin-1')
            f2 = chars(3, encoding='latin-1')

        data = b"abc\x00\x00cd\x00"
        a = A.load(data)
        self.assertEqual(a.f1 ,"abc")
        self.assertEqual(a.f2 ,"cd")

        data = b"abc\x00\x00\x00cd\x00"
        a.reload(data)
        self.assertEqual(a.f1 ,"abc")
        self.assertEqual(a.f2 ,"")







